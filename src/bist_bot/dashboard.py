"""Flask JSON API entry point with authentication and rate limiting."""

from __future__ import annotations

import concurrent.futures
import json
import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from functools import wraps
from typing import Any, cast

from flask import Flask, g, has_request_context, jsonify, redirect, render_template, request
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
    set_access_cookies,
    unset_jwt_cookies,
    verify_jwt_in_request,
)
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


def _safe_json_payload() -> dict[str, Any]:
    raw = request.get_json(silent=True)
    return raw if isinstance(raw, dict) else {}


def _auth_rate_limit_key() -> str:
    payload = _safe_json_payload()
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

    from pathlib import Path

    base_dir = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
    )
    app.config["fetcher"] = fetcher
    app.config["engine"] = engine
    app.config["db"] = db
    app.config["broker"] = broker
    app.config["circuit_breaker"] = circuit_breaker
    app.config["SECRET_KEY"] = settings.JWT_SECRET_KEY
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
    app.config["SESSION_COOKIE_SECURE"] = settings.JWT_COOKIE_SECURE
    app.config["JWT_SECRET_KEY"] = settings.JWT_SECRET_KEY
    app.config["JWT_ALGORITHM"] = "HS256"
    app.config["JWT_DECODE_ALGORITHMS"] = ["HS256"]
    access_token_minutes = max(1, min(int(settings.JWT_ACCESS_TOKEN_MINUTES), 15))
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(minutes=access_token_minutes)
    # HttpOnly UI cookie is the server-side authority for /ui/* page renders.
    # /api/* keeps using the Authorization header; cookie CSRF stays at the
    # Flask-JWT-Extended default (enforced only for unsafe methods).
    app.config["JWT_COOKIE_HTTPONLY"] = True
    app.config["JWT_COOKIE_SAMESITE"] = "Strict"
    app.config["JWT_COOKIE_SECURE"] = settings.JWT_COOKIE_SECURE
    app.config["RATELIMIT_STORAGE_URI"] = settings.RATE_LIMIT_STORAGE_URI
    app.config["ALLOW_PUBLIC_REGISTRATION"] = settings.ALLOW_PUBLIC_REGISTRATION
    app.config["RBAC_MODE"] = settings.RBAC_MODE
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024  # 1MB payload cap to mitigate DoS

    jwt = JWTManager(app)
    _REVOKED_JTIS: dict[str, float] = {}
    _REVOKED_LOCK = threading.Lock()

    def _revoke_jti(jti: str, exp: float) -> None:
        now = time.time()
        with _REVOKED_LOCK:
            # Purge expired entries to avoid memory leak
            expired = [k for k, v in _REVOKED_JTIS.items() if v <= now]
            for k in expired:
                _REVOKED_JTIS.pop(k, None)
            _REVOKED_JTIS[jti] = exp

    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(_jwt_header: Any, jwt_payload: dict[str, Any]) -> bool:
        jti = jwt_payload.get("jti")
        if not jti:
            return False
        with _REVOKED_LOCK:
            return jti in _REVOKED_JTIS

    @jwt.revoked_token_loader
    def _custom_jwt_revoked(_jwt_header: Any, _jwt_payload: Any):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Bu oturum kapatılmıştır. Lütfen tekrar giriş yapın.",
                }
            ),
            401,
        )

    @jwt.unauthorized_loader
    def _custom_jwt_unauthorized(err_str: str):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Oturum doğrulanmadı veya token eksik.",
                    "detail": err_str,
                }
            ),
            401,
        )

    @jwt.expired_token_loader
    def _custom_jwt_expired(_jwt_header: Any, _jwt_payload: Any):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Oturum süresi doldu. Lütfen tekrar giriş yapın.",
                }
            ),
            401,
        )

    @jwt.invalid_token_loader
    def _custom_jwt_invalid(err_str: str):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Geçersiz oturum anahtarı.",
                    "detail": err_str,
                }
            ),
            422,
        )

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

    def _request_id() -> str:
        existing = getattr(g, "request_id", None)
        if existing:
            return str(existing)
        supplied = request.headers.get("X-Request-ID", "").strip()
        if supplied and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied):
            g.request_id = supplied
        else:
            g.request_id = secrets.token_hex(12)
        return str(g.request_id)

    def _write_security_audit(event_type: str, details: dict[str, Any]) -> None:
        manager = getattr(get_db(), "manager", None)
        if manager is None:
            return
        try:
            with manager.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO audit_trail "
                        "(timestamp, event_type, agent_state, details, trigger_source, created_at) "
                        "VALUES (:timestamp, :event_type, :agent_state, :details, "
                        ":trigger_source, :created_at)"
                    ),
                    {
                        "timestamp": datetime.now(UTC),
                        "event_type": event_type,
                        "agent_state": "security",
                        "details": json.dumps(details, ensure_ascii=False, default=str),
                        "trigger_source": "http",
                        "created_at": datetime.now(UTC),
                    },
                )
        except SQLAlchemyError:
            logger.exception("security_audit_write_failed", event_type=event_type)

    def _db_user_for_identity(identity: str) -> dict[str, Any] | None:
        manager = getattr(get_db(), "manager", None)
        if manager is None:
            return None
        try:
            user_id = int(identity)
        except (TypeError, ValueError):
            return None
        try:
            with manager.engine.connect() as conn:
                row = (
                    conn.execute(
                        text("SELECT id, email, role FROM users WHERE id = :id LIMIT 1"),
                        {"id": user_id},
                    )
                    .mappings()
                    .first()
                )
        except SQLAlchemyError:
            logger.exception("rbac_user_lookup_failed", user_id=user_id)
            raise
        return dict(row) if row is not None else None

    def require_roles(*allowed_roles: str):
        """Require a current DB role, with a warn-only migration mode."""

        allowed = frozenset(allowed_roles)

        def decorator(view):
            @wraps(view)
            def wrapped(*args, **kwargs):
                claims = get_jwt()
                claim_role = str(claims.get("role", "") or "").lower()
                identity = str(get_jwt_identity() or "")
                request_id = _request_id()
                try:
                    db_user = _db_user_for_identity(identity)
                except SQLAlchemyError:
                    logger.error(
                        "auth_identity_lookup_unavailable",
                        user_id=identity or None,
                        route=request.path,
                        request_id=request_id,
                    )
                    return jsonify(
                        {"status": "error", "message": "Identity store unavailable"}
                    ), 503
                if db_user is None:
                    audit_details = {
                        "user_id": identity or None,
                        "claim_role": claim_role or None,
                        "db_role": None,
                        "route": request.path,
                        "request_id": request_id,
                        "allowed_roles": sorted(allowed),
                    }
                    logger.warning("auth_identity_unresolved", **audit_details)
                    _write_security_audit("auth_identity_unresolved", audit_details)
                    return jsonify({"status": "error", "message": "Authentication required"}), 401
                db_role = str((db_user or {}).get("role", "") or "").lower()
                authorized = bool(claim_role in allowed and db_role in allowed)
                g.rbac_authorized = authorized
                audit_details = {
                    "user_id": identity or None,
                    "claim_role": claim_role or None,
                    "db_role": db_role or None,
                    "route": request.path,
                    "request_id": request_id,
                    "allowed_roles": sorted(allowed),
                }
                if not authorized:
                    mode = str(app.config.get("RBAC_MODE", "warn") or "warn").lower()
                    event_type = "rbac_access_denied" if mode == "enforce" else "rbac_would_deny"
                    logger.warning(
                        event_type,
                        **audit_details,
                    )
                    _write_security_audit(event_type, audit_details)
                    if mode == "enforce":
                        return jsonify({"status": "error", "message": "Forbidden"}), 403
                else:
                    logger.info(
                        "rbac_access_granted",
                        **audit_details,
                    )
                    _write_security_audit("rbac_access_granted", audit_details)
                return view(*args, **kwargs)

            return wrapped

        return decorator

    def get_scan_service() -> ScanService:
        factory = app.config.get("scan_service_factory")
        if callable(factory):
            return factory()
        scan_settings = settings.replace()
        if has_request_context() and getattr(g, "rbac_authorized", True) is False:
            scan_settings = scan_settings.replace(AUTO_EXECUTE_ENABLED=False, AUTO_EXECUTE=False)
        return ScanService(
            get_fetcher(),
            get_engine(),
            SilentNotifier(),
            get_db(),
            broker=get_broker(),
            settings=scan_settings,
            circuit_breaker=app.config.get("circuit_breaker"),
        )

    # Process-level state to track actively executing scan jobs with an auto-expiring lease
    _scan_lock = threading.Lock()
    _scan_started_at = [0.0]

    def _acquire_scan_lock() -> bool:
        now = time.time()
        with _scan_lock:
            max_scan_dur = float(getattr(settings, "SCAN_TIMEOUT_SECONDS", 180)) + 10.0
            if _scan_started_at[0] > 0 and (now - _scan_started_at[0]) < max_scan_dur:
                return False
            _scan_started_at[0] = now
            return True

    def _release_scan_lock() -> None:
        with _scan_lock:
            _scan_started_at[0] = 0.0
    _benchmark_cache: dict[str, Any] = {
        "timestamp": 0.0,
        "data": {
            "USDTRY": {"val": 48.45, "chg": 0.07},
            "XU100": {"val": 14120.64, "chg": -0.22},
            "XU030": {"val": 16734.88, "chg": 0.02},
        },
    }
    _benchmark_updating = threading.Event()

    def _refresh_benchmarks_background() -> None:
        if _benchmark_updating.is_set():
            return
        _benchmark_updating.set()

        def _worker():
            try:
                import yfinance as yf
                tickers = {"XU100": "XU100.IS", "XU030": "XU030.IS", "USDTRY": "USDTRY=X"}
                res: dict[str, Any] = {}
                for k, sym in tickers.items():
                    try:
                        h = yf.Ticker(sym).history(period="5d", interval="1d")
                        if h is not None and not h.empty and len(h) >= 2:
                            last = float(h["Close"].iloc[-1])
                            prev = float(h["Close"].iloc[-2])
                            pct = ((last - prev) / prev) * 100
                            res[k] = {"val": round(last, 2), "chg": round(pct, 2)}
                        elif h is not None and not h.empty:
                            last = float(h["Close"].iloc[-1])
                            res[k] = {"val": round(last, 2), "chg": 0.0}
                    except Exception:
                        pass
                if res:
                    _benchmark_cache["timestamp"] = time.time()
                    _benchmark_cache["data"].update(res)
            except Exception:
                pass
            try:
                # Pre-warm history cache for the most-viewed tickers so the
                # first /api/analyze click never pays a cold-fetch (~600ms).
                # Respects fetcher TTLs: no-ops when cache entries are fresh.
                fetcher = get_fetcher()
                for sym, period, interval in (
                    ("THYAO.IS", "6mo", "1d"),
                    ("ASELS.IS", "6mo", "1d"),
                    ("KCHOL.IS", "6mo", "1d"),
                    ("THYAO.IS", "3mo", "60m"),
                ):
                    try:
                        fetcher.fetch_single(sym, period=period, interval=interval)
                    except Exception:
                        pass
            except Exception:
                pass
            finally:
                _benchmark_updating.clear()

        t = threading.Thread(target=_worker, daemon=True, name="benchmarks-bg-refresh")
        t.start()

    def _get_live_benchmarks() -> dict[str, Any]:
        now = time.time()
        if now - float(_benchmark_cache.get("timestamp", 0.0)) > 90.0:
            _refresh_benchmarks_background()
        return cast(dict[str, Any], _benchmark_cache["data"])

    def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
        logger.info("verify_admin_start", email=_mask_email(email))
        manager = getattr(get_db(), "manager", None)
        if manager is None:
            logger.warning("login_db_unavailable", email=_mask_email(email))
            return None
        try:
            logger.info("verify_admin_db_transaction_start", email=_mask_email(email))
            with manager.engine.begin() as conn:
                logger.info("verify_admin_select_user_start", email=_mask_email(email))
                row = (
                    conn.execute(
                        text(
                            "SELECT id, email, password_hash, role "
                            "FROM users WHERE email = :email LIMIT 1"
                        ),
                        {"email": email},
                    )
                    .mappings()
                    .first()
                )
                logger.info("verify_admin_select_user_end", email=_mask_email(email))
        except SQLAlchemyError as exc:
            logger.error("verify_admin_db_error", email=_mask_email(email), error=str(exc))
            return None
        if row is None:
            logger.info("login_user_not_found", email=_mask_email(email))
            verify_and_rehash_password(_DUMMY_PASSWORD, _DUMMY_HASH)
            return None
        logger.info("verify_admin_password_check_start", email=_mask_email(email))
        verified, upgraded_hash = verify_and_rehash_password(password, str(row["password_hash"]))
        logger.info("verify_admin_password_check_end", email=_mask_email(email))
        if not verified:
            logger.info("login_password_invalid", email=_mask_email(email))
            return None
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
        return {
            "id": int(row["id"]),
            "email": str(row["email"]),
            "role": str(row["role"] or "user").lower(),
        }

    def create_user(email: str, password: str) -> tuple[bool, str, dict[str, Any] | None]:
        manager = getattr(get_db(), "manager", None)
        if manager is None:
            return False, get_message("api.register_error"), None
        parts = email.rsplit("@", 1)
        if len(parts) != 2 or not parts[0] or "." not in parts[1] or " " in email:
            return False, get_message("api.invalid_email"), None
        if len(password) < 12:
            return False, get_message("api.password_too_short"), None

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
                user_id = int(
                    conn.execute(
                        text("SELECT id FROM users WHERE email = :email LIMIT 1"),
                        {"email": email},
                    ).scalar_one()
                )
        except IntegrityError:
            return False, get_message("api.email_already_exists"), None

        return True, "", {"id": user_id, "email": email, "role": "user"}

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Server"] = "BistBot"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-Request-ID"] = _request_id()
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: https://lh3.googleusercontent.com; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "form-action 'self'; frame-ancestors 'none'"
        )

        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=3600"

        # Transparent Gzip compression for dynamic API JSON and template responses >= 512B
        accept_enc = request.headers.get("Accept-Encoding", "").lower()
        if (
            "gzip" in accept_enc
            and 200 <= response.status_code < 300
            and not response.direct_passthrough
            and "Content-Encoding" not in response.headers
        ):
            c_type = response.headers.get("Content-Type", "").lower()
            if any(ct in c_type for ct in ("text/", "application/json", "application/javascript", "image/svg+xml")):
                body_bytes = response.get_data()
                if len(body_bytes) >= 512:
                    import gzip
                    compressed = gzip.compress(body_bytes, compresslevel=6)
                    response.set_data(compressed)
                    response.headers["Content-Encoding"] = "gzip"
                    response.headers["Content-Length"] = str(len(compressed))

        return response

    @app.errorhandler(400)
    def _handle_bad_request(e: Any):
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "message": "Geçersiz istek parametreleri."}), 400
        return e

    @app.errorhandler(404)
    def _handle_not_found(_e: Any):
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "message": "İstenen kaynak veya endpoint bulunamadı."}), 404
        return redirect("/ui/dashboard", code=302)

    @app.errorhandler(405)
    def _handle_method_not_allowed(e: Any):
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "message": "Bu endpoint için HTTP metodu desteklenmiyor."}), 405
        return e

    @app.errorhandler(429)
    def _handle_rate_limit(_e: Any):
        return jsonify({"status": "error", "message": "Çok fazla istek gönderildi. Lütfen biraz bekleyin."}), 429

    @app.errorhandler(500)
    def _handle_internal_error(e: Any):
        logger.exception("unhandled_internal_server_error", path=request.path)
        if request.path.startswith("/api/"):
            return jsonify({"status": "error", "message": "Sunucu içi beklenmeyen bir hata oluştu."}), 500
        return e

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

    @app.route("/livez")
    def liveness_check():
        """Lightweight liveness probe for Kubernetes / orchestrators.

        Returns 200 OK as long as process responds.
        """
        return (
            jsonify(
                {
                    "status": "alive",
                    "timestamp": datetime.now(TR).isoformat(),
                    "version": "1.0.0",
                }
            ),
            200,
        )

    @app.route("/ready")
    def legacy_readiness_check():
        """Legacy lightweight readiness probe (non-blocking)."""
        return jsonify({"status": "ready", "timestamp": datetime.now(TR).isoformat()}), 200

    @app.route("/readyz")
    def readiness_check():
        """Readiness probe for traffic admission with deep dependency checks."""
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
                auth = getattr(broker, "authenticate", None)
                if (
                    callable(auth)
                    and broker_mode != "paper"
                    and broker_provider not in {"paper", ""}
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
        ready_payload = {
            "status": "ready",
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
            ready_payload["status"] = "not_ready"

        status_code = 200 if ready_payload["status"] == "ready" else 503
        return jsonify(ready_payload), status_code

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
        payload = _safe_json_payload()
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        if (
            not email
            or not password
            or len(email) > 128
            or len(password) > 256
            or "@" not in email
        ):
            logger.warning(
                "api_login_failed", reason="invalid_format_or_length", email=_mask_email(email) or ""
            )
            return jsonify(
                {"status": "error", "message": get_message("api.invalid_credentials")}
            ), 401

        logger.info("api_login_attempt", email=_mask_email(email))
        user = authenticate_user(email, password)
        if user is None:
            logger.warning(
                "api_login_failed", reason="invalid_credentials", email=_mask_email(email)
            )
            return jsonify(
                {"status": "error", "message": get_message("api.invalid_credentials")}
            ), 401

        logger.info("api_login_succeeded", email=_mask_email(email))
        token = create_access_token(
            identity=str(user["id"]),
            additional_claims={"role": user["role"], "email": user["email"]},
        )
        response = jsonify(
            {
                "status": "ok",
                "access_token": token,
                "expires_in_hours": access_token_minutes / 60,
                "expires_in_seconds": access_token_minutes * 60,
            }
        )
        # HttpOnly cookie is the server-side authority for /ui/* page renders.
        # /api/* keeps using the Authorization header (see _ui_auth_required).
        set_access_cookies(response, token)
        return response

    @app.route("/api/auth/register", methods=["POST"])
    @limiter.limit("5 per minute", key_func=_auth_rate_limit_key)
    def api_auth_register():
        if not bool(app.config.get("ALLOW_PUBLIC_REGISTRATION", False)):
            return jsonify(
                {"status": "error", "message": get_message("api.registration_disabled")}
            ), 403

        payload = _safe_json_payload()
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        success, message, user = create_user(email, password)
        if not success:
            return jsonify({"status": "error", "message": message}), 400

        assert user is not None
        token = create_access_token(
            identity=str(user["id"]),
            additional_claims={"role": user["role"], "email": user["email"]},
        )
        response = jsonify(
            {
                "status": "ok",
                "access_token": token,
                "expires_in_hours": access_token_minutes / 60,
                "expires_in_seconds": access_token_minutes * 60,
            }
        )
        set_access_cookies(response, token)
        return response, 201

    @app.route("/api/auth/verify", methods=["GET"])
    @jwt_required()
    def api_auth_verify():
        """Validate a Bearer token without side effects (used by the login UI).

        The token itself is never echoed back in logs or the response body.
        """
        claims = get_jwt()
        return jsonify(
            {
                "status": "ok",
                "valid": True,
                "user_id": str(get_jwt_identity() or ""),
                "email": str(claims.get("email") or ""),
                "role": str(claims.get("role") or ""),
            }
        ), 200

    @app.route("/api/auth/session", methods=["POST"])
    @jwt_required()
    @limiter.limit("10 per minute")
    def api_auth_session():
        """Mint the HttpOnly UI cookie from a valid Bearer token.

        Used by the login page AFTER verify succeeds, so the browser never
        navigates to a gated /ui/* page without a cookie the server accepts.
        This ordering (verify -> session -> navigate) makes a login<->dashboard
        redirect loop structurally impossible.
        """
        claims = get_jwt()
        identity = str(get_jwt_identity() or "")
        if not identity:
            return jsonify({"status": "error", "message": "Authentication required"}), 401
        cookie_token = create_access_token(
            identity=identity,
            additional_claims={
                "role": str(claims.get("role") or ""),
                "email": str(claims.get("email") or ""),
            },
        )
        response = jsonify({"status": "ok"})
        set_access_cookies(response, cookie_token)
        return response, 200

    @app.route("/api/auth/logout", methods=["POST", "GET"])
    def api_auth_logout():
        """Revoke the current JWT (jti) and clear client session cookies."""
        try:
            verify_jwt_in_request(optional=True)
            claims = get_jwt()
            if claims and claims.get("jti"):
                exp = float(claims.get("exp", time.time() + 900))
                _revoke_jti(str(claims["jti"]), exp)
        except Exception:
            pass

        response = jsonify({"status": "ok", "message": "Oturum başarıyla kapatıldı."})
        unset_jwt_cookies(response)
        response.delete_cookie("access_token_cookie", path="/")
        return response, 200

    @app.route("/api/scan", methods=["POST"])
    @jwt_required()
    @require_roles("admin", "trader")
    @limiter.limit("10 per minute")
    def api_scan():
        start_time = time.time()
        try:
            payload = _safe_json_payload()
            force_refresh = _coerce_bool(
                payload.get("force_refresh", request.args.get("force_refresh"))
            )
            scan_service = get_scan_service()
            logger.info("api_scan_started", force_refresh=force_refresh)

            # Check if a scan is already running (lease-protected against permanent deadlock)
            if not _acquire_scan_lock():
                logger.warning("api_scan_already_in_progress")
                return jsonify(
                    {
                        "status": "error",
                        "message": "A scan is already in progress. Please retry shortly.",
                    }
                ), 429

            abort_event = threading.Event()
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

            def _run_scan() -> list[Any]:
                return scan_service.scan_once(
                    force_refresh=force_refresh, abort_event=abort_event
                )

            scan_future = executor.submit(_run_scan)
            try:
                signals = scan_future.result(timeout=settings.SCAN_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                logger.error(
                    "api_scan_timed_out",
                    timeout_seconds=settings.SCAN_TIMEOUT_SECONDS,
                    force_refresh=force_refresh,
                )
                abort_event.set()
                scan_future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
                _release_scan_lock()
                return jsonify(
                    {
                        "status": "error",
                        "message": "Scan timed out",
                        "timeout_seconds": settings.SCAN_TIMEOUT_SECONDS,
                    }
                ), 504
            else:
                executor.shutdown(wait=True)
                _release_scan_lock()
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
            _release_scan_lock()
            logger.exception(
                "api_scan_failed",
                error=exc,
                duration_ms=round((time.time() - start_time) * 1000, 2),
                component="dashboard",
            )
            return jsonify({"status": "error", "message": "scan provider unavailable"}), 500

    @app.route("/api/orders/intents/<client_id>/resolve", methods=["POST"])
    @jwt_required()
    @require_roles("admin")
    @limiter.limit("10 per minute")
    def resolve_order_intent(client_id: str):
        if not client_id or len(client_id) > 128:
            return jsonify({"status": "error", "message": "Invalid client_id"}), 400
        data = _safe_json_payload()
        resolution = str(data.get("resolution", data.get("status", ""))).lower()
        if resolution not in {"ack", "ack_unaccounted", "rejected"}:
            return jsonify(
                {
                    "status": "error",
                    "message": "resolution must be ack, ack_unaccounted, or rejected",
                }
            ), 400
        reason = str(data.get("reason", data.get("detail", ""))).strip()
        if len(reason) < 10:
            return jsonify(
                {"status": "error", "message": "reason must be at least 10 characters"}
            ), 400
        if data.get("confirmed_in_broker_ui") is not True:
            return (
                jsonify({"status": "error", "message": "confirmed_in_broker_ui must be true"}),
                400,
            )
        broker_order_id = str(data.get("broker_order_id", "")).strip() or None
        if resolution in {"ack", "ack_unaccounted"} and not broker_order_id:
            return jsonify(
                {"status": "error", "message": "broker_order_id is required for ack resolutions"}
            ), 400

        repository = getattr(get_db(), "order_intents", None)
        if repository is None:
            return jsonify({"status": "error", "message": "Order intent store unavailable"}), 503

        existing_intent = repository.get(client_id)
        if existing_intent is None:
            return jsonify({"status": "error", "message": "Order intent not found"}), 404

        # Cross-check or parse filled quantity and average fill price for ack.
        # A full ack is only possible with broker-history verification; body
        # values alone can only ever yield ack_unaccounted.
        filled_qty = data.get("filled_qty")
        avg_fill_price = data.get("avg_fill_price")
        history_verified = False
        history_error = False
        history_state: str | None = None
        history_filled: float | None = None

        # Try pulling from broker history if broker is wired
        broker = get_broker()
        if (
            broker
            and hasattr(broker, "get_daily_orders")
            and hasattr(existing_intent.get("created_at"), "date")
        ):
            try:
                intent_date = existing_intent["created_at"].date()
                daily_orders = broker.get_daily_orders(intent_date)
                match = next(
                    (
                        o
                        for o in daily_orders
                        if o.broker_order_id == broker_order_id or o.order_id == broker_order_id
                    ),
                    None,
                )
                if match:
                    history_verified = True
                    history_filled = float(getattr(match, "filled_quantity", 0.0) or 0.0)
                    history_avg = getattr(match, "average_fill_price", None)
                    history_state = str(getattr(match.state, "value", match.state))
                    if filled_qty is not None and abs(float(filled_qty) - history_filled) > 1e-6:
                        return jsonify(
                            {
                                "status": "error",
                                "message": f"Conflict: body filled_qty ({filled_qty}) does not match broker history ({history_filled})",
                            }
                        ), 409
                    if (
                        avg_fill_price is not None
                        and history_avg is not None
                        and abs(float(avg_fill_price) - float(history_avg)) > 1e-4
                    ):
                        return jsonify(
                            {
                                "status": "error",
                                "message": f"Conflict: body avg_fill_price ({avg_fill_price}) does not match broker history ({history_avg})",
                            }
                        ), 409
                    if filled_qty is None:
                        filled_qty = history_filled
                    if avg_fill_price is None:
                        avg_fill_price = history_avg
                else:
                    logger.warning(
                        "resolve_broker_order_not_in_history",
                        order_id=broker_order_id,
                    )
            except Exception as exc:
                history_error = True
                logger.warning("resolve_broker_history_check_failed", error=str(exc))
        else:
            history_error = True

        # A filled order must never be hidden behind a rejected resolution.
        if resolution == "rejected":
            never_submitted = (
                str(existing_intent.get("status", "")).lower() == "pending"
                and not existing_intent.get("broker_order_id")
                and not broker_order_id
            )
            if not never_submitted:
                if history_error or not history_verified:
                    return jsonify(
                        {
                            "status": "error",
                            "message": "Broker history unavailable; terminal state cannot be "
                            "verified. Use ack_unaccounted instead.",
                        }
                    ), 503
            if (history_filled or 0.0) > 0:
                return jsonify(
                    {
                        "status": "error",
                        "message": "Broker history shows fills; a filled order cannot be "
                        "resolved as rejected. Use ack or ack_unaccounted.",
                    }
                ), 409
            if history_state not in {"CANCELLED", "REJECTED"}:
                return jsonify(
                    {
                        "status": "error",
                        "message": f"Broker history state is {history_state}; only terminal "
                        "CANCELLED/REJECTED with zero fills may resolve as rejected.",
                    }
                ), 409

        # If resolution is ack, require accounting if possible.
        # Without broker-history verification a full ack is never granted.
        if resolution == "ack" and not history_verified:
            resolution = "ack_unaccounted"
            reason = f"{reason} (unaccounted: broker history unavailable for verification)"
        if resolution == "ack":
            if filled_qty is None or avg_fill_price is None:
                resolution = "ack_unaccounted"
                reason = f"{reason} (unaccounted: missing fill qty or price)"
            else:
                try:
                    from bist_bot.agent.position_manager import PositionManager
                    from bist_bot.execution.reconcile_accounting import ReconcileAccountingService

                    pm = PositionManager(get_db(), settings)
                    accounting = ReconcileAccountingService(db=get_db(), position_manager=pm)
                    outcome = accounting.record_fill(
                        intent=existing_intent,
                        broker_order_id=broker_order_id,
                        filled_qty=float(filled_qty),
                        avg_fill_price=float(avg_fill_price),
                        broker_state="FILLED",
                    )
                    if not outcome.success:
                        resolution = outcome.status
                        reason = f"{reason} (accounting detail: {outcome.detail})"
                except Exception:
                    logger.exception("resolve_manual_accounting_failed", client_id=client_id)
                    resolution = "ack_unaccounted"
                    reason = f"{reason} (accounting failed)"

        row = repository.update(
            client_id,
            status=resolution,
            broker_order_id=broker_order_id,
            detail=reason,
            release_lock=True,
        )
        if row is None:
            return jsonify({"status": "error", "message": "Order intent not found"}), 404
        claims = get_jwt()
        audit_details = {
            "user_id": str(get_jwt_identity() or ""),
            "role": claims.get("role"),
            "route": request.path,
            "request_id": _request_id(),
            "client_id": client_id,
            "resolution": resolution,
            "broker_order_id": broker_order_id,
            "reason": reason,
            "confirmed_in_broker_ui": True,
        }
        if resolution == "rejected":
            logger.error(
                "order_intent_manually_resolved",
                order_id=client_id,
                severity="critical",
                **{k: v for k, v in audit_details.items() if k != "reason"},
                reason=reason,
            )
        else:
            logger.warning(
                "order_intent_manually_resolved",
                order_id=client_id,
                **{k: v for k, v in audit_details.items() if k != "reason"},
                reason=reason,
            )
        _write_security_audit(
            "order_intent_manually_resolved",
            audit_details,
        )
        return jsonify(
            {
                "status": "ok",
                "client_id": client_id,
                "resolution": resolution,
                "lock_released": True,
            }
        )

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

            # Check universe membership if fetcher has watchlist
            runtime_fetcher = get_fetcher()
            watchlist = getattr(runtime_fetcher, "watchlist", None)
            if watchlist and normalized_ticker not in watchlist and raw not in watchlist:
                # Still allow analysis if universe is not strictly enforced, but log
                logger.debug("api_analyze_external_ticker", ticker=normalized_ticker)
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
            # Parse requested timeframe / interval / period
            req_interval = request.args.get("interval", "").strip().lower()
            req_period = request.args.get("period", "").strip().lower()
            tf_map = {
                "15m": ("5d", "15m"),
                "15d": ("5d", "15m"),
                "1h": ("1mo", "60m"),
                "1s": ("1mo", "60m"),
                "60m": ("1mo", "60m"),
                "4h": ("3mo", "60m"),
                "4s": ("3mo", "60m"),
                "1d": ("6mo", "1d"),
                "1g": ("6mo", "1d"),
                "günlük": ("6mo", "1d"),
                "gunluk": ("6mo", "1d"),
                "1w": ("1y", "1wk"),
                "1wk": ("1y", "1wk"),
                "haftalık": ("1y", "1wk"),
                "haftalik": ("1y", "1wk"),
            }
            _ALLOWED_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"}
            _ALLOWED_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo"}
            if req_interval in tf_map:
                target_period, target_interval = tf_map[req_interval]
            elif req_period in _ALLOWED_PERIODS and req_interval in _ALLOWED_INTERVALS:
                target_period, target_interval = req_period, req_interval
            else:
                target_period, target_interval = "6mo", settings.DATA_INTERVAL

            if use_mtf_analysis and fetch_mtf is not None:
                cache_key = (
                    f"{normalized_ticker}|analyze|mtf|"
                    f"{settings.MTF_TREND_PERIOD}:{settings.MTF_TREND_INTERVAL}|"
                    f"{settings.MTF_TRIGGER_PERIOD}:{settings.MTF_TRIGGER_INTERVAL}"
                )
            else:
                cache_key = f"{normalized_ticker}|analyze|single|{target_period}:{target_interval}"

            cached_response = runtime_fetcher.get_cached_analysis(cache_key, force=force_refresh)
            if cached_response is not None:
                payload = dict(cached_response)
                payload["duration_ms"] = round((time.time() - start_time) * 1000, 2)
                payload["force_refresh"] = force_refresh
                payload["timeframe"] = {"period": target_period, "interval": target_interval}
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
                    normalized_ticker,
                    period=target_period,
                    interval=target_interval,
                    force=force_refresh,
                )
                analysis_input = chart_df
                fetch_meta_raw = (
                    fetch_meta_getter(normalized_ticker, target_period, target_interval)
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
                    "date": str(idx)[:19],
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
                "timeframe": {"period": target_period, "interval": target_interval},
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
        compact = _coerce_bool(request.args.get("compact"))
        signals = get_db().get_recent_signals(limit=limit, ticker=ticker)
        if compact:
            # UI renders only reasons[0]; conditions are never read client-side.
            # Strip them to cut ~70% of payload (opt-in, default unchanged).
            trimmed = []
            for sig in signals:
                s = dict(sig)
                s.pop("conditions", None)
                reasons = s.get("reasons")
                if isinstance(reasons, list):
                    s["reasons"] = reasons[:1]
                trimmed.append(s)
            signals = trimmed
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

        # Market breadth calculation from recent signals
        recent_signals = get_db().get_recent_signals(limit=40)
        rsi_vals: list[float] = []
        actionable_symbols: list[str] = []
        vol_up_count = 0

        for sig in recent_signals:
            st = str(sig.get("signal_type", "")).upper()
            ticker = str(sig.get("ticker", "")).replace(".IS", "")
            if ("AL" in st or "SAT" in st or "BUY" in st or "SELL" in st) and ticker not in actionable_symbols:
                actionable_symbols.append(ticker)
            for cond in sig.get("conditions", []):
                cond_str = str(cond)
                if "Hacim artıyor" in cond_str or "Fiyat-Hacim" in cond_str:
                    vol_up_count += 1
                m = re.search(r"RSI.*?\((\d+\.?\d*)\)", cond_str)
                if m:
                    try:
                        rsi_vals.append(float(m.group(1)))
                    except ValueError:
                        pass

        avg_rsi = round(sum(rsi_vals) / len(rsi_vals), 1) if rsi_vals else 54.2
        if avg_rsi >= 65:
            rsi_status = "Aşırı Alım Bölgesi"
        elif avg_rsi >= 55:
            rsi_status = "Dinamik Nötr-Alış"
        elif avg_rsi >= 45:
            rsi_status = "Dengeli Nötr"
        elif avg_rsi >= 35:
            rsi_status = "Dinamik Nötr-Satış"
        else:
            rsi_status = "Aşırı Satım Bölgesi"

        vol_ratio = round(1.0 + (vol_up_count / max(1, len(recent_signals))), 2)
        actionable_summary = (
            ", ".join(actionable_symbols[:3]) + (f" +{len(actionable_symbols)-3}" if len(actionable_symbols) > 3 else "")
            if actionable_symbols else "Beklemede"
        )

        breadth = {
            "avg_rsi": avg_rsi,
            "rsi_status": rsi_status,
            "vol_ratio": f"{vol_ratio:.2f}x",
            "actionable_tickers": actionable_symbols[:5],
            "actionable_summary": actionable_summary,
        }

        return jsonify(
            {
                "status": "ok",
                "stats": stats,
                "latest_scan": latest_scan,
                "rejection_breakdown": latest_scan["rejection_breakdown"],
                "breadth": breadth,
                "benchmarks": _get_live_benchmarks(),
            }
        )

    @app.route("/api/scans/history")
    @jwt_required()
    def api_scan_history():
        limit = max(1, min(request.args.get("limit", 20, type=int) or 20, 100))
        scan_rows = get_db().get_recent_scan_logs(limit=limit)
        history = _build_scan_history_payload(scan_rows, limit)
        return jsonify({"status": "ok", "history": history})

    # -----------------------------------------------------------------------
    # Stitch 1:1 Pixel-Exact UI Routes (Modern Web Sitesi Yenileme)
    # -----------------------------------------------------------------------
    def _ui_auth_required(view):
        """Server-side gate for /ui/* HTML pages (the login page stays public).

        The HttpOnly JWT cookie is the authority here; /api/* keeps using the
        Authorization header. Cookie auth only ever guards GET page renders,
        so no CSRF token dance is needed (unsafe methods still require the
        header). Missing/invalid cookie -> 302 to /login.
        """

        @wraps(view)
        def wrapped(*args, **kwargs):
            try:
                verify_jwt_in_request(locations=["cookies"])
            except Exception:
                # Fail closed: missing, malformed (raw PyJWT errors escape
                # Flask-JWT-Extended's own hierarchy on the cookie path),
                # expired, or wrong-type tokens all bounce to /login.
                logger.info("ui_auth_redirect_login", route=request.path)
                resp = redirect("/login", code=302)
                resp.delete_cookie("access_token_cookie", path="/")
                return resp
            return view(*args, **kwargs)

        return wrapped

    @app.route("/login")
    @app.route("/ui/login")
    def ui_login():
        return render_template("stitch/login.html")

    @app.route("/")
    @app.route("/ui")
    @app.route("/ui/dashboard")
    @_ui_auth_required
    def ui_dashboard():
        return render_template("stitch/dashboard.html")

    @app.route("/ui/signals")
    @_ui_auth_required
    def ui_signals():
        return render_template("stitch/signals.html")

    @app.route("/ui/analysis")
    @_ui_auth_required
    def ui_analysis():
        return render_template("stitch/analysis.html")

    @app.route("/ui/settings")
    @_ui_auth_required
    def ui_settings():
        return render_template("stitch/settings.html")

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
