import csv
import io
from datetime import datetime, timedelta

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.admin.forms import (
    AutoAssignSettingsForm, CategoryForm, SLAPolicyForm, TechnicianSettingsForm, UserCreateAdminForm,
    UserEditAdminForm,
)
from app.auth.decorators import admin_required
from app.extensions import db
from app.models import AuditLog, SLAPolicy, Ticket, TicketCategory, TicketStatus, User, UserRole
from app.services import metrics
from app.services.assignment import (
    away_technicians_with_work, format_minutes, run_auto_assign, set_availability, technician_overview,
)
from app.services.audit import log_audit_event
from app.services.settings import get_auto_assign_config, save_auto_assign_config
from app.services.sla import apply_sla_to_ticket, get_sla_metrics
from app.tickets.forms import ClaimForm

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def _get_or_404(model, ident):
    obj = db.session.get(model, ident)
    if obj is None:
        abort(404)
    return obj


def _active_admin_count(exclude_id=None):
    q = User.query.filter(User.role == UserRole.ADMIN, User.is_active.is_(True))
    if exclude_id:
        q = q.filter(User.id != exclude_id)
    return q.count()


# ---------------- USER MANAGEMENT ---------------- #

@admin_bp.route('/users', methods=['GET', 'POST'])
@login_required
@admin_required
def users():
    """User directory with search, role/status filters, pagination and creation."""
    create_form = UserCreateAdminForm()
    open_create_modal = False

    if request.method == 'POST':
        if create_form.validate_on_submit():
            user = User(
                full_name=create_form.full_name.data.strip(),
                username=create_form.username.data.strip(),
                email=create_form.email.data.strip().lower(),
                role=create_form.role.data,
                department=(create_form.department.data or '').strip() or None,
                is_active=create_form.is_active.data,
            )
            user.set_password(create_form.password.data)
            db.session.add(user)
            db.session.flush()
            log_audit_event('ADMIN_USER_CREATE', 'User', user.id,
                            f"Created user '{user.username}' with role '{user.role}'", commit=False)
            db.session.commit()
            flash(f"User '{user.username}' created.", 'success')
            return redirect(url_for('admin.users'))
        open_create_modal = True

    query = User.query
    search = request.args.get('search', '').strip()[:100]
    role_filter = request.args.get('role', '').strip()
    status_filter = request.args.get('status', '').strip()
    if search:
        like = f"%{search}%"
        query = query.filter(User.username.ilike(like) | User.email.ilike(like) |
                             User.full_name.ilike(like) | User.department.ilike(like))
    if role_filter in UserRole.VALUES:
        query = query.filter(User.role == role_filter)
    else:
        role_filter = ''
    if status_filter == 'active':
        query = query.filter(User.is_active.is_(True))
    elif status_filter == 'inactive':
        query = query.filter(User.is_active.is_(False))
    else:
        status_filter = ''

    page = max(request.args.get('page', 1, type=int), 1)
    pagination = query.order_by(User.created_at.desc(), User.id.desc()).paginate(page=page, per_page=15, error_out=False)
    filters = {k: v for k, v in {'search': search, 'role': role_filter, 'status': status_filter}.items() if v}

    return render_template('admin/users.html', users=pagination.items, pagination=pagination,
                           create_form=create_form, open_create_modal=open_create_modal, filters=filters,
                           role_counts={r: User.query.filter_by(role=r).count() for r in UserRole.VALUES})


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = _get_or_404(User, user_id)
    form = UserEditAdminForm(obj=user, user=user)
    if request.method == 'GET':
        form.new_password.data = None

    active_assignments = Ticket.query.filter(Ticket.technician_id == user.id,
                                             Ticket.status.in_(TicketStatus.ACTIVE)).count()
    tech_form = None
    if user.is_technician:
        tech_form = TechnicianSettingsForm(formdata=None).fill_from(user)
        tech_form.skills.data = [c.id for c in user.skills]

    def render_edit(status=200):
        return render_template('admin/user_edit.html', form=form, user=user, tech_form=tech_form,
                               active_assignments=active_assignments), status

    if form.validate_on_submit():
        new_role, new_active = form.role.data, bool(form.is_active.data)
        if user.id == current_user.id and (new_role != UserRole.ADMIN or not new_active):
            flash('You cannot remove your own administrator role or deactivate your own account.', 'danger')
            return render_edit(400)
        if user.is_admin and user.is_active and (new_role != UserRole.ADMIN or not new_active) and _active_admin_count(user.id) == 0:
            flash('At least one active administrator must remain.', 'danger')
            return render_edit(400)
        if new_role == UserRole.EMPLOYEE and active_assignments:
            flash(f'{user.full_name} still has {active_assignments} active assigned ticket(s). Reassign them first.', 'danger')
            return render_edit(400)

        old_role, old_active = user.role, user.is_active
        user.full_name = form.full_name.data.strip()
        user.email = form.email.data.strip().lower()
        user.role = new_role
        user.department = (form.department.data or '').strip() or None
        user.is_active = new_active

        if old_role != new_role:
            log_audit_event('ADMIN_ROLE_CHANGE', 'User', user.id,
                            f"Role of '{user.username}' changed {old_role} -> {new_role}", commit=False)
        if old_active != new_active:
            log_audit_event('ADMIN_USER_STATUS_CHANGE', 'User', user.id,
                            f"'{user.username}' {'activated' if new_active else 'deactivated'}", commit=False)
        if form.new_password.data:
            user.set_password(form.new_password.data)
            log_audit_event('ADMIN_PASSWORD_RESET', 'User', user.id,
                            f"Password reset for '{user.username}' by administrator", commit=False)
        log_audit_event('ADMIN_USER_EDIT', 'User', user.id, f"Profile of '{user.username}' updated", commit=False)
        db.session.commit()
        flash(f"User '{user.username}' updated.", 'success')
        return redirect(url_for('admin.users'))

    return render_edit()


@admin_bp.route('/users/<int:user_id>/technician-settings', methods=['POST'])
@login_required
@admin_required
def technician_settings(user_id):
    """Skills (categories) and availability of a technician, used by auto-assignment."""
    user = _get_or_404(User, user_id)
    if not user.is_technician:
        flash('Skills and availability apply to support technicians only.', 'warning')
        return redirect(url_for('admin.edit_user', user_id=user.id))
    form = TechnicianSettingsForm()
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for err in errors:
                flash(err, 'danger')
        return redirect(url_for('admin.edit_user', user_id=user.id))

    old_skills = sorted(c.name for c in user.skills)
    user.skills = TicketCategory.query.filter(TicketCategory.id.in_(form.skills.data or [])).all()
    new_skills = sorted(c.name for c in user.skills)
    if new_skills != old_skills:
        log_audit_event('ADMIN_TECH_SKILLS_CHANGE', 'User', user.id,
                        f"Skills of '{user.username}': {', '.join(old_skills) or 'none'} -> {', '.join(new_skills) or 'none'}",
                        commit=False)

    available = form.status.data == 'available'
    current_back_on = user.away_until.date() if user.away_until else None
    if available == user.is_away or (not available and ((form.away_note.data or '').strip() or None) != user.away_note) \
            or (not available and form.back_on.data != current_back_on):
        set_availability(user, available, note=form.away_note.data, back_on=form.back_on.data, actor=current_user)
    db.session.commit()
    flash(f"Technician settings for {user.full_name} saved ({user.availability_label}).", 'success')
    return redirect(url_for('admin.edit_user', user_id=user.id))


@admin_bp.route('/users/<int:user_id>/toggle-status', methods=['POST'])
@login_required
@admin_required
def toggle_user_status(user_id):
    user = _get_or_404(User, user_id)
    if user.id == current_user.id:
        flash('You cannot deactivate your own account.', 'warning')
        return redirect(url_for('admin.users'))
    if user.is_admin and user.is_active and _active_admin_count(user.id) == 0:
        flash('At least one active administrator must remain.', 'danger')
        return redirect(url_for('admin.users'))

    user.is_active = not user.is_active
    log_audit_event('ADMIN_USER_STATUS_CHANGE', 'User', user.id,
                    f"'{user.username}' {'activated' if user.is_active else 'deactivated'}", commit=False)
    db.session.commit()
    msg = f"User '{user.username}' {'activated' if user.is_active else 'deactivated'}."
    if not user.is_active:
        active = Ticket.query.filter(Ticket.technician_id == user.id, Ticket.status.in_(TicketStatus.ACTIVE)).count()
        if active:
            msg += f" They still have {active} active assigned ticket(s) — reassign them."
    flash(msg, 'info')
    return redirect(request.referrer if request.referrer and request.referrer.startswith(request.host_url) else url_for('admin.users'))


# ---------------- CATEGORIES ---------------- #

@admin_bp.route('/categories', methods=['GET', 'POST'])
@login_required
@admin_required
def categories():
    form = CategoryForm()
    if form.validate_on_submit():
        category = TicketCategory(name=form.name.data.strip(),
                                  description=(form.description.data or '').strip() or None,
                                  is_active=form.is_active.data)
        db.session.add(category)
        db.session.flush()
        log_audit_event('ADMIN_CATEGORY_CREATE', 'TicketCategory', category.id,
                        f"Created category '{category.name}'", commit=False)
        db.session.commit()
        flash(f"Category '{category.name}' created.", 'success')
        return redirect(url_for('admin.categories'))

    rows = (db.session.query(TicketCategory, db.func.count(Ticket.id))
            .outerjoin(Ticket, Ticket.category_id == TicketCategory.id)
            .group_by(TicketCategory.id).order_by(TicketCategory.name).all())
    return render_template('admin/categories.html', rows=rows, form=form,
                           open_create_modal=request.method == 'POST')


@admin_bp.route('/categories/<int:category_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_category(category_id):
    category = _get_or_404(TicketCategory, category_id)
    form = CategoryForm(category=category)
    if form.validate_on_submit():
        old_name = category.name
        category.name = form.name.data.strip()
        category.description = (form.description.data or '').strip() or None
        category.is_active = form.is_active.data
        log_audit_event('ADMIN_CATEGORY_EDIT', 'TicketCategory', category.id,
                        f"Category '{old_name}' updated (name='{category.name}', active={category.is_active})", commit=False)
        db.session.commit()
        flash(f"Category '{category.name}' updated.", 'success')
    else:
        for errors in form.errors.values():
            for err in errors:
                flash(err, 'danger')
    return redirect(url_for('admin.categories'))


@admin_bp.route('/categories/<int:category_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_category(category_id):
    category = _get_or_404(TicketCategory, category_id)
    category.is_active = not category.is_active
    log_audit_event('ADMIN_CATEGORY_TOGGLE', 'TicketCategory', category.id,
                    f"Category '{category.name}' active={category.is_active}", commit=False)
    db.session.commit()
    flash(f"Category '{category.name}' {'enabled' if category.is_active else 'disabled'}.", 'info')
    return redirect(url_for('admin.categories'))


# ---------------- SLA POLICIES ---------------- #

@admin_bp.route('/sla', methods=['GET', 'POST'])
@login_required
@admin_required
def sla():
    form = SLAPolicyForm()
    if form.validate_on_submit():
        priority = form.priority.data
        policy = SLAPolicy.query.filter_by(priority=priority).first()
        if not policy:
            policy = SLAPolicy(priority=priority)
            db.session.add(policy)
        old = (policy.response_time_hours, policy.resolution_time_hours)
        policy.response_time_hours = form.response_time_hours.data
        policy.resolution_time_hours = form.resolution_time_hours.data
        policy.description = (form.description.data or '').strip() or None
        db.session.flush()

        recalculated = 0
        if form.apply_to_active.data:
            for ticket in Ticket.query.filter(Ticket.priority == priority, Ticket.status.in_(TicketStatus.ACTIVE)).all():
                apply_sla_to_ticket(ticket, start_time=ticket.created_at)
                recalculated += 1

        log_audit_event('ADMIN_SLA_UPDATE', 'SLAPolicy', priority,
                        f"{priority}: response {old[0]}h->{policy.response_time_hours}h, resolution "
                        f"{old[1]}h->{policy.resolution_time_hours}h; {recalculated} active ticket(s) recalculated",
                        commit=False)
        db.session.commit()
        flash(f"SLA policy for {priority} saved" + (f"; {recalculated} active ticket(s) recalculated." if recalculated else '.'), 'success')
        return redirect(url_for('admin.sla'))

    policies = {p.priority: p for p in SLAPolicy.query.all()}
    return render_template('admin/sla.html', policies=policies, form=form, sla_metrics=get_sla_metrics(),
                           by_priority=metrics.resolution_by_priority(),
                           open_modal=request.method == 'POST')


# ---------------- AUTO-ASSIGNMENT ---------------- #

@admin_bp.route('/auto-assign', methods=['GET', 'POST'])
@login_required
@admin_required
def auto_assign():
    """Auto-assignment settings, technician status and the waiting queue."""
    config = get_auto_assign_config()
    form = AutoAssignSettingsForm()
    if form.validate_on_submit():
        waits = form.wait_minutes()
        save_auto_assign_config(form.enabled.data, form.max_open.data, waits)
        log_audit_event('ADMIN_AUTO_ASSIGN_SETTINGS', 'SystemSetting', 'auto_assign',
                        f"Auto-assignment {'ON' if form.enabled.data else 'OFF'}; max {form.max_open.data} open "
                        f"tickets per technician; queue wait " + ', '.join(f"{p} {m} min" for p, m in waits.items()),
                        commit=False)
        db.session.commit()
        flash(f"Auto-assignment settings saved ({'ON' if form.enabled.data else 'OFF'}, "
              f"max {form.max_open.data} open tickets per technician).", 'success')
        return redirect(url_for('admin.auto_assign'))
    if request.method == 'GET':
        form.fill_from(config)

    queue = (Ticket.query.filter(Ticket.technician_id.is_(None), Ticket.status == TicketStatus.OPEN)
             .order_by(Ticket.created_at).all())
    return render_template(
        'admin/auto_assign.html', form=form, config=config, overview=technician_overview(config),
        away_with_work=away_technicians_with_work(), queue=queue, run_form=ClaimForm(),
        wait_labels={p: format_minutes(m) for p, m in config.wait_minutes.items()},
    ), 400 if request.method == 'POST' else 200


@admin_bp.route('/auto-assign/run', methods=['POST'])
@login_required
@admin_required
def auto_assign_run():
    """'Run auto-assign now': assigns every queued ticket immediately (ignores wait times)."""
    if not ClaimForm().validate_on_submit():
        flash('Your form expired. Please try again.', 'warning')
        return redirect(url_for('admin.auto_assign'))
    assigned, waiting = run_auto_assign(force=True, actor=current_user)
    log_audit_event('ADMIN_AUTO_ASSIGN_RUN', 'Ticket', None,
                    f"'Run auto-assign now' by {current_user.username}: {len(assigned)} assigned, "
                    f"{len(waiting)} still waiting", commit=False)
    db.session.commit()
    if assigned:
        flash(f"Assigned {len(assigned)} ticket(s): " +
              '; '.join(f"{t.reference_id} → {tech.full_name}" for t, tech, _ in assigned), 'success')
    if waiting:
        flash(f"{len(waiting)} ticket(s) could not be assigned: {waiting[0][1]}.", 'warning')
    if not assigned and not waiting:
        flash('The queue is empty, so there was nothing to assign.', 'info')
    return redirect(url_for('admin.auto_assign'))


# ---------------- AUDIT LOGS ---------------- #

def _audit_query():
    query = AuditLog.query
    args = request.args
    action = args.get('action', '').strip()
    if action:
        query = query.filter(AuditLog.action == action)
    user_id = args.get('user_id', type=int)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    search = args.get('search', '').strip()[:100]
    if search:
        like = f"%{search}%"
        query = query.filter(AuditLog.details.ilike(like) | AuditLog.entity_id.ilike(like) | AuditLog.ip_address.ilike(like))
    for name, op in (('date_from', '>='), ('date_to', '<')):
        try:
            value = datetime.strptime(args.get(name, ''), '%Y-%m-%d')
        except ValueError:
            continue
        query = query.filter(AuditLog.created_at >= value) if op == '>=' else \
            query.filter(AuditLog.created_at < value + timedelta(days=1))
    filters = {k: args.get(k) for k in ('action', 'user_id', 'search', 'date_from', 'date_to') if args.get(k)}
    return query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()), filters


@admin_bp.route('/audit-logs', methods=['GET'])
@login_required
@admin_required
def audit_logs():
    query, filters = _audit_query()
    page = max(request.args.get('page', 1, type=int), 1)
    pagination = query.paginate(page=page, per_page=25, error_out=False)
    actions = [a for (a,) in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()]
    return render_template('admin/audit_logs.html', logs=pagination.items, pagination=pagination, filters=filters,
                           actions=actions, users=User.query.order_by(User.username).all())


@admin_bp.route('/audit-logs/export.csv', methods=['GET'])
@login_required
@admin_required
def export_audit_logs():
    query, _ = _audit_query()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['timestamp_utc', 'action', 'actor', 'entity_type', 'entity_id', 'details', 'ip_address'])
    for log in query.limit(10000).all():
        row = [log.created_at.isoformat(), log.action, log.actor.username if log.actor else 'system',
               log.entity_type or '', log.entity_id or '', log.details or '', log.ip_address or '']
        # Neutralise spreadsheet formula injection
        writer.writerow([("'" + v) if isinstance(v, str) and v[:1] in ('=', '+', '-', '@') else v for v in row])
    log_audit_event('ADMIN_AUDIT_EXPORT', 'AuditLog', None, f"Audit log exported by {current_user.username}")
    return Response(buffer.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=cloudops360-audit-log.csv'})


# ---------------- ANALYTICS ---------------- #

@admin_bp.route('/analytics', methods=['GET'])
@login_required
@admin_required
def analytics():
    days = request.args.get('days', 30, type=int)
    if days not in (7, 14, 30, 90):
        days = 30
    query = Ticket.query
    return render_template(
        'admin/analytics.html',
        days=days,
        sla_data=get_sla_metrics(),
        priority_data=metrics.priority_counts(query),
        status_data=metrics.status_counts(query),
        category_data=metrics.category_counts(query),
        trend=metrics.daily_trend(query, days=days),
        by_priority=metrics.resolution_by_priority(),
        workload=metrics.technician_workload(),
        ratings=metrics.rating_summary(query),
        total=query.count(),
    )
