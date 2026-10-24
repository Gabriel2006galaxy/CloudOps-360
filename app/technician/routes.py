from datetime import timedelta

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.auth.decorators import technician_or_admin_required
from app.extensions import db
from app.models import Ticket, TicketPriority, TicketStatus, utcnow
from app.services import metrics
from app.services.assignment import format_minutes, set_availability
from app.services.audit import log_audit_event
from app.services.settings import get_auto_assign_config
from app.services.workflow import WorkflowError, assign_ticket
from app.technician.forms import AvailabilityForm
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

    config = get_auto_assign_config()
    return render_template(
        'technician/workload.html',
        assigned_active=assigned_active,
        overdue_incidents=[t for t in assigned_active if t.is_overdue],
        unassigned_tickets=unassigned,
        recently_resolved=recently_resolved,
        claim_form=ClaimForm(),
        availability_form=AvailabilityForm().fill_from(current_user) if current_user.is_technician else None,
        my_rating=metrics.rating_summary(Ticket.query.filter(Ticket.technician_id == user_id)),
        auto_assign=config,
        wait_labels={p: format_minutes(m) for p, m in config.wait_minutes.items()},
    )


@technician_bp.route('/availability', methods=['POST'])
@login_required
@technician_or_admin_required
def availability():
    """A technician marks themselves available or away."""
    if not current_user.is_technician:
        abort(403)
    form = AvailabilityForm()
    if form.validate_on_submit():
        set_availability(current_user, form.status.data == 'available', note=form.away_note.data,
                         back_on=form.back_on.data, actor=current_user)
        db.session.commit()
        if current_user.is_away:
            flash(f"You are now {current_user.availability_label.lower()}. No new tickets will be auto-assigned to you.", 'info')
        else:
            flash('You are available again and can receive auto-assigned tickets.', 'success')
    else:
        for errors in form.errors.values():
            for err in errors:
                flash(err, 'danger')
    return redirect(url_for('technician.workload'))


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
