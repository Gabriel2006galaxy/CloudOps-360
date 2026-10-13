import uuid
from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import asc, case, desc, or_

from app.extensions import db
from app.models import (
    Attachment, Comment, Ticket, TicketCategory, TicketPriority, TicketStatus,
    TicketStatusHistory, User, UserRole, utcnow,
)
from app.services import permissions as perm
from app.services.audit import log_audit_event
from app.services.notifications import create_notification
from app.services.sla import apply_sla_to_ticket, overdue_filter
from app.services.storage import StorageError, get_storage
from app.services.workflow import (
    WorkflowError, assign_ticket, change_priority, change_status, new_ticket_reference,
    staff_choices, transition_actions,
)
from app.tickets.forms import (
    AssignForm, AttachmentUploadForm, ClaimForm, CommentForm, DetailsForm, PriorityForm,
    StatusChangeForm, TicketCreateForm,
)

tickets_bp = Blueprint('tickets', __name__, url_prefix='/tickets')

PRIORITY_ORDER = case({p: TicketPriority.RANK[p] for p in TicketPriority.VALUES}, value=Ticket.priority, else_=0)
STATUS_ORDER = case({s: i for i, s in enumerate(TicketStatus.VALUES)}, value=Ticket.status, else_=0)
SORT_COLUMNS = {
    'reference_id': Ticket.id,
    'title': Ticket.title,
    'priority': PRIORITY_ORDER,
    'status': STATUS_ORDER,
    'created_at': Ticket.created_at,
    'updated_at': Ticket.updated_at,
    'resolution_due_at': Ticket.resolution_due_at,
}
PER_PAGE_OPTIONS = (10, 25, 50)


def _parse_date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d') if value else None
    except ValueError:
        return None


def get_ticket_or_404(reference_id):
    return Ticket.query.filter_by(reference_id=reference_id).first_or_404()


def require_view(ticket):
    """403 + audit trail when the current user may not see the ticket."""
    if not perm.can_view_ticket(current_user, ticket):
        log_audit_event('TICKET_UNAUTHORIZED_ACCESS', 'Ticket', ticket.reference_id,
                        f"'{current_user.username}' ({current_user.role}) denied access to {ticket.reference_id} "
                        f"[{request.method} {request.path}]")
        abort(403)


def _form_errors(form):
    for field, errors in form.errors.items():
        label = getattr(getattr(form, field, None), 'label', None)
        for err in errors:
            flash(f"{label.text if label else field}: {err}", 'danger')


@tickets_bp.route('', methods=['GET'])
@login_required
def index():
    """Ticket list with search, filters, sorting and pagination, scoped by role."""
    query = perm.visible_tickets_query(current_user)
    args = request.args

    q = args.get('q', '').strip()[:100]
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Ticket.reference_id.ilike(like), Ticket.title.ilike(like), Ticket.description.ilike(like),
            Ticket.affected_system.ilike(like), Ticket.department.ilike(like),
        ))

    status = args.get('status', '').strip()
    if status == 'active':
        query = query.filter(Ticket.status.in_(TicketStatus.ACTIVE))
    elif status in TicketStatus.VALUES:
        query = query.filter(Ticket.status == status)
    else:
        status = ''

    priority = args.get('priority', '').strip()
    if priority in TicketPriority.VALUES:
        query = query.filter(Ticket.priority == priority)
    else:
        priority = ''

    category_id = args.get('category_id', type=int)
    if category_id:
        query = query.filter(Ticket.category_id == category_id)

    technician = args.get('technician', '').strip()
    if current_user.is_staff and technician:
        if technician == 'me':
            query = query.filter(Ticket.technician_id == current_user.id)
        elif technician == 'unassigned':
            query = query.filter(Ticket.technician_id.is_(None))
        elif technician.isdigit() and current_user.is_admin:
            query = query.filter(Ticket.technician_id == int(technician))
        else:
            technician = ''
    else:
        technician = ''

    date_from, date_to = _parse_date(args.get('date_from')), _parse_date(args.get('date_to'))
    if date_from:
        query = query.filter(Ticket.created_at >= date_from)
    if date_to:
        query = query.filter(Ticket.created_at < date_to + timedelta(days=1))

    overdue_only = args.get('overdue') == '1'
    if overdue_only:
        query = overdue_filter(query)

    sort_by = args.get('sort_by', 'created_at')
    if sort_by not in SORT_COLUMNS:
        sort_by = 'created_at'
    order = 'asc' if args.get('order') == 'asc' else 'desc'
    column = SORT_COLUMNS[sort_by]
    query = query.order_by(asc(column) if order == 'asc' else desc(column), desc(Ticket.id))

    per_page = args.get('per_page', 10, type=int)
    if per_page not in PER_PAGE_OPTIONS:
        per_page = 10
    page = max(args.get('page', 1, type=int), 1)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    filters = {k: v for k, v in {
        'q': q, 'status': status, 'priority': priority, 'category_id': category_id or '',
        'technician': technician, 'date_from': args.get('date_from', '') if date_from else '',
        'date_to': args.get('date_to', '') if date_to else '', 'overdue': '1' if overdue_only else '',
        'sort_by': sort_by, 'order': order, 'per_page': per_page,
    }.items() if v not in ('', None)}

    return render_template(
        'tickets/index.html',
        tickets=pagination.items,
        pagination=pagination,
        filters=filters,
        categories=TicketCategory.query.order_by(TicketCategory.name).all(),
        technicians=staff_choices() if current_user.is_admin else [],
        statuses=TicketStatus.VALUES,
        priorities=TicketPriority.ORDERED,
        per_page_options=PER_PAGE_OPTIONS,
        has_filters=any(k in filters for k in ('q', 'status', 'priority', 'category_id', 'technician', 'date_from', 'date_to', 'overdue')),
    )


@tickets_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create an incident ticket with an optional screenshot/diagnostic file."""
    form = TicketCreateForm()
    if not form.category_id.choices:
        flash('No active incident categories exist yet. An administrator must create one first.', 'warning')

    if request.method == 'GET' and current_user.department:
        form.department.data = current_user.department

    if form.validate_on_submit():
        storage = get_storage()
        stored = None
        upload = form.attachment.data
        try:
            if upload and getattr(upload, 'filename', ''):
                stored = storage.save(upload)

            now = utcnow()
            ticket = Ticket(
                reference_id=f"PENDING-{uuid.uuid4().hex[:24]}",
                title=form.title.data.strip(),
                description=form.description.data.strip(),
                category_id=form.category_id.data,
                priority=form.priority.data,
                status=TicketStatus.OPEN,
                creator_id=current_user.id,
                affected_system=(form.affected_system.data or '').strip() or None,
                department=(form.department.data or '').strip() or current_user.department,
                created_at=now,
                updated_at=now,
            )
            apply_sla_to_ticket(ticket, start_time=now)
            db.session.add(ticket)
            db.session.flush()
            ticket.reference_id = new_ticket_reference(ticket)

            db.session.add(TicketStatusHistory(
                ticket_id=ticket.id, changed_by_id=current_user.id, old_status='New',
                new_status=TicketStatus.OPEN, notes='Incident reported.', created_at=now,
            ))
            if stored:
                db.session.add(Attachment(
                    ticket_id=ticket.id, user_id=current_user.id, filename=stored['key'],
                    original_filename=stored['original_filename'], file_size=stored['size'],
                    mime_type=stored['mime_type'], storage_path=stored['key'],
                    checksum_sha256=stored['checksum_sha256'], created_at=now,
                ))
            log_audit_event('TICKET_CREATE', 'Ticket', ticket.reference_id,
                            f"{ticket.reference_id} [{ticket.priority}] created by {current_user.username}"
                            + (f" with attachment '{stored['original_filename']}'" if stored else ''),
                            commit=False)

            link = url_for('tickets.detail', reference_id=ticket.reference_id)
            for staff in User.query.filter(User.role.in_(UserRole.STAFF), User.is_active.is_(True),
                                           User.id != current_user.id).all():
                create_notification(staff.id, f"New incident {ticket.reference_id}",
                                    f"[{ticket.priority}] {ticket.title} — reported by {current_user.full_name}",
                                    link=link, type='danger' if ticket.priority == TicketPriority.CRITICAL else 'info',
                                    commit=False)
            db.session.commit()
        except StorageError as exc:
            db.session.rollback()
            form.attachment.errors = list(form.attachment.errors) + [str(exc)]
            return render_template('tickets/create.html', form=form), 400
        except Exception:
            db.session.rollback()
            if stored:
                storage.delete(stored['key'])
            raise

        flash(f"Incident {ticket.reference_id} created successfully.", 'success')
        return redirect(url_for('tickets.detail', reference_id=ticket.reference_id))

    status_code = 400 if request.method == 'POST' else 200
    return render_template('tickets/create.html', form=form), status_code


@tickets_bp.route('/<reference_id>', methods=['GET'])
@login_required
def detail(reference_id):
    ticket = get_ticket_or_404(reference_id)
    require_view(ticket)

    comments_query = Comment.query.filter_by(ticket_id=ticket.id)
    if not perm.can_see_internal_notes(current_user, ticket):
        comments_query = comments_query.filter(Comment.is_internal.is_(False))
    comments = comments_query.order_by(Comment.created_at.asc(), Comment.id.asc()).all()

    activity = [{'kind': 'status', 'at': h.created_at, 'item': h} for h in ticket.status_history]
    activity += [{'kind': 'attachment', 'at': a.created_at, 'item': a} for a in ticket.attachments]
    activity += [{'kind': 'internal' if c.is_internal else 'comment', 'at': c.created_at, 'item': c} for c in comments]
    activity.sort(key=lambda e: e['at'], reverse=True)

    staff = staff_choices() if perm.can_assign_ticket(current_user, ticket) else []
    assign_form = AssignForm(staff=staff)
    assign_form.technician_id.data = ticket.technician_id or 0
    priority_form = PriorityForm(priority=ticket.priority)
    details_form = DetailsForm(obj=ticket)

    return render_template(
        'tickets/detail.html',
        ticket=ticket,
        comments=comments,
        activity=activity,
        comment_form=CommentForm(),
        attachment_form=AttachmentUploadForm(),
        status_form=StatusChangeForm(),
        assign_form=assign_form,
        priority_form=priority_form,
        details_form=details_form,
        claim_form=ClaimForm(),
        actions=transition_actions(current_user, ticket),
        can=dict(
            work=perm.can_work_ticket(current_user, ticket),
            assign=perm.can_assign_ticket(current_user, ticket),
            claim=perm.can_claim_ticket(current_user, ticket),
            comment=perm.can_comment(current_user, ticket),
            internal=perm.can_post_internal_note(current_user, ticket),
            upload=perm.can_upload_attachment(current_user, ticket),
            edit_priority=perm.can_work_ticket(current_user, ticket) and not ticket.is_resolved,
        ),
        can_delete_attachment=lambda att: perm.can_delete_attachment(current_user, att),
        internal_count=sum(1 for c in comments if c.is_internal),
    )


@tickets_bp.route('/<reference_id>/status', methods=['POST'])
@login_required
def update_status(reference_id):
    ticket = get_ticket_or_404(reference_id)
    require_view(ticket)
    form = StatusChangeForm()
    if not form.validate_on_submit():
        _form_errors(form)
        return redirect(url_for('tickets.detail', reference_id=reference_id))
    try:
        old = change_status(ticket, form.status.data, current_user, note=form.note.data,
                            resolution_summary=form.resolution_summary.data)
        db.session.commit()
        flash(f"{ticket.reference_id}: {old} → {ticket.status}.", 'success')
    except WorkflowError as exc:
        db.session.rollback()
        log_audit_event('TICKET_TRANSITION_REJECTED', 'Ticket', ticket.reference_id,
                        f"{current_user.username} attempted {ticket.status} -> {form.status.data}: {exc}")
        flash(str(exc), 'danger')
    return redirect(url_for('tickets.detail', reference_id=reference_id))


@tickets_bp.route('/<reference_id>/assign', methods=['POST'])
@login_required
def assign(reference_id):
    ticket = get_ticket_or_404(reference_id)
    require_view(ticket)
    if not perm.can_assign_ticket(current_user, ticket):
        log_audit_event('ACCESS_DENIED_RBAC', 'Ticket', ticket.reference_id,
                        f"'{current_user.username}' attempted to reassign {ticket.reference_id}")
        abort(403)
    form = AssignForm(staff=staff_choices())
    if not form.validate_on_submit():
        _form_errors(form)
        return redirect(url_for('tickets.detail', reference_id=reference_id))
    technician = db.session.get(User, form.technician_id.data) if form.technician_id.data else None
    try:
        changed = assign_ticket(ticket, technician, current_user)
        db.session.commit()
        if changed:
            flash(f"{ticket.reference_id} assigned to {technician.full_name}." if technician
                  else f"{ticket.reference_id} returned to the unassigned queue.", 'success')
        else:
            flash('Assignment unchanged.', 'info')
    except WorkflowError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(url_for('tickets.detail', reference_id=reference_id))


@tickets_bp.route('/<reference_id>/priority', methods=['POST'])
@login_required
def update_priority(reference_id):
    ticket = get_ticket_or_404(reference_id)
    require_view(ticket)
    form = PriorityForm()
    if not form.validate_on_submit():
        _form_errors(form)
        return redirect(url_for('tickets.detail', reference_id=reference_id))
    try:
        if change_priority(ticket, form.priority.data, current_user):
            db.session.commit()
            flash(f"Priority set to {ticket.priority}; SLA targets recalculated.", 'success')
        else:
            flash('Priority unchanged.', 'info')
    except WorkflowError as exc:
        db.session.rollback()
        log_audit_event('ACCESS_DENIED_RBAC', 'Ticket', ticket.reference_id,
                        f"'{current_user.username}' priority change rejected: {exc}")
        flash(str(exc), 'danger')
    return redirect(url_for('tickets.detail', reference_id=reference_id))


@tickets_bp.route('/<reference_id>/details', methods=['POST'])
@login_required
def update_details(reference_id):
    ticket = get_ticket_or_404(reference_id)
    require_view(ticket)
    if not perm.can_work_ticket(current_user, ticket) or ticket.status == TicketStatus.CLOSED:
        abort(403)
    form = DetailsForm()
    if form.validate_on_submit():
        ticket.affected_system = (form.affected_system.data or '').strip() or None
        ticket.department = (form.department.data or '').strip() or None
        ticket.updated_at = utcnow()
        log_audit_event('TICKET_DETAILS_UPDATE', 'Ticket', ticket.reference_id,
                        f"Affected system/department updated by {current_user.username}", commit=False)
        db.session.commit()
        flash('Ticket details updated.', 'success')
    else:
        _form_errors(form)
    return redirect(url_for('tickets.detail', reference_id=reference_id))


@tickets_bp.route('/<reference_id>/comment', methods=['POST'])
@login_required
def add_comment(reference_id):
    """Public comment, or private internal note for technicians/admins."""
    ticket = get_ticket_or_404(reference_id)
    require_view(ticket)
    if not perm.can_comment(current_user, ticket):
        flash('You cannot comment on this ticket (closed tickets must be reopened first; '
              'technicians must claim a ticket before working on it).', 'warning')
        return redirect(url_for('tickets.detail', reference_id=reference_id))

    form = CommentForm()
    if not form.validate_on_submit():
        _form_errors(form)
        return redirect(url_for('tickets.detail', reference_id=reference_id) + '#comments')

    # Employees can never create internal notes, whatever the request contains
    is_internal = bool(form.is_internal.data) and perm.can_post_internal_note(current_user, ticket)
    now = utcnow()
    comment = Comment(ticket_id=ticket.id, user_id=current_user.id, content=form.content.data.strip(),
                      is_internal=is_internal, created_at=now)
    db.session.add(comment)

    if current_user.is_staff and not is_internal and not ticket.first_responded_at:
        ticket.first_responded_at = now  # first public response stops the response-SLA clock
    ticket.updated_at = now

    link = url_for('tickets.detail', reference_id=ticket.reference_id) + '#comments'
    preview = comment.content[:100] + ('…' if len(comment.content) > 100 else '')
    if is_internal:
        if ticket.technician_id and ticket.technician_id != current_user.id:
            create_notification(ticket.technician_id, f"Internal note on {ticket.reference_id}",
                                f"{current_user.full_name}: {preview}", link=link, commit=False)
    else:
        for user_id in {ticket.creator_id, ticket.technician_id} - {None, current_user.id}:
            create_notification(user_id, f"New comment on {ticket.reference_id}",
                                f"{current_user.full_name}: {preview}", link=link, commit=False)

    log_audit_event('TICKET_INTERNAL_NOTE_ADD' if is_internal else 'TICKET_COMMENT_ADD', 'Ticket',
                    ticket.reference_id, f"{'Internal note' if is_internal else 'Comment'} by {current_user.username}",
                    commit=False)
    db.session.commit()
    flash('Internal note added (hidden from the employee).' if is_internal else 'Comment posted.', 'success')
    return redirect(link)


@tickets_bp.route('/<reference_id>/attach', methods=['POST'])
@login_required
def upload_attachment(reference_id):
    ticket = get_ticket_or_404(reference_id)
    require_view(ticket)
    if not perm.can_upload_attachment(current_user, ticket):
        flash('You cannot add attachments to this ticket.', 'warning')
        return redirect(url_for('tickets.detail', reference_id=reference_id))

    form = AttachmentUploadForm()
    if not form.validate_on_submit():
        _form_errors(form)
        return redirect(url_for('tickets.detail', reference_id=reference_id) + '#attachments')

    storage = get_storage()
    try:
        stored = storage.save(form.attachment.data)
    except StorageError as exc:
        log_audit_event('ATTACHMENT_UPLOAD_REJECTED', 'Ticket', ticket.reference_id,
                        f"Upload by {current_user.username} rejected: {exc}")
        flash(f"Upload rejected: {exc}", 'danger')
        return redirect(url_for('tickets.detail', reference_id=reference_id) + '#attachments')

    try:
        now = utcnow()
        att = Attachment(ticket_id=ticket.id, user_id=current_user.id, filename=stored['key'],
                         original_filename=stored['original_filename'], file_size=stored['size'],
                         mime_type=stored['mime_type'], storage_path=stored['key'],
                         checksum_sha256=stored['checksum_sha256'], created_at=now)
        db.session.add(att)
        ticket.updated_at = now
        log_audit_event('ATTACHMENT_UPLOAD', 'Ticket', ticket.reference_id,
                        f"'{stored['original_filename']}' ({stored['size']} bytes) uploaded by {current_user.username}",
                        commit=False)
        for user_id in {ticket.creator_id, ticket.technician_id} - {None, current_user.id}:
            create_notification(user_id, f"New attachment on {ticket.reference_id}",
                                f"{current_user.full_name} uploaded {stored['original_filename']}",
                                link=url_for('tickets.detail', reference_id=ticket.reference_id) + '#attachments',
                                commit=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
        storage.delete(stored['key'])
        raise

    flash(f"'{stored['original_filename']}' uploaded to shared storage.", 'success')
    return redirect(url_for('tickets.detail', reference_id=reference_id) + '#attachments')
