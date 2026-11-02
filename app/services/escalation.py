"""SLA escalation for active tickets.

1. Warning: once 75 % of a ticket's resolution window is used, the assigned
   technician is warned (the administrators when nobody is assigned yet).
2. Escalation: once the resolution SLA is breached, every active administrator
   and the assigned technician are alerted, the ticket shows "Escalated" and
   the event goes to the audit log.

Each step happens once per deadline: a conditional UPDATE marks the ticket, so
several Gunicorn workers never send the same alert twice. Recalculating the SLA
(new priority, reopened ticket, changed policy) clears the marks and starts again.
Runs in the throttled request sweep and in `flask sla-check`.

Functions stage changes on the session and leave the commit to the caller.
"""
from datetime import timedelta

from flask import url_for

from app.models import Ticket, TicketStatus, User, UserRole, as_utc, format_duration, utcnow
from app.services.audit import log_audit_event
from app.services.notifications import create_notification

WARN_PERCENT = 75


def _ticket_link(ticket):
    try:
        return url_for('tickets.detail', reference_id=ticket.reference_id)
    except RuntimeError:  # CLI run without a request context
        return f'/tickets/{ticket.reference_id}'


def _mark_once(ticket, column, now):
    """Sets ticket.<column> = now only if it is still empty. True for the one caller that won."""
    won = (Ticket.query.filter(Ticket.id == ticket.id, getattr(Ticket, column).is_(None))
           .update({column: now}, synchronize_session=False))
    if won:
        setattr(ticket, column, now)
    return bool(won)


def _admins():
    return User.query.filter(User.role == UserRole.ADMIN, User.is_active.is_(True)).all()


def _escalate(ticket, now):
    link = _ticket_link(ticket)
    tech = ticket.technician
    who = tech.full_name if tech else 'nobody (unassigned)'
    overdue_by = format_duration((as_utc(now) - as_utc(ticket.resolution_due_at)).total_seconds())
    for admin in _admins():
        create_notification(admin.id, f"SLA breached: {ticket.reference_id}",
                            f"{ticket.priority} ticket '{ticket.title}' is overdue by {overdue_by}. "
                            f"Assigned to {who}. Reassign it or follow up.",
                            link=link, type='danger', commit=False)
    if tech:
        create_notification(tech.id, f"SLA breached: {ticket.reference_id}",
                            f"'{ticket.title}' passed its resolution deadline and was escalated to the administrators.",
                            link=link, type='danger', commit=False)
    log_audit_event('TICKET_SLA_ESCALATED', 'Ticket', ticket.reference_id,
                    f"Resolution SLA breached ({ticket.priority}); escalated to administrators. Assigned to {who}.",
                    commit=False, as_system=True)


def _warn(ticket, now):
    link = _ticket_link(ticket)
    left = format_duration((as_utc(ticket.resolution_due_at) - as_utc(now)).total_seconds())
    message = (f"'{ticket.title}' is due in {left} ({WARN_PERCENT}% of its {ticket.priority} SLA time is used).")
    recipients = [ticket.technician] if ticket.technician else _admins()
    for user in recipients:
        create_notification(user.id, f"SLA warning: {ticket.reference_id}", message, link=link, type='warning',
                            commit=False)
    log_audit_event('TICKET_SLA_WARNING', 'Ticket', ticket.reference_id,
                    f"{WARN_PERCENT}% of the resolution time used; due in {left}", commit=False, as_system=True)


def run_sla_escalation(now=None):
    """Warns about tickets close to their deadline and escalates breached ones.

    Returns (warned, escalated) lists of tickets.
    """
    now = now or utcnow()
    active = Ticket.query.filter(Ticket.status.in_(TicketStatus.ACTIVE), Ticket.resolution_due_at.isnot(None))

    escalated = []
    for ticket in active.filter(Ticket.resolution_due_at <= now, Ticket.escalated_at.is_(None)).all():
        if _mark_once(ticket, 'escalated_at', now):
            _mark_once(ticket, 'sla_warning_sent_at', now)  # a breached ticket needs no warning any more
            _escalate(ticket, now)
            escalated.append(ticket)

    warned = []
    for ticket in active.filter(Ticket.resolution_due_at > now, Ticket.sla_warning_sent_at.is_(None)).all():
        start, due = as_utc(ticket.created_at), as_utc(ticket.resolution_due_at)
        warn_at = start + timedelta(seconds=(due - start).total_seconds() * WARN_PERCENT / 100)
        if as_utc(now) >= warn_at and _mark_once(ticket, 'sla_warning_sent_at', now):
            _warn(ticket, now)
            warned.append(ticket)
    return warned, escalated
