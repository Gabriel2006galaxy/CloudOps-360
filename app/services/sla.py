"""SLA engine: priority-based response/resolution targets and compliance metrics.

All timestamps are UTC. Targets come from the configurable sla_policies table;
DEFAULT_SLA_TARGETS is only used if an administrator deleted a policy row.
"""
from datetime import timedelta

from app.models import SLAPolicy, Ticket, TicketPriority, TicketStatus, as_utc, utcnow

DEFAULT_SLA_TARGETS = {
    TicketPriority.CRITICAL: {'response': 1, 'resolution': 4},
    TicketPriority.HIGH: {'response': 4, 'resolution': 12},
    TicketPriority.MEDIUM: {'response': 8, 'resolution': 24},
    TicketPriority.LOW: {'response': 24, 'resolution': 72}
}


def _naive_utc(value):
    return as_utc(value).replace(tzinfo=None) if value is not None else None


def get_sla_targets(priority):
    """Returns (response_hours, resolution_hours) for a priority."""
    policy = SLAPolicy.query.filter_by(priority=priority).first()
    if policy:
        return policy.response_time_hours, policy.resolution_time_hours
    defaults = DEFAULT_SLA_TARGETS.get(priority, DEFAULT_SLA_TARGETS[TicketPriority.MEDIUM])
    return defaults['response'], defaults['resolution']


def calculate_sla_due_dates(priority, start_time=None):
    """Computes (response_due_at, resolution_due_at) as naive UTC datetimes."""
    start = _naive_utc(start_time) if start_time is not None else utcnow()
    resp_hours, resol_hours = get_sla_targets(priority)
    return start + timedelta(hours=resp_hours), start + timedelta(hours=resol_hours)


def apply_sla_to_ticket(ticket, start_time=None, response=True):
    """Applies SLA deadlines to a new, re-prioritised or reopened ticket."""
    resp_due, resol_due = calculate_sla_due_dates(ticket.priority, start_time or ticket.created_at)
    if response:
        ticket.response_due_at = resp_due
    ticket.resolution_due_at = resol_due


def overdue_filter(query):
    """SQL filter for active tickets whose resolution target has passed."""
    return query.filter(
        Ticket.status.in_(TicketStatus.ACTIVE),
        Ticket.resolution_due_at.isnot(None),
        Ticket.resolution_due_at < utcnow(),
    )


def compute_sla_metrics(tickets):
    """Pure function: SLA metrics for an iterable of tickets.

    compliance_rate = resolved within target / (all resolved + active overdue).
    Returns None for compliance_rate when nothing has been evaluated yet so the
    UI can show an empty state instead of a misleading 100%.
    """
    met = breached_resolved = overdue = responded_on_time = response_evaluated = 0
    durations = []
    overdue_tickets = []
    for t in tickets:
        if t.status in TicketStatus.DONE and t.resolved_at:
            if t.resolution_met_sla is False:
                breached_resolved += 1
            else:
                met += 1
            durations.append(t.resolution_duration_seconds)
        elif t.status in TicketStatus.ACTIVE and t.is_overdue:
            overdue += 1
            overdue_tickets.append(t)

        if t.response_due_at:
            if t.first_responded_at:
                response_evaluated += 1
                if as_utc(t.first_responded_at) <= as_utc(t.response_due_at):
                    responded_on_time += 1
            elif t.response_overdue:
                response_evaluated += 1

    evaluated = met + breached_resolved + overdue
    return {
        'compliance_rate': round(met / evaluated * 100, 1) if evaluated else None,
        'response_compliance_rate': round(responded_on_time / response_evaluated * 100, 1) if response_evaluated else None,
        'resolved_within_sla': met,
        'resolved_breached': breached_resolved,
        'overdue_count': overdue,
        'breached_count': breached_resolved + overdue,
        'evaluated_count': evaluated,
        'avg_resolution_seconds': (sum(durations) / len(durations)) if durations else None,
        'active_overdue_tickets': sorted(overdue_tickets, key=lambda t: t.resolution_due_at),
    }


def get_sla_metrics(query=None):
    """SLA metrics for all tickets (or a pre-filtered Ticket query)."""
    query = query if query is not None else Ticket.query
    return compute_sla_metrics(query.all())
