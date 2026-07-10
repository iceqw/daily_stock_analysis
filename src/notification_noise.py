# -*- coding: utf-8 -*-
"""In-process notification noise-control helpers.

The primary state is process-local memory for hot-path performance, with an
optional SQLite persistence layer for cross-process dedup (e.g. Docker
Compose dual-service deployments).  DB operations are fail-open: on any
error the module falls back to in-memory checks without blocking sends.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

try:  # pragma: no cover - Python <3.9 fallback is not expected in CI.
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore
    ZoneInfoNotFoundError = Exception  # type: ignore

logger = logging.getLogger(__name__)

NOTIFICATION_SEVERITIES: Tuple[str, ...] = ("info", "warning", "error", "critical")
NOTIFICATION_SEVERITY_RANK = {severity: index for index, severity in enumerate(NOTIFICATION_SEVERITIES)}
DEFAULT_NOTIFICATION_SEVERITY_BY_ROUTE = {
    "report": "info",
    "alert": "warning",
    "system_error": "error",
}
P4_NOISE_ENV_KEYS: Tuple[str, ...] = (
    "NOTIFICATION_DEDUP_TTL_SECONDS",
    "NOTIFICATION_COOLDOWN_SECONDS",
    "NOTIFICATION_QUIET_HOURS",
    "NOTIFICATION_TIMEZONE",
    "NOTIFICATION_MIN_SEVERITY",
    "NOTIFICATION_DAILY_DIGEST_ENABLED",
)

_QUIET_HOURS_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")
_INFLIGHT_RESERVATION_SECONDS = 300


@dataclass(frozen=True)
class NotificationNoiseDecision:
    """Decision returned by the notification noise-control gate."""

    should_send: bool
    reason_code: str = "allowed"
    message: str = ""
    route_type: str = "default"
    severity: str = "info"
    dedup_key: Optional[str] = None
    cooldown_key: Optional[str] = None
    dedup_ttl_seconds: int = 0
    cooldown_seconds: int = 0
    evaluated_at: Optional[datetime] = None
    dedup_reserved: bool = False
    cooldown_reserved: bool = False
    reservation_token: Optional[str] = None


_dedup_expires_at: Dict[str, float] = {}
_cooldown_expires_at: Dict[str, float] = {}
_dedup_inflight_until: Dict[str, Tuple[float, str]] = {}
_cooldown_inflight_until: Dict[str, Tuple[float, str]] = {}
_state_lock = threading.Lock()

# ---- SQLite persistence helpers (cross-process dedup) --------------------

_DB_DEDUP_TABLE = "notification_dedup_entries"
_DB_CLEANUP_INTERVAL_SEC = 300  # minimum interval between expired-row cleanups
_last_db_cleanup_at: float = 0.0
_db_table_ready: bool = False


def _resolve_db_path() -> Optional[str]:
    """Return the SQLite database path from config, or None if unavailable."""
    return os.getenv("DATABASE_PATH", "./data/stock_analysis.db") or "./data/stock_analysis.db"


def _get_db_connection():
    """Get a new sqlite3 connection (fail-open: return None on error)."""
    import sqlite3

    db_path = _resolve_db_path()
    if not db_path:
        return None
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    except Exception:
        logger.debug("notification_noise: DB connect failed, falling back to in-memory only")
        return None


def _ensure_db_table() -> bool:
    """Create the dedup table if it does not exist. Idempotent and fail-open."""
    global _db_table_ready
    if _db_table_ready:
        return True
    conn = _get_db_connection()
    if conn is None:
        return False
    try:
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {_DB_DEDUP_TABLE} ("
            "  dedup_key   TEXT PRIMARY KEY,"
            "  expires_at  REAL NOT NULL,"
            "  created_at  REAL NOT NULL DEFAULT (strftime('%s','now'))"
            ")"
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{_DB_DEDUP_TABLE}_expires "
            f"ON {_DB_DEDUP_TABLE}(expires_at)"
        )
        conn.commit()
        _db_table_ready = True
        return True
    except Exception:
        logger.debug("notification_noise: DB table init failed, falling back to in-memory only")
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _db_dedup_exists(conn, dedup_key: str, now_ts: float) -> bool:
    """Check if *dedup_key* exists in DB and is not yet expired."""
    try:
        row = conn.execute(
            f"SELECT expires_at FROM {_DB_DEDUP_TABLE} WHERE dedup_key = ?",
            (dedup_key,),
        ).fetchone()
        return row is not None and row[0] > now_ts
    except Exception:
        return False


def _db_dedup_record(conn, dedup_key: str, expires_ts: float) -> None:
    """Insert or update a dedup entry."""
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO {_DB_DEDUP_TABLE} (dedup_key, expires_at, created_at) "
            "VALUES (?, ?, ?)",
            (dedup_key, expires_ts, time.time()),
        )
        conn.commit()
    except Exception:
        pass


def _db_cleanup_expired(conn, now_ts: float) -> None:
    """Remove expired dedup rows from DB, rate-limited to avoid I/O storms."""
    global _last_db_cleanup_at
    if now_ts - _last_db_cleanup_at < _DB_CLEANUP_INTERVAL_SEC:
        return
    try:
        conn.execute(f"DELETE FROM {_DB_DEDUP_TABLE} WHERE expires_at <= ?", (now_ts,))
        conn.commit()
        _last_db_cleanup_at = now_ts
    except Exception:
        pass


def _check_db_dedup_and_cache(state_key: str, now_ts: float, ttl: int) -> bool:
    """Check SQLite persistence layer for state_key, caching result in memory.

    Returns True if the key is already present in the DB (should suppress).
    On any error, returns False (fail-open: allow the notification).
    Must NOT be called under _state_lock to avoid holding the lock during I/O.
    """
    conn = _get_db_connection()
    if conn is None or not _ensure_db_table():
        return False
    try:
        _db_cleanup_expired(conn, now_ts)
        if _db_dedup_exists(conn, state_key, now_ts):
            # Cache the DB hit in memory so we skip DB lookups in this process
            with _state_lock:
                _dedup_expires_at[state_key] = now_ts + ttl
            return True
        return False
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _record_db_dedup_and_cache(state_key: str, expires_ts: float) -> None:
    """Record a dedup entry to both memory (hot cache) and SQLite (cross-process).

    Fail-open: on any error, the in-memory state is already set by the caller.
    """
    conn = _get_db_connection()
    if conn is None or not _ensure_db_table():
        return
    try:
        _db_dedup_record(conn, state_key, expires_ts)
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def reset_notification_noise_state() -> None:
    """Clear process-local notification noise state. Intended for tests."""
    with _state_lock:
        _dedup_expires_at.clear()
        _cooldown_expires_at.clear()
        _dedup_inflight_until.clear()
        _cooldown_inflight_until.clear()


def is_supported_notification_severity(value: object) -> bool:
    """Return whether *value* is a supported severity string."""
    return str(value or "").strip().lower() in NOTIFICATION_SEVERITY_RANK


def normalize_notification_severity(route_type: Optional[str], severity: Optional[str] = None) -> str:
    """Normalize explicit severity, or derive a default from route type."""
    explicit = str(severity or "").strip().lower()
    if explicit in NOTIFICATION_SEVERITY_RANK:
        return explicit

    route = str(route_type or "").strip().lower()
    return DEFAULT_NOTIFICATION_SEVERITY_BY_ROUTE.get(route, "info")


def parse_notification_quiet_hours(value: Optional[str]) -> Optional[Tuple[int, int]]:
    """Parse ``HH:MM-HH:MM`` into start/end minute-of-day values."""
    raw = str(value or "").strip()
    if not raw:
        return None

    match = _QUIET_HOURS_RE.match(raw)
    if not match:
        raise ValueError("NOTIFICATION_QUIET_HOURS must be in HH:MM-HH:MM format")

    start_hour, start_minute, end_hour, end_minute = [int(group) for group in match.groups()]
    return start_hour * 60 + start_minute, end_hour * 60 + end_minute


def validate_notification_timezone(value: Optional[str]) -> None:
    """Validate an optional IANA timezone name."""
    raw = str(value or "").strip()
    if not raw:
        return
    if ZoneInfo is None:
        raise ValueError("zoneinfo is unavailable")
    try:
        ZoneInfo(raw)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {raw}") from exc


def is_time_in_quiet_hours(now: datetime, quiet_hours: Tuple[int, int]) -> bool:
    """Return whether *now* falls inside a quiet-hours interval."""
    start_minute, end_minute = quiet_hours
    minute_of_day = now.hour * 60 + now.minute

    if start_minute == end_minute:
        return False
    if start_minute < end_minute:
        return start_minute <= minute_of_day < end_minute
    return minute_of_day >= start_minute or minute_of_day < end_minute


def _resolve_now(timezone_name: Optional[str], now: Optional[datetime]) -> datetime:
    raw_timezone = str(timezone_name or "").strip()
    if raw_timezone:
        if ZoneInfo is None:
            raise ValueError("zoneinfo is unavailable")
        tz = ZoneInfo(raw_timezone)
        if now is None:
            return datetime.now(tz)
        if now.tzinfo is None:
            return now.replace(tzinfo=tz)
        return now.astimezone(tz)

    if now is None:
        return datetime.now().astimezone()
    if now.tzinfo is not None:
        return now.astimezone()
    return now


def _timestamp(now: datetime) -> float:
    return now.timestamp()


def _cleanup_expired(now_ts: float) -> None:
    expired_dedup = [key for key, expires_at in _dedup_expires_at.items() if expires_at <= now_ts]
    for key in expired_dedup:
        _dedup_expires_at.pop(key, None)

    expired_cooldown = [key for key, expires_at in _cooldown_expires_at.items() if expires_at <= now_ts]
    for key in expired_cooldown:
        _cooldown_expires_at.pop(key, None)

    expired_dedup_inflight = [
        key
        for key, (expires_at, _token) in _dedup_inflight_until.items()
        if expires_at <= now_ts
    ]
    for key in expired_dedup_inflight:
        _dedup_inflight_until.pop(key, None)

    expired_cooldown_inflight = [
        key
        for key, (expires_at, _token) in _cooldown_inflight_until.items()
        if expires_at <= now_ts
    ]
    for key in expired_cooldown_inflight:
        _cooldown_inflight_until.pop(key, None)


def _stable_content_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _state_key(prefix: str, route_type: str, severity: str, key: str) -> str:
    return f"{prefix}:{route_type}:{severity}:{key}"


def _build_keys(
    *,
    content: str,
    route_type: str,
    severity: str,
    dedup_key: Optional[str],
    cooldown_key: Optional[str],
) -> Tuple[str, str]:
    dedup_part = str(dedup_key).strip() if dedup_key else _stable_content_hash(content)
    cooldown_part = str(cooldown_key).strip() if cooldown_key else "default"
    return (
        _state_key("dedup", route_type, severity, dedup_part),
        _state_key("cooldown", route_type, severity, cooldown_part),
    )


def evaluate_notification_noise(
    config: object,
    *,
    content: str,
    route_type: Optional[str],
    severity: Optional[str] = None,
    dedup_key: Optional[str] = None,
    cooldown_key: Optional[str] = None,
    now: Optional[datetime] = None,
) -> NotificationNoiseDecision:
    """Evaluate whether static notification channels should be sent.

    This function is fail-open: invalid runtime state or unexpected exceptions
    produce an allow decision and a warning log rather than blocking notification.
    """
    try:
        return _evaluate_notification_noise(
            config,
            content=content,
            route_type=route_type,
            severity=severity,
            dedup_key=dedup_key,
            cooldown_key=cooldown_key,
            now=now,
        )
    except Exception as exc:  # pragma: no cover - defensive behavior is tested via monkeypatch.
        logger.warning("通知降噪判断失败，将继续发送静态通知渠道: %s", exc)
        return NotificationNoiseDecision(
            should_send=True,
            reason_code="noise_check_failed_open",
            message="Noise-control check failed open.",
            route_type=str(route_type or "default").strip().lower() or "default",
            severity=normalize_notification_severity(route_type, severity),
        )


def _evaluate_notification_noise(
    config: object,
    *,
    content: str,
    route_type: Optional[str],
    severity: Optional[str],
    dedup_key: Optional[str],
    cooldown_key: Optional[str],
    now: Optional[datetime],
) -> NotificationNoiseDecision:
    route = str(route_type or "default").strip().lower() or "default"
    resolved_severity = normalize_notification_severity(route, severity)
    dedup_ttl = max(0, int(getattr(config, "notification_dedup_ttl_seconds", 0) or 0))
    cooldown = max(0, int(getattr(config, "notification_cooldown_seconds", 0) or 0))
    quiet_hours_raw = getattr(config, "notification_quiet_hours", "") or ""
    timezone_name = getattr(config, "notification_timezone", "") or ""
    min_severity_raw = str(getattr(config, "notification_min_severity", "") or "").strip().lower()

    effective_now = _resolve_now(timezone_name, now)
    now_ts = _timestamp(effective_now)
    decision_base = {
        "route_type": route,
        "severity": resolved_severity,
        "dedup_ttl_seconds": dedup_ttl,
        "cooldown_seconds": cooldown,
        "evaluated_at": effective_now,
    }

    if min_severity_raw:
        if min_severity_raw not in NOTIFICATION_SEVERITY_RANK:
            logger.warning("NOTIFICATION_MIN_SEVERITY=%s 无效，将忽略最低级别过滤", min_severity_raw)
        elif NOTIFICATION_SEVERITY_RANK[resolved_severity] < NOTIFICATION_SEVERITY_RANK[min_severity_raw]:
            return NotificationNoiseDecision(
                should_send=False,
                reason_code="min_severity",
                message=(
                    f"通知级别 {resolved_severity} 低于最低级别 {min_severity_raw}，"
                    "已跳过静态通知渠道。"
                ),
                **decision_base,
            )

    quiet_hours = parse_notification_quiet_hours(quiet_hours_raw)
    if quiet_hours and is_time_in_quiet_hours(effective_now, quiet_hours):
        return NotificationNoiseDecision(
            should_send=False,
            reason_code="quiet_hours",
            message=f"当前时间处于静默时段 {quiet_hours_raw}，已跳过静态通知渠道。",
            **decision_base,
        )

    dedup_state_key, cooldown_state_key = _build_keys(
        content=content,
        route_type=route,
        severity=resolved_severity,
        dedup_key=dedup_key,
        cooldown_key=cooldown_key,
    )
    with _state_lock:
        _cleanup_expired(now_ts)
        if dedup_ttl > 0 and _dedup_expires_at.get(dedup_state_key, 0) > now_ts:
            return NotificationNoiseDecision(
                should_send=False,
                reason_code="dedup",
                message="通知内容在去重 TTL 内已发送，已跳过静态通知渠道。",
                dedup_key=dedup_state_key,
                cooldown_key=cooldown_state_key,
                **decision_base,
            )
        dedup_inflight = _dedup_inflight_until.get(dedup_state_key)
        if dedup_ttl > 0 and dedup_inflight and dedup_inflight[0] > now_ts:
            return NotificationNoiseDecision(
                should_send=False,
                reason_code="dedup_inflight",
                message="同一通知正在发送中，已跳过静态通知渠道。",
                dedup_key=dedup_state_key,
                cooldown_key=cooldown_state_key,
                **decision_base,
            )
        if cooldown > 0 and _cooldown_expires_at.get(cooldown_state_key, 0) > now_ts:
            return NotificationNoiseDecision(
                should_send=False,
                reason_code="cooldown",
                message="通知冷却时间尚未结束，已跳过静态通知渠道。",
                dedup_key=dedup_state_key,
                cooldown_key=cooldown_state_key,
                **decision_base,
            )
        cooldown_inflight = _cooldown_inflight_until.get(cooldown_state_key)
        if cooldown > 0 and cooldown_inflight and cooldown_inflight[0] > now_ts:
            return NotificationNoiseDecision(
                should_send=False,
                reason_code="cooldown_inflight",
                message="同一通知正在发送中，已跳过静态通知渠道。",
                dedup_key=dedup_state_key,
                cooldown_key=cooldown_state_key,
                **decision_base,
            )

        reservation_until = now_ts + _INFLIGHT_RESERVATION_SECONDS
        dedup_reserved = dedup_ttl > 0
        cooldown_reserved = cooldown > 0
        reservation_token = uuid.uuid4().hex if dedup_reserved or cooldown_reserved else None
        if dedup_reserved:
            _dedup_inflight_until[dedup_state_key] = (reservation_until, reservation_token)
        if cooldown_reserved:
            _cooldown_inflight_until[cooldown_state_key] = (reservation_until, reservation_token)

    # ---- cross-process DB dedup check (outside _state_lock to avoid deadlock) ----
    _db_suppressed = False
    if dedup_ttl > 0:
        _db_suppressed = _check_db_dedup_and_cache(dedup_state_key, now_ts, dedup_ttl)
    if not _db_suppressed and cooldown > 0:
        _db_suppressed = _check_db_dedup_and_cache(cooldown_state_key, now_ts, cooldown)
    if _db_suppressed:
        return NotificationNoiseDecision(
            should_send=False,
            reason_code="dedup_db",
            message="通知在跨进程去重记录中已存在，已跳过静态通知渠道。",
            dedup_key=dedup_state_key,
            cooldown_key=cooldown_state_key,
            **decision_base,
        )

    return NotificationNoiseDecision(
        should_send=True,
        dedup_key=dedup_state_key,
        cooldown_key=cooldown_state_key,
        dedup_reserved=dedup_reserved,
        cooldown_reserved=cooldown_reserved,
        reservation_token=reservation_token,
        **decision_base,
    )


def _release_reserved_locked(decision: NotificationNoiseDecision) -> None:
    if decision.dedup_reserved and decision.dedup_key:
        dedup_inflight = _dedup_inflight_until.get(decision.dedup_key)
        if dedup_inflight and dedup_inflight[1] == decision.reservation_token:
            _dedup_inflight_until.pop(decision.dedup_key, None)
    if decision.cooldown_reserved and decision.cooldown_key:
        cooldown_inflight = _cooldown_inflight_until.get(decision.cooldown_key)
        if cooldown_inflight and cooldown_inflight[1] == decision.reservation_token:
            _cooldown_inflight_until.pop(decision.cooldown_key, None)


def release_notification_noise(decision: NotificationNoiseDecision) -> None:
    """Release in-flight reservation without recording dedup/cooldown state."""
    if not decision.should_send:
        return

    try:
        with _state_lock:
            _release_reserved_locked(decision)
    except Exception as exc:  # pragma: no cover - defensive branch.
        logger.warning("通知降噪发送中状态释放失败，忽略该错误: %s", exc)


def record_notification_noise(decision: NotificationNoiseDecision, now: Optional[datetime] = None) -> None:
    """Record dedup/cooldown state after a static notification send succeeds."""
    if not decision.should_send or decision.evaluated_at is None:
        return

    try:
        record_at = now
        if record_at is None:
            record_at = datetime.now(decision.evaluated_at.tzinfo)
        now_ts = _timestamp(record_at)
        with _state_lock:
            _cleanup_expired(now_ts)
            _release_reserved_locked(decision)
            if decision.dedup_ttl_seconds > 0 and decision.dedup_key:
                _dedup_expires_at[decision.dedup_key] = now_ts + decision.dedup_ttl_seconds
            if decision.cooldown_seconds > 0 and decision.cooldown_key:
                _cooldown_expires_at[decision.cooldown_key] = now_ts + decision.cooldown_seconds
        # Persist to SQLite for cross-process dedup (outside lock, fail-open)
        if decision.dedup_ttl_seconds > 0 and decision.dedup_key:
            _record_db_dedup_and_cache(decision.dedup_key, now_ts + decision.dedup_ttl_seconds)
        if decision.cooldown_seconds > 0 and decision.cooldown_key:
            _record_db_dedup_and_cache(decision.cooldown_key, now_ts + decision.cooldown_seconds)
    except Exception as exc:  # pragma: no cover - defensive branch.
        logger.warning("通知降噪状态记录失败，忽略该错误: %s", exc)
