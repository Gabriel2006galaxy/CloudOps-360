from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User, UserRole, TicketCategory, SLAPolicy, AuditLog, Ticket, TicketStatus, TicketPriority
from app.admin.forms import UserCreateAdminForm, UserEditAdminForm, CategoryForm, SLAPolicyForm
from app.auth.decorators import admin_required
from app.services.audit import log_audit_event
from app.services.sla import get_sla_metrics

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# ---------------- USER MANAGEMENT ---------------- #

@admin_bp.route('/users', methods=['GET', 'POST'])
@login_required
@admin_required
def users():
    """Admin user directory with search, role filtering, and new user creation."""
    create_form = UserCreateAdminForm()
    
    if create_form.validate_on_submit():
        user = User(
            full_name=create_form.full_name.data.strip(),
            username=create_form.username.data.strip(),
            email=create_form.email.data.strip().lower(),
            role=create_form.role.data,
            department=create_form.department.data.strip() if create_form.department.data else None,
            is_active=create_form.is_active.data
        )
        user.set_password(create_form.password.data)
        db.session.add(user)
        db.session.commit()

        log_audit_event(
            action='ADMIN_USER_CREATE',
            entity_type='User',
            entity_id=user.id,
            details=f"Admin created user '{user.username}' with role '{user.role}'"
        )
        flash(f"User account '{user.username}' created successfully.", 'success')
        return redirect(url_for('admin.users'))

    query = User.query
    search = request.args.get('search', '').strip()
    role_filter = request.args.get('role', '').strip()

    if search:
        query = query.filter(
            (User.username.ilike(f"%{search}%")) |
            (User.email.ilike(f"%{search}%")) |
            (User.full_name.ilike(f"%{search}%")) |
            (User.department.ilike(f"%{search}%"))
        )

    if role_filter and role_filter in [r[0] for r in UserRole.CHOICES]:
        query = query.filter(User.role == role_filter)

    page = request.args.get('page', 1, type=int)
    users_pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=15, error_out=False)

    return render_template(
        'admin/users.html',
        users=users_pagination.items,
        pagination=users_pagination,
        create_form=create_form,
        current_search=search,
        current_role=role_filter
    )


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    """Edit user details, roles, or reset credentials."""
    user = User.query.get_or_404(user_id)
    form = UserEditAdminForm(obj=user)

    if form.validate_on_submit():
        old_role = user.role
        user.full_name = form.full_name.data.strip()
        user.email = form.email.data.strip().lower()
        user.role = form.role.data
        user.department = form.department.data.strip() if form.department.data else None
        user.is_active = form.is_active.data

        if form.new_password.data:
            user.set_password(form.new_password.data)
            flash(f"Password reset for user '{user.username}'.", 'info')

        db.session.commit()

        log_audit_event(
            action='ADMIN_USER_EDIT',
            entity_type='User',
            entity_id=user.id,
            details=f"User '{user.username}' updated. Role: '{old_role}' -> '{user.role}', Active: {user.is_active}"
        )
        flash(f"User '{user.username}' successfully updated.", 'success')
        return redirect(url_for('admin.users'))

    return render_template('admin/user_edit.html', form=form, user=user)


@admin_bp.route('/users/<int:user_id>/toggle-status', methods=['POST'])
@login_required
@admin_required
def toggle_user_status(user_id):
    """Toggle user active/deactivated state."""
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot deactivate your own administrative account.', 'warning')
        return redirect(url_for('admin.users'))

    user.is_active = not user.is_active
    db.session.commit()

    log_audit_event(
        action='ADMIN_USER_STATUS_TOGGLE',
        entity_type='User',
        entity_id=user.id,
        details=f"User '{user.username}' active status changed to {user.is_active}"
    )
    flash(f"User '{user.username}' {'activated' if user.is_active else 'deactivated'}.", 'info')
    return redirect(url_for('admin.users'))


# ---------------- CATEGORIES ---------------- #

@admin_bp.route('/categories', methods=['GET', 'POST'])
@login_required
@admin_required
def categories():
    """Manage incident categories."""
    form = CategoryForm()
    if form.validate_on_submit():
        category = TicketCategory(
            name=form.name.data.strip(),
            description=form.description.data.strip() if form.description.data else None,
            is_active=form.is_active.data
        )
        db.session.add(category)
        db.session.commit()

        log_audit_event(
            action='ADMIN_CATEGORY_CREATE',
            entity_type='TicketCategory',
            entity_id=category.id,
            details=f"Created category '{category.name}'"
        )
        flash(f"Category '{category.name}' created.", 'success')
        return redirect(url_for('admin.categories'))

    categories = TicketCategory.query.order_by(TicketCategory.name).all()
    return render_template('admin/categories.html', categories=categories, form=form)


@admin_bp.route('/categories/<int:category_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_category(category_id):
    category = TicketCategory.query.get_or_404(category_id)
    category.is_active = not category.is_active
    db.session.commit()
    log_audit_event(
        action='ADMIN_CATEGORY_TOGGLE',
        entity_type='TicketCategory',
        entity_id=category.id,
        details=f"Category '{category.name}' active state: {category.is_active}"
    )
    flash(f"Category '{category.name}' updated.", 'info')
    return redirect(url_for('admin.categories'))


# ---------------- SLA POLICIES ---------------- #

@admin_bp.route('/sla', methods=['GET', 'POST'])
@login_required
@admin_required
def sla():
    """Configure response and resolution SLA deadlines by priority."""
    form = SLAPolicyForm()
    if form.validate_on_submit():
        priority = form.priority.data
        policy = SLAPolicy.query.filter_by(priority=priority).first()
        if not policy:
            policy = SLAPolicy(priority=priority)
            db.session.add(policy)

        policy.response_time_hours = form.response_time_hours.data
        policy.resolution_time_hours = form.resolution_time_hours.data
        policy.description = form.description.data.strip() if form.description.data else None
        db.session.commit()

        log_audit_event(
            action='ADMIN_SLA_UPDATE',
            entity_type='SLAPolicy',
            entity_id=policy.priority,
            details=f"SLA policy for {policy.priority} set to Response: {policy.response_time_hours}h, Resolution: {policy.resolution_time_hours}h"
        )
        flash(f"SLA Policy for {policy.priority} updated successfully.", 'success')
        return redirect(url_for('admin.sla'))

    policies = SLAPolicy.query.order_by(SLAPolicy.id).all()
    sla_metrics = get_sla_metrics()
    return render_template('admin/sla.html', policies=policies, form=form, sla_metrics=sla_metrics)


# ---------------- AUDIT LOGS ---------------- #

@admin_bp.route('/audit-logs', methods=['GET'])
@login_required
@admin_required
def audit_logs():
    """Security and compliance audit trail explorer."""
    query = AuditLog.query

    action_filter = request.args.get('action', '').strip()
    if action_filter:
        query = query.filter(AuditLog.action.ilike(f"%{action_filter}%"))

    search = request.args.get('search', '').strip()
    if search:
        query = query.filter(
            (AuditLog.details.ilike(f"%{search}%")) |
            (AuditLog.entity_id.ilike(f"%{search}%")) |
            (AuditLog.ip_address.ilike(f"%{search}%"))
        )

    page = request.args.get('page', 1, type=int)
    pagination = query.order_by(AuditLog.created_at.desc()).paginate(page=page, per_page=20, error_out=False)

    return render_template(
        'admin/audit_logs.html',
        logs=pagination.items,
        pagination=pagination,
        current_action=action_filter,
        current_search=search
    )


# ---------------- ANALYTICS ---------------- #

@admin_bp.route('/analytics', methods=['GET'])
@login_required
@admin_required
def analytics():
    """Operational and incident reporting with Chart.js visualization."""
    sla_data = get_sla_metrics()
    
    # Priority Breakdown
    priority_data = {
        'Critical': Ticket.query.filter_by(priority=TicketPriority.CRITICAL).count(),
        'High': Ticket.query.filter_by(priority=TicketPriority.HIGH).count(),
        'Medium': Ticket.query.filter_by(priority=TicketPriority.MEDIUM).count(),
        'Low': Ticket.query.filter_by(priority=TicketPriority.LOW).count()
    }

    # Status Breakdown
    status_data = {
        'Open': Ticket.query.filter_by(status=TicketStatus.OPEN).count(),
        'Assigned': Ticket.query.filter_by(status=TicketStatus.ASSIGNED).count(),
        'In Progress': Ticket.query.filter_by(status=TicketStatus.IN_PROGRESS).count(),
        'Resolved': Ticket.query.filter_by(status=TicketStatus.RESOLVED).count(),
        'Closed': Ticket.query.filter_by(status=TicketStatus.CLOSED).count()
    }

    # Category Breakdown
    categories = TicketCategory.query.all()
    category_chart = {c.name: c.tickets.count() for c in categories}

    return render_template(
        'admin/analytics.html',
        sla_data=sla_data,
        priority_data=priority_data,
        status_data=status_data,
        category_chart=category_chart
    )
