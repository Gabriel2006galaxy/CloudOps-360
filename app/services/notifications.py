import logging

from app.extensions import db
from app.models import Notification, utcnow

logger = logging.getLogger(__name__)

VALID_TYPES = ('info', 'success', 'warning', 'danger')


def is_safe_internal_link(link):
    """Only relative, same-site paths are stored/redirected to (no open redirects)."""
    return bool(link) and link.startswith('/') and not link.startswith('//') and '\\' not in link


def create_notification(user_id, title, message, link=None, type='info', commit=True):
    """Creates a database-backed notification for a user.

    commit=False stages it in the caller's transaction.
    """
    if not user_id:
        return None
    try:
        notif = Notification(
            user_id=user_id,
            title=title[:120],
            message=message,
            link=link if is_safe_internal_link(link) else None,
            type=type if type in VALID_TYPES else 'info',
            is_read=False,
            created_at=utcnow(),
        )
        db.session.add(notif)
        if commit:
            db.session.commit()
        return notif
    except Exception as exc:  # noqa: BLE001
        if commit:
            db.session.rollback()
        logger.error("[Notifications] Could not create notification: %s", type(exc).__name__)
        return None


def get_unread_count(user_id):
    if not user_id:
        return 0
    return Notification.query.filter_by(user_id=user_id, is_read=False).count()


def get_user_notifications(user_id, limit=10):
    if not user_id:
        return []
    return (Notification.query.filter_by(user_id=user_id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit).all())


def mark_notification_as_read(notification_id, user_id):
    """Marks one notification read - only if it belongs to the user."""
    notif = Notification.query.filter_by(id=notification_id, user_id=user_id).first()
    if not notif:
        return None
    if not notif.is_read:
        notif.is_read = True
        db.session.commit()
    return notif


def mark_all_notifications_as_read(user_id):
    if not user_id:
        return 0
    updated = Notification.query.filter_by(user_id=user_id, is_read=False).update({'is_read': True})
    db.session.commit()
    return updated
