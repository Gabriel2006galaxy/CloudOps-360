"""Dashboard and analytics metrics. Every number is computed from database rows."""
from datetime import date, datetime, timedelta

from sqlalchemy import func

from app.extensions import db
from app.models import (
    AuditLog, Ticket, TicketCategory, TicketPriority, TicketStatus, TicketStatusHistory, User, UserRole,
    format_duration, utcnow,
)
from app.services.assignment import away_technicians_with_work
from app.services.settings import get_auto_assign_config
from app.services.sla import compute_sla_metrics


def _counts(query, column, keys):
    rows = query.with_entities(column, func.count(Ticket.id)).group_by(column).all()
    found = {k: c for k, c in rows}
    return {k: found.get(k, 0) for k in keys}


def status_counts(query):
    return _counts(query, Ticket.status, TicketStatus.VALUES)


def priority_counts(query):
    return _counts(query, Ticket.priority, TicketPriority.ORDERED)


def category_counts(query):
    rows = (query.join(TicketCategory, Ticket.category_id == TicketCategory.id)
            .with_entities(TicketCategory.name, func.count(Ticket.id))
            .group_by(TicketCategory.name).order_by(func.count(Ticket.id).desc()).all())
    return [{'name': name, 'count': count} for name, count in rows]


def _as_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def daily_trend(query, days=14):
    """Tickets created and resolved per UTC day for the last `days` days."""
    today = utcnow().date()
    start = today - timedelta(days=days - 1)
    start_dt = datetime.combine(start, datetime.min.time())

    created = (query.filter(Ticket.created_at >= start_dt)
               .with_entities(func.date(Ticket.created_at), func.count(Ticket.id))
               .group_by(func.date(Ticket.created_at)).all())
    resolved = (query.filter(Ticket.resolved_at.isnot(None), Ticket.resolved_at >= start_dt)
                .with_entities(func.date(Ticket.resolved_at), func.count(Ticket.id))
                .group_by(func.date(Ticket.resolved_at)).all())
    created_map = {_as_date(d): c for d, c in created}
    resolved_map = {_as_date(d): c for d, c in resolved}
    labels, created_series, resolved_series = [], [], []
    for i in range(days):
        day = start + timedelta(days=i)
        labels.append(day.strftime('%b %d'))
        created_series.append(created_map.get(day, 0))
        resolved_series.append(resolved_map.get(day, 0))
    return {'labels': labels, 'created': created_series, 'resolved': resolved_series}


def rating_summary(query=None):
    """Customer satisfaction: average stars, number of ratings and 5..1 distribution."""
    query = query if query is not None else Ticket.query
    rows = (query.filter(Ticket.satisfaction_rating.isnot(None))
            .with_entities(Ticket.satisfaction_rating, func.count(Ticket.id))
            .group_by(Ticket.satisfaction_rating).all())
    distribution = {stars: 0 for stars in range(5, 0, -1)}
    for stars, count in rows:
        distribution[int(stars)] = count
    total = sum(distribution.values())
    average = round(sum(s * c for s, c in distribution.items()) / total, 1) if total else None
    return {'avg': average, 'count': total, 'distribution': distribution}


def technician_workload():
    """Active, overdue and resolved counts, workload points, rating and average
    resolution time per staff member."""
    staff = User.query.filter(User.role.in_(UserRole.STAFF), User.is_active.is_(True)).order_by(User.full_name).all()
    rows = []
    for user in staff:
        assigned = Ticket.query.filter(Ticket.technician_id == user.id).all()
        active = [t for t in assigned if t.status in (TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS)]
        resolved = [t for t in assigned if t.resolved_at]
        durations = [t.resolution_duration_seconds for t in resolved]
        ratings = [t.satisfaction_rating for t in assigned if t.satisfaction_rating]
        rows.append({
            'user': user,
            'active_count': len(active),
            'points': sum(TicketPriority.RANK.get(t.priority, 1) for t in active),
            'critical_count': sum(1 for t in active if t.priority == TicketPriority.CRITICAL),
            'overdue_count': sum(1 for t in active if t.is_overdue),
            'resolved_count': len(resolved),
            'avg_resolution': format_duration(sum(durations) / len(durations)) if durations else None,
            'avg_rating': round(sum(ratings) / len(ratings), 1) if ratings else None,
            'rating_count': len(ratings),
        })
    return rows


def resolution_by_priority():
    """Average resolution time and SLA attainment per priority (resolved tickets only)."""
    result = []
    for priority in TicketPriority.ORDERED:
        tickets = Ticket.query.filter(Ticket.priority == priority, Ticket.resolved_at.isnot(None)).all()
        durations = [t.resolution_duration_seconds for t in tickets]
        met = sum(1 for t in tickets if t.resolution_met_sla is not False)
        result.append({
            'priority': priority,
            'resolved': len(tickets),
            'avg_hours': round(sum(durations) / len(durations) / 3600, 1) if durations else 0,
            'sla_rate': round(met / len(tickets) * 100, 1) if tickets else None,
        })
    return result


def recent_activity_for(ticket_query, limit=8):
    """Latest status changes on the tickets in ticket_query."""
    ids = ticket_query.with_entities(Ticket.id)
    return (TicketStatusHistory.query.filter(TicketStatusHistory.ticket_id.in_(ids))
            .order_by(TicketStatusHistory.created_at.desc(), TicketStatusHistory.id.desc())
            .limit(limit).all())


def employee_dashboard(user):
    query = Ticket.query.filter(Ticket.creator_id == user.id)
    counts = status_counts(query)
    return {
        'total': sum(counts.values()),
        'status_counts': counts,
        'open_count': counts[TicketStatus.OPEN] + counts[TicketStatus.ASSIGNED],
        'in_progress': counts[TicketStatus.IN_PROGRESS],
        'awaiting_confirmation': counts[TicketStatus.RESOLVED],
        'resolved_count': counts[TicketStatus.RESOLVED] + counts[TicketStatus.CLOSED],
        'recent_tickets': query.order_by(Ticket.created_at.desc(), Ticket.id.desc()).limit(6).all(),
        'recent_activity': recent_activity_for(query),
        'sla': compute_sla_metrics(query.all()),
    }


def technician_dashboard(user):
    query = Ticket.query.filter(Ticket.technician_id == user.id)
    tickets = query.all()
    active = [t for t in tickets if t.status in (TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS)]
    week_ago = utcnow() - timedelta(days=7)
    resolved_week = [t for t in tickets if t.resolved_at and t.resolved_at >= week_ago]
    queue = Ticket.query.filter(Ticket.technician_id.is_(None), Ticket.status == TicketStatus.OPEN)
    return {
        'assigned_total': len(tickets),
        'active_count': len(active),
        'in_progress': sum(1 for t in active if t.status == TicketStatus.IN_PROGRESS),
        'critical_tickets': [t for t in active if t.priority == TicketPriority.CRITICAL],
        'overdue_tickets': sorted([t for t in active if t.is_overdue], key=lambda t: t.resolution_due_at),
        'response_due': [t for t in active if t.response_overdue],
        'resolved_week': len(resolved_week),
        'resolved_total': sum(1 for t in tickets if t.resolved_at),
        'priority_counts': {p: sum(1 for t in active if t.priority == p) for p in TicketPriority.ORDERED},
        'queue_count': queue.count(),
        'queue_preview': sorted(queue.all(), key=lambda t: (-TicketPriority.RANK[t.priority], t.created_at))[:6],
        'active_tickets': sorted(active, key=lambda t: (-TicketPriority.RANK[t.priority], t.resolution_due_at or t.created_at))[:8],
        'trend': daily_trend(query, days=14),
        'sla': compute_sla_metrics(tickets),
        'recent_activity': recent_activity_for(query),
    }


def admin_dashboard():
    query = Ticket.query
    counts = status_counts(query)
    return {
        'total_users': User.query.count(),
        'active_users': User.query.filter(User.is_active.is_(True)).count(),
        'users_by_role': {r: User.query.filter_by(role=r).count() for r in UserRole.VALUES},
        'total_tickets': sum(counts.values()),
        'status_counts': counts,
        'open_tickets': sum(counts[s] for s in TicketStatus.ACTIVE),
        'unassigned': Ticket.query.filter(Ticket.technician_id.is_(None), Ticket.status == TicketStatus.OPEN).count(),
        'resolved_tickets': counts[TicketStatus.RESOLVED] + counts[TicketStatus.CLOSED],
        'priority_counts': priority_counts(query),
        'category_counts': category_counts(query),
        'trend': daily_trend(query, days=14),
        'workload': technician_workload(),
        'sla': compute_sla_metrics(query.all()),
        'ratings': rating_summary(query),
        'away_with_work': away_technicians_with_work(),
        'auto_assign_enabled': get_auto_assign_config().enabled,
        'recent_audits': AuditLog.query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(8).all(),
    }
