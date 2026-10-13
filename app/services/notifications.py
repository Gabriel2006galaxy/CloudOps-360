from datetime import datetime, timezone
from app.extensions import db
from app.models import Notification


def create_notification(user_id, title, message, link=None, type='info'):
    """
    Creates a database-backed notification for a specific user.
    Types: 'info', 'success', 'warning', 'danger'
    """
    if not user_id:
        return None
    try:
        notif = Notification(
            user_id=user_id,
            title=title,
            message=message,
            link=link,
            type=type,
            is_read=False,
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(notif)
        db.session.commit()
        return notif
    except Exception as e:
        db.session.rollback()
        print(f"[NotificationService] Error creating notification: {e}")
        return None


def get_unread_count(user_id):
    """Returns number of unread notifications for user."""
    if not user_id:
        return 0
    return Notification.query.filter_by(user_id=user_id, is_read=False).count()


def get_user_notifications(user_id, limit=10):
    """Retrieves recent notifications for the dropdown and notification center."""
    if not user_id:
        return []
    return Notification.query.filter_by(user_id=user_id).order_by(Notification.created_at.desc()).limit(limit).all()


def mark_notification_as_read(notification_id, user_id):
    """Marks a single notification as read if owned by the user."""
    notif = Notification.query.filter_by(id=notification_id, user_id=user_id).first()
    if notif:
        notif.is_read = True
        db.session.commit()
        return True
    return False


def mark_all_notifications_as_read(user_id):
    """Marks all notifications as read for a given user."""
    if not user_id:
        return 0
    updated = Notification.query.filter_by(user_id=user_id, is_read=False).update({'is_read': True})
    db.session.commit()
    return updated
