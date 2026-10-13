# CloudOps 360 — Request & Data Flows

Every flow below is implemented in the code referenced and covered by the tests named.

## 1. Sign-in, session and authorization

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant N as Nginx
    participant F as Flask (auth)
    participant DB as MySQL / RDS
    B->>N: POST /auth/login (CSRF token, username, password)
    N->>F: proxy (X-Forwarded-For / Proto)
    F->>F: validate CSRF token (Flask-WTF)
    F->>DB: count recent failed login_attempts (account + IP)
    alt locked out
        F->>DB: audit AUTH_LOGIN_LOCKED
        F-->>B: 429 "Too many failed sign-in attempts"
    else
        F->>DB: SELECT user; check_password_hash()
        alt wrong password / unknown user
            F->>DB: insert login_attempt(success=false), audit AUTH_LOGIN_FAILED
            F-->>B: 401 generic error
        else deactivated
            F-->>B: 403
        else success
            F->>F: session.clear() (rotate), login_user, login_at/last_seen
            F->>DB: insert login_attempt(success=true), audit AUTH_LOGIN_SUCCESS
            F-->>B: 302 → role dashboard (HttpOnly, SameSite=Lax, Secure over HTTPS)
        end
    end
    Note over F: Every later request: account still active? idle < 30 min? absolute < 8 h?<br/>otherwise logout + audit AUTH_SESSION_EXPIRED / REVOKED
```

Code: `app/auth/routes.py`, `app/services/login_security.py`, `app/__init__.py` (`enforce_session_policy`).
Tests: `tests/test_auth.py`.

## 2. Creating an incident with an attachment

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser (Employee)
    participant F as Flask (tickets)
    participant S as Storage (local dir / EFS)
    participant DB as MySQL / RDS
    B->>F: POST /tickets/create (multipart, CSRF)
    F->>F: validate form (title, active category, priority, description)
    F->>S: stream file in 64 KB chunks → .part file<br/>size limit, extension whitelist, magic bytes, SHA-256
    alt invalid file
        S-->>F: UploadValidationError (partial file deleted)
        F-->>B: 400 form with error, nothing saved
    else valid
        S->>S: atomic rename to YYYY/MM/uuid.ext (0640)
        F->>DB: INSERT ticket → id → reference INC-YYYY-00042<br/>SLA due dates from sla_policies<br/>status history, attachment row, audit, notifications
        F->>DB: COMMIT (one transaction)
        F-->>B: 302 /tickets/INC-YYYY-00042
    end
```

If the database commit fails after the file was stored, the file is deleted (no orphans).
Code: `app/tickets/routes.py::create`, `app/services/storage.py`. Tests: `tests/test_tickets.py`, `tests/test_attachments.py`.

## 3. Authorized download

```mermaid
sequenceDiagram
    participant B as Browser
    participant F as Flask (attachments)
    participant DB as MySQL / RDS
    participant S as Storage (EFS)
    B->>F: GET /attachments/7/download
    F->>DB: load attachment + ticket
    F->>F: can_view_ticket(user, ticket)?<br/>creator / assigned technician / admin
    alt not allowed
        F->>DB: audit ATTACHMENT_UNAUTHORIZED_DOWNLOAD
        F-->>B: 403
    else allowed
        F->>S: resolve key inside storage root (no traversal)
        F->>DB: audit ATTACHMENT_DOWNLOAD
        F-->>B: 200 Content-Disposition: attachment; X-Content-Type-Options: nosniff;<br/>CSP: sandbox; Cache-Control: private, no-store
    end
```

## 4. Ticket lifecycle and notifications

```mermaid
stateDiagram-v2
    [*] --> Open: employee reports
    Open --> Assigned: technician claims / admin assigns
    Assigned --> InProgress: assigned technician starts work
    Assigned --> Open: admin returns to queue
    InProgress --> Resolved: technician (resolution summary ≥ 10 chars required)
    InProgress --> Assigned: admin pauses
    Resolved --> Closed: reporter confirms / technician / admin
    Resolved --> InProgress: reopen (reporter, technician, admin)
    Closed --> InProgress: reopen within 14 days (reporter) or any time (admin)
    Open --> Closed: admin cancels
    Assigned --> Closed: admin cancels
    Closed --> [*]
```

Every accepted transition writes `ticket_status_history`, an audit entry
(`TICKET_STATUS_CHANGE` / `TICKET_REOPEN`) and notifications to the other parties; rejected ones are
audited as `TICKET_TRANSITION_REJECTED`. Reopening restarts the resolution SLA window. Changing
priority recalculates SLA targets. Code: `app/services/workflow.py`. Tests: `tests/test_workflow.py`.

## 5. Internal notes

```mermaid
flowchart LR
    T["Technician posts comment<br/>is_internal checked"] --> P{"can_post_internal_note?<br/>(staff + assigned / admin)"}
    P -- no --> PUB["stored as public"]
    P -- yes --> INT["stored with is_internal = true"]
    INT --> Q{"viewer is staff?"}
    Q -- employee --> HIDE["filtered out in SQL:<br/>Comment.is_internal = false"]
    Q -- technician/admin --> SHOW["shown with 'Internal note' badge"]
```

Employees never receive internal notes in HTML, notifications or the activity timeline.
Tests: `tests/test_internal_notes.py`.

## 6. SLA evaluation

* On create: `response_due_at = created + policy.response_hours`, `resolution_due_at = created + policy.resolution_hours`.
* First public staff reply or move to *In Progress* sets `first_responded_at`.
* Overdue = active status and `now > resolution_due_at` (SQL filter for lists; property for display).
* Compliance = resolved on time ÷ (all resolved + active overdue). Shown as "—" when nothing is evaluated yet.
* Code: `app/services/sla.py`, `app/services/metrics.py`. Tests: `tests/test_sla.py`, `tests/test_dashboards.py`.

## 7. Production secret resolution (EC2)

```mermaid
sequenceDiagram
    participant G as Gunicorn worker (create_app)
    participant IMDS as EC2 instance metadata
    participant SM as Secrets Manager
    participant RDS as RDS MySQL
    G->>IMDS: temporary credentials for CloudOps360-EC2-Role (boto3)
    G->>SM: GetSecretValue cloudops360/prod/app → SECRET_KEY
    G->>SM: GetSecretValue cloudops360/prod/db → user/password/host
    alt any secret missing in production
        G-->>G: SecretResolutionError → worker refuses to start (fail closed)
    end
    G->>RDS: connect with TLS, CA = DB_SSL_CA (certificate verified)
```

Code: `app/services/secrets.py`. Tests: `tests/test_security.py` (fail-closed cases).
