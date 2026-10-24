from flask_wtf import FlaskForm
from wtforms import (
    BooleanField, IntegerField, PasswordField, SelectField, SelectMultipleField, StringField, SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional, Regexp, ValidationError
from wtforms.widgets import CheckboxInput, ListWidget

from app.auth.forms import EMAIL_REGEX, USERNAME_REGEX, StrongPassword
from app.models import TicketCategory, TicketPriority, User, UserRole
from app.services.settings import MAX_OPEN_LIMITS, WAIT_MINUTES_LIMITS
from app.technician.forms import AvailabilityForm


class UserCreateAdminForm(FlaskForm):
    """Admin form to create users with an assigned role."""
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=100)])
    username = StringField('Username', validators=[
        DataRequired(), Length(min=3, max=64),
        Regexp(USERNAME_REGEX, message='Letters, numbers, dots, dashes and underscores only.')])
    email = StringField('Email Address', validators=[
        DataRequired(), Regexp(EMAIL_REGEX, message='Please enter a valid email address.'), Length(max=120)])
    role = SelectField('Role', choices=UserRole.CHOICES, default=UserRole.EMPLOYEE)
    department = StringField('Department', validators=[Optional(), Length(max=100)])
    password = PasswordField('Initial Password', validators=[DataRequired(), StrongPassword(), Length(max=128)])
    is_active = BooleanField('Account active', default=True)
    submit = SubmitField('Create User')

    def validate_username(self, username):
        if User.query.filter_by(username=username.data.strip()).first():
            raise ValidationError('Username already exists.')

    def validate_email(self, email):
        if User.query.filter_by(email=email.data.strip().lower()).first():
            raise ValidationError('Email already registered.')


class UserEditAdminForm(FlaskForm):
    """Admin form to edit an existing user."""
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField('Email Address', validators=[
        DataRequired(), Regexp(EMAIL_REGEX, message='Please enter a valid email address.'), Length(max=120)])
    role = SelectField('Role', choices=UserRole.CHOICES)
    department = StringField('Department', validators=[Optional(), Length(max=100)])
    new_password = PasswordField('Reset Password (optional)', validators=[Optional(), StrongPassword(), Length(max=128)])
    is_active = BooleanField('Account active')
    submit = SubmitField('Save Changes')

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user

    def validate_email(self, email):
        existing = User.query.filter_by(email=email.data.strip().lower()).first()
        if existing and (self._user is None or existing.id != self._user.id):
            raise ValidationError('Email already registered to another user.')


class CategoryForm(FlaskForm):
    """Incident category create/edit form."""
    name = StringField('Category Name', validators=[DataRequired(), Length(min=2, max=64)])
    description = StringField('Description', validators=[Optional(), Length(max=255)])
    is_active = BooleanField('Active (available for new tickets)', default=True)
    submit = SubmitField('Save Category')

    def __init__(self, *args, category=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._category = category

    def validate_name(self, name):
        existing = TicketCategory.query.filter(TicketCategory.name == name.data.strip()).first()
        if existing and (self._category is None or existing.id != self._category.id):
            raise ValidationError('A category with this name already exists.')


class SLAPolicyForm(FlaskForm):
    """SLA target configuration."""
    priority = SelectField('Priority', choices=TicketPriority.CHOICES)
    response_time_hours = IntegerField('First Response Target (hours)', validators=[DataRequired(), NumberRange(min=1, max=720)])
    resolution_time_hours = IntegerField('Resolution Target (hours)', validators=[DataRequired(), NumberRange(min=1, max=2160)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=255)])
    apply_to_active = BooleanField('Recalculate deadlines of active tickets with this priority')
    submit = SubmitField('Save SLA Policy')

    def validate_resolution_time_hours(self, field):
        if self.response_time_hours.data and field.data and field.data < self.response_time_hours.data:
            raise ValidationError('Resolution target cannot be shorter than the response target.')


def _wait_field(label):
    return IntegerField(label, validators=[InputRequired(message='Enter a number of minutes.'),
                                           NumberRange(min=WAIT_MINUTES_LIMITS[0], max=WAIT_MINUTES_LIMITS[1])])


class AutoAssignSettingsForm(FlaskForm):
    """Auto-assignment configuration (stored in system_settings)."""
    enabled = BooleanField('Auto-assign new tickets')
    max_open = IntegerField('Maximum open tickets per technician', validators=[
        InputRequired(message='Enter a number between 1 and 50.'),
        NumberRange(min=MAX_OPEN_LIMITS[0], max=MAX_OPEN_LIMITS[1],
                    message=f'Choose between {MAX_OPEN_LIMITS[0]} and {MAX_OPEN_LIMITS[1]} tickets.')])
    wait_critical = _wait_field('Critical')
    wait_high = _wait_field('High')
    wait_medium = _wait_field('Medium')
    wait_low = _wait_field('Low')
    submit = SubmitField('Save Settings')

    WAIT_FIELDS = {
        TicketPriority.CRITICAL: 'wait_critical',
        TicketPriority.HIGH: 'wait_high',
        TicketPriority.MEDIUM: 'wait_medium',
        TicketPriority.LOW: 'wait_low',
    }

    def fill_from(self, config):
        self.enabled.data = config.enabled
        self.max_open.data = config.max_open
        for priority, name in self.WAIT_FIELDS.items():
            getattr(self, name).data = config.wait_minutes[priority]
        return self

    def wait_minutes(self):
        return {priority: getattr(self, name).data for priority, name in self.WAIT_FIELDS.items()}


class TechnicianSettingsForm(AvailabilityForm):
    """Administrator view of a technician: skills (categories) plus availability."""
    skills = SelectMultipleField('Skills (categories this technician specialises in)', coerce=int,
                                 widget=ListWidget(prefix_label=False), option_widget=CheckboxInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.skills.choices = [(c.id, c.name) for c in TicketCategory.query.order_by(TicketCategory.name).all()]
