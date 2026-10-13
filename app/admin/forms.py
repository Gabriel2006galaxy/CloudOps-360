from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField, IntegerField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Email, Length, NumberRange, ValidationError, Regexp
from app.models import User, UserRole, TicketPriority

EMAIL_REGEX = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'


class UserCreateAdminForm(FlaskForm):
    """Admin form to create new users with assigned roles."""
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=100)])
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email Address', validators=[DataRequired(), Regexp(EMAIL_REGEX, message="Please enter a valid email address."), Length(max=120)])
    role = SelectField('System Role', choices=UserRole.CHOICES, default=UserRole.EMPLOYEE)
    department = StringField('Department', validators=[Length(max=100)])
    password = PasswordField('Initial Password', validators=[DataRequired(), Length(min=8)])
    is_active = BooleanField('Account Active', default=True)
    submit = SubmitField('Create User')

    def validate_username(self, username):
        if User.query.filter_by(username=username.data.strip()).first():
            raise ValidationError('Username already exists in the system.')

    def validate_email(self, email):
        if User.query.filter_by(email=email.data.strip().lower()).first():
            raise ValidationError('Email already registered.')


class UserEditAdminForm(FlaskForm):
    """Admin form to edit existing users."""
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField('Email Address', validators=[DataRequired(), Regexp(EMAIL_REGEX, message="Please enter a valid email address."), Length(max=120)])
    role = SelectField('System Role', choices=UserRole.CHOICES)
    department = StringField('Department', validators=[Length(max=100)])
    new_password = PasswordField('Reset Password (Optional)', validators=[Length(min=8, message="Password must be at least 8 characters.")])
    is_active = BooleanField('Account Active')
    submit = SubmitField('Update User')


class CategoryForm(FlaskForm):
    """Incident category management form."""
    name = StringField('Category Name', validators=[DataRequired(), Length(min=2, max=64)])
    description = StringField('Description', validators=[Length(max=255)])
    is_active = BooleanField('Category Active', default=True)
    submit = SubmitField('Save Category')


class SLAPolicyForm(FlaskForm):
    """SLA policy target configuration form."""
    priority = SelectField('Priority Level', choices=TicketPriority.CHOICES)
    response_time_hours = IntegerField('Response Target (Hours)', validators=[DataRequired(), NumberRange(min=1, max=720)])
    resolution_time_hours = IntegerField('Resolution Target (Hours)', validators=[DataRequired(), NumberRange(min=1, max=720)])
    description = TextAreaField('Policy SLA Description', validators=[Length(max=255)])
    submit = SubmitField('Save SLA Policy')
