from functools import wraps
from flask import abort, flash, redirect, url_for, request
from flask_login import current_user
from app.models import UserRole
from app.services.audit import log_audit_event


def role_required(*roles):
    """
    Decorator to restrict view access to specific user roles.
    Logs an audit event on authorization failure.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login', next=request.url))
            if current_user.role not in roles:
                log_audit_event(
                    action='ACCESS_DENIED_RBAC',
                    entity_type='Endpoint',
                    entity_id=request.path,
                    details=f"User '{current_user.username}' (role: {current_user.role}) denied access. Required: {roles}"
                )
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f):
    """Restricts access strictly to Administrator users."""
    return role_required(UserRole.ADMIN)(f)


def technician_or_admin_required(f):
    """Restricts access to Support Technicians and Administrators."""
    return role_required(UserRole.TECHNICIAN, UserRole.ADMIN)(f)
