"""Administrator-editable settings stored in the system_settings table.

Values live in the database (not in .env) so every EC2 instance behind a load
balancer sees the same configuration and a change applies immediately.
"""
from dataclasses import dataclass, field

from flask import current_app

from app.extensions import db
from app.models import SystemSetting, TicketPriority, utcnow

MAX_OPEN_LIMITS = (1, 50)
WAIT_MINUTES_LIMITS = (0, 10080)  # up to 7 days

# Queue wait before auto-assignment: half of the default first-response target
DEFAULT_WAIT_MINUTES = {
    TicketPriority.CRITICAL: 30,
    TicketPriority.HIGH: 120,
    TicketPriority.MEDIUM: 240,
    TicketPriority.LOW: 720,
}
DEFAULT_MAX_OPEN = 10


def _wait_key(priority):
    return f'auto_assign_wait_{priority.lower()}'


def get_setting(key, default=None):
    row = db.session.get(SystemSetting, key)
    return row.value if row else default


def set_setting(key, value):
    """Stages a setting change; the caller commits."""
    row = db.session.get(SystemSetting, key)
    if row is None:
        row = SystemSetting(key=key, value=str(value))
        db.session.add(row)
    else:
        row.value = str(value)
        row.updated_at = utcnow()
    return row


def _int_setting(key, default, limits):
    try:
        value = int(get_setting(key, default))
    except (TypeError, ValueError):
        return default
    return min(max(value, limits[0]), limits[1])


@dataclass
class AutoAssignConfig:
    enabled: bool
    max_open: int
    wait_minutes: dict = field(default_factory=dict)


def get_auto_assign_config():
    default_enabled = 'true' if current_app.config.get('AUTO_ASSIGN_DEFAULT_ENABLED', True) else 'false'
    return AutoAssignConfig(
        enabled=get_setting('auto_assign_enabled', default_enabled) == 'true',
        max_open=_int_setting('auto_assign_max_open', DEFAULT_MAX_OPEN, MAX_OPEN_LIMITS),
        wait_minutes={p: _int_setting(_wait_key(p), DEFAULT_WAIT_MINUTES[p], WAIT_MINUTES_LIMITS)
                      for p in TicketPriority.ORDERED},
    )


def save_auto_assign_config(enabled, max_open, wait_minutes):
    """Stages the auto-assignment settings; the caller commits."""
    set_setting('auto_assign_enabled', 'true' if enabled else 'false')
    set_setting('auto_assign_max_open', int(max_open))
    for priority, minutes in wait_minutes.items():
        set_setting(_wait_key(priority), int(minutes))
