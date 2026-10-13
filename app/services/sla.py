from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models import SLAPolicy, Ticket, TicketPriority, TicketStatus


DEFAULT_SLA_TARGETS = {
    TicketPriority.CRITICAL: {'response': 1, 'resolution': 4},
    TicketPriority.HIGH: {'response': 4, 'resolution': 12},
    TicketPriority.MEDIUM: {'response': 8, 'resolution': 24},
    TicketPriority.LOW: {'response': 24, 'resolution': 72}
}


def calculate_sla_due_dates(priority, start_time=None):
    """
    Computes response_due_at and resolution_due_at timestamps based on SLA policies.
    """
    if start_time is None:
        start_time = datetime.now(timezone.utc)
    elif start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)

    # Check database policy
    policy = SLAPolicy.query.filter_by(priority=priority).first()
    if policy:
        resp_hours = policy.response_time_hours
        resol_hours = policy.resolution_time_hours
    else:
        defaults = DEFAULT_SLA_TARGETS.get(priority, DEFAULT_SLA_TARGETS[TicketPriority.MEDIUM])
        resp_hours = defaults['response']
        resol_hours = defaults['resolution']

    response_due_at = start_time + timedelta(hours=resp_hours)
    resolution_due_at = start_time + timedelta(hours=resol_hours)
    return response_due_at, resolution_due_at


def apply_sla_to_ticket(ticket, start_time=None):
    """Applies SLA deadlines to a newly created or priority-updated ticket."""
    resp_due, resol_due = calculate_sla_due_dates(ticket.priority, start_time or ticket.created_at)
    ticket.response_due_at = resp_due
    ticket.resolution_due_at = resol_due


def get_sla_metrics():
    """
    Aggregates real-time SLA metrics for the administrator dashboard.
    """
    total_tickets = Ticket.query.count()
    if total_tickets == 0:
        return {
            'compliance_rate': 100.0,
            'overdue_count': 0,
            'resolved_within_sla': 0,
            'breached_count': 0,
            'active_overdue_tickets': []
        }

    now = datetime.now(timezone.utc)
    # Active overdue tickets
    open_statuses = [TicketStatus.OPEN, TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS]
    open_tickets = Ticket.query.filter(Ticket.status.in_(open_statuses)).all()
    
    active_overdue = [t for t in open_tickets if t.is_overdue]
    overdue_count = len(active_overdue)

    # Closed/Resolved tickets analysis
    resolved_tickets = Ticket.query.filter(Ticket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED])).all()
    resolved_within_sla = 0
    resolved_breached = 0

    for t in resolved_tickets:
        if t.resolved_at and t.resolution_due_at:
            resolved_at = t.resolved_at.replace(tzinfo=timezone.utc) if t.resolved_at.tzinfo is None else t.resolved_at
            due_at = t.resolution_due_at.replace(tzinfo=timezone.utc) if t.resolution_due_at.tzinfo is None else t.resolution_due_at
            if resolved_at <= due_at:
                resolved_within_sla += 1
            else:
                resolved_breached += 1
        else:
            resolved_within_sla += 1

    total_evaluated = resolved_within_sla + resolved_breached + overdue_count
    compliance_rate = (resolved_within_sla / total_evaluated * 100.0) if total_evaluated > 0 else 100.0

    return {
        'compliance_rate': round(compliance_rate, 1),
        'overdue_count': overdue_count,
        'resolved_within_sla': resolved_within_sla,
        'breached_count': resolved_breached + overdue_count,
        'active_overdue_tickets': active_overdue
    }
