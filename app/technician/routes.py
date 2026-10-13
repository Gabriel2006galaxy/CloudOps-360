from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Ticket, TicketStatus, TicketPriority, TicketStatusHistory
from app.auth.decorators import technician_or_admin_required
from app.services.audit import log_audit_event
from app.services.notifications import create_notification

technician_bp = Blueprint('technician', __name__, url_prefix='/technician')


@technician_bp.route('/workload')
@login_required
@technician_or_admin_required
def workload():
    """Technician personal queue and workload management view."""
    user_id = current_user.id
    
    assigned_active = Ticket.query.filter(
        Ticket.technician_id == user_id,
        Ticket.status.in_([TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS])
    ).order_by(Ticket.priority.desc(), Ticket.resolution_due_at.asc()).all()

    overdue_incidents = [t for t in assigned_active if t.is_overdue]

    unassigned_tickets = Ticket.query.filter(
        Ticket.technician_id == None,
        Ticket.status == TicketStatus.OPEN
    ).order_by(Ticket.created_at.asc()).all()

    recently_resolved = Ticket.query.filter(
        Ticket.technician_id == user_id,
        Ticket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED])
    ).order_by(Ticket.resolved_at.desc()).limit(10).all()

    return render_template(
        'technician/workload.html',
        assigned_active=assigned_active,
        overdue_incidents=overdue_incidents,
        unassigned_tickets=unassigned_tickets,
        recently_resolved=recently_resolved
    )


@technician_bp.route('/claim/<reference_id>', methods=['POST'])
@login_required
@technician_or_admin_required
def claim(reference_id):
    """Claim an unassigned ticket into the technician's queue."""
    ticket = Ticket.query.filter_by(reference_id=reference_id).first_or_404()
    
    if ticket.technician_id and ticket.technician_id != current_user.id and not current_user.is_admin:
        flash(f"Ticket {reference_id} is already assigned to {ticket.technician.full_name}.", 'warning')
        return redirect(url_for('tickets.detail', reference_id=reference_id))

    old_status = ticket.status
    ticket.technician_id = current_user.id
    if ticket.status == TicketStatus.OPEN:
        ticket.status = TicketStatus.ASSIGNED
    ticket.updated_at = datetime.now(timezone.utc)

    history = TicketStatusHistory(
        ticket_id=ticket.id,
        changed_by_id=current_user.id,
        old_status=old_status,
        new_status=ticket.status,
        notes=f"Ticket claimed by {current_user.full_name}",
        created_at=datetime.now(timezone.utc)
    )
    db.session.add(history)
    db.session.commit()

    log_audit_event(
        action='TICKET_CLAIM',
        entity_type='Ticket',
        entity_id=ticket.reference_id,
        details=f"Ticket {ticket.reference_id} claimed by technician {current_user.username}"
    )

    create_notification(
        user_id=ticket.creator_id,
        title=f"Technician Assigned: {ticket.reference_id}",
        message=f"{current_user.full_name} has claimed your incident and started review.",
        link=url_for('tickets.detail', reference_id=ticket.reference_id),
        type='info'
    )

    flash(f"Incident {ticket.reference_id} claimed successfully and added to your queue.", 'success')
    return redirect(url_for('tickets.detail', reference_id=reference_id))
