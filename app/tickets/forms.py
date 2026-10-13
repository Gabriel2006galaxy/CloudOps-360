from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, TextAreaField, SelectField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Length, Optional
from app.models import TicketPriority, TicketStatus, TicketCategory, User, UserRole


class TicketCreateForm(FlaskForm):
    """Incident Ticket creation form."""
    title = StringField('Incident Title', validators=[
        DataRequired(message="Please provide a descriptive incident title."),
        Length(min=5, max=150)
    ])
    category_id = SelectField('Incident Category', coerce=int, validators=[DataRequired()])
    priority = SelectField('Priority Level', choices=TicketPriority.CHOICES, default=TicketPriority.MEDIUM)
    affected_system = StringField('Affected System / Resource', validators=[Length(max=100)], description="e.g. AWS EC2 Prod Cluster, VPN Gateway, Workstation-12")
    department = StringField('Department', validators=[Length(max=100)])
    description = TextAreaField('Detailed Incident Description & Steps to Reproduce', validators=[
        DataRequired(message="Please provide comprehensive description details."),
        Length(min=10)
    ])
    attachment = FileField('Diagnostic Attachment / Screenshot (Optional)')
    submit = SubmitField('Submit Incident Ticket')

    def __init__(self, *args, **kwargs):
        super(TicketCreateForm, self).__init__(*args, **kwargs)
        self.category_id.choices = [
            (c.id, c.name) for c in TicketCategory.query.filter_by(is_active=True).order_by(TicketCategory.name).all()
        ]


class TicketUpdateForm(FlaskForm):
    """Ticket status, priority, and assignment modification form."""
    status = SelectField('Status', choices=TicketStatus.CHOICES)
    priority = SelectField('Priority', choices=TicketPriority.CHOICES)
    technician_id = SelectField('Assigned Technician', coerce=int, validators=[Optional()])
    affected_system = StringField('Affected System', validators=[Length(max=100)])
    department = StringField('Department', validators=[Length(max=100)])
    resolution_summary = TextAreaField('Resolution Summary & Root Cause Analysis')
    submit = SubmitField('Save Updates')

    def __init__(self, *args, **kwargs):
        super(TicketUpdateForm, self).__init__(*args, **kwargs)
        technicians = User.query.filter(User.role.in_([UserRole.TECHNICIAN, UserRole.ADMIN]), User.is_active == True).order_by(User.full_name).all()
        self.technician_id.choices = [(0, '-- Unassigned --')] + [(t.id, f"{t.full_name} ({t.role})") for t in technicians]


class CommentForm(FlaskForm):
    """Ticket comment and internal technician note form."""
    content = TextAreaField('Comment Content', validators=[DataRequired(), Length(min=2)])
    is_internal = BooleanField('Internal Technician Note (Hidden from Employee)')
    submit = SubmitField('Post Comment')


class AttachmentUploadForm(FlaskForm):
    """Upload supplemental attachment form."""
    attachment = FileField('Select Diagnostic File or Screenshot', validators=[DataRequired()])
    submit = SubmitField('Upload Attachment')
