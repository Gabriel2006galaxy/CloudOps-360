"""Database-backed sign-in rate limiting.

An account is locked after LOGIN_MAX_FAILED_PER_ACCOUNT failed attempts within
LOGIN_LOCKOUT_WINDOW_MINUTES (failures before the last successful sign-in do not
count). A client IP is throttled after LOGIN_MAX_FAILED_PER_IP failures in the
same window, which also slows password spraying across many accounts.
"""
from datetime import timedelta

from flask import current_app
from sqlalchemy import func

from app.extensions import db
from app.models import LoginAttempt, utcnow


def normalize_identifier(identifier):
    return (identifier or '').strip().lower()[:120]


def _window_start():
    minutes = current_app.config.get('LOGIN_LOCKOUT_WINDOW_MINUTES', 15)
    return utcnow() - timedelta(minutes=minutes)


def login_lock_status(identifier, ip_address):
    """Returns (locked, retry_after_seconds, reason)."""
    window_start = _window_start()
    identifier = normalize_identifier(identifier)
    cfg = current_app.config

    last_success = (db.session.query(func.max(LoginAttempt.created_at))
                    .filter(LoginAttempt.identifier == identifier, LoginAttempt.success.is_(True))
                    .scalar())
    since = max(window_start, last_success) if last_success else window_start

    account_failures = (LoginAttempt.query
                        .filter(LoginAttempt.identifier == identifier,
                                LoginAttempt.success.is_(False),
                                LoginAttempt.created_at > since)
                        .order_by(LoginAttempt.created_at.asc()).all())
    if len(account_failures) >= cfg.get('LOGIN_MAX_FAILED_PER_ACCOUNT', 5):
        oldest = account_failures[-cfg.get('LOGIN_MAX_FAILED_PER_ACCOUNT', 5)].created_at
        retry = int((oldest - window_start).total_seconds()) + 1
        return True, max(retry, 1), 'account'

    if ip_address:
        ip_failures = (LoginAttempt.query
                       .filter(LoginAttempt.ip_address == ip_address,
                               LoginAttempt.success.is_(False),
                               LoginAttempt.created_at > window_start)
                       .count())
        if ip_failures >= cfg.get('LOGIN_MAX_FAILED_PER_IP', 20):
            return True, cfg.get('LOGIN_LOCKOUT_WINDOW_MINUTES', 15) * 60, 'ip'

    return False, 0, None


def record_login_attempt(identifier, ip_address, success):
    db.session.add(LoginAttempt(
        identifier=normalize_identifier(identifier),
        ip_address=(ip_address or '')[:45] or None,
        success=bool(success),
        created_at=utcnow(),
    ))
    db.session.commit()


def purge_old_attempts(days=30):
    """Housekeeping for the `flask purge-login-attempts` command."""
    cutoff = utcnow() - timedelta(days=days)
    deleted = LoginAttempt.query.filter(LoginAttempt.created_at < cutoff).delete()
    db.session.commit()
    return deleted
