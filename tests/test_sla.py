from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models import Ticket, TicketCategory, TicketPriority, TicketStatus
from app.services.sla import calculate_sla_due_dates, apply_sla_to_ticket, get_sla_metrics


def test_sla_deadline_calculation(app):
    """Test SLA response and resolution deadline calculations."""
    with app.app_context():
        start = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
        
        # Critical
        r_due, res_due = calculate_sla_due_dates(TicketPriority.CRITICAL, start)
        assert res_due == start + timedelta(hours=4)
        assert r_due == start + timedelta(hours=1)

        # High
        r_due, res_due = calculate_sla_due_dates(TicketPriority.HIGH, start)
        assert res_due == start + timedelta(hours=12)
        assert r_due == start + timedelta(hours=4)


def test_overdue_detection(app, emp_user):
    """Test overdue calculation when resolution deadline is in the past."""
    with app.app_context():
        cat = TicketCategory.query.first()
        now = datetime.now(timezone.utc)
        
        # Ticket created 5 hours ago with 4h resolution target -> OVERDUE
        overdue_ticket = Ticket(
            reference_id='INC-2026-55501',
            title='Overdue Critical Outage',
            description='System down',
            category_id=cat.id,
            priority=TicketPriority.CRITICAL,
            status=TicketStatus.IN_PROGRESS,
            creator_id=emp_user.id,
            created_at=now - timedelta(hours=5),
            resolution_due_at=now - timedelta(hours=1)
        )
        # Ticket created 1 hour ago with 24h resolution target -> NOT OVERDUE
        active_ticket = Ticket(
            reference_id='INC-2026-55502',
            title='Standard Maintenance',
            description='Routine upgrade',
            category_id=cat.id,
            priority=TicketPriority.MEDIUM,
            status=TicketStatus.OPEN,
            creator_id=emp_user.id,
            created_at=now - timedelta(hours=1),
            resolution_due_at=now + timedelta(hours=23)
        )
        db.session.add_all([overdue_ticket, active_ticket])
        db.session.commit()

        assert overdue_ticket.is_overdue is True
        assert active_ticket.is_overdue is False

        metrics = get_sla_metrics()
        assert metrics['overdue_count'] >= 1
