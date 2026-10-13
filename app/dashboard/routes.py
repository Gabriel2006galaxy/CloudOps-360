from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.auth.decorators import admin_required, role_required, technician_or_admin_required
from app.models import UserRole
from app.services import metrics

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')


@dashboard_bp.route('')
@login_required
def index():
    """Sends each user to their role-specific dashboard."""
    if current_user.is_admin:
        return redirect(url_for('dashboard.admin'))
    if current_user.is_technician:
        return redirect(url_for('dashboard.technician'))
    return redirect(url_for('dashboard.employee'))


@dashboard_bp.route('/employee')
@login_required
@role_required(UserRole.EMPLOYEE)
def employee():
    return render_template('dashboard/employee.html', m=metrics.employee_dashboard(current_user))


@dashboard_bp.route('/technician')
@login_required
@technician_or_admin_required
def technician():
    return render_template('dashboard/technician.html', m=metrics.technician_dashboard(current_user))


@dashboard_bp.route('/admin')
@login_required
@admin_required
def admin():
    return render_template('dashboard/admin.html', m=metrics.admin_dashboard())
