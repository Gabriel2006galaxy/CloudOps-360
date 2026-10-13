from flask import request
from flask_login import current_user
from app.extensions import db
from app.models import AuditLog


def log_audit_event(action, entity_type=None, entity_id=None, details=None, user_id=None):
    """
    Records an enterprise audit log entry for compliance and security forensics.
    
    Parameters:
    - action: Short string identifier, e.g. 'AUTH_LOGIN_SUCCESS', 'TICKET_STATUS_CHANGE'
    - entity_type: Class name e.g. 'Ticket', 'User', 'SLAPolicy'
    - entity_id: ID or reference of affected entity
    - details: Human-readable or structured details string
    - user_id: Specific actor ID (defaults to current_user.id if authenticated)
    """
    try:
        actor_id = user_id
        if actor_id is None and current_user and current_user.is_authenticated:
            actor_id = current_user.id

        ip_address = None
        user_agent = None

        if request:
            # Check for standard reverse-proxy headers (AWS ALB / Nginx)
            if request.headers.get('X-Forwarded-For'):
                ip_address = request.headers.get('X-Forwarded-For').split(',')[0].strip()
            else:
                ip_address = request.remote_addr
            
            user_agent = request.user_agent.string[:250] if request.user_agent else None

        audit_entry = AuditLog(
            user_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.session.add(audit_entry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Ensure audit failure does not crash core application logic
        print(f"[AuditService] Failed to record audit log: {e}")
