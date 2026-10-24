# CloudOps 360 — Database Design (ER)

Engine: **MySQL 8.0** locally and **Amazon RDS for MySQL** in production (`utf8mb4`).
Schema is created only through **Alembic migrations** (`flask db upgrade`); models live in
`app/models.py`. All timestamps are stored as UTC `DATETIME`.

Verified locally on MySQL 8.0.43: `flask db upgrade` → `downgrade` → `upgrade`, `flask db check`
(models match migrations) and the CHECK constraints rejecting invalid values (MySQL error 3819).

## 1. Entity-relationship diagram

```mermaid
erDiagram
    users ||--o{ tickets : "creates (creator_id)"
    users |o--o{ tickets : "assigned (technician_id)"
    users ||--o{ comments : "writes"
    users ||--o{ attachments : "uploads"
    users |o--o{ ticket_status_history : "changes (NULL = system)"
    users ||--o{ technician_skills : "specialises in"
    ticket_categories ||--o{ technician_skills : "skill"
    users |o--o{ audit_logs : "acts (nullable)"
    users ||--o{ notifications : "receives"
    ticket_categories ||--o{ tickets : "classifies"
    tickets ||--o{ comments : "has"
    tickets ||--o{ attachments : "has"
    tickets ||--o{ ticket_status_history : "has"
    sla_policies ||..o{ tickets : "targets by priority (no FK)"

    users {
        int id PK
        varchar email UK
        varchar username UK
        varchar password_hash "scrypt/pbkdf2 hash, never plaintext"
        varchar full_name
        varchar role "CHECK employee|technician|admin"
        varchar department
        bool is_active
        datetime created_at
        datetime last_login_at
        bool is_available "away technicians get no auto-assigned tickets"
        varchar away_note
        datetime away_until "available again from this moment"
    }
    ticket_categories {
        int id PK
        varchar name UK
        varchar description
        bool is_active
        datetime created_at
    }
    sla_policies {
        int id PK
        varchar priority UK "CHECK Low|Medium|High|Critical"
        int response_time_hours "CHECK > 0"
        int resolution_time_hours "CHECK >= response"
        varchar description
        datetime created_at
        datetime updated_at
    }
    tickets {
        int id PK
        varchar reference_id UK "INC-YYYY-00001"
        varchar title
        text description
        int category_id FK
        varchar priority "CHECK"
        varchar status "CHECK Open..Closed"
        int creator_id FK
        int technician_id FK "nullable"
        varchar affected_system
        varchar department
        text resolution_summary
        datetime created_at
        datetime updated_at
        datetime response_due_at
        datetime resolution_due_at
        datetime first_responded_at
        datetime resolved_at
        datetime closed_at
        smallint satisfaction_rating "CHECK 1..5, nullable (CSAT)"
        varchar satisfaction_comment
        datetime rated_at
    }
    comments {
        int id PK
        int ticket_id FK "ON DELETE CASCADE"
        int user_id FK
        text content
        bool is_internal "hidden from employees"
        datetime created_at
    }
    attachments {
        int id PK
        int ticket_id FK "ON DELETE CASCADE"
        int user_id FK
        varchar filename "generated key"
        varchar original_filename "sanitised"
        int file_size
        varchar mime_type "server-determined"
        varchar storage_path "key relative to storage root"
        varchar checksum_sha256
        datetime created_at
    }
    ticket_status_history {
        int id PK
        int ticket_id FK "ON DELETE CASCADE"
        int changed_by_id FK "nullable: NULL = auto-assignment"
        varchar old_status
        varchar new_status
        text notes
        datetime created_at
    }
    audit_logs {
        int id PK
        int user_id FK "nullable (anonymous events)"
        varchar action
        varchar entity_type
        varchar entity_id
        text details "credentials scrubbed"
        varchar ip_address
        varchar user_agent
        datetime created_at
    }
    technician_skills {
        int user_id PK,FK "ON DELETE CASCADE"
        int category_id PK,FK "ON DELETE CASCADE"
    }
    system_settings {
        varchar key PK "e.g. auto_assign_max_open"
        varchar value
        datetime updated_at
    }
    notifications {
        int id PK
        int user_id FK "ON DELETE CASCADE"
        varchar title
        text message
        varchar link "internal paths only"
        varchar type
        bool is_read
        datetime created_at
    }
    login_attempts {
        int id PK
        varchar identifier "normalised username/email"
        varchar ip_address
        bool success
        datetime created_at
    }
```

`login_attempts` has no foreign key on purpose: it must also record attempts for usernames that
do not exist, without revealing which accounts exist.

## 2. Constraints

| Kind | Where |
| :--- | :--- |
| Primary keys | every table (`id`) |
| Unique | `users.email`, `users.username`, `ticket_categories.name`, `sla_policies.priority`, `tickets.reference_id` |
| Foreign keys | tickets → users (creator, technician), tickets → ticket_categories; comments/attachments/status history → tickets (cascade) and → users; notifications → users (cascade); audit_logs → users |
| CHECK | `ck_users_role`, `ck_tickets_status`, `ck_tickets_priority`, `ck_sla_policies_priority`, `ck_sla_policies_response_positive`, `ck_sla_policies_resolution_gte_response` |
| NOT NULL | all identifying and workflow columns |

Application-level rules (workflow transitions, who may do what) are enforced in
`app/services/workflow.py` and `app/services/permissions.py`; the database constraints are a
second line of defence against invalid values.

## 3. Indexes

| Index | Serves |
| :--- | :--- |
| `tickets(reference_id)` unique | ticket URLs |
| `tickets(creator_id, status)` | employee dashboards and "My tickets" |
| `tickets(technician_id, status)` | technician queue / workload |
| `tickets(status)`, `(priority)`, `(created_at)`, `(title)` | filters, sorting, trends |
| `notifications(user_id, is_read)` | unread badge polling |
| `audit_logs(action)`, `(created_at)`, `(user_id)` | audit filters |
| `login_attempts(identifier, created_at)`, `(ip_address, created_at)` | rate-limit lookups |

## 4. Migrations

| Revision | Content |
| :--- | :--- |
| `808b3a0090e9` | initial schema (9 tables) |
| `824a33157b1b` | `login_attempts`, `attachments.checksum_sha256`, relative storage keys, CHECK constraints, composite indexes |

Commands: `flask db upgrade` (apply), `flask db downgrade` (revert one), `flask db migrate -m "msg"`
(generate after model changes — review the file, then commit it), `flask db check` (verify models
and migrations agree).

## 5. Transactions

Each user action is committed once: the ticket change, its status-history row, audit entry and
notifications are staged on the same session and committed together (`commit=False` in
`log_audit_event` / `create_notification`). Failed uploads roll back the transaction and delete
any file already written.
