from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, EqualTo, Length, Optional, Regexp, ValidationError

from app.models import User

EMAIL_REGEX = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
USERNAME_REGEX = r'^[A-Za-z0-9_.-]+$'


class StrongPassword:
    """At least 10 characters with upper, lower and a digit."""

    def __init__(self, min_length=10):
        self.min_length = min_length

    def __call__(self, form, field):
        value = field.data or ''
        if not value:
            return
        if (len(value) < self.min_length or not any(c.islower() for c in value)
                or not any(c.isupper() for c in value) or not any(c.isdigit() for c in value)):
            raise ValidationError(
                f'Use at least {self.min_length} characters including upper-case, lower-case letters and a number.'
            )


class LoginForm(FlaskForm):
    """Sign-in form (CSRF protected)."""
    username_or_email = StringField('Username or Email', validators=[DataRequired(), Length(max=120)])
    password = PasswordField('Password', validators=[DataRequired(), Length(max=128)])
    submit = SubmitField('Sign In')


class RegisterForm(FlaskForm):
    """Public self-registration. Always creates an Employee - the role is never read from the request."""
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=100)])
    username = StringField('Username', validators=[
        DataRequired(), Length(min=3, max=64),
        Regexp(USERNAME_REGEX, message='Letters, numbers, dots, dashes and underscores only.')])
    email = StringField('Email Address', validators=[
        DataRequired(), Regexp(EMAIL_REGEX, message='Please enter a valid email address.'), Length(max=120)])
    department = StringField('Department', validators=[Optional(), Length(max=100)])
    password = PasswordField('Password', validators=[DataRequired(), StrongPassword(), Length(max=128)])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(), EqualTo('password', message='Passwords must match.')])
    submit = SubmitField('Create Account')

    def validate_username(self, username):
        if User.query.filter_by(username=username.data.strip()).first():
            raise ValidationError('This username is already registered. Please choose another.')

    def validate_email(self, email):
        if User.query.filter_by(email=email.data.strip().lower()).first():
            raise ValidationError('This email is already registered. Please use another.')


class ProfileForm(FlaskForm):
    """Self-service profile. Deliberately has no role or status fields."""
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=100)])
    department = StringField('Department', validators=[Optional(), Length(max=100)])
    current_password = PasswordField('Current Password', validators=[Optional(), Length(max=128)])
    new_password = PasswordField('New Password', validators=[Optional(), StrongPassword(), Length(max=128)])
    confirm_new_password = PasswordField('Confirm New Password', validators=[
        EqualTo('new_password', message='New passwords must match.')])
    submit = SubmitField('Save Changes')
