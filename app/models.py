from datetime import datetime, timezone
from sqlalchemy import true as sql_true
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app.extensions import db, login_manager


def utcnow():
    """Naive UTC timestamp. All timestamps are stored as UTC (MySQL DATETIME has no tz)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_utc(value):
    """Returns an aware UTC datetime for a stored (naive UTC) or aware value."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def format_duration(seconds):
    seconds = int(max(seconds, 0))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"{days}d {hours}h"
    return f"{hours}h {mins}m"


class UserRole:
    EMPLOYEE = 'employee'
    TECHNICIAN = 'technician'
    ADMIN = 'admin'

    CHOICES = [
        (EMPLOYEE, 'Employee'),
        (TECHNICIAN, 'Support Technician'),
        (ADMIN, 'Administrator')
    ]
    VALUES = (EMPLOYEE, TECHNICIAN, ADMIN)
    STAFF = (TECHNICIAN, ADMIN)


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
    VALUES = (LOW, MEDIUM, HIGH, CRITICAL)
    # Highest first, for ordering and charts
    ORDERED = (CRITICAL, HIGH, MEDIUM, LOW)
    RANK = {CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1}


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
    VALUES = (OPEN, ASSIGNED, IN_PROGRESS, RESOLVED, CLOSED)
    ACTIVE = (OPEN, ASSIGNED, IN_PROGRESS)
    DONE = (RESOLVED, CLOSED)

    # Valid workflow state transitions (the graph). Which role may perform each
    # edge is decided in app.services.workflow.
    TRANSITIONS = {
        OPEN: [ASSIGNED, CLOSED],
        ASSIGNED: [IN_PROGRESS, OPEN, CLOSED],
        IN_PROGRESS: [RESOLVED, ASSIGNED],
        RESOLVED: [CLOSED, IN_PROGRESS],  # reopen
        CLOSED: [IN_PROGRESS, OPEN],      # authorized reopen
    }


def _sql_in(values):
    return ', '.join(f"'{v}'" for v in values)


# Categories a technician specialises in (used by auto-assignment)
technician_skills = db.Table(
    'technician_skills',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('ticket_categories.id', ondelete='CASCADE'), primary_key=True),
)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    __table_args__ = (
        db.CheckConstraint(f"role IN ({_sql_in(UserRole.VALUES)})", name='ck_users_role'),
    )

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=UserRole.EMPLOYEE, index=True)
    department = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)

    # Technician availability: away technicians never receive auto-assigned tickets
    is_available = db.Column(db.Boolean, default=True, server_default=sql_true(), nullable=False)
    away_note = db.Column(db.String(120), nullable=True)
    away_until = db.Column(db.DateTime, nullable=True)  # UTC; available again from this moment
    # Leave request: a technician asks to be away, an administrator approves or rejects it
    leave_requested_at = db.Column(db.DateTime, nullable=True)
    leave_note = db.Column(db.String(120), nullable=True)
    leave_until = db.Column(db.DateTime, nullable=True)

    # Relationships
    skills = db.relationship('TicketCategory', secondary=technician_skills, lazy='selectin',
                             order_by='TicketCategory.name')
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
    def is_staff(self):
        return self.role in UserRole.STAFF

    @property
    def role_label(self):
        return dict(UserRole.CHOICES).get(self.role, self.role)

    @property
    def is_away(self):
        """Marked away and the 'back on' moment (if any) has not arrived yet."""
        if self.is_available:
            return False
        return self.away_until is None or as_utc(self.away_until) > datetime.now(timezone.utc)

    @property
    def availability_label(self):
        if not self.is_away:
            return 'Available'
        label = 'Away'
        if self.away_until:
            label += f" until {as_utc(self.away_until).strftime('%b %d')}"
        return label

    @property
    def availability_phrase(self):
        """Label for use inside a sentence: 'available', 'away until Oct 28'."""
        label = self.availability_label
        return label[0].lower() + label[1:]

    @property
    def has_leave_request(self):
        """A leave request is waiting for an administrator's decision."""
        return self.leave_requested_at is not None

    @property
    def leave_request_label(self):
        label = 'Leave requested'
        if self.leave_until:
            label += f" until {as_utc(self.leave_until).strftime('%b %d')}"
        return label

    @property
    def initials(self):
        parts = [p for p in (self.full_name or '').split() if p]
        return ''.join(p[0] for p in parts[:2]).upper() or '?'

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
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


class LoginAttempt(db.Model):
    """Sign-in attempts used for database-backed brute-force rate limiting.

    Stored in the shared database so limits hold across multiple EC2 instances.
    Never stores the submitted password.
    """
    __tablename__ = 'login_attempts'
    __table_args__ = (
        db.Index('ix_login_attempts_identifier_created', 'identifier', 'created_at'),
        db.Index('ix_login_attempts_ip_created', 'ip_address', 'created_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(120), nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    success = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class TicketCategory(db.Model):
    __tablename__ = 'ticket_categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    tickets = db.relationship('Ticket', backref='category', lazy='dynamic')

    def __repr__(self):
        return f'<TicketCategory {self.name}>'


class SLAPolicy(db.Model):
    __tablename__ = 'sla_policies'
    __table_args__ = (
        db.CheckConstraint(f"priority IN ({_sql_in(TicketPriority.VALUES)})", name='ck_sla_policies_priority'),
        db.CheckConstraint('response_time_hours > 0', name='ck_sla_policies_response_positive'),
        db.CheckConstraint('resolution_time_hours >= response_time_hours', name='ck_sla_policies_resolution_gte_response'),
    )

    id = db.Column(db.Integer, primary_key=True)
    priority = db.Column(db.String(20), unique=True, nullable=False)  # Low, Medium, High, Critical
    response_time_hours = db.Column(db.Integer, nullable=False)
    resolution_time_hours = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def __repr__(self):
        return f'<SLAPolicy {self.priority}: Response {self.response_time_hours}h, Resolve {self.resolution_time_hours}h>'


class Ticket(db.Model):
    __tablename__ = 'tickets'
    __table_args__ = (
        db.CheckConstraint(f"status IN ({_sql_in(TicketStatus.VALUES)})", name='ck_tickets_status'),
        db.CheckConstraint(f"priority IN ({_sql_in(TicketPriority.VALUES)})", name='ck_tickets_priority'),
        db.CheckConstraint('satisfaction_rating IS NULL OR (satisfaction_rating >= 1 AND satisfaction_rating <= 5)',
                           name='ck_tickets_satisfaction_rating'),
        db.Index('ix_tickets_technician_status', 'technician_id', 'status'),
        db.Index('ix_tickets_creator_status', 'creator_id', 'status'),
    )

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

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    # SLA Fields (UTC)
    response_due_at = db.Column(db.DateTime, nullable=True)
    resolution_due_at = db.Column(db.DateTime, nullable=True)
    first_responded_at = db.Column(db.DateTime, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)

    # Customer satisfaction (CSAT), given once by the reporter after closing
    satisfaction_rating = db.Column(db.SmallInteger, nullable=True)  # 1-5 stars
    satisfaction_comment = db.Column(db.String(500), nullable=True)
    rated_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    comments = db.relationship('Comment', backref='ticket', cascade='all, delete-orphan', order_by='Comment.created_at.asc()')
    attachments = db.relationship('Attachment', backref='ticket', cascade='all, delete-orphan', order_by='Attachment.created_at.asc()')
    status_history = db.relationship('TicketStatusHistory', backref='ticket', cascade='all, delete-orphan', order_by='TicketStatusHistory.created_at.asc()')

    @property
    def is_resolved(self):
        return self.status in TicketStatus.DONE

    @property
    def is_overdue(self):
        """Resolution SLA breached and the ticket is still active."""
        if self.is_resolved or not self.resolution_due_at:
            return False
        return datetime.now(timezone.utc) > as_utc(self.resolution_due_at)

    @property
    def response_overdue(self):
        """No first response yet and the response SLA has passed."""
        if self.first_responded_at or self.is_resolved or not self.response_due_at:
            return False
        return datetime.now(timezone.utc) > as_utc(self.response_due_at)

    @property
    def resolution_met_sla(self):
        """True/False once resolved, None while still active or without SLA."""
        if not self.resolved_at or not self.resolution_due_at:
            return None
        return as_utc(self.resolved_at) <= as_utc(self.resolution_due_at)

    @property
    def seconds_remaining(self):
        if self.is_resolved or not self.resolution_due_at:
            return None
        return (as_utc(self.resolution_due_at) - datetime.now(timezone.utc)).total_seconds()

    @property
    def sla_progress_percent(self):
        """Share of the resolution window already consumed (0-100) for progress bars."""
        if not self.resolution_due_at or not self.created_at:
            return 0
        start, due = as_utc(self.created_at), as_utc(self.resolution_due_at)
        end = as_utc(self.resolved_at) if self.resolved_at else datetime.now(timezone.utc)
        window = (due - start).total_seconds()
        if window <= 0:
            return 100
        return int(min(max((end - start).total_seconds() / window * 100, 0), 100))

    @property
    def time_remaining_display(self):
        if self.is_resolved:
            return "Met SLA" if self.resolution_met_sla in (True, None) else "Resolved late"
        if not self.resolution_due_at:
            return "No SLA"
        remaining = self.seconds_remaining
        if remaining <= 0:
            return f"Overdue by {format_duration(-remaining)}"
        return f"{format_duration(remaining)} remaining"

    @property
    def resolution_duration_seconds(self):
        if not self.resolved_at:
            return None
        return (as_utc(self.resolved_at) - as_utc(self.created_at)).total_seconds()

    @property
    def resolution_duration(self):
        seconds = self.resolution_duration_seconds
        return None if seconds is None else format_duration(seconds)

    @property
    def priority_badge_class(self):
        return f"badge-priority-{self.priority.lower()}"

    @property
    def status_badge_class(self):
        return f"badge-status-{self.status.lower().replace(' ', '-')}"

    def can_transition_to(self, new_status):
        return new_status in TicketStatus.TRANSITIONS.get(self.status, [])

    def __repr__(self):
        return f'<Ticket {self.reference_id}: {self.title}>'


class Comment(db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, default=False, nullable=False)  # Private internal note for tech/admin
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    def __repr__(self):
        return f'<Comment {self.id} on Ticket {self.ticket_id} (Internal: {self.is_internal})>'


class Attachment(db.Model):
    __tablename__ = 'attachments'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)  # Generated storage key (never user supplied)
    original_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)  # Bytes
    mime_type = db.Column(db.String(100), nullable=True)
    # Storage key relative to the configured storage root (portable across EC2 instances)
    storage_path = db.Column(db.String(500), nullable=False)
    checksum_sha256 = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    uploader = db.relationship('User', backref='attachments')

    @property
    def file_size_display(self):
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        else:
            return f"{self.file_size / (1024 * 1024):.1f} MB"

    @property
    def icon_class(self):
        ext = self.original_filename.rsplit('.', 1)[-1].lower() if '.' in self.original_filename else ''
        return {
            'png': 'bi-file-earmark-image', 'jpg': 'bi-file-earmark-image', 'jpeg': 'bi-file-earmark-image',
            'gif': 'bi-file-earmark-image', 'pdf': 'bi-file-earmark-pdf', 'zip': 'bi-file-earmark-zip',
            'csv': 'bi-file-earmark-spreadsheet', 'docx': 'bi-file-earmark-word',
            'log': 'bi-file-earmark-code', 'txt': 'bi-file-earmark-text',
        }.get(ext, 'bi-file-earmark')

    def __repr__(self):
        return f'<Attachment {self.original_filename} (Ticket {self.ticket_id})>'


class TicketStatusHistory(db.Model):
    __tablename__ = 'ticket_status_history'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    changed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # NULL = system (auto-assignment)
    old_status = db.Column(db.String(20), nullable=False)
    new_status = db.Column(db.String(20), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    changed_by = db.relationship('User')

    @property
    def actor_name(self):
        return self.changed_by.full_name if self.changed_by else 'System (auto-assign)'

    def __repr__(self):
        return f'<StatusHistory Ticket {self.ticket_id}: {self.old_status} -> {self.new_status}>'


class SystemSetting(db.Model):
    """Administrator-editable settings stored as key/value pairs (e.g. auto-assignment)."""
    __tablename__ = 'system_settings'

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.String(255), nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def __repr__(self):
        return f'<SystemSetting {self.key}={self.value}>'


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
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)

    @property
    def severity(self):
        if 'DENIED' in self.action or 'UNAUTHORIZED' in self.action or 'LOCKED' in self.action:
            return 'danger'
        if 'FAILED' in self.action or 'DEACTIVATED' in self.action:
            return 'warning'
        if self.action.startswith('ADMIN_'):
            return 'info'
        return 'secondary'

    def __repr__(self):
        return f'<AuditLog {self.action} on {self.entity_type} {self.entity_id} at {self.created_at}>'


class Notification(db.Model):
    __tablename__ = 'notifications'
    __table_args__ = (
        db.Index('ix_notifications_user_read', 'user_id', 'is_read'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(255), nullable=True)
    type = db.Column(db.String(32), default='info', nullable=False)  # info, success, warning, danger
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)

    @property
    def icon_class(self):
        return {
            'success': 'bi-check-circle-fill text-success',
            'warning': 'bi-exclamation-triangle-fill text-warning',
            'danger': 'bi-exclamation-octagon-fill text-danger',
        }.get(self.type, 'bi-info-circle-fill text-info')

    def __repr__(self):
        return f'<Notification {self.id} for User {self.user_id}: {self.title}>'
