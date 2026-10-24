"""Automatic ticket assignment and technician availability.

Rules (all enforced here, in one place):

1. When auto-assignment is ON, a new ticket goes straight to the best available
   technician.
2. Exception: when every available technician is free (no open tickets), the
   ticket waits in the queue so any technician can claim it.
3. A ticket left unclaimed longer than the wait time for its priority is
   assigned automatically (checked on web requests and by `flask auto-assign`).
4. Choosing the technician:
   - active technicians who are not away,
   - below the maximum number of open tickets,
   - specialists in the ticket's category first (technician skills),
   - lowest workload points (open tickets weighted Critical 4, High 3, Medium 2, Low 1),
   - a random pick only between equally loaded technicians.
5. Away technicians become available again automatically on their 'back on' date.
6. Technicians cannot mark themselves away: they send a leave request and only an
   administrator's approval makes them away.

Functions stage changes on the session and leave the commit to the caller.
"""
import random
import time
from datetime import datetime, time as dt_time, timedelta

from flask import url_for
from sqlalchemy import func

from app.extensions import db
from app.models import (
    Ticket, TicketPriority, TicketStatus, TicketStatusHistory, User, UserRole, format_duration, utcnow,
)
from app.services.audit import log_audit_event
from app.services.notifications import create_notification
from app.services.settings import get_auto_assign_config

S = TicketStatus
WORKLOAD_POINTS = TicketPriority.RANK  # Critical 4, High 3, Medium 2, Low 1


def format_minutes(minutes):
    if minutes <= 0:
        return 'immediately'
    hours, mins = divmod(int(minutes), 60)
    if not hours:
        return f'{mins} min'
    return f'{hours} h' + (f' {mins} min' if mins else '')


def _ticket_link(ticket):
    try:
        return url_for('tickets.detail', reference_id=ticket.reference_id)
    except RuntimeError:  # CLI run without a request context
        return f'/tickets/{ticket.reference_id}'


# ---------------- technicians ---------------- #

def _open_ticket_count(user):
    return Ticket.query.filter(Ticket.technician_id == user.id, Ticket.status.in_(S.ACTIVE)).count()


def active_technicians():
    return (User.query.filter(User.role == UserRole.TECHNICIAN, User.is_active.is_(True))
            .order_by(User.full_name).all())


def available_technicians():
    return [t for t in active_technicians() if not t.is_away]


def technician_loads(technicians):
    """{user_id: {'count': open tickets, 'points': weighted workload}}."""
    loads = {t.id: {'count': 0, 'points': 0} for t in technicians}
    if not loads:
        return loads
    rows = (db.session.query(Ticket.technician_id, Ticket.priority, func.count(Ticket.id))
            .filter(Ticket.technician_id.in_(list(loads)), Ticket.status.in_(S.ACTIVE))
            .group_by(Ticket.technician_id, Ticket.priority).all())
    for tech_id, priority, count in rows:
        loads[tech_id]['count'] += count
        loads[tech_id]['points'] += count * WORKLOAD_POINTS.get(priority, 1)
    return loads


def release_returned_technicians(now=None):
    """Marks technicians available again once their 'back on' moment has passed."""
    now = now or utcnow()
    returned = User.query.filter(User.is_available.is_(False), User.away_until.isnot(None),
                                 User.away_until <= now).all()
    for user in returned:
        user.is_available = True
        user.away_note = None
        user.away_until = None
        log_audit_event('TECH_AVAILABILITY_AUTO_RETURN', 'User', user.id,
                        f"'{user.username}' is available again (away period ended)", commit=False, as_system=True)
    return returned


def set_availability(user, available, note=None, back_on=None, actor=None):
    """Marks a technician available or away. back_on: date they return (00:00 UTC). Caller commits."""
    user.is_available = bool(available)
    user.leave_requested_at = user.leave_note = user.leave_until = None  # a status change settles any request
    user.away_note = None if available else ((note or '').strip()[:120] or None)
    user.away_until = None if available or not back_on else datetime.combine(back_on, dt_time.min)
    by = 'themselves' if actor is None or actor.id == user.id else actor.username
    details = f"'{user.username}' set to {user.availability_label} by {by}"
    if user.away_note:
        details += f" ({user.away_note})"
    log_audit_event('TECH_AVAILABILITY_CHANGE', 'User', user.id, details, commit=False)

    if not available:
        open_count = _open_ticket_count(user)
        if open_count:
            admins = User.query.filter(User.role == UserRole.ADMIN, User.is_active.is_(True)).all()
            for admin in admins:
                if actor is None or admin.id != actor.id:
                    create_notification(admin.id, f"{user.full_name} is away",
                                        f"{user.full_name} is {user.availability_phrase} and still has "
                                        f"{open_count} open ticket(s). Reassign them if they are urgent.",
                                        link=f"/tickets?technician={user.id}&status=active", type='warning',
                                        commit=False)


def request_leave(user, note, back_on=None):
    """A technician asks to be away. Nothing changes until an administrator approves. Caller commits."""
    user.leave_requested_at = utcnow()
    user.leave_note = (note or '').strip()[:120] or None
    user.leave_until = datetime.combine(back_on, dt_time.min) if back_on else None
    details = f"'{user.username}' asked for leave"
    if user.leave_note:
        details += f" ({user.leave_note})"
    log_audit_event('TECH_LEAVE_REQUESTED', 'User', user.id, details, commit=False)

    until = f" until {back_on.strftime('%b %d')}" if back_on else ''
    reason = f": {user.leave_note}" if user.leave_note else ''
    open_count = _open_ticket_count(user)
    for admin in User.query.filter(User.role == UserRole.ADMIN, User.is_active.is_(True)).all():
        create_notification(admin.id, f"Leave request: {user.full_name}",
                            f"{user.full_name} asks to be away{until}{reason}. Open tickets: {open_count}. "
                            f"Approve or reject it on the dashboard.",
                            link='/dashboard/admin', type='warning', commit=False)


def cancel_leave_request(user):
    """The technician withdraws a request that is still waiting. Caller commits."""
    user.leave_requested_at = user.leave_note = user.leave_until = None
    log_audit_event('TECH_LEAVE_CANCELLED', 'User', user.id, f"'{user.username}' withdrew the leave request",
                    commit=False)


def decide_leave_request(user, approve, admin):
    """An administrator approves (the technician becomes away) or rejects a leave request. Caller commits."""
    note = user.leave_note
    back_on = user.leave_until.date() if user.leave_until else None
    until = f" until {back_on.strftime('%b %d')}" if back_on else ''
    if approve:
        set_availability(user, False, note=note, back_on=back_on, actor=admin)
        title, kind = 'Leave approved', 'success'
        message = f"{admin.full_name} approved your leave{until}. You get no new tickets while you are away."
    else:
        user.leave_requested_at = user.leave_note = user.leave_until = None
        title, kind = 'Leave request rejected', 'danger'
        message = f"{admin.full_name} rejected your leave request{until}. Talk to them if you still need the time off."
    log_audit_event('TECH_LEAVE_APPROVED' if approve else 'TECH_LEAVE_REJECTED', 'User', user.id,
                    f"Leave of '{user.username}' {'approved' if approve else 'rejected'} by {admin.username}",
                    commit=False)
    create_notification(user.id, title, message, link='/technician/workload', type=kind, commit=False)


def pending_leave_requests():
    """Leave requests waiting for an administrator's decision (shown on the admin dashboard)."""
    techs = (User.query.filter(User.role == UserRole.TECHNICIAN, User.is_active.is_(True),
                               User.leave_requested_at.isnot(None))
             .order_by(User.leave_requested_at).all())
    return [{'user': tech, 'open_count': _open_ticket_count(tech)} for tech in techs]


def away_technicians_with_work():
    """Away technicians who still hold open tickets (shown to administrators)."""
    rows = []
    for tech in active_technicians():
        if tech.is_away:
            count = _open_ticket_count(tech)
            if count:
                rows.append({'user': tech, 'open_count': count})
    return rows


def technician_overview(config=None):
    """Every active technician with status, skills and workload for the settings page."""
    config = config or get_auto_assign_config()
    technicians = active_technicians()
    loads = technician_loads(technicians)
    return [{
        'user': t,
        'count': loads[t.id]['count'],
        'points': loads[t.id]['points'],
        'full': loads[t.id]['count'] >= config.max_open,
        'away': t.is_away,
    } for t in technicians]


# ---------------- choosing and assigning ---------------- #

def choose_technician(ticket, config, technicians=None, loads=None, rng=None):
    """Returns (technician, reason) or (None, why nobody could be chosen)."""
    rng = rng or random
    technicians = available_technicians() if technicians is None else technicians
    if not technicians:
        return None, 'no technician is available right now (everyone is away)'
    loads = technician_loads(technicians) if loads is None else loads

    under_cap = [t for t in technicians if loads[t.id]['count'] < config.max_open]
    if not under_cap:
        return None, f'every available technician already has the maximum of {config.max_open} open tickets'

    specialists = [t for t in under_cap if any(c.id == ticket.category_id for c in t.skills)]
    pool = specialists or under_cap
    lowest = min(loads[t.id]['points'] for t in pool)
    best = [t for t in pool if loads[t.id]['points'] == lowest]
    chosen = rng.choice(best) if len(best) > 1 else best[0]

    parts = []
    if specialists:
        parts.append(f"specialist in {ticket.category.name}")
    if len(pool) > 1:
        comparison = ', '.join(f"{t.full_name} {loads[t.id]['points']} pts" for t in pool)
        parts.append(f"lightest workload ({comparison})")
    else:
        parts.append(f"workload {loads[chosen.id]['points']} pts")
    if len(best) > 1:
        parts.append('picked at random between equally free technicians')
    return chosen, '; '.join(parts)


def _apply_assignment(ticket, technician, reason, notify_creator=True):
    """Assigns an Open, unassigned ticket. The conditional UPDATE makes this safe when
    several Gunicorn workers or EC2 instances run the sweep at the same moment."""
    now = utcnow()
    updated = (Ticket.query
               .filter(Ticket.id == ticket.id, Ticket.technician_id.is_(None), Ticket.status == S.OPEN)
               .update({Ticket.technician_id: technician.id, Ticket.status: S.ASSIGNED, Ticket.updated_at: now},
                       synchronize_session='fetch'))
    if updated != 1:
        return False

    db.session.add(TicketStatusHistory(
        ticket_id=ticket.id, changed_by_id=None,
        old_status=S.OPEN, new_status=S.ASSIGNED,
        notes=f"Auto-assigned to {technician.full_name}: {reason}", created_at=now,
    ))
    log_audit_event('TICKET_AUTO_ASSIGN', 'Ticket', ticket.reference_id,
                    f"{ticket.reference_id} -> '{technician.username}' ({reason})", commit=False, as_system=True)
    link = _ticket_link(ticket)
    open_count = Ticket.query.filter(Ticket.technician_id == technician.id, Ticket.status.in_(S.ACTIVE)).count()
    create_notification(technician.id, f"Auto-assigned: {ticket.reference_id}",
                        f"[{ticket.priority}] {ticket.title} — {reason}. You now have {open_count} open "
                        f"ticket{'s' if open_count != 1 else ''}.", link=link,
                        type='danger' if ticket.priority == TicketPriority.CRITICAL else 'info', commit=False)
    if notify_creator:
        create_notification(ticket.creator_id, f"Technician update: {ticket.reference_id}",
                            f"Your incident is now handled by {technician.full_name}.",
                            link=link, type='info', commit=False)
    return True


def auto_assign_new_ticket(ticket):
    """Runs when a ticket is created. Caller commits.

    Returns (technician or None, explanation, needs_admin). needs_admin is True
    when nobody can take the ticket (everyone away or at the maximum), so an
    administrator has to assign it by hand.
    """
    config = get_auto_assign_config()
    if not config.enabled:
        return None, 'Auto-assignment is switched off, so the ticket waits in the queue.', False
    release_returned_technicians()
    technicians = available_technicians()
    loads = technician_loads(technicians)
    if technicians and all(loads[t.id]['count'] == 0 for t in technicians):
        wait = format_minutes(config.wait_minutes[ticket.priority])
        return None, (f"Every technician is free, so the ticket waits in the queue for the first one to claim it "
                      f"(assigned automatically after {wait} if nobody does)."), False
    technician, reason = choose_technician(ticket, config, technicians, loads)
    if technician is None:
        return None, f"The ticket waits in the queue: {reason}.", True
    if not _apply_assignment(ticket, technician, reason, notify_creator=False):
        return None, 'The ticket waits in the queue.', False
    return technician, reason, False


def announce_new_ticket(ticket, reporter, technician=None, note='', needs_admin=False):
    """Tells the support team about a new ticket. Caller commits.

    * Technicians (except away ones) hear about every new ticket, with how many
      tickets are waiting in the queue when it was not auto-assigned.
    * Administrators get the same information, and a warning only when nobody
      could take the ticket, because then they must assign it themselves.
    """
    link = _ticket_link(ticket)
    summary = f"[{ticket.priority}] {ticket.title} — reported by {reporter.full_name}"
    critical = ticket.priority == TicketPriority.CRITICAL
    if technician:
        title = f"New incident {ticket.reference_id}"
        message = f"{summary}. Auto-assigned to {technician.full_name}."
    else:
        waiting = Ticket.query.filter(Ticket.technician_id.is_(None), Ticket.status == S.OPEN).count()
        title = f"New ticket in the queue: {ticket.reference_id}"
        message = (f"{summary}. {waiting} ticket{'s are' if waiting != 1 else ' is'} waiting to be claimed "
                   f"in Queue & Workload.")

    skip = {reporter.id} | ({technician.id} if technician else set())
    for tech in active_technicians():
        if tech.id not in skip and not tech.is_away:
            create_notification(tech.id, title, message, link=link,
                                type='danger' if critical else 'info', commit=False)

    admins = User.query.filter(User.role == UserRole.ADMIN, User.is_active.is_(True), User.id.notin_(skip)).all()
    for admin in admins:
        if needs_admin:
            create_notification(admin.id, f"Needs assignment: {ticket.reference_id}",
                                f"{summary}. {note} Please assign it manually.", link=link, type='warning',
                                commit=False)
        else:
            create_notification(admin.id, title, message, link=link, type='danger' if critical else 'info',
                                commit=False)


def _queued_since(ticket):
    """When the ticket (last) entered the Open queue."""
    returned = (db.session.query(func.max(TicketStatusHistory.created_at))
                .filter(TicketStatusHistory.ticket_id == ticket.id,
                        TicketStatusHistory.new_status == S.OPEN).scalar())
    return max(t for t in (ticket.created_at, returned) if t is not None)


def run_auto_assign(force=False, now=None):
    """Assigns queued tickets whose wait time is over (force=True: all of them, used by
    `flask auto-assign --now`).

    Returns (assigned, waiting): lists of (ticket, technician, reason) and (ticket, reason).
    Caller commits.
    """
    config = get_auto_assign_config()
    now = now or utcnow()
    release_returned_technicians(now)
    queue = Ticket.query.filter(Ticket.technician_id.is_(None), Ticket.status == S.OPEN).all()
    queue.sort(key=lambda t: (-WORKLOAD_POINTS.get(t.priority, 0), t.created_at))
    technicians = available_technicians()
    loads = technician_loads(technicians)

    assigned, waiting = [], []
    for ticket in queue:
        limit_minutes = config.wait_minutes[ticket.priority]
        waited = now - _queued_since(ticket)
        if not force and waited < timedelta(minutes=limit_minutes):
            waiting.append((ticket, f"in the queue for {format_duration(waited.total_seconds())}; "
                                    f"auto-assigned after {format_minutes(limit_minutes)}"))
            continue
        technician, reason = choose_technician(ticket, config, technicians, loads)
        if technician is None:
            waiting.append((ticket, reason))
            continue
        prefix = (f"unclaimed for {format_duration(waited.total_seconds())} "
                  f"(limit {format_minutes(limit_minutes)})")
        if waited < timedelta(minutes=limit_minutes):
            prefix = 'assigned early with `flask auto-assign --now`'
        full_reason = f"{prefix}; {reason}"
        if _apply_assignment(ticket, technician, full_reason):
            loads[technician.id]['count'] += 1
            loads[technician.id]['points'] += WORKLOAD_POINTS.get(ticket.priority, 1)
            assigned.append((ticket, technician, full_reason))
    return assigned, waiting


def run_scheduled_sweep(app):
    """Called at the start of web requests: assigns overdue queue tickets at most
    once every AUTO_ASSIGN_SWEEP_SECONDS per worker. Never breaks the request."""
    interval = app.config.get('AUTO_ASSIGN_SWEEP_SECONDS', 60)
    if interval <= 0:
        return
    state = app.extensions.setdefault('cloudops_auto_assign', {'last_run': None})
    now = time.monotonic()
    if state['last_run'] is not None and now - state['last_run'] < interval:
        return
    state['last_run'] = now
    try:
        if not get_auto_assign_config().enabled:
            return
        assigned, _ = run_auto_assign()
        db.session.commit()
        if assigned:
            app.logger.info('[Auto-assign] %d queued ticket(s) assigned', len(assigned))
    except Exception as exc:  # noqa: BLE001 - background work must not fail the page
        db.session.rollback()
        app.logger.error('[Auto-assign] Scheduled run failed: %s', type(exc).__name__)
