from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.auth.decorators import technician_or_admin_required
from app.extensions import db
from app.models import Ticket, TicketPriority, TicketStatus, utcnow
from app.services.audit import log_audit_event
from app.services.workflow import WorkflowError, assign_ticket
from app.tickets.forms import ClaimForm

technician_bp = Blueprint('technician', __name__, url_prefix='/technician')


def _priority_sort_key(ticket):
    due = ticket.resolution_due_at or utcnow() + timedelta(days=3650)
    return (-TicketPriority.RANK.get(ticket.priority, 0), due)


@technician_bp.route('/workload')
@login_required
@technician_or_admin_required
def workload():
    """Personal queue: active assignments, overdue items, unassigned queue, recent resolutions."""
    user_id = current_user.id
    assigned_active = sorted(
        Ticket.query.filter(Ticket.technician_id == user_id, Ticket.status.in_([TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS])).all(),
        key=_priority_sort_key,
    )
    unassigned = sorted(
        Ticket.query.filter(Ticket.technician_id.is_(None), Ticket.status == TicketStatus.OPEN).all(),
        key=_priority_sort_key,
    )
    recently_resolved = (Ticket.query
                         .filter(Ticket.technician_id == user_id, Ticket.status.in_(TicketStatus.DONE))
                         .order_by(Ticket.resolved_at.desc()).limit(10).all())

    return render_template(
        'technician/workload.html',
        assigned_active=assigned_active,
        overdue_incidents=[t for t in assigned_active if t.is_overdue],
        unassigned_tickets=unassigned,
        recently_resolved=recently_resolved,
        claim_form=ClaimForm(),
    )


@technician_bp.route('/claim/<reference_id>', methods=['POST'])
@login_required
@technician_or_admin_required
def claim(reference_id):
    """Self-assign an unassigned Open ticket."""
    ticket = Ticket.query.filter_by(reference_id=reference_id).first_or_404()
    form = ClaimForm()
    if not form.validate_on_submit():
        flash('Your form expired. Please try again.', 'warning')
        return redirect(url_for('technician.workload'))
    try:
        assign_ticket(ticket, current_user, current_user)
        db.session.commit()
        flash(f"{ticket.reference_id} claimed and added to your queue.", 'success')
    except WorkflowError as exc:
        db.session.rollback()
        log_audit_event('TICKET_CLAIM_REJECTED', 'Ticket', ticket.reference_id,
                        f"'{current_user.username}' could not claim {ticket.reference_id}: {exc}")
        flash(str(exc), 'warning')
        return redirect(url_for('technician.workload'))
    return redirect(url_for('tickets.detail', reference_id=reference_id))
