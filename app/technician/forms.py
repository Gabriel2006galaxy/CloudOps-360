from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, StringField
from wtforms.validators import Length, Optional, ValidationError

from app.models import utcnow


class AvailabilityForm(FlaskForm):
    """Technician availability: away technicians receive no auto-assigned tickets."""
    status = SelectField('Status', choices=[('available', 'Available'), ('away', 'Away (sick, leave, training…)')])
    away_note = StringField('Note (optional)', validators=[Optional(), Length(max=120)])
    back_on = DateField('Back on (optional)', validators=[Optional()])

    def validate_back_on(self, field):
        if field.data and self.status.data == 'away' and field.data <= utcnow().date():
            raise ValidationError('The return date must be in the future.')

    def fill_from(self, user):
        self.status.data = 'away' if user.is_away else 'available'
        self.away_note.data = user.away_note if user.is_away else None
        self.back_on.data = user.away_until.date() if user.is_away and user.away_until else None
        return self
