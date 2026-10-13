import logging

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Notification
from app.services.notifications import (
    get_unread_count, is_safe_internal_link, mark_all_notifications_as_read, mark_notification_as_read,
)
from app.services.secrets import describe_database
from app.services.storage import get_storage

main_bp = Blueprint('main', __name__)
logger = logging.getLogger(__name__)


@main_bp.route('/')
def index():
    """Public landing page."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    return render_template('landing.html')


@main_bp.route('/health')
def health():
    """Load balancer / monitoring health check.

    Reports database connectivity and storage (EFS) writability plus the
    instance hostname, which makes multi-instance EFS demos easy. Error details
    are logged server-side only - never returned to the caller.
    """
    status = {'status': 'healthy', 'services': {}}
    try:
        db.session.execute(db.text('SELECT 1'))
        status['services']['database'] = {
            'status': 'connected',
            'engine': describe_database(current_app.config.get('SQLALCHEMY_DATABASE_URI')),
        }
    except Exception as exc:  # noqa: BLE001
        logger.error('[Health] Database check failed: %s', type(exc).__name__)
        status['status'] = 'degraded'
        status['services']['database'] = {'status': 'unavailable'}

    storage = get_storage().health()
    status['services']['storage'] = storage
    status['instance'] = storage.get('instance')
    if storage.get('status') != 'accessible':
        status['status'] = 'degraded'

    return jsonify(status), 200 if status['status'] == 'healthy' else 503


# ---------------- Notifications ---------------- #

@main_bp.route('/notifications')
@login_required
def notifications():
    show = request.args.get('show', 'all')
    query = Notification.query.filter_by(user_id=current_user.id)
    if show == 'unread':
        query = query.filter(Notification.is_read.is_(False))
    page = max(request.args.get('page', 1, type=int), 1)
    pagination = query.order_by(Notification.created_at.desc(), Notification.id.desc()).paginate(
        page=page, per_page=20, error_out=False)
    return render_template('notifications.html', notifications=pagination.items, pagination=pagination, show=show)


@main_bp.route('/notifications/<int:notification_id>/open')
@login_required
def open_notification(notification_id):
    """Marks the notification read, then follows its (internal-only) link."""
    notif = mark_notification_as_read(notification_id, current_user.id)
    if notif and is_safe_internal_link(notif.link):
        return redirect(notif.link)
    return redirect(url_for('main.notifications'))


@main_bp.route('/notifications/read-all', methods=['POST'])
@login_required
def mark_all_notifications():
    count = mark_all_notifications_as_read(current_user.id)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'count': count, 'unread_count': 0})
    return redirect(request.referrer if request.referrer and request.referrer.startswith(request.host_url)
                    else url_for('main.notifications'))


@main_bp.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification(notification_id):
    notif = mark_notification_as_read(notification_id, current_user.id)
    return jsonify({'success': notif is not None, 'unread_count': get_unread_count(current_user.id)}), \
        (200 if notif else 404)


@main_bp.route('/api/notifications/unread-count')
@login_required
def unread_count():
    """Polled by the navbar badge (sent with X-Background-Poll so it does not extend the session)."""
    return jsonify({'unread_count': get_unread_count(current_user.id)})
