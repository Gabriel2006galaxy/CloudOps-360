"""Ticket lifecycle engine: status transitions, assignment and priority changes.

Workflow: Open -> Assigned -> In Progress -> Resolved -> Closed, with
authorized reopening. All rules are enforced here on the server; templates only
render the transitions this module reports as allowed.

Functions stage changes on the SQLAlchemy session (history, audit entries and
notifications included) and leave the commit to the caller, so each user action
is persisted atomically.
"""
from datetime import timedelta

from flask import url_for

from app.extensions import db
from app.models import Ticket, TicketPriority, TicketStatus, TicketStatusHistory, User, UserRole, as_utc, utcnow
from app.services.audit import log_audit_event
from app.services.notifications import create_notification
from app.services.permissions import can_assign_ticket, can_claim_ticket, can_work_ticket
from app.services.sla import apply_sla_to_ticket

S = TicketStatus
REOPEN_WINDOW_DAYS = 14
MIN_RESOLUTION_SUMMARY = 10

# Transitions a technician may perform on tickets assigned to them
TECHNICIAN_EDGES = {
    (S.ASSIGNED, S.IN_PROGRESS),
    (S.IN_PROGRESS, S.RESOLVED),
    (S.RESOLVED, S.IN_PROGRESS),
    (S.RESOLVED, S.CLOSED),
}

ACTION_LABELS = {
    (S.ASSIGNED, S.IN_PROGRESS): ('Start Work', 'bi-play-circle', 'btn-cyan'),
    (S.IN_PROGRESS, S.RESOLVED): ('Resolve', 'bi-check2-circle', 'btn-success'),
    (S.RESOLVED, S.CLOSED): ('Confirm & Close', 'bi-lock', 'btn-outline-secondary'),
    (S.RESOLVED, S.IN_PROGRESS): ('Reopen', 'bi-arrow-counterclockwise', 'btn-outline-warning'),
    (S.CLOSED, S.IN_PROGRESS): ('Reopen', 'bi-arrow-counterclockwise', 'btn-outline-warning'),
    (S.CLOSED, S.OPEN): ('Reopen', 'bi-arrow-counterclockwise', 'btn-outline-warning'),
    (S.IN_PROGRESS, S.ASSIGNED): ('Pause (back to Assigned)', 'bi-pause-circle', 'btn-outline-secondary'),
    (S.ASSIGNED, S.OPEN): ('Return to Queue', 'bi-inbox', 'btn-outline-secondary'),
    (S.OPEN, S.CLOSED): ('Close (cancel)', 'bi-x-circle', 'btn-outline-danger'),
    (S.ASSIGNED, S.CLOSED): ('Close (cancel)', 'bi-x-circle', 'btn-outline-danger'),
}


class WorkflowError(Exception):
    """A requested change violates the workflow or the actor's permissions."""


def _reopen_window_open(ticket):
    if ticket.status != S.CLOSED or not ticket.closed_at:
        return True
    return utcnow() - as_utc(ticket.closed_at).replace(tzinfo=None) <= timedelta(days=REOPEN_WINDOW_DAYS)


def _role_may(user, ticket, target):
    edge = (ticket.status, target)
    if user.is_admin:
        return True
    if user.is_technician:
        return ticket.technician_id == user.id and edge in TECHNICIAN_EDGES
    # Employees: only on their own tickets - confirm a resolution or reopen it
    if ticket.creator_id != user.id:
        return False
    if edge in {(S.RESOLVED, S.CLOSED), (S.RESOLVED, S.IN_PROGRESS)}:
        return True
    if ticket.status == S.CLOSED and target in (S.IN_PROGRESS, S.OPEN):
        return _reopen_window_open(ticket)
    return False


def allowed_transitions(user, ticket):
    """Statuses the user may move this ticket to right now."""
    targets = []
    for target in S.TRANSITIONS.get(ticket.status, []):
        # Structural preconditions
        if target == S.ASSIGNED and not ticket.technician_id:
            continue
        if ticket.status == S.CLOSED and target == S.IN_PROGRESS and not ticket.technician_id:
            continue
        if ticket.status == S.CLOSED and target == S.OPEN and ticket.technician_id:
            continue
        if _role_may(user, ticket, target):
            targets.append(target)
    return targets


def transition_actions(user, ticket):
    """Allowed transitions with UI labels for the ticket detail page."""
    actions = []
    for target in allowed_transitions(user, ticket):
        label, icon, css = ACTION_LABELS.get((ticket.status, target), (f'Move to {target}', 'bi-arrow-right', 'btn-outline-secondary'))
        actions.append({'target': target, 'label': label, 'icon': icon, 'css': css,
                        'needs_summary': target == S.RESOLVED,
                        'is_reopen': ticket.status in S.DONE and target in S.ACTIVE})
    return actions


def _ticket_link(ticket):
    return url_for('tickets.detail', reference_id=ticket.reference_id)


def _record_history(ticket, actor, old_status, new_status, notes):
    db.session.add(TicketStatusHistory(
        ticket_id=ticket.id,
        changed_by_id=actor.id,
        old_status=old_status,
        new_status=new_status,
        notes=notes,
        created_at=utcnow(),
    ))


def change_status(ticket, new_status, actor, note=None, resolution_summary=None):
    """Validates and applies a status transition. Caller commits."""
    if new_status not in S.VALUES:
        raise WorkflowError('Unknown status.')
    if new_status == ticket.status:
        raise WorkflowError(f'Ticket is already {new_status}.')
    if new_status not in allowed_transitions(actor, ticket):
        raise WorkflowError(f'You are not allowed to move this ticket from {ticket.status} to {new_status}.')

    now = utcnow()
    old_status = ticket.status
    note = (note or '').strip() or None

    if new_status == S.RESOLVED:
        summary = (resolution_summary or ticket.resolution_summary or '').strip()
        if len(summary) < MIN_RESOLUTION_SUMMARY:
            raise WorkflowError(f'A resolution summary of at least {MIN_RESOLUTION_SUMMARY} characters is required to resolve a ticket.')
        ticket.resolution_summary = summary
        ticket.resolved_at = now
        if not ticket.first_responded_at:
            ticket.first_responded_at = now
    elif new_status == S.CLOSED:
        ticket.closed_at = now
    elif new_status == S.OPEN:
        ticket.technician_id = None if old_status != S.CLOSED else ticket.technician_id

    if new_status == S.IN_PROGRESS and not ticket.first_responded_at and actor.is_staff:
        ticket.first_responded_at = now

    is_reopen = old_status in S.DONE and new_status in S.ACTIVE
    if is_reopen:
        ticket.resolved_at = None
        ticket.closed_at = None
        # A reopened incident gets a fresh resolution window from now
        apply_sla_to_ticket(ticket, start_time=now, response=False)

    ticket.status = new_status
    ticket.updated_at = now

    default_note = f"{'Reopened' if is_reopen else 'Status changed'} by {actor.full_name}"
    _record_history(ticket, actor, old_status, new_status, note or (ticket.resolution_summary if new_status == S.RESOLVED else default_note))

    log_audit_event(
        action='TICKET_REOPEN' if is_reopen else 'TICKET_STATUS_CHANGE',
        entity_type='Ticket', entity_id=ticket.reference_id,
        details=f"{old_status} -> {new_status} by {actor.username}",
        commit=False,
    )

    message = f"{ticket.reference_id} moved from {old_status} to {new_status} by {actor.full_name}."
    kind = 'success' if new_status == S.RESOLVED else ('warning' if is_reopen else 'info')
    recipients = {ticket.creator_id, ticket.technician_id} - {None, actor.id}
    for user_id in recipients:
        create_notification(user_id, f"Status: {ticket.reference_id} is {new_status}", message,
                            link=_ticket_link(ticket), type=kind, commit=False)
    return old_status


def assign_ticket(ticket, technician, actor):
    """Assigns (or unassigns when technician is None) a ticket. Caller commits."""
    claiming = technician is not None and technician.id == actor.id and not actor.is_admin
    if claiming:
        if not can_claim_ticket(actor, ticket):
            raise WorkflowError('Only unassigned tickets in the Open queue can be claimed.')
    elif not can_assign_ticket(actor, ticket):
        raise WorkflowError('Only administrators can assign tickets to other technicians.')

    if technician is not None and (not technician.is_active or technician.role not in UserRole.STAFF):
        raise WorkflowError('Tickets can only be assigned to active technicians or administrators.')

    old_tech = ticket.technician
    if (old_tech.id if old_tech else None) == (technician.id if technician else None):
        return False

    now = utcnow()
    ticket.technician_id = technician.id if technician else None
    ticket.updated_at = now
    old_status = ticket.status

    if technician and ticket.status == S.OPEN:
        ticket.status = S.ASSIGNED
        _record_history(ticket, actor, old_status, S.ASSIGNED,
                        f"{'Claimed' if claiming else 'Assigned to ' + technician.full_name} by {actor.full_name}")
    elif technician is None and ticket.status in (S.ASSIGNED, S.IN_PROGRESS):
        ticket.status = S.OPEN
        _record_history(ticket, actor, old_status, S.OPEN, f"Returned to the unassigned queue by {actor.full_name}")

    log_audit_event(
        action='TICKET_CLAIM' if claiming else 'TICKET_ASSIGNMENT_CHANGE',
        entity_type='Ticket', entity_id=ticket.reference_id,
        details=f"Assignee '{old_tech.username if old_tech else 'unassigned'}' -> "
                f"'{technician.username if technician else 'unassigned'}' by {actor.username}",
        commit=False,
    )

    if technician and technician.id != actor.id:
        create_notification(technician.id, f"Assigned: {ticket.reference_id}",
                            f"You have been assigned [{ticket.priority}] {ticket.title}",
                            link=_ticket_link(ticket), type='danger' if ticket.priority == TicketPriority.CRITICAL else 'info',
                            commit=False)
    if old_tech and old_tech.id != actor.id and (not technician or old_tech.id != technician.id):
        create_notification(old_tech.id, f"Unassigned: {ticket.reference_id}",
                            f"{ticket.reference_id} was reassigned by {actor.full_name}.",
                            link=None, type='warning', commit=False)
    if ticket.creator_id != actor.id:
        who = technician.full_name if technician else 'the support queue'
        create_notification(ticket.creator_id, f"Technician update: {ticket.reference_id}",
                            f"Your incident is now handled by {who}.",
                            link=_ticket_link(ticket), type='info', commit=False)
    return True


def change_priority(ticket, new_priority, actor):
    """Changes priority and recalculates SLA targets. Caller commits."""
    if new_priority not in TicketPriority.VALUES:
        raise WorkflowError('Unknown priority.')
    if not can_work_ticket(actor, ticket):
        raise WorkflowError('Only the assigned technician or an administrator can change priority.')
    if ticket.is_resolved:
        raise WorkflowError('Priority cannot be changed on a resolved or closed ticket.')
    if new_priority == ticket.priority:
        return False

    old_priority = ticket.priority
    ticket.priority = new_priority
    ticket.updated_at = utcnow()
    apply_sla_to_ticket(ticket, start_time=ticket.created_at)

    log_audit_event(
        action='TICKET_PRIORITY_CHANGE', entity_type='Ticket', entity_id=ticket.reference_id,
        details=f"Priority {old_priority} -> {new_priority} by {actor.username}; SLA targets recalculated",
        commit=False,
    )
    if ticket.creator_id != actor.id:
        create_notification(ticket.creator_id, f"Priority: {ticket.reference_id}",
                            f"Priority changed from {old_priority} to {new_priority}.",
                            link=_ticket_link(ticket), type='info', commit=False)
    return True


def staff_choices():
    """Active technicians and administrators eligible for assignment."""
    return User.query.filter(User.role.in_(UserRole.STAFF), User.is_active.is_(True)).order_by(User.full_name).all()


def new_ticket_reference(ticket):
    """INC-<year>-<zero padded id>. Derived from the primary key, so it is unique
    even when several Gunicorn workers create tickets at the same moment."""
    year = (ticket.created_at or utcnow()).year
    return f"INC-{year}-{ticket.id:05d}"


__all__ = [
    'WorkflowError', 'allowed_transitions', 'transition_actions', 'change_status',
    'assign_ticket', 'change_priority', 'staff_choices', 'new_ticket_reference', 'Ticket',
]
