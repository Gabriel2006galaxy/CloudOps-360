from datetime import datetime, timezone
import enum
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app.extensions import db, login_manager


class UserRole:
    EMPLOYEE = 'employee'
    TECHNICIAN = 'technician'
    ADMIN = 'admin'
    
    CHOICES = [
        (EMPLOYEE, 'Employee'),
        (TECHNICIAN, 'Support Technician'),
        (ADMIN, 'Administrator')
    ]


class TicketPriority:
    LOW = 'Low'
    MEDIUM = 'Medium'
    HIGH = 'High'
    CRITICAL = 'Critical'
    
    CHOICES = [
        (LOW, 'Low'),
        (MEDIUM, 'Medium'),
        (HIGH, 'High'),
        (CRITICAL, 'Critical')
    ]


class TicketStatus:
    OPEN = 'Open'
    ASSIGNED = 'Assigned'
    IN_PROGRESS = 'In Progress'
    RESOLVED = 'Resolved'
    CLOSED = 'Closed'
    
    CHOICES = [
        (OPEN, 'Open'),
        (ASSIGNED, 'Assigned'),
        (IN_PROGRESS, 'In Progress'),
        (RESOLVED, 'Resolved'),
        (CLOSED, 'Closed')
    ]
    
    # Valid workflow state transitions
    TRANSITIONS = {
        OPEN: [ASSIGNED, IN_PROGRESS, CLOSED],
        ASSIGNED: [IN_PROGRESS, RESOLVED, CLOSED, OPEN],
        IN_PROGRESS: [RESOLVED, CLOSED, ASSIGNED],
        RESOLVED: [CLOSED, IN_PROGRESS],  # reopening allowed
        CLOSED: [OPEN]  # Reopen by authorized users
    }


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=UserRole.EMPLOYEE, index=True)
    department = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    created_tickets = db.relationship('Ticket', foreign_keys='Ticket.creator_id', backref='creator', lazy='dynamic')
    assigned_tickets = db.relationship('Ticket', foreign_keys='Ticket.technician_id', backref='technician', lazy='dynamic')
    comments = db.relationship('Comment', backref='author', lazy='dynamic')
    notifications = db.relationship('Notification', backref='recipient', lazy='dynamic', cascade='all, delete-orphan')
    audit_logs = db.relationship('AuditLog', backref='actor', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN

    @property
    def is_technician(self):
        return self.role == UserRole.TECHNICIAN

    @property
    def is_employee(self):
        return self.role == UserRole.EMPLOYEE

    @property
    def role_badge_class(self):
        badges = {
            UserRole.ADMIN: 'bg-danger text-white',
            UserRole.TECHNICIAN: 'bg-primary text-white',
            UserRole.EMPLOYEE: 'bg-secondary text-white'
        }
        return badges.get(self.role, 'bg-light text-dark')

    def __repr__(self):
        return f'<User {self.username} [{self.role}]>'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class TicketCategory(db.Model):
    __tablename__ = 'ticket_categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    tickets = db.relationship('Ticket', backref='category', lazy='dynamic')

    def __repr__(self):
        return f'<TicketCategory {self.name}>'


class SLAPolicy(db.Model):
    __tablename__ = 'sla_policies'

    id = db.Column(db.Integer, primary_key=True)
    priority = db.Column(db.String(20), unique=True, nullable=False)  # Low, Medium, High, Critical
    response_time_hours = db.Column(db.Integer, nullable=False)
    resolution_time_hours = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f'<SLAPolicy {self.priority}: Response {self.response_time_hours}h, Resolve {self.resolution_time_hours}h>'


class Ticket(db.Model):
    __tablename__ = 'tickets'

    id = db.Column(db.Integer, primary_key=True)
    reference_id = db.Column(db.String(32), unique=True, nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('ticket_categories.id'), nullable=False)
    priority = db.Column(db.String(20), nullable=False, default=TicketPriority.MEDIUM, index=True)
    status = db.Column(db.String(20), nullable=False, default=TicketStatus.OPEN, index=True)
    
    creator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    technician_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    
    affected_system = db.Column(db.String(100), nullable=True)
    department = db.Column(db.String(100), nullable=True)
    resolution_summary = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    
    # SLA Fields
    response_due_at = db.Column(db.DateTime, nullable=True)
    resolution_due_at = db.Column(db.DateTime, nullable=True)
    first_responded_at = db.Column(db.DateTime, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    comments = db.relationship('Comment', backref='ticket', cascade='all, delete-orphan', order_by='Comment.created_at.asc()')
    attachments = db.relationship('Attachment', backref='ticket', cascade='all, delete-orphan', order_by='Attachment.created_at.asc()')
    status_history = db.relationship('TicketStatusHistory', backref='ticket', cascade='all, delete-orphan', order_by='TicketStatusHistory.created_at.asc()')

    @property
    def is_resolved(self):
        return self.status in [TicketStatus.RESOLVED, TicketStatus.CLOSED]

    @property
    def is_overdue(self):
        if self.is_resolved:
            return False
        if not self.resolution_due_at:
            return False
        now = datetime.now(timezone.utc)
        # Handle timezone-naive resolution_due_at safely
        due_at = self.resolution_due_at.replace(tzinfo=timezone.utc) if self.resolution_due_at.tzinfo is None else self.resolution_due_at
        return now > due_at

    @property
    def time_remaining_display(self):
        if self.is_resolved:
            return "Resolved"
        if not self.resolution_due_at:
            return "No SLA"
        now = datetime.now(timezone.utc)
        due_at = self.resolution_due_at.replace(tzinfo=timezone.utc) if self.resolution_due_at.tzinfo is None else self.resolution_due_at
        delta = due_at - now
        if delta.total_seconds() <= 0:
            overdue_delta = now - due_at
            hours = int(overdue_delta.total_seconds() // 3600)
            mins = int((overdue_delta.total_seconds() % 3600) // 60)
            return f"Overdue by {hours}h {mins}m"
        else:
            hours = int(delta.total_seconds() // 3600)
            mins = int((delta.total_seconds() % 3600) // 60)
            return f"{hours}h {mins}m remaining"

    @property
    def resolution_duration(self):
        if not self.resolved_at:
            return None
        created = self.created_at.replace(tzinfo=timezone.utc) if self.created_at.tzinfo is None else self.created_at
        resolved = self.resolved_at.replace(tzinfo=timezone.utc) if self.resolved_at.tzinfo is None else self.resolved_at
        delta = resolved - created
        hours = int(delta.total_seconds() // 3600)
        mins = int((delta.total_seconds() % 3600) // 60)
        return f"{hours}h {mins}m"

    @property
    def priority_badge_class(self):
        badges = {
            TicketPriority.CRITICAL: 'bg-danger text-white',
            TicketPriority.HIGH: 'bg-warning text-dark',
            TicketPriority.MEDIUM: 'bg-info text-dark',
            TicketPriority.LOW: 'bg-secondary text-white'
        }
        return badges.get(self.priority, 'bg-secondary text-white')

    @property
    def status_badge_class(self):
        badges = {
            TicketStatus.OPEN: 'bg-primary text-white',
            TicketStatus.ASSIGNED: 'bg-info text-dark',
            TicketStatus.IN_PROGRESS: 'bg-warning text-dark',
            TicketStatus.RESOLVED: 'bg-success text-white',
            TicketStatus.CLOSED: 'bg-dark text-white'
        }
        return badges.get(self.status, 'bg-light text-dark')

    def can_transition_to(self, new_status):
        allowed = TicketStatus.TRANSITIONS.get(self.status, [])
        return new_status in allowed

    def __repr__(self):
        return f'<Ticket {self.reference_id}: {self.title}>'


class Comment(db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, default=False, nullable=False)  # Private internal note for tech/admin
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f'<Comment {self.id} on Ticket {self.ticket_id} (Internal: {self.is_internal})>'


class Attachment(db.Model):
    __tablename__ = 'attachments'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)  # Sanitized/UUID filename on EFS / local filesystem
    original_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)  # Bytes
    mime_type = db.Column(db.String(100), nullable=True)
    storage_path = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    uploader = db.relationship('User', backref='attachments')

    @property
    def file_size_display(self):
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        else:
            return f"{self.file_size / (1024 * 1024):.1f} MB"

    def __repr__(self):
        return f'<Attachment {self.original_filename} (Ticket {self.ticket_id})>'


class TicketStatusHistory(db.Model):
    __tablename__ = 'ticket_status_history'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    changed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    old_status = db.Column(db.String(20), nullable=False)
    new_status = db.Column(db.String(20), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    changed_by = db.relationship('User')

    def __repr__(self):
        return f'<StatusHistory Ticket {self.ticket_id}: {self.old_status} -> {self.new_status}>'


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    action = db.Column(db.String(64), nullable=False, index=True)
    entity_type = db.Column(db.String(32), nullable=True)
    entity_id = db.Column(db.String(64), nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    def __repr__(self):
        return f'<AuditLog {self.action} on {self.entity_type} {self.entity_id} at {self.created_at}>'


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(255), nullable=True)
    type = db.Column(db.String(32), default='info', nullable=False)  # info, success, warning, danger
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    def __repr__(self):
        return f'<Notification {self.id} for User {self.user_id}: {self.title}>'
