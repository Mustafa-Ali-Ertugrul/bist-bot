"""Flask JSON API entry point with authentication and rate limiting."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from passlib.context import CryptContext
from sqlalchemy import text

from config import settings
from contracts import DataFetcherProtocol, SignalRepositoryProtocol, StrategyEngineProtocol
from dependencies import AppContainer, get_default_container
from indicators import TechnicalIndicators

TR = timezone(timedelta(hours=3))
logger = logging.getLogger(__name__)
PASSWORD_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _round_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _cors_origins() -> list[str]:
    return [origin for origin in settings.CORS_ORIGINS if origin and origin != "*"]


def create_dashboard_app(
    fetcher: DataFetcherProtocol,
    engine: StrategyEngineProtocol,
    db: SignalRepositoryProtocol,
) -> Flask:
    """Create the authenticated Flask API application."""
    settings.require_security_config()

    app = Flask(__name__)
    app.config["fetcher"] = fetcher
    app.config["engine"] = engine
    app.config["db"] = db
    app.config["JWT_SECRET_KEY"] = settings.JWT_SECRET_KEY
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=12)
    app.config["RATELIMIT_STORAGE_URI"] = settings.RATE_LIMIT_STORAGE_URI

    JWTManager(app)
    limiter = Limiter(get_remote_address, app=app, default_limits=["60 per minute"])
    CORS(app, resources={r"/api/*": {"origins": _cors_origins()}})

    def get_fetcher() -> DataFetcherProtocol:
        return app.config["fetcher"]

    def get_engine() -> StrategyEngineProtocol:
        return app.config["engine"]

    def get_db() -> SignalRepositoryProtocol:
        return app.config["db"]

    def verify_admin(email: str, password: str) -> bool:
        manager = getattr(get_db(), "manager", None)
        if manager is None:
            return False
        with manager.engine.begin() as conn:
            row = conn.execute(
                text("SELECT password_hash FROM users WHERE email = :email LIMIT 1"),
                {"email": email},
            ).mappings().first()
        if row is None:
            return False
        return PASSWORD_CONTEXT.verify(password, str(row["password_hash"]))

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.route("/health")
    def health_check():
        health = {
            "status": "healthy",
            "database": "ok" if get_db().ping() else "error",
            "version": "1.0.0",
            "timestamp": datetime.now(TR).isoformat(),
        }
        if health["database"] != "ok":
            health["status"] = "degraded"
        status_code = 200 if health["status"] == "healthy" else 503
        return jsonify(health), status_code

    @app.route("/api/auth/login", methods=["POST"])
    @limiter.limit("5 per minute")
    def api_auth_login():
        payload = request.get_json(silent=True) or {}
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        if not email or not password or not verify_admin(email, password):
            return jsonify({"status": "error", "message": "Gecersiz kimlik bilgileri"}), 401

        token = create_access_token(identity=email)
        return jsonify({"status": "ok", "access_token": token, "expires_in_hours": 12})

    @app.route("/api/scan", methods=["POST"])
    @jwt_required()
    @limiter.limit("10 per minute")
    def api_scan():
        start_time = time.time()
        try:
            runtime_fetcher = get_fetcher()
            runtime_engine = get_engine()
            runtime_db = get_db()

            runtime_fetcher.clear_cache()
            all_data = runtime_fetcher.fetch_multi_timeframe_all(
                trend_period=getattr(settings, "MTF_TREND_PERIOD", "6mo"),
                trend_interval=getattr(settings, "MTF_TREND_INTERVAL", "1d"),
                trigger_period=getattr(settings, "MTF_TRIGGER_PERIOD", "1mo"),
                trigger_interval=getattr(settings, "MTF_TRIGGER_INTERVAL", "15m"),
            )
            signals = runtime_engine.scan_all(all_data)
            actionable = runtime_engine.get_actionable_signals(signals)

            runtime_db.save_signals(actionable)

            buys = [signal for signal in signals if signal.score > 0]
            sells = [signal for signal in signals if signal.score < 0]
            runtime_db.save_scan_log(
                len(all_data),
                len(actionable),
                len(buys),
                len(sells),
            )

            results = [
                {
                    "ticker": signal.ticker,
                    "name": settings.TICKER_NAMES.get(signal.ticker, signal.ticker),
                    "signal": signal.signal_type.value,
                    "score": signal.score,
                    "price": signal.price,
                    "stop_loss": signal.stop_loss,
                    "target": signal.target_price,
                    "confidence": signal.confidence,
                    "reasons": signal.reasons,
                    "timestamp": signal.timestamp.isoformat(),
                }
                for signal in signals
            ]

            return jsonify(
                {
                    "status": "ok",
                    "scanned": len(all_data),
                    "signals": results,
                    "timestamp": datetime.now(TR).isoformat(),
                    "duration_ms": round((time.time() - start_time) * 1000, 2),
                }
            )
        except Exception as exc:
            logger.error("Tarama hatasi: %s", exc)
            return jsonify({"status": "error", "message": str(exc)}), 500

    @app.route("/api/analyze/<ticker>")
    @jwt_required()
    @limiter.limit("30 per minute")
    def api_analyze(ticker: str):
        start_time = time.time()
        try:
            runtime_fetcher = get_fetcher()
            runtime_engine = get_engine()
            normalized_ticker = ticker if ticker.endswith(".IS") else f"{ticker}.IS"

            df = runtime_fetcher.fetch_single(normalized_ticker, period="6mo")
            if df is None:
                return jsonify({"status": "error", "message": "Veri bulunamadi"}), 404

            indicator_engine = TechnicalIndicators()
            enriched = indicator_engine.add_all(df.copy())
            snapshot = indicator_engine.get_snapshot(enriched)
            signal = runtime_engine.analyze(normalized_ticker, df)

            price_data = [
                {
                    "date": str(idx)[:10],
                    "open": _round_value(row.get("open")),
                    "high": _round_value(row.get("high")),
                    "low": _round_value(row.get("low")),
                    "close": _round_value(row.get("close")),
                    "volume": int(float(row.get("volume", 0) or 0)),
                    "rsi": _round_value(row.get("rsi")),
                    "sma_fast": _round_value(row.get(f"sma_{settings.SMA_FAST}")),
                    "sma_slow": _round_value(row.get(f"sma_{settings.SMA_SLOW}")),
                }
                for idx, row in enriched.tail(60).iterrows()
            ]

            return jsonify(
                {
                    "status": "ok",
                    "ticker": normalized_ticker,
                    "name": settings.TICKER_NAMES.get(normalized_ticker, normalized_ticker),
                    "snapshot": snapshot,
                    "signal": {
                        "type": signal.signal_type.value if signal else "N/A",
                        "score": signal.score if signal else 0,
                        "reasons": signal.reasons if signal else [],
                        "stop_loss": signal.stop_loss if signal else 0,
                        "target": signal.target_price if signal else 0,
                    },
                    "price_data": price_data,
                    "duration_ms": round((time.time() - start_time) * 1000, 2),
                }
            )
        except Exception as exc:
            logger.exception("Analiz hatasi")
            return jsonify({"status": "error", "message": str(exc)}), 500

    @app.route("/api/signals/history")
    @jwt_required()
    def api_signal_history():
        limit = request.args.get("limit", 50, type=int)
        ticker = request.args.get("ticker")
        signals = get_db().get_recent_signals(limit=limit, ticker=ticker)
        return jsonify({"status": "ok", "signals": signals})

    @app.route("/api/stats")
    @jwt_required()
    def api_stats():
        stats = get_db().get_performance_stats()
        return jsonify({"status": "ok", "stats": stats})

    return app


def create_default_dashboard_app(container: AppContainer | None = None) -> Flask:
    """Build the Flask API app from the shared application container."""
    runtime_container = container or get_default_container()
    return create_dashboard_app(
        fetcher=runtime_container.fetcher,
        engine=runtime_container.engine,
        db=runtime_container.db,
    )


def main() -> None:
    """Run the standalone Flask API process."""
    app = create_default_dashboard_app()
    app.run(
        host="0.0.0.0",
        port=settings.FLASK_PORT,
        debug=False,
        use_reloader=settings.FLASK_DEBUG,
    )


if __name__ == "__main__":
    main()
