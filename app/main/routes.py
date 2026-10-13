from flask import Blueprint, render_template, redirect, url_for, jsonify, request
from flask_login import current_user, login_required
from app.extensions import db
from app.models import Notification, Ticket, User
from app.services.notifications import get_unread_count, mark_all_notifications_as_read, mark_notification_as_read
from app.services.storage import get_upload_dir

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Enterprise landing page for CloudOps 360."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    return render_template('landing.html')


@main_bp.route('/health')
def health():
    """
    AWS Application Load Balancer / EC2 Target Group Health Check.
    Verifies database connectivity and storage directory writeability.
    """
    status = {'status': 'healthy', 'services': {}}
    
    # Check Database Connectivity
    try:
        db.session.execute(db.text('SELECT 1'))
        status['services']['database'] = 'connected'
    except Exception as e:
        status['status'] = 'degraded'
        status['services']['database'] = f'error: {str(e)}'

    # Check EFS / Upload Storage
    try:
        upload_dir = get_upload_dir()
        test_file = f"{upload_dir}/.health_check"
        with open(test_file, 'w') as f:
            f.write("ok")
        import os
        if os.path.exists(test_file):
            os.remove(test_file)
        status['services']['storage'] = 'accessible'
    except Exception as e:
        status['status'] = 'degraded'
        status['services']['storage'] = f'error: {str(e)}'

    status_code = 200 if status['status'] == 'healthy' else 503
    return jsonify(status), status_code


@main_bp.route('/notifications/read-all', methods=['POST'])
@login_required
def mark_all_notifications():
    """Mark all notifications read for the current user."""
    count = mark_all_notifications_as_read(current_user.id)
    return jsonify({'success': True, 'count': count})


@main_bp.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification(notification_id):
    """Mark a specific notification read."""
    success = mark_notification_as_read(notification_id, current_user.id)
    return jsonify({'success': success})


@main_bp.route('/api/notifications/unread-count')
@login_required
def unread_count():
    """Endpoint for live navbar polling and badge counter."""
    count = get_unread_count(current_user.id)
    return jsonify({'unread_count': count})
