from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required, current_user
from sqlalchemy import or_, desc, asc
from app.extensions import db
from app.models import (
    Ticket, TicketStatus, TicketPriority, TicketCategory,
    Comment, Attachment, TicketStatusHistory, User, UserRole
)
from app.tickets.forms import TicketCreateForm, TicketUpdateForm, CommentForm, AttachmentUploadForm
from app.services.storage import save_file
from app.services.sla import apply_sla_to_ticket
from app.services.audit import log_audit_event
from app.services.notifications import create_notification
from app.auth.decorators import technician_or_admin_required

tickets_bp = Blueprint('tickets', __name__, url_prefix='/tickets')


def generate_ticket_reference():
    """Generates an enterprise-standard incident reference e.g., INC-2026-00001."""
    year = datetime.now(timezone.utc).year
    prefix = f"INC-{year}-"
    last_ticket = Ticket.query.filter(Ticket.reference_id.like(f"{prefix}%")).order_by(Ticket.id.desc()).first()
    if last_ticket and last_ticket.reference_id:
        try:
            seq_num = int(last_ticket.reference_id.split('-')[-1]) + 1
        except (ValueError, IndexError):
            seq_num = 1
    else:
        seq_num = 1
    return f"{prefix}{seq_num:05d}"


@tickets_bp.route('', methods=['GET'])
@login_required
def index():
    """List tickets with robust filtering, search, sorting, and RBAC isolation."""
    query = Ticket.query

    # RBAC Data Isolation: Employees can only view tickets they created
    if current_user.is_employee:
        query = query.filter(Ticket.creator_id == current_user.id)

    # Search query
    q = request.args.get('q', '').strip()
    if q:
        search_filter = or_(
            Ticket.reference_id.ilike(f"%{q}%"),
            Ticket.title.ilike(f"%{q}%"),
            Ticket.description.ilike(f"%{q}%"),
            Ticket.affected_system.ilike(f"%{q}%"),
            Ticket.department.ilike(f"%{q}%")
        )
        query = query.filter(search_filter)

    # Status filter
    status = request.args.get('status', '').strip()
    if status and status in [s[0] for s in TicketStatus.CHOICES]:
        query = query.filter(Ticket.status == status)

    # Priority filter
    priority = request.args.get('priority', '').strip()
    if priority and priority in [p[0] for p in TicketPriority.CHOICES]:
        query = query.filter(Ticket.priority == priority)

    # Category filter
    category_id = request.args.get('category_id', type=int)
    if category_id:
        query = query.filter(Ticket.category_id == category_id)

    # Technician filter (for Technicians and Admins)
    technician_id = request.args.get('technician_id', type=int)
    if technician_id is not None and not current_user.is_employee:
        if technician_id == 0:
            query = query.filter(Ticket.technician_id == None)
        else:
            query = query.filter(Ticket.technician_id == technician_id)

    # Overdue filter
    overdue_only = request.args.get('overdue', type=int)
    if overdue_only == 1:
        now = datetime.now(timezone.utc)
        query = query.filter(
            Ticket.status.notin_([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
            Ticket.resolution_due_at < now
        )

    # Sorting
    sort_by = request.args.get('sort_by', 'created_at')
    order = request.args.get('order', 'desc')
    
    sort_column = {
        'reference_id': Ticket.reference_id,
        'title': Ticket.title,
        'priority': Ticket.priority,
        'status': Ticket.status,
        'created_at': Ticket.created_at,
        'resolution_due_at': Ticket.resolution_due_at
    }.get(sort_by, Ticket.created_at)

    query = query.order_by(desc(sort_column) if order == 'desc' else asc(sort_column))

    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = 10
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    tickets = pagination.items

    categories = TicketCategory.query.filter_by(is_active=True).order_by(TicketCategory.name).all()
    technicians = User.query.filter(User.role.in_([UserRole.TECHNICIAN, UserRole.ADMIN]), User.is_active == True).all()

    return render_template(
        'tickets/index.html',
        tickets=tickets,
        pagination=pagination,
        categories=categories,
        technicians=technicians,
        current_status=status,
        current_priority=priority,
        current_category=category_id,
        current_technician=technician_id,
        current_search=q,
        current_sort=sort_by,
        current_order=order,
        overdue_only=overdue_only
    )


@tickets_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create a new IT incident ticket with optional initial file upload."""
    form = TicketCreateForm()
    if form.validate_on_submit():
        ref_id = generate_ticket_reference()
        ticket = Ticket(
            reference_id=ref_id,
            title=form.title.data.strip(),
            description=form.description.data.strip(),
            category_id=form.category_id.data,
            priority=form.priority.data,
            status=TicketStatus.OPEN,
            creator_id=current_user.id,
            affected_system=form.affected_system.data.strip() if form.affected_system.data else None,
            department=form.department.data.strip() if form.department.data else (current_user.department or None),
            created_at=datetime.now(timezone.utc)
        )
        
        # Apply SLA targets based on priority
        apply_sla_to_ticket(ticket)
        
        db.session.add(ticket)
        db.session.flush()  # Obtain ticket.id for attachments and status history

        # Record initial status history
        history = TicketStatusHistory(
            ticket_id=ticket.id,
            changed_by_id=current_user.id,
            old_status='None',
            new_status=TicketStatus.OPEN,
            notes='Ticket created by employee.',
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(history)

        # Handle attachment if uploaded
        if form.attachment.data and form.attachment.data.filename:
            try:
                stored_filename, orig_name, file_size, storage_path, mime_type = save_file(form.attachment.data)
                attachment = Attachment(
                    ticket_id=ticket.id,
                    user_id=current_user.id,
                    filename=stored_filename,
                    original_filename=orig_name,
                    file_size=file_size,
                    mime_type=mime_type,
                    storage_path=storage_path,
                    created_at=datetime.now(timezone.utc)
                )
                db.session.add(attachment)
            except Exception as e:
                db.session.rollback()
                flash(f"Error saving diagnostic attachment: {e}", 'danger')
                return render_template('tickets/create.html', form=form)

        db.session.commit()

        # Audit log entry
        log_audit_event(
            action='TICKET_CREATE',
            entity_type='Ticket',
            entity_id=ticket.reference_id,
            details=f"Ticket '{ticket.reference_id}' ({ticket.priority}) created by {current_user.username}"
        )

        # Notify active technicians and admins
        techs = User.query.filter(User.role.in_([UserRole.TECHNICIAN, UserRole.ADMIN]), User.is_active == True).all()
        for tech in techs:
            create_notification(
                user_id=tech.id,
                title=f"New Incident: {ticket.reference_id}",
                message=f"[{ticket.priority}] {ticket.title} submitted by {current_user.full_name}",
                link=url_for('tickets.detail', reference_id=ticket.reference_id),
                type='info' if ticket.priority != TicketPriority.CRITICAL else 'danger'
            )

        flash(f"Incident ticket {ticket.reference_id} created successfully!", 'success')
        return redirect(url_for('tickets.detail', reference_id=ticket.reference_id))

    return render_template('tickets/create.html', form=form)


@tickets_bp.route('/<reference_id>', methods=['GET'])
@login_required
def detail(reference_id):
    """View ticket details, comment thread, attachments, and audit timeline."""
    ticket = Ticket.query.filter_by(reference_id=reference_id).first_or_404()

    # RBAC verification: Employees cannot view other employees' tickets
    if current_user.is_employee and ticket.creator_id != current_user.id:
        log_audit_event(
            action='TICKET_UNAUTHORIZED_VIEW_ATTEMPT',
            entity_type='Ticket',
            entity_id=reference_id,
            details=f"Employee '{current_user.username}' attempted to view restricted ticket {reference_id}"
        )
        abort(403)

    # Filter comments: Employees CANNOT see internal technician notes!
    comments_query = Comment.query.filter_by(ticket_id=ticket.id)
    if current_user.is_employee:
        comments_query = comments_query.filter_by(is_internal=False)
    comments = comments_query.order_by(Comment.created_at.asc()).all()

    comment_form = CommentForm()
    attachment_form = AttachmentUploadForm()
    update_form = TicketUpdateForm(obj=ticket)
    update_form.technician_id.data = ticket.technician_id or 0

    return render_template(
        'tickets/detail.html',
        ticket=ticket,
        comments=comments,
        comment_form=comment_form,
        attachment_form=attachment_form,
        update_form=update_form,
        status_history=ticket.status_history
    )


@tickets_bp.route('/<reference_id>/update', methods=['POST'])
@login_required
@technician_or_admin_required
def update(reference_id):
    """Updates ticket status, priority, assignment, and resolution details."""
    ticket = Ticket.query.filter_by(reference_id=reference_id).first_or_404()
    form = TicketUpdateForm()

    if form.validate_on_submit():
        old_status = ticket.status
        new_status = form.status.data
        old_priority = ticket.priority
        new_priority = form.priority.data
        new_tech_id = form.technician_id.data if form.technician_id.data != 0 else None

        # Validate status transition if status changed
        if new_status != old_status:
            if not ticket.can_transition_to(new_status) and not current_user.is_admin:
                flash(f"Invalid status transition from {old_status} to {new_status}.", 'danger')
                return redirect(url_for('tickets.detail', reference_id=reference_id))

            ticket.status = new_status
            if new_status == TicketStatus.RESOLVED:
                ticket.resolved_at = datetime.now(timezone.utc)
                if form.resolution_summary.data:
                    ticket.resolution_summary = form.resolution_summary.data.strip()
            elif new_status == TicketStatus.CLOSED:
                ticket.closed_at = datetime.now(timezone.utc)
            elif new_status == TicketStatus.IN_PROGRESS and not ticket.first_responded_at:
                ticket.first_responded_at = datetime.now(timezone.utc)

            # Record status history
            history = TicketStatusHistory(
                ticket_id=ticket.id,
                changed_by_id=current_user.id,
                old_status=old_status,
                new_status=new_status,
                notes=form.resolution_summary.data or f"Status updated by {current_user.full_name}",
                created_at=datetime.now(timezone.utc)
            )
            db.session.add(history)

            # Notify creator
            create_notification(
                user_id=ticket.creator_id,
                title=f"Status Updated: {ticket.reference_id}",
                message=f"Your ticket status changed to '{new_status}' by {current_user.full_name}",
                link=url_for('tickets.detail', reference_id=ticket.reference_id),
                type='success' if new_status == TicketStatus.RESOLVED else 'info'
            )

        # Update assignment
        if new_tech_id != ticket.technician_id:
            old_tech = ticket.technician.full_name if ticket.technician else 'Unassigned'
            ticket.technician_id = new_tech_id
            if new_tech_id:
                new_tech = User.query.get(new_tech_id)
                if ticket.status == TicketStatus.OPEN:
                    ticket.status = TicketStatus.ASSIGNED
                create_notification(
                    user_id=new_tech_id,
                    title=f"Ticket Assigned: {ticket.reference_id}",
                    message=f"You have been assigned to incident {ticket.reference_id}: {ticket.title}",
                    link=url_for('tickets.detail', reference_id=ticket.reference_id),
                    type='info'
                )
            log_audit_event(
                action='TICKET_ASSIGNMENT_CHANGE',
                entity_type='Ticket',
                entity_id=ticket.reference_id,
                details=f"Assigned changed from '{old_tech}' to '{new_tech.full_name if new_tech_id else 'Unassigned'}'"
            )

        # Update priority and recalculate SLA if necessary
        if new_priority != old_priority:
            ticket.priority = new_priority
            if not ticket.is_resolved:
                apply_sla_to_ticket(ticket, start_time=ticket.created_at)
            log_audit_event(
                action='TICKET_PRIORITY_CHANGE',
                entity_type='Ticket',
                entity_id=ticket.reference_id,
                details=f"Priority updated from {old_priority} to {new_priority}. SLA recalculation applied."
            )

        if form.affected_system.data:
            ticket.affected_system = form.affected_system.data.strip()
        if form.department.data:
            ticket.department = form.department.data.strip()
        if form.resolution_summary.data:
            ticket.resolution_summary = form.resolution_summary.data.strip()

        ticket.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        log_audit_event(
            action='TICKET_UPDATE',
            entity_type='Ticket',
            entity_id=ticket.reference_id,
            details=f"Ticket {ticket.reference_id} updated (Status: {ticket.status}, Priority: {ticket.priority})"
        )

        flash('Ticket details updated successfully.', 'success')
    else:
        for field, errors in form.errors.items():
            for err in errors:
                flash(f"Error in {field}: {err}", 'danger')

    return redirect(url_for('tickets.detail', reference_id=reference_id))


@tickets_bp.route('/<reference_id>/comment', methods=['POST'])
@login_required
def add_comment(reference_id):
    """Post public comment or private internal technician note."""
    ticket = Ticket.query.filter_by(reference_id=reference_id).first_or_404()

    # RBAC check for ticket view permission
    if current_user.is_employee and ticket.creator_id != current_user.id:
        abort(403)

    form = CommentForm()
    if form.validate_on_submit():
        # RBAC Check: Employees can NEVER post internal notes
        is_internal = form.is_internal.data
        if current_user.is_employee:
            is_internal = False

        comment = Comment(
            ticket_id=ticket.id,
            user_id=current_user.id,
            content=form.content.data.strip(),
            is_internal=is_internal,
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(comment)

        # If technician is responding for the first time, update first_responded_at
        if current_user.is_technician or current_user.is_admin:
            if not ticket.first_responded_at:
                ticket.first_responded_at = datetime.now(timezone.utc)
            if ticket.status == TicketStatus.ASSIGNED:
                ticket.status = TicketStatus.IN_PROGRESS

        ticket.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        # Send notifications
        if not is_internal:
            # If commenter is technician/admin, notify creator
            if current_user.id != ticket.creator_id:
                create_notification(
                    user_id=ticket.creator_id,
                    title=f"New Comment on {ticket.reference_id}",
                    message=f"{current_user.full_name} commented: {comment.content[:80]}...",
                    link=url_for('tickets.detail', reference_id=ticket.reference_id),
                    type='info'
                )
            # If commenter is employee/creator, notify technician if assigned
            elif ticket.technician_id and ticket.technician_id != current_user.id:
                create_notification(
                    user_id=ticket.technician_id,
                    title=f"Client Response: {ticket.reference_id}",
                    message=f"{current_user.full_name} commented: {comment.content[:80]}...",
                    link=url_for('tickets.detail', reference_id=ticket.reference_id),
                    type='info'
                )

        log_audit_event(
            action='TICKET_COMMENT_ADD',
            entity_type='Ticket',
            entity_id=ticket.reference_id,
            details=f"Comment added by {current_user.username} (Internal: {is_internal})"
        )

        flash('Comment posted successfully.', 'success')
    else:
        flash('Failed to post comment. Please provide valid text content.', 'danger')

    return redirect(url_for('tickets.detail', reference_id=reference_id))


@tickets_bp.route('/<reference_id>/attach', methods=['POST'])
@login_required
def upload_attachment(reference_id):
    """Upload supplemental attachment to existing ticket."""
    ticket = Ticket.query.filter_by(reference_id=reference_id).first_or_404()

    # RBAC Check
    if current_user.is_employee and ticket.creator_id != current_user.id:
        abort(403)

    form = AttachmentUploadForm()
    if form.validate_on_submit():
        if form.attachment.data:
            try:
                stored_name, orig_name, file_size, storage_path, mime_type = save_file(form.attachment.data)
                attachment = Attachment(
                    ticket_id=ticket.id,
                    user_id=current_user.id,
                    filename=stored_name,
                    original_filename=orig_name,
                    file_size=file_size,
                    mime_type=mime_type,
                    storage_path=storage_path,
                    created_at=datetime.now(timezone.utc)
                )
                db.session.add(attachment)
                ticket.updated_at = datetime.now(timezone.utc)
                db.session.commit()

                log_audit_event(
                    action='ATTACHMENT_UPLOAD',
                    entity_type='Ticket',
                    entity_id=ticket.reference_id,
                    details=f"File '{orig_name}' ({attachment.file_size_display}) uploaded by {current_user.username}"
                )

                flash(f"File '{orig_name}' uploaded successfully to shared storage.", 'success')
            except Exception as e:
                flash(f"Upload failed: {e}", 'danger')
    return redirect(url_for('tickets.detail', reference_id=reference_id))


@tickets_bp.route('/<reference_id>/reopen', methods=['POST'])
@login_required
def reopen(reference_id):
    """Reopens a resolved or closed ticket."""
    ticket = Ticket.query.filter_by(reference_id=reference_id).first_or_404()
    if current_user.is_employee and ticket.creator_id != current_user.id:
        abort(403)

    if ticket.status not in [TicketStatus.RESOLVED, TicketStatus.CLOSED]:
        flash('Only resolved or closed tickets can be reopened.', 'warning')
        return redirect(url_for('tickets.detail', reference_id=reference_id))

    old_status = ticket.status
    ticket.status = TicketStatus.IN_PROGRESS
    ticket.resolved_at = None
    ticket.closed_at = None
    ticket.updated_at = datetime.now(timezone.utc)

    # Reapply SLA target from current time
    apply_sla_to_ticket(ticket, start_time=datetime.now(timezone.utc))

    history = TicketStatusHistory(
        ticket_id=ticket.id,
        changed_by_id=current_user.id,
        old_status=old_status,
        new_status=TicketStatus.IN_PROGRESS,
        notes=f"Ticket reopened by {current_user.full_name}",
        created_at=datetime.now(timezone.utc)
    )
    db.session.add(history)
    db.session.commit()

    log_audit_event(
        action='TICKET_REOPEN',
        entity_type='Ticket',
        entity_id=ticket.reference_id,
        details=f"Ticket {ticket.reference_id} reopened by {current_user.username}"
    )

    if ticket.technician_id and ticket.technician_id != current_user.id:
        create_notification(
            user_id=ticket.technician_id,
            title=f"Incident Reopened: {ticket.reference_id}",
            message=f"{current_user.full_name} has reopened ticket {ticket.reference_id}.",
            link=url_for('tickets.detail', reference_id=ticket.reference_id),
            type='warning'
        )

    flash('Ticket has been reopened and set to In Progress.', 'info')
    return redirect(url_for('tickets.detail', reference_id=reference_id))
