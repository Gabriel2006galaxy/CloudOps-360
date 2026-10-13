from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, SelectField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError, Regexp
from app.models import User, UserRole

EMAIL_REGEX = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'


class LoginForm(FlaskForm):
    """Secure user login form with CSRF validation."""
    username_or_email = StringField('Username or Email', validators=[DataRequired(), Length(max=120)])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Sign In')


class RegisterForm(FlaskForm):
    """User registration form with strict input sanitation."""
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=100)])
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email Address', validators=[DataRequired(), Regexp(EMAIL_REGEX, message="Please enter a valid email address."), Length(max=120)])
    department = StringField('Department', validators=[Length(max=100)])
    role = SelectField('Role', choices=[(UserRole.EMPLOYEE, 'Employee')], default=UserRole.EMPLOYEE)
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8, message="Password must be at least 8 characters.")])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password', message="Passwords must match.")])
    submit = SubmitField('Create Account')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data.strip()).first()
        if user:
            raise ValidationError('This username is already registered. Please choose another.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data.strip().lower()).first()
        if user:
            raise ValidationError('This email is already registered. Please use another.')


class ProfileForm(FlaskForm):
    """User profile update form."""
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=100)])
    department = StringField('Department', validators=[Length(max=100)])
    current_password = PasswordField('Current Password (Required for password changes)')
    new_password = PasswordField('New Password (Optional)', validators=[Length(min=8, message="Password must be at least 8 characters.")])
    confirm_new_password = PasswordField('Confirm New Password', validators=[EqualTo('new_password', message="New passwords must match.")])
    submit = SubmitField('Update Profile')
