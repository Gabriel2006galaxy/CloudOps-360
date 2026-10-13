# CloudOps 360 — Request & Data-Flow Documentation

This document diagrams the complete lifecycle of requests, data boundaries, and security validation checks across **CloudOps 360**.

---

## 1. Authentication & Role-Based Access Control (RBAC) Flow

```mermaid
sequenceDiagram
    autonumber
    actor User as Client Browser
    participant Nginx as Nginx (Reverse Proxy)
    participant Flask as Flask App / Auth Blueprint
    participant DB as Amazon RDS (MySQL)
    participant Audit as Audit Service

    User->>Nginx: POST /auth/login (username_or_email, password, CSRF)
    Nginx->>Flask: Reverse proxy request with X-Forwarded-For
    Flask->>Flask: Verify CSRF token & sanitize input
    Flask->>DB: SELECT * FROM users WHERE username = ? OR email = ?
    DB-->>Flask: Return user record (or null)

    alt Invalid Credentials or Deactivated Account
        Flask->>Audit: log_audit_event('AUTH_LOGIN_FAILED' / 'DEACTIVATED')
        Audit->>DB: INSERT INTO audit_logs (...)
        Flask-->>User: 200 OK (Flash error: Invalid credentials)
    else Successful Authentication
        Flask->>Flask: check_password_hash(user.password_hash, input_password)
        Flask->>DB: UPDATE users SET last_login_at = NOW() WHERE id = user.id
        Flask->>Audit: log_audit_event('AUTH_LOGIN_SUCCESS')
        Audit->>DB: INSERT INTO audit_logs (...)
        Flask->>Flask: Establish signed, HTTPOnly, SameSite session cookie
        Flask-->>User: 302 Found -> Redirect to /dashboard
    end
```

---

## 2. Incident Ticket Creation & Amazon EFS Storage Flow

```mermaid
sequenceDiagram
    autonumber
    actor Emp as Employee
    participant Flask as Flask App (tickets.create)
    participant Storage as Storage Service
    participant EFS as Amazon EFS (/mnt/efs/cloudops360-attachments)
    participant RDS as Amazon RDS (MySQL)
    participant Notif as Notification Service
    participant Audit as Audit Service

    Emp->>Flask: POST /tickets/create (title, description, priority, category_id, file)
    Flask->>Flask: Verify authenticated user & CSRF token
    Flask->>Flask: Generate reference ID: INC-2026-XXXXX
    Flask->>RDS: Query SLA Policy for priority (e.g. Critical -> Resp: 1h, Resol: 4h)
    RDS-->>Flask: Return SLA thresholds
    Flask->>Flask: Compute response_due_at and resolution_due_at (UTC)

    opt Attachment File Provided
        Flask->>Storage: save_file(file_storage)
        Storage->>Storage: Validate extension against whitelist (png, jpg, log, pdf, etc.)
        Storage->>Storage: Generate cryptographic UUID: <uuid>.<ext>
        Storage->>Storage: Path-traversal sanitization check
        Storage->>EFS: Write binary payload to /mnt/efs/cloudops360-attachments/<uuid>.<ext>
        EFS-->>Storage: Confirm file write & file size (<= 10MB)
        Storage-->>Flask: Return (stored_filename, original_filename, file_size, storage_path)
    end

    Flask->>RDS: BEGIN TRANSACTION
    Flask->>RDS: INSERT INTO tickets (reference_id, title, priority, status='Open', ...)
    Flask->>RDS: INSERT INTO ticket_status_history (ticket_id, old_status='None', new_status='Open')
    opt Attachment File Uploaded
        Flask->>RDS: INSERT INTO attachments (ticket_id, user_id, filename, original_filename, storage_path)
    end
    Flask->>RDS: COMMIT TRANSACTION

    Flask->>Audit: log_audit_event('TICKET_CREATE', reference_id)
    Audit->>RDS: INSERT INTO audit_logs (...)
    Flask->>Notif: Create alerts for Active Technicians
    Notif->>RDS: INSERT INTO notifications (technician_id, title, message, link)

    Flask-->>Emp: 302 Found -> Redirect to /tickets/INC-2026-XXXXX
```

---

## 3. Support Technician Review, Private Internal Notes & Resolution Flow

```mermaid
sequenceDiagram
    autonumber
    actor Tech as Support Technician
    actor Emp as Ticket Creator (Employee)
    participant Flask as Flask App
    participant RDS as Amazon RDS (MySQL)
    participant Audit as Audit Service
    participant Notif as Notification Service

    Tech->>Flask: POST /technician/claim/INC-2026-00001
    Flask->>Flask: Enforce technician_or_admin_required decorator
    Flask->>RDS: UPDATE tickets SET technician_id = tech.id, status = 'Assigned'
    Flask->>RDS: INSERT INTO ticket_status_history (...)
    Flask->>Notif: Notify Employee that technician has claimed ticket
    Notif->>RDS: INSERT INTO notifications (creator_id, ...)

    Note over Tech, Flask: Adding Confidential Diagnostic Internal Note
    Tech->>Flask: POST /tickets/INC-2026-00001/comment (content, is_internal=True)
    Flask->>Flask: Verify user is Technician or Admin (Employees cannot set is_internal=True)
    Flask->>RDS: INSERT INTO comments (ticket_id, user_id, content, is_internal=True)
    Flask->>Audit: log_audit_event('TICKET_COMMENT_ADD', details='Internal: True')

    Note over Emp, Flask: Employee views ticket details
    Emp->>Flask: GET /tickets/INC-2026-00001
    Flask->>RDS: SELECT * FROM comments WHERE ticket_id = ? AND is_internal = FALSE
    RDS-->>Flask: Returns ONLY public comments
    Flask-->>Emp: Render page (Private internal note is NEVER sent to Employee DOM)

    Note over Tech, Flask: Ticket Resolution
    Tech->>Flask: POST /tickets/INC-2026-00001/update (status='Resolved', resolution_summary=...)
    Flask->>Flask: Validate status transition (In Progress -> Resolved is valid)
    Flask->>RDS: UPDATE tickets SET status='Resolved', resolved_at=NOW(), resolution_summary=?
    Flask->>RDS: INSERT INTO ticket_status_history (old_status='In Progress', new_status='Resolved')
    Flask->>Audit: log_audit_event('TICKET_UPDATE', 'Status: Resolved')
    Flask->>Notif: Notify Employee of resolution
    Flask-->>Tech: 302 Found -> Redirect to /tickets/INC-2026-00001
```

---

## 4. SLA Monitoring Engine & Overdue Detection Flow

```mermaid
sequenceDiagram
    autonumber
    participant Client as User / Dashboard Request
    participant App as SLA Service (app.services.sla)
    participant DB as Amazon RDS (MySQL)

    Client->>App: Request dashboard metrics or ticket queue
    App->>DB: SELECT * FROM tickets WHERE status IN ('Open', 'Assigned', 'In Progress')
    DB-->>App: Return active open tickets

    loop For each open ticket
        App->>App: Compare resolution_due_at against datetime.now(timezone.utc)
        alt resolution_due_at < current_utc_time
            App->>App: Flag ticket as is_overdue = True
            App->>App: Format overdue duration e.g. "Overdue by 3h 15m"
        else resolution_due_at >= current_utc_time
            App->>App: Flag ticket as is_overdue = False
            App->>App: Format remaining time e.g. "2h 45m remaining"
        end
    end

    App->>DB: Query resolved tickets to calculate overall SLA compliance %
    DB-->>App: Return resolved tickets count within vs breached SLA
    App->>App: compliance_rate = (resolved_within_sla / total_evaluated) * 100
    App-->>Client: Render live overdue badges, alerts, and SLA compliance charts
```
