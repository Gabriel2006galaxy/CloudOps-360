import logging
import re

from flask import has_request_context, request
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog

logger = logging.getLogger(__name__)

# Defence in depth: scrub anything that looks like a credential before it is stored
_SECRET_PATTERNS = [
    (re.compile(r'(?i)(password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]\s*\S+'), r'\1=[REDACTED]'),
    (re.compile(r'(mysql\+pymysql://[^:/\s]+):[^@\s]+@'), r'\1:[REDACTED]@'),
]


def scrub_secrets(text):
    if not text:
        return text
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def client_ip():
    """Client IP. Behind Nginx, ProxyFix (TRUSTED_PROXY_COUNT) has already resolved
    X-Forwarded-For safely, so the raw header is never trusted here."""
    if not has_request_context():
        return None
    return (request.remote_addr or '')[:45] or None


def log_audit_event(action, entity_type=None, entity_id=None, details=None, user_id=None, commit=True):
    """Records an audit log entry for compliance and security forensics.

    - action: identifier, e.g. 'AUTH_LOGIN_SUCCESS', 'TICKET_STATUS_CHANGE'
    - commit=False stages the entry in the caller's transaction so the audit
      record and the change it describes are committed atomically.
    Never pass passwords or secrets; details are scrubbed as a safety net.
    """
    try:
        actor_id = user_id
        if actor_id is None and has_request_context() and current_user and current_user.is_authenticated:
            actor_id = current_user.id

        user_agent = None
        if has_request_context() and request.user_agent:
            user_agent = (request.user_agent.string or '')[:250] or None

        entry = AuditLog(
            user_id=actor_id,
            action=action[:64],
            entity_type=entity_type,
            entity_id=str(entity_id)[:64] if entity_id is not None else None,
            details=scrub_secrets(details),
            ip_address=client_ip(),
            user_agent=user_agent,
        )
        db.session.add(entry)
        if commit:
            db.session.commit()
        return entry
    except Exception as exc:  # noqa: BLE001 - audit failure must not break the request
        if commit:
            db.session.rollback()
        logger.error("[Audit] Failed to record audit event %s: %s", action, type(exc).__name__)
        return None
