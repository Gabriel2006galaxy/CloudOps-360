from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models import (
    User, UserRole, Ticket, TicketStatus, TicketPriority,
    TicketCategory, AuditLog, Notification, SLAPolicy
)
from app.services.sla import get_sla_metrics
from app.auth.decorators import admin_required, technician_or_admin_required

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')


@dashboard_bp.route('')
@login_required
def index():
    """Smart router directing users to their role-specific executive dashboard."""
    if current_user.is_admin:
        return redirect(url_for('dashboard.admin'))
    elif current_user.is_technician:
        return redirect(url_for('dashboard.technician'))
    else:
        return redirect(url_for('dashboard.employee'))


@dashboard_bp.route('/employee')
@login_required
def employee():
    """Employee personal IT service dashboard."""
    user_id = current_user.id
    
    total_tickets = Ticket.query.filter_by(creator_id=user_id).count()
    open_tickets = Ticket.query.filter(
        Ticket.creator_id == user_id,
        Ticket.status.in_([TicketStatus.OPEN, TicketStatus.ASSIGNED])
    ).count()
    in_progress = Ticket.query.filter_by(creator_id=user_id, status=TicketStatus.IN_PROGRESS).count()
    resolved = Ticket.query.filter(
        Ticket.creator_id == user_id,
        Ticket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED])
    ).count()

    recent_tickets = Ticket.query.filter_by(creator_id=user_id).order_by(Ticket.created_at.desc()).limit(6).all()
    recent_notifications = Notification.query.filter_by(user_id=user_id).order_by(Notification.created_at.desc()).limit(5).all()

    return render_template(
        'dashboard/employee.html',
        total_tickets=total_tickets,
        open_tickets=open_tickets,
        in_progress=in_progress,
        resolved=resolved,
        recent_tickets=recent_tickets,
        recent_notifications=recent_notifications
    )


@dashboard_bp.route('/technician')
@login_required
@technician_or_admin_required
def technician():
    """Support Technician operational workload and SLA dashboard."""
    user_id = current_user.id
    now = datetime.now(timezone.utc)

    assigned_count = Ticket.query.filter_by(technician_id=user_id).count()
    active_assigned = Ticket.query.filter(
        Ticket.technician_id == user_id,
        Ticket.status.in_([TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS])
    ).all()

    critical_count = Ticket.query.filter(
        Ticket.technician_id == user_id,
        Ticket.priority == TicketPriority.CRITICAL,
        Ticket.status.notin_([TicketStatus.RESOLVED, TicketStatus.CLOSED])
    ).count()

    overdue_tickets = [t for t in active_assigned if t.is_overdue]
    overdue_count = len(overdue_tickets)

    resolved_count = Ticket.query.filter(
        Ticket.technician_id == user_id,
        Ticket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED])
    ).count()

    # Unassigned queue available for technicians to take
    unassigned_queue = Ticket.query.filter(
        Ticket.technician_id == None,
        Ticket.status == TicketStatus.OPEN
    ).order_by(
        # Prioritize Critical, then High, etc.
        Ticket.created_at.asc()
    ).limit(8).all()

    recent_assigned = Ticket.query.filter_by(technician_id=user_id).order_by(Ticket.updated_at.desc()).limit(8).all()

    return render_template(
        'dashboard/technician.html',
        assigned_count=assigned_count,
        active_count=len(active_assigned),
        critical_count=critical_count,
        overdue_count=overdue_count,
        resolved_count=resolved_count,
        overdue_tickets=overdue_tickets,
        unassigned_queue=unassigned_queue,
        recent_assigned=recent_assigned
    )


@dashboard_bp.route('/admin')
@login_required
@admin_required
def admin():
    """Enterprise Administrator analytics and management overview dashboard."""
    now = datetime.now(timezone.utc)

    # Core system metrics
    total_users = User.query.count()
    total_tickets = Ticket.query.count()
    open_tickets = Ticket.query.filter(Ticket.status.in_([TicketStatus.OPEN, TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS])).count()
    resolved_tickets = Ticket.query.filter(Ticket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED])).count()

    # Priority distribution for Chart.js
    priority_counts = {
        TicketPriority.CRITICAL: Ticket.query.filter_by(priority=TicketPriority.CRITICAL).count(),
        TicketPriority.HIGH: Ticket.query.filter_by(priority=TicketPriority.HIGH).count(),
        TicketPriority.MEDIUM: Ticket.query.filter_by(priority=TicketPriority.MEDIUM).count(),
        TicketPriority.LOW: Ticket.query.filter_by(priority=TicketPriority.LOW).count()
    }

    # Status distribution for Chart.js
    status_counts = {
        TicketStatus.OPEN: Ticket.query.filter_by(status=TicketStatus.OPEN).count(),
        TicketStatus.ASSIGNED: Ticket.query.filter_by(status=TicketStatus.ASSIGNED).count(),
        TicketStatus.IN_PROGRESS: Ticket.query.filter_by(status=TicketStatus.IN_PROGRESS).count(),
        TicketStatus.RESOLVED: Ticket.query.filter_by(status=TicketStatus.RESOLVED).count(),
        TicketStatus.CLOSED: Ticket.query.filter_by(status=TicketStatus.CLOSED).count()
    }

    # Category distribution
    categories = TicketCategory.query.all()
    category_labels = [c.name for c in categories]
    category_counts = [c.tickets.count() for c in categories]

    # Technician Workload
    technicians = User.query.filter(User.role.in_([UserRole.TECHNICIAN, UserRole.ADMIN]), User.is_active == True).all()
    technician_workload = []
    for tech in technicians:
        assigned = Ticket.query.filter(
            Ticket.technician_id == tech.id,
            Ticket.status.in_([TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS])
        ).count()
        tech_resolved = Ticket.query.filter(
            Ticket.technician_id == tech.id,
            Ticket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED])
        ).count()
        technician_workload.append({
            'user': tech,
            'active_count': assigned,
            'resolved_count': tech_resolved
        })

    # SLA Metrics
    sla_data = get_sla_metrics()

    # Recent Audit Events
    recent_audits = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(10).all()

    return render_template(
        'dashboard/admin.html',
        total_users=total_users,
        total_tickets=total_tickets,
        open_tickets=open_tickets,
        resolved_tickets=resolved_tickets,
        priority_counts=priority_counts,
        status_counts=status_counts,
        category_labels=category_labels,
        category_counts=category_counts,
        technician_workload=technician_workload,
        sla_data=sla_data,
        recent_audits=recent_audits
    )
