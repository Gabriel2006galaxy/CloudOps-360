from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import BooleanField, HiddenField, RadioField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from app.models import TicketCategory, TicketPriority, TicketStatus


class TicketCreateForm(FlaskForm):
    """Incident ticket creation form."""
    title = StringField('Incident Title', validators=[
        DataRequired(message='Please provide a descriptive incident title.'),
        Length(min=5, max=150)
    ])
    category_id = SelectField('Category', coerce=int, validators=[DataRequired(message='Choose a category.')])
    priority = SelectField('Priority', choices=TicketPriority.CHOICES, default=TicketPriority.MEDIUM)
    affected_system = StringField('Affected System / Resource', validators=[Optional(), Length(max=100)])
    department = StringField('Department', validators=[Optional(), Length(max=100)])
    description = TextAreaField('Description & Steps to Reproduce', validators=[
        DataRequired(message='Please describe the incident.'),
        Length(min=10, max=10000)
    ])
    attachment = FileField('Screenshot or Diagnostic File (optional)')
    submit = SubmitField('Submit Incident')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.category_id.choices = [
            (c.id, c.name) for c in TicketCategory.query.filter_by(is_active=True).order_by(TicketCategory.name).all()
        ]


class StatusChangeForm(FlaskForm):
    status = SelectField('New Status', choices=TicketStatus.CHOICES, validators=[DataRequired()])
    note = TextAreaField('Note', validators=[Optional(), Length(max=2000)])
    resolution_summary = TextAreaField('Resolution Summary & Root Cause', validators=[Optional(), Length(max=5000)])


class AssignForm(FlaskForm):
    technician_id = SelectField('Assigned Technician', coerce=int, validators=[Optional()])

    def __init__(self, *args, staff=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.technician_id.choices = [(0, '— Unassigned (return to queue) —')] + [
            (u.id, f"{u.full_name} ({u.role_label})" + (f" — {u.availability_label}" if u.is_away else ''))
            for u in (staff or [])
        ]


class PriorityForm(FlaskForm):
    priority = SelectField('Priority', choices=TicketPriority.CHOICES, validators=[DataRequired()])


class DetailsForm(FlaskForm):
    affected_system = StringField('Affected System', validators=[Optional(), Length(max=100)])
    department = StringField('Department', validators=[Optional(), Length(max=100)])


class CommentForm(FlaskForm):
    """Public comment or private internal technician note."""
    content = TextAreaField('Comment', validators=[DataRequired(message='Comment cannot be empty.'), Length(min=2, max=5000)])
    is_internal = BooleanField('Internal note (hidden from the employee)')
    submit = SubmitField('Post')


class AttachmentUploadForm(FlaskForm):
    attachment = FileField('Select a screenshot or diagnostic file', validators=[DataRequired(message='Choose a file to upload.')])
    submit = SubmitField('Upload')


class ClaimForm(FlaskForm):
    """CSRF-only form for single-button actions."""
    confirm = HiddenField(default='1')


class RatingForm(FlaskForm):
    """Customer satisfaction: 1-5 stars plus an optional comment."""
    rating = RadioField('Rating', coerce=int, choices=[(i, str(i)) for i in range(5, 0, -1)],
                        validators=[DataRequired(message='Choose between 1 and 5 stars.')])
    comment = TextAreaField('Comment (optional)', validators=[Optional(), Length(max=500)])
