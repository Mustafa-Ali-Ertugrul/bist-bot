"""Flask JSON API entry point with authentication and rate limiting."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from bist_bot.app_logging import configure_logging, get_logger
from bist_bot.app_metrics import render_metrics
from bist_bot.auth.passwords import hash_password, verify_and_rehash_password
from bist_bot.config.settings import settings
from bist_bot.contracts import (
    DataFetcherProtocol,
    SignalRepositoryProtocol,
    StrategyEngineProtocol,
)
from bist_bot.dependencies import AppContainer, get_default_container
from bist_bot.indicators import TechnicalIndicators
from bist_bot.locales import get_message
from bist_bot.scanner import ScanService

TR = timezone(timedelta(hours=3))
logger = get_logger(__name__, component="dashboard")


class _SilentNotifier:
    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        _ = text, parse_mode
        return True

    def send_signal(self, signal) -> bool:
        _ = signal
        return True

    def send_scan_summary(self, signals, total_scanned: int) -> bool:
        _ = signals, total_scanned
        return True

    def send_signal_change(self, ticker: str, old_signal, new_signal) -> bool:
        _ = ticker, old_signal, new_signal
        return True

    def send_startup_message(self) -> bool:
        return True


def _round_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _cors_origins() -> list[str]:
    return [origin for origin in settings.CORS_ORIGINS if origin and origin != "*"]


def _auth_rate_limit_key() -> str:
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    remote_addr = get_remote_address()
    if email:
        return f"{remote_addr}:{email}"
    return str(remote_addr)


def create_dashboard_app(
    fetcher: DataFetcherProtocol,
    engine: StrategyEngineProtocol,
    db: SignalRepositoryProtocol,
    broker: Any | None = None,
) -> Flask:
    """Create the authenticated Flask API application."""
    settings.require_security_config()

    app = Flask(__name__)
    app.config["fetcher"] = fetcher
    app.config["engine"] = engine
    app.config["db"] = db
    app.config["broker"] = broker
    app.config["JWT_SECRET_KEY"] = settings.JWT_SECRET_KEY
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=12)
    app.config["RATELIMIT_STORAGE_URI"] = settings.RATE_LIMIT_STORAGE_URI

    JWTManager(app)
    limiter = Limiter(get_remote_address, app=app, default_limits=["60 per minute"])
    CORS(app, resources={r"/api/*": {"origins": _cors_origins()}})

    def get_fetcher() -> DataFetcherProtocol:
        return cast(DataFetcherProtocol, app.config["fetcher"])

    def get_engine() -> StrategyEngineProtocol:
        return cast(StrategyEngineProtocol, app.config["engine"])

    def get_db() -> SignalRepositoryProtocol:
        return cast(SignalRepositoryProtocol, app.config["db"])

    def get_broker() -> Any | None:
        return app.config["broker"]

    def get_scan_service() -> ScanService:
        return ScanService(
            get_fetcher(),
            get_engine(),
            _SilentNotifier(),
            get_db(),
            broker=get_broker(),
            settings=settings,
        )

    def verify_admin(email: str, password: str) -> bool:
        manager = getattr(get_db(), "manager", None)
        if manager is None:
            return False
        with manager.engine.begin() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT id, password_hash FROM users WHERE email = :email LIMIT 1"
                    ),
                    {"email": email},
                )
                .mappings()
                .first()
            )
        if row is None:
            return False
        verified, upgraded_hash = verify_and_rehash_password(
            password, str(row["password_hash"])
        )
        if not verified:
            return False
        if upgraded_hash is not None:
            with manager.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE users SET password_hash = :password_hash, updated_at = :updated_at WHERE id = :id"
                    ),
                    {
                        "id": int(row["id"]),
                        "password_hash": upgraded_hash,
                        "updated_at": datetime.now(TR),
                    },
                )
        return True

    def create_user(email: str, password: str) -> tuple[bool, str]:
        manager = getattr(get_db(), "manager", None)
        if manager is None:
            return False, get_message("api.register_error")
        if "@" not in email or "." not in email.split("@")[-1]:
            return False, get_message("api.invalid_email")
        if len(password) < 8:
            return False, get_message("api.password_too_short")

        timestamp = datetime.now(TR)
        try:
            with manager.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO users (email, password_hash, role, created_at, updated_at)
                        VALUES (:email, :password_hash, 'admin', :created_at, :updated_at)
                        """
                    ),
                    {
                        "email": email,
                        "password_hash": hash_password(password),
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    },
                )
        except IntegrityError:
            return False, get_message("api.email_already_exists")

        return True, ""

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
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

    @app.route("/ready")
    def readiness_check():
        ready = {"status": "ready", "timestamp": datetime.now(TR).isoformat()}
        return jsonify(ready), 200

    @app.route("/metrics")
    def metrics():
        return app.response_class(
            render_metrics(), mimetype="text/plain; version=0.0.4"
        )

    @app.route("/api/auth/login", methods=["POST"])
    @limiter.limit("5 per minute", key_func=_auth_rate_limit_key)
    def api_auth_login():
        payload = request.get_json(silent=True) or {}
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        if not email or not password or not verify_admin(email, password):
            return jsonify(
                {"status": "error", "message": get_message("api.invalid_credentials")}
            ), 401

        token = create_access_token(identity=email)
        return jsonify({"status": "ok", "access_token": token, "expires_in_hours": 12})

    @app.route("/api/auth/register", methods=["POST"])
    @limiter.limit("5 per minute", key_func=_auth_rate_limit_key)
    def api_auth_register():
        if not getattr(settings, "ALLOW_PUBLIC_REGISTRATION", False):
            return jsonify(
                {"status": "error", "message": get_message("api.registration_disabled")}
            ), 403

        payload = request.get_json(silent=True) or {}
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        success, message = create_user(email, password)
        if not success:
            return jsonify({"status": "error", "message": message}), 400

        token = create_access_token(identity=email)
        return jsonify(
            {"status": "ok", "access_token": token, "expires_in_hours": 12}
        ), 201

    @app.route("/api/scan", methods=["POST"])
    @jwt_required()
    @limiter.limit("10 per minute")
    def api_scan():
        start_time = time.time()
        try:
            payload = request.get_json(silent=True) or {}
            force_refresh = _coerce_bool(
                payload.get("force_refresh", request.args.get("force_refresh"))
            )
            scan_service = get_scan_service()
            signals = scan_service.scan_once(force_refresh=force_refresh)
            scan_stats = scan_service.last_scan_stats

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

            response_payload: dict[str, Any] = {
                "status": "ok",
                "scanned": scan_stats["scanned"],
                "signals": results,
                "force_refresh": force_refresh,
                "timestamp": datetime.now(TR).isoformat(),
                "duration_ms": round((time.time() - start_time) * 1000, 2),
            }
            logger.info(
                "api_scan_completed",
                duration_ms=response_payload["duration_ms"],
                scanned_count=scan_stats["scanned"],
                actionable_count=scan_stats["actionable"],
            )
            return jsonify(response_payload)
        except Exception as exc:
            logger.exception(
                "api_scan_failed",
                error=exc,
                duration_ms=round((time.time() - start_time) * 1000, 2),
                component="dashboard",
            )
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
            force_refresh = _coerce_bool(request.args.get("force_refresh"))
            cache_key = f"{normalized_ticker}|analyze|6mo"

            cached_response = runtime_fetcher.get_cached_analysis(
                cache_key, force=force_refresh
            )
            if cached_response is not None:
                payload = dict(cached_response)
                payload["duration_ms"] = round((time.time() - start_time) * 1000, 2)
                payload["force_refresh"] = force_refresh
                logger.info(
                    "api_analyze_completed",
                    ticker=normalized_ticker,
                    duration_ms=payload["duration_ms"],
                )
                return jsonify(payload)

            if force_refresh:
                runtime_fetcher.clear_cache(scope="analysis", ticker=normalized_ticker)

            df = runtime_fetcher.fetch_single(
                normalized_ticker, period="6mo", force=force_refresh
            )
            if df is None:
                return jsonify(
                    {"status": "error", "message": get_message("api.data_not_found")}
                ), 404

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

            response_payload: dict[str, Any] = {
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
                    "position_size": signal.position_size if signal else None,
                },
                "price_data": price_data,
            }
            runtime_fetcher.store_analysis(cache_key, response_payload)
            response_payload["force_refresh"] = force_refresh
            response_payload["duration_ms"] = round(
                (time.time() - start_time) * 1000, 2
            )
            logger.info(
                "api_analyze_completed",
                ticker=normalized_ticker,
                signal_type=signal.signal_type.value if signal else None,
                duration_ms=response_payload["duration_ms"],
            )
            return jsonify(response_payload)
        except Exception as exc:
            logger.exception(
                "api_analyze_failed",
                error=exc,
                ticker=ticker,
                duration_ms=round((time.time() - start_time) * 1000, 2),
            )
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
        broker=runtime_container.broker,
    )


def main() -> None:
    """Run the standalone Flask API process."""
    configure_logging()
    app = create_default_dashboard_app()
    app.run(
        host="0.0.0.0",
        port=settings.FLASK_PORT,
        debug=False,
        use_reloader=settings.FLASK_DEBUG,
    )


if __name__ == "__main__":
    main()
