"""Server-side ticket authorization policy.

Every route that reads or changes a ticket goes through these functions so the
rules live in one place:

* Administrators: every ticket.
* Support technicians: tickets assigned to them, plus the unassigned Open queue
  (read-only until they claim it).
* Employees: only tickets they created. Never internal technician notes.
"""
from sqlalchemy import and_, or_

from app.models import Ticket, TicketStatus


def visible_tickets_query(user, query=None):
    """Restricts a Ticket query to the rows the user may see."""
    query = query if query is not None else Ticket.query
    if user.is_admin:
        return query
    if user.is_technician:
        return query.filter(or_(
            Ticket.technician_id == user.id,
            and_(Ticket.technician_id.is_(None), Ticket.status == TicketStatus.OPEN),
        ))
    return query.filter(Ticket.creator_id == user.id)


def can_view_ticket(user, ticket):
    if user.is_admin:
        return True
    if user.is_technician:
        return ticket.technician_id == user.id or (
            ticket.technician_id is None and ticket.status == TicketStatus.OPEN
        )
    return ticket.creator_id == user.id


def can_work_ticket(user, ticket):
    """Technician/admin may change status, priority and post internal notes."""
    if user.is_admin:
        return True
    return user.is_technician and ticket.technician_id == user.id


def can_claim_ticket(user, ticket):
    return user.is_staff and ticket.technician_id is None and ticket.status == TicketStatus.OPEN


def can_assign_ticket(user, ticket):
    """Only administrators assign/reassign tickets to other technicians."""
    return user.is_admin and ticket.status != TicketStatus.CLOSED


def can_comment(user, ticket):
    if ticket.status == TicketStatus.CLOSED:
        return False
    if user.is_employee:
        return ticket.creator_id == user.id
    return can_work_ticket(user, ticket)


def can_post_internal_note(user, ticket):
    return user.is_staff and can_work_ticket(user, ticket) and ticket.status != TicketStatus.CLOSED


def can_see_internal_notes(user, ticket):
    return user.is_staff and can_view_ticket(user, ticket)


def can_upload_attachment(user, ticket):
    return can_comment(user, ticket)


def can_rate_ticket(user, ticket):
    """The reporter rates the support once, after a resolved ticket is closed."""
    return (ticket.creator_id == user.id and ticket.status == TicketStatus.CLOSED
            and ticket.resolved_at is not None and ticket.satisfaction_rating is None)


def can_download_attachment(user, attachment):
    return can_view_ticket(user, attachment.ticket)


def can_delete_attachment(user, attachment):
    ticket = attachment.ticket
    if ticket.status == TicketStatus.CLOSED:
        return False
    if user.is_admin:
        return True
    return attachment.user_id == user.id and can_view_ticket(user, ticket)
