"""Flask JSON API entry point with authentication and rate limiting."""

from __future__ import annotations

import concurrent.futures
import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from bist_bot.app_logging import configure_logging, get_logger
from bist_bot.app_metrics import render_metrics
from bist_bot.auth.passwords import hash_password, verify_and_rehash_password
from bist_bot.config.settings import settings
from bist_bot.contracts import (
    DataFetcherProtocol,
    SignalRepositoryProtocol,
    SilentNotifier,
    StrategyEngineProtocol,
)
from bist_bot.dependencies import AppContainer, get_default_container
from bist_bot.indicators import TechnicalIndicators
from bist_bot.locales import get_message
from bist_bot.risk.circuit_breaker import CircuitBreaker
from bist_bot.scanner import ScanService

TR = timezone(timedelta(hours=3))
logger = get_logger(__name__, component="dashboard")


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


_DUMMY_PASSWORD = secrets.token_urlsafe(24)
_DUMMY_HASH = hash_password(_DUMMY_PASSWORD)


def _mask_email(email: str) -> str:
    """Log-safe email representation: `ab***@domain.tld` (no PII in logs)."""
    if not email:
        return ""
    local, sep, domain = email.partition("@")
    if not sep:
        return email[:2] + "***" if len(email) > 2 else "***"
    visible = local[:2] + "***" if len(local) > 2 else local + "***"
    return f"{visible}@{domain}"


def _coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return default if value is None else int(value)
    except (TypeError, ValueError):
        return default


def _empty_rejection_breakdown(scan_id: str = "") -> dict[str, Any]:
    return {
        "total_rejections": 0,
        "by_reason": [],
        "by_stage": [],
        "scan_id": scan_id,
    }


def _normalize_rejection_breakdown(payload: Any, *, scan_id: str = "") -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_rejection_breakdown(scan_id=scan_id)

    resolved_scan_id = str(payload.get("scan_id", scan_id) or scan_id or "")

    def _normalize_rows(rows: Any, key_name: str) -> list[dict[str, Any]]:
        if not isinstance(rows, list):
            return []
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get(key_name, "") or "")
            count = _coerce_int(row.get("count", 0))
            if not key or count <= 0:
                continue
            normalized.append({key_name: key, "count": count})
        return normalized

    by_reason = _normalize_rows(payload.get("by_reason", []), "reason_code")
    by_stage = _normalize_rows(payload.get("by_stage", []), "stage")
    total_rejections = _coerce_int(payload.get("total_rejections", 0))
    if total_rejections <= 0:
        total_rejections = sum(int(item["count"]) for item in by_reason)

    return {
        "total_rejections": total_rejections,
        "by_reason": by_reason,
        "by_stage": by_stage,
        "scan_id": resolved_scan_id,
    }


def _summary_entry(rows: list[dict[str, Any]], key_name: str) -> dict[str, Any]:
    if not rows:
        return {key_name: "", "count": 0}
    first = rows[0]
    return {
        key_name: str(first.get(key_name, "") or ""),
        "count": _coerce_int(first.get("count", 0)),
    }


def _build_scan_history_payload(scan_rows: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    reason_totals: dict[str, int] = {}
    stage_totals: dict[str, int] = {}
    normalized_scans: list[dict[str, Any]] = []
    total_scanned = 0
    total_rejections = 0

    for row in scan_rows:
        if not isinstance(row, dict):
            continue
        scan_id = str(row.get("scan_id", "") or "")
        scanned = _coerce_int(row.get("total_scanned", 0))
        generated = _coerce_int(row.get("signals_generated", 0))
        actionable = _coerce_int(row.get("actionable", 0))
        breakdown = _normalize_rejection_breakdown(
            row.get("rejection_breakdown", {}), scan_id=scan_id
        )
        scan_rejections = _coerce_int(breakdown.get("total_rejections", 0))
        total_scanned += max(scanned, 0)
        total_rejections += max(scan_rejections, 0)

        by_reason = list(breakdown.get("by_reason", []))
        by_stage = list(breakdown.get("by_stage", []))
        for item in by_reason:
            reason_code = str(item.get("reason_code", "") or "")
            count = _coerce_int(item.get("count", 0))
            if reason_code and count > 0:
                reason_totals[reason_code] = reason_totals.get(reason_code, 0) + count
        for item in by_stage:
            stage = str(item.get("stage", "") or "")
            count = _coerce_int(item.get("count", 0))
            if stage and count > 0:
                stage_totals[stage] = stage_totals.get(stage, 0) + count

        normalized_scans.append(
            {
                "scan_id": scan_id,
                "timestamp": row.get("timestamp"),
                "total_scanned": scanned,
                "signals_generated": generated,
                "actionable": actionable,
                "total_rejections": scan_rejections,
                "rejection_rate": round((scan_rejections / scanned) * 100, 1)
                if scanned > 0
                else 0.0,
                "top_reason": _summary_entry(by_reason, "reason_code"),
                "top_stage": _summary_entry(by_stage, "stage"),
            }
        )

    by_reason = sorted(
        (
            {"reason_code": reason_code, "count": count}
            for reason_code, count in reason_totals.items()
        ),
        key=lambda item: (-int(item["count"]), str(item["reason_code"])),
    )
    by_stage = sorted(
        ({"stage": stage, "count": count} for stage, count in stage_totals.items()),
        key=lambda item: (-int(item["count"]), str(item["stage"])),
    )

    return {
        "window_size": limit,
        "returned_scans": len(normalized_scans),
        "average_rejection_rate": round((total_rejections / total_scanned) * 100, 1)
        if total_scanned > 0
        else 0.0,
        "by_reason": by_reason,
        "by_stage": by_stage,
        "scans": normalized_scans,
    }


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
    circuit_breaker: CircuitBreaker | None = None,
) -> Flask:
    """Create the authenticated Flask API application."""
    settings.require_security_config()

    app = Flask(__name__)
    app.config["fetcher"] = fetcher
    app.config["engine"] = engine
    app.config["db"] = db
    app.config["broker"] = broker
    app.config["circuit_breaker"] = circuit_breaker
    app.config["JWT_SECRET_KEY"] = settings.JWT_SECRET_KEY
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)
    app.config["RATELIMIT_STORAGE_URI"] = settings.RATE_LIMIT_STORAGE_URI
    app.config["ALLOW_PUBLIC_REGISTRATION"] = settings.ALLOW_PUBLIC_REGISTRATION

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
            SilentNotifier(),
            get_db(),
            broker=get_broker(),
            settings=settings.replace(),
            circuit_breaker=app.config.get("circuit_breaker"),
        )

    # Process-level mutex to prevent concurrent /api/scan race on shared RiskManager
    _scan_mutex = threading.Lock()

    def verify_admin(email: str, password: str) -> bool:
        logger.info("verify_admin_start", email=_mask_email(email))
        manager = getattr(get_db(), "manager", None)
        if manager is None:
            logger.warning("login_db_unavailable", email=_mask_email(email))
            return False
        try:
            logger.info("verify_admin_db_transaction_start", email=_mask_email(email))
            with manager.engine.begin() as conn:
                logger.info("verify_admin_select_user_start", email=_mask_email(email))
                row = (
                    conn.execute(
                        text("SELECT id, password_hash FROM users WHERE email = :email LIMIT 1"),
                        {"email": email},
                    )
                    .mappings()
                    .first()
                )
                logger.info("verify_admin_select_user_end", email=_mask_email(email))
        except SQLAlchemyError as exc:
            logger.error("verify_admin_db_error", email=_mask_email(email), error=str(exc))
            return False
        if row is None:
            logger.info("login_user_not_found", email=_mask_email(email))
            verify_and_rehash_password(_DUMMY_PASSWORD, _DUMMY_HASH)
            return False
        logger.info("verify_admin_password_check_start", email=_mask_email(email))
        verified, upgraded_hash = verify_and_rehash_password(password, str(row["password_hash"]))
        logger.info("verify_admin_password_check_end", email=_mask_email(email))
        if not verified:
            logger.info("login_password_invalid", email=_mask_email(email))
            return False
        if upgraded_hash is not None:
            try:
                logger.info("verify_admin_hash_upgrade_start", email=_mask_email(email))
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
                logger.info("verify_admin_hash_upgrade_end", email=_mask_email(email))
            except SQLAlchemyError as exc:
                logger.warning(
                    "verify_admin_hash_upgrade_failed", email=_mask_email(email), error=str(exc)
                )
        logger.info("login_success", email=_mask_email(email))
        return True

    def create_user(email: str, password: str) -> tuple[bool, str]:
        manager = getattr(get_db(), "manager", None)
        if manager is None:
            return False, get_message("api.register_error")
        parts = email.rsplit("@", 1)
        if len(parts) != 2 or not parts[0] or "." not in parts[1] or " " in email:
            return False, get_message("api.invalid_email")
        if len(password) < 12:
            return False, get_message("api.password_too_short")

        timestamp = datetime.now(TR)
        try:
            with manager.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO users (email, password_hash, role, created_at, updated_at)
                        VALUES (:email, :password_hash, 'user', :created_at, :updated_at)
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
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; form-action 'self'; frame-ancestors 'none'"
        )
        return response

    @app.route("/health")
    def health_check():
        """Liveness/readiness probe for Docker/Cloud Run.

        Checks DB connectivity, broker configuration, circuit breaker, and
        last successful scan timestamp when available.
        """
        circuit = app.config.get("circuit_breaker")
        db = get_db()
        db_ok = False
        try:
            db_ok = bool(db.ping())
        except Exception:
            db_ok = False

        broker = get_broker()
        broker_mode = str(getattr(settings, "BROKER_MODE", "") or settings.BROKER_PROVIDER).lower()
        broker_provider = str(getattr(settings, "BROKER_PROVIDER", "paper") or "paper").lower()
        broker_status = "ok"
        broker_detail = type(broker).__name__ if broker is not None else "none"
        if broker is None:
            broker_status = "unconfigured"
        else:
            try:
                # Prefer lightweight auth probe when available; do not fail hard on paper.
                auth = getattr(broker, "authenticate", None)
                if (
                    callable(auth)
                    and broker_mode != "paper"
                    and broker_provider
                    not in {
                        "paper",
                        "",
                    }
                ):
                    ok = bool(auth())
                    broker_status = "ok" if ok else "auth_failed"
            except NotImplementedError:
                broker_status = "stub"
            except Exception as exc:
                broker_status = "error"
                broker_detail = f"{type(exc).__name__}"

        last_scan_at: str | None = None
        last_scan_age_seconds: float | None = None
        try:
            if hasattr(db, "get_latest_scan_log"):
                latest = db.get_latest_scan_log()
                if latest and latest.get("timestamp"):
                    last_scan_at = str(latest["timestamp"])
                    try:
                        raw_ts = latest["timestamp"]
                        if isinstance(raw_ts, datetime):
                            ts = raw_ts
                        else:
                            ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=UTC)
                        last_scan_age_seconds = round(
                            (datetime.now(UTC) - ts.astimezone(UTC)).total_seconds(),
                            1,
                        )
                    except (TypeError, ValueError):
                        last_scan_age_seconds = None
        except Exception:
            last_scan_at = None

        circuit_state = str(circuit.state) if circuit else "UNKNOWN"
        health = {
            "status": "healthy",
            "database": "ok" if db_ok else "error",
            "broker": {
                "status": broker_status,
                "mode": broker_mode,
                "provider": broker_provider,
                "detail": broker_detail,
            },
            "last_scan": {
                "timestamp": last_scan_at,
                "age_seconds": last_scan_age_seconds,
            },
            "version": "1.0.0",
            "timestamp": datetime.now(TR).isoformat(),
            "circuit_state": circuit_state,
        }
        if not db_ok or broker_status in {"error", "auth_failed"}:
            health["status"] = "degraded"
        # Circuit OPEN halts trading but the process is still live — do not fail
        # Docker/Cloud Run healthchecks (would cause restart loops).
        status_code = 200 if health["status"] == "healthy" else 503
        return jsonify(health), status_code

    @app.route("/ready")
    def readiness_check():
        ready = {"status": "ready", "timestamp": datetime.now(TR).isoformat()}
        return jsonify(ready), 200

    def _metrics_view():
        return app.response_class(render_metrics(), mimetype="text/plain; version=0.0.4")

    if getattr(settings, "METRICS_PUBLIC", False):
        app.add_url_rule("/metrics", "metrics", _metrics_view, methods=["GET"])
    else:
        app.add_url_rule(
            "/metrics",
            "metrics",
            jwt_required()(_metrics_view),
            methods=["GET"],
        )

    @app.route("/api/auth/login", methods=["POST"])
    @limiter.limit("5 per minute", key_func=_auth_rate_limit_key)
    def api_auth_login():
        payload = request.get_json(silent=True) or {}
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        if not email or not password:
            logger.warning(
                "api_login_failed", reason="missing_credentials", email=_mask_email(email) or ""
            )
            return jsonify(
                {"status": "error", "message": get_message("api.invalid_credentials")}
            ), 401

        logger.info("api_login_attempt", email=_mask_email(email))
        if not verify_admin(email, password):
            logger.warning(
                "api_login_failed", reason="invalid_credentials", email=_mask_email(email)
            )
            return jsonify(
                {"status": "error", "message": get_message("api.invalid_credentials")}
            ), 401

        logger.info("api_login_succeeded", email=_mask_email(email))
        token = create_access_token(identity=email)
        return jsonify({"status": "ok", "access_token": token, "expires_in_hours": 1})

    @app.route("/api/auth/register", methods=["POST"])
    @limiter.limit("5 per minute", key_func=_auth_rate_limit_key)
    def api_auth_register():
        if not bool(app.config.get("ALLOW_PUBLIC_REGISTRATION", False)):
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
        return jsonify({"status": "ok", "access_token": token, "expires_in_hours": 1}), 201

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
            logger.info("api_scan_started", force_refresh=force_refresh)
            with _scan_mutex, concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(scan_service.scan_once, force_refresh=force_refresh)
                try:
                    signals = future.result(timeout=settings.SCAN_TIMEOUT_SECONDS)
                except concurrent.futures.TimeoutError:
                    logger.error(
                        "api_scan_timed_out",
                        timeout_seconds=settings.SCAN_TIMEOUT_SECONDS,
                        force_refresh=force_refresh,
                    )
                    return jsonify(
                        {
                            "status": "error",
                            "message": "Scan timed out",
                            "timeout_seconds": settings.SCAN_TIMEOUT_SECONDS,
                        }
                    ), 504
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
                "scanned_count": scan_stats["scanned"],
                "generated_signals_count": scan_stats.get("signals", len(results)),
                "actionable_count": scan_stats.get("actionable", 0),
                "rejection_breakdown": scan_service.last_rejection_breakdown,
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
                signals_count=len(results),
            )
            return jsonify(response_payload)
        except Exception as exc:
            logger.exception(
                "api_scan_failed",
                error=exc,
                duration_ms=round((time.time() - start_time) * 1000, 2),
                component="dashboard",
            )
            return jsonify({"status": "error", "message": "scan provider unavailable"}), 500

    _TICKER_BASE_RE = re.compile(r"^[A-Z0-9]{1,10}$")

    @app.route("/api/analyze/<ticker>")
    @jwt_required()
    @limiter.limit("30 per minute")
    def api_analyze(ticker: str):
        start_time = time.time()
        try:
            raw = (ticker or "").strip().upper()
            if raw.endswith(".IS"):
                raw = raw[:-3]
            if not _TICKER_BASE_RE.fullmatch(raw):
                return jsonify({"status": "error", "message": "Invalid ticker symbol format"}), 400
            normalized_ticker = f"{raw}.IS"

            runtime_fetcher = get_fetcher()
            runtime_engine = get_engine()
            force_refresh = _coerce_bool(request.args.get("force_refresh"))
            mtf_enabled = bool(getattr(settings, "MTF_ENABLED", True))
            fetch_mtf = cast(
                Callable[..., dict[str, dict[str, Any]]] | None,
                getattr(runtime_fetcher, "fetch_multi_timeframe", None),
            )
            use_mtf_analysis = (
                mtf_enabled and _coerce_bool(request.args.get("mtf")) and callable(fetch_mtf)
            )
            if use_mtf_analysis and fetch_mtf is not None:
                cache_key = (
                    f"{normalized_ticker}|analyze|mtf|"
                    f"{settings.MTF_TREND_PERIOD}:{settings.MTF_TREND_INTERVAL}|"
                    f"{settings.MTF_TRIGGER_PERIOD}:{settings.MTF_TRIGGER_INTERVAL}"
                )
            else:
                cache_key = f"{normalized_ticker}|analyze|single|6mo:{settings.DATA_INTERVAL}"

            cached_response = runtime_fetcher.get_cached_analysis(cache_key, force=force_refresh)
            if cached_response is not None:
                payload = dict(cached_response)
                payload["duration_ms"] = round((time.time() - start_time) * 1000, 2)
                payload["force_refresh"] = force_refresh
                logger.info(
                    "api_analyze_completed",
                    ticker=normalized_ticker,
                    fetch_source="cache",
                    duration_ms=payload["duration_ms"],
                )
                return jsonify(payload)

            if force_refresh:
                runtime_fetcher.clear_cache(scope="analysis", ticker=normalized_ticker)

            fetch_meta_getter = getattr(runtime_fetcher, "get_last_history_fetch_meta", None)
            if use_mtf_analysis and fetch_mtf is not None:
                mtf_data = fetch_mtf(
                    tickers=[normalized_ticker],
                    trend_period=settings.MTF_TREND_PERIOD,
                    trend_interval=settings.MTF_TREND_INTERVAL,
                    trigger_period=settings.MTF_TRIGGER_PERIOD,
                    trigger_interval=settings.MTF_TRIGGER_INTERVAL,
                    force_refresh=force_refresh,
                )
                analysis_input = mtf_data.get(normalized_ticker)
                chart_df = analysis_input.get("trigger") if analysis_input else None
                fetch_meta_raw = (
                    fetch_meta_getter(
                        normalized_ticker,
                        settings.MTF_TRIGGER_PERIOD,
                        settings.MTF_TRIGGER_INTERVAL,
                    )
                    if callable(fetch_meta_getter)
                    else None
                )
            else:
                chart_df = runtime_fetcher.fetch_single(
                    normalized_ticker, period="6mo", force=force_refresh
                )
                analysis_input = chart_df
                fetch_meta_raw = (
                    fetch_meta_getter(normalized_ticker, "6mo", settings.DATA_INTERVAL)
                    if callable(fetch_meta_getter)
                    else None
                )
            fetch_meta = fetch_meta_raw if isinstance(fetch_meta_raw, dict) else {}
            if chart_df is None or analysis_input is None:
                logger.warning(
                    "api_analyze_data_unavailable",
                    ticker=normalized_ticker,
                    fetch_source=fetch_meta.get("source", "unknown"),
                    fetch_status=fetch_meta.get("status", "unknown"),
                    fetch_reason=fetch_meta.get("reason"),
                )
                return jsonify(
                    {"status": "error", "message": get_message("api.data_not_found")}
                ), 404

            indicator_engine = TechnicalIndicators()
            enriched = indicator_engine.add_all(chart_df.copy())
            snapshot = indicator_engine.get_snapshot(enriched)
            signal = runtime_engine.analyze(normalized_ticker, analysis_input)

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
            response_payload["duration_ms"] = round((time.time() - start_time) * 1000, 2)
            logger.info(
                "api_analyze_completed",
                ticker=normalized_ticker,
                fetch_source=fetch_meta.get("source", "unknown"),
                fetch_status=fetch_meta.get("status", "unknown"),
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
            return jsonify({"status": "error", "message": "indicator calculation failed"}), 500

    @app.route("/api/signals/history")
    @jwt_required()
    @limiter.limit("60 per minute")
    def api_signal_history():
        raw_limit = request.args.get("limit", 50, type=int)
        limit = max(1, min(raw_limit if raw_limit is not None else 50, 200))
        ticker = request.args.get("ticker")
        signals = get_db().get_recent_signals(limit=limit, ticker=ticker)
        return jsonify({"status": "ok", "signals": signals})

    @app.route("/api/stats")
    @jwt_required()
    def api_stats():
        stats = get_db().get_performance_stats()
        latest_scan_record = get_db().get_latest_scan_log()
        if latest_scan_record is None:
            latest_scan = {
                "total_scanned": 0,
                "signals_generated": 0,
                "buy_signals": 0,
                "sell_signals": 0,
                "actionable": 0,
                "timestamp": None,
                "rejection_breakdown": _normalize_rejection_breakdown({}),
            }
        else:
            buy = int(latest_scan_record.get("buy_signals", 0) or 0)
            sell = int(latest_scan_record.get("sell_signals", 0) or 0)
            latest_scan = {
                "total_scanned": int(latest_scan_record.get("total_scanned", 0) or 0),
                "signals_generated": int(latest_scan_record.get("signals_generated", 0) or 0),
                "buy_signals": buy,
                "sell_signals": sell,
                "actionable": latest_scan_record.get("actionable", buy + sell),
                "timestamp": latest_scan_record.get("timestamp"),
                "rejection_breakdown": _normalize_rejection_breakdown(
                    latest_scan_record.get("rejection_breakdown", {}),
                    scan_id=str(latest_scan_record.get("scan_id", "") or ""),
                ),
            }
        stats["latest_scan"] = latest_scan
        stats["rejection_breakdown"] = latest_scan["rejection_breakdown"]
        return jsonify(
            {
                "status": "ok",
                "stats": stats,
                "latest_scan": latest_scan,
                "rejection_breakdown": latest_scan["rejection_breakdown"],
            }
        )

    @app.route("/api/scans/history")
    @jwt_required()
    def api_scan_history():
        limit = max(1, min(request.args.get("limit", 20, type=int) or 20, 100))
        scan_rows = get_db().get_recent_scan_logs(limit=limit)
        history = _build_scan_history_payload(scan_rows, limit)
        return jsonify({"status": "ok", "history": history})

    return app


def create_default_dashboard_app(container: AppContainer | None = None) -> Flask:
    """Build the Flask API app from the shared application container."""
    logger.info("api_startup_begin")
    runtime_container = container or get_default_container()
    app = create_dashboard_app(
        fetcher=runtime_container.fetcher,
        engine=runtime_container.engine,
        db=runtime_container.db,
        broker=runtime_container.broker,
        circuit_breaker=runtime_container.circuit_breaker,
    )
    logger.info("api_startup_complete")
    return app


def main() -> None:
    """Run the standalone Flask API process."""
    configure_logging()
    app = create_default_dashboard_app()
    # Container entrypoint must listen on all interfaces; external exposure
    # is controlled by compose ports / Cloud Run ingress.
    bind_host = "0.0.0.0"  # nosec B104
    logger.info(
        "api_listening",
        host=bind_host,
        port=settings.FLASK_PORT,
    )
    app.run(
        host=bind_host,
        port=settings.FLASK_PORT,
        debug=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
