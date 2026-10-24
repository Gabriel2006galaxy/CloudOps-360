# CloudOps 360 — Secure IT Service & Incident Management Platform

> **Intelligent IT Operations. Secure by Design.**
> A full-stack IT service-management application for the AWS Cloud Computing Lab:
> Flask + MySQL/Amazon RDS + Amazon EFS on Amazon EC2, with role-based dashboards,
> a real ticket workflow, SLA tracking and demonstrable security controls.

| | |
| :--- | :--- |
| **Stack** | Python 3.11/3.12 · Flask 3 (blueprints, Jinja2) · Flask-SQLAlchemy · Flask-Migrate (Alembic) · Flask-Login · Flask-WTF · MySQL 8 / Amazon RDS · Bootstrap 5 · Bootstrap Icons · Chart.js · Nginx + Gunicorn on EC2 · Amazon EFS · IAM · Secrets Manager |
| **Tests** | 143 pytest tests — passing on SQLite **and** MySQL 8.0 |
| **Status** | Application complete and verified locally. AWS deployment is scripted and documented but **not yet verified on AWS** — see [What still needs your action](#11-what-still-needs-your-action-aws). |

Documentation: [Requirements checklist](docs/REQUIREMENTS_CHECKLIST.md) ·
[AWS deployment guide](docs/aws_deployment.md) · [Architecture](docs/architecture.md) ·
[Database ER](docs/database_er.md) · [Data flows](docs/data_flow.md) ·
[Security checklist](docs/security_checklist.md) · [Lab 1–3 guides](docs/lab_guides.md)

---

## 1. Features

**Roles (enforced on the server for every request)**

| Employee | Support Technician | Administrator |
| :--- | :--- | :--- |
| Report incidents with screenshots/logs | Work tickets assigned to them | Everything technicians can do, on every ticket |
| See only their own tickets, public comments and status history | Claim tickets from the unassigned queue | Manage users, roles and account status |
| Comment, upload files, confirm or reopen a resolution | Change status/priority, public replies, **private internal notes** | Assign / reassign tickets, manage categories |
| Personal dashboard and notifications | Workload, critical and overdue views, resolution trend | Configure SLA targets, analytics, audit trail (CSV export) |

**Tickets** — reference `INC-YYYY-00001`, title, description, category, priority (Low → Critical),
creator, assignee, affected system, department, attachments, resolution summary, timestamps.
Workflow **Open → Assigned → In Progress → Resolved → Closed** with server-validated transitions,
required resolution summary and authorized reopening. Search, filters (status, priority, category,
assignee, created-date range, overdue), column sorting, pagination and a full activity history.

**SLA** — configurable first-response and resolution targets per priority, live countdown,
overdue flags, resolution duration, compliance rates. All timestamps UTC.

**Auto-assignment** — a new ticket goes straight to the best available technician: only technicians
who are *Available* and below the maximum open tickets (default 10, admin can set 1–50), specialists in
the ticket's category first, then the lightest workload (points: Critical 4, High 3, Medium 2, Low 1),
random only between equal candidates. If every technician is free the ticket waits in the queue for
anyone to claim; unclaimed tickets are assigned after a per-priority wait (default Critical 30 min,
High 2 h, Medium 4 h, Low 12 h). The reason is written to the ticket history and the audit trail.
Admins configure it under **Administration → Auto-Assignment** (switch on/off, limits, *Run auto-assign
now*) and set technician skills on the user's edit page. Technicians mark themselves **Available/Away**
(with note and "back on" date, after which they return automatically); admins are warned about
away technicians who still hold open tickets. CLI for cron: `flask auto-assign [--now]`.

**Customer satisfaction (CSAT)** — after a resolved ticket is closed, the reporter rates the support
1–5 stars with an optional comment (once). Ratings appear on the ticket, notify the technician, and
feed the average rating on the analytics page and technician tables.

**Notifications** — database-backed notifications for assignments, comments, status and priority
changes, with unread badge (polled), notification centre and mark-as-read.

**Security** — hashed passwords, login rate limiting, session idle/absolute expiry, CSRF on every
form, RBAC + data isolation, internal-note privacy, validated uploads (type, content, size),
authorized downloads, security headers, audit log, fail-closed production configuration,
Secrets Manager integration. Details: [security checklist](docs/security_checklist.md).

**UI** — navy/cyan enterprise theme, light/dark mode, collapsible sidebar, breadcrumbs, global
search (Ctrl+K), notification dropdown, toasts, confirmation dialogs, chart skeletons, empty
states, responsive down to phone width, skip link and keyboard-visible focus.

---

## 2. Project structure

```text
CloudOps-360/
├── app/
│   ├── __init__.py            # app factory, security hooks, error handlers, CLI commands
│   ├── extensions.py          # db, migrate, login_manager, csrf
│   ├── models.py              # 12 tables (9 required + login_attempts, technician_skills, system_settings)
│   ├── auth/ tickets/ technician/ admin/ dashboard/ attachments/ main/   # blueprints
│   ├── services/
│   │   ├── permissions.py     # who may see/do what (single source of truth)
│   │   ├── workflow.py        # status transitions, assignment, priority
│   │   ├── storage.py         # local disk / Amazon EFS storage abstraction
│   │   ├── secrets.py         # Secrets Manager / env resolution (fail closed)
│   │   ├── sla.py metrics.py  # SLA engine and dashboard metrics
│   │   ├── assignment.py      # auto-assignment, technician availability
│   │   ├── settings.py        # admin-editable settings (system_settings table)
│   │   ├── audit.py notifications.py login_security.py
│   ├── templates/  static/css/  static/js/
├── migrations/                # Alembic migrations (flask db upgrade)
├── tests/                     # pytest suite
├── scripts/                   # seed data, local MySQL setup, MySQL test runner
├── infrastructure/aws/        # EC2 bootstrap, systemd, Nginx, EFS, TLS, IAM/EFS policies, RDS SQL, verification
├── docs/                      # deployment guide, diagrams, checklists
├── config.py  run.py  wsgi.py  requirements.txt  .env.example  docker-compose.yml  Dockerfile
```

---

## 3. Local setup (Windows, verified)

Prerequisites: Python 3.11 or 3.12, Git, MySQL 8.0 Server running locally (or Docker, see §4).

```powershell
git clone https://github.com/Gabriel2006galaxy/CloudOps-360.git
cd CloudOps-360
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# Creates .env (random SECRET_KEY + DB password) and the MySQL databases/user.
# You are prompted for your MySQL *root* password; it is not stored.
powershell -ExecutionPolicy Bypass -File scripts\setup_local_mysql.ps1

.venv\Scripts\flask db upgrade          # create tables via migrations
.venv\Scripts\flask seed-db             # DEVELOPMENT demo users + sample incidents
.venv\Scripts\python run.py             # http://127.0.0.1:5000
```

Linux/macOS: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`,
copy `.env.example` to `.env`, create the database and user (SQL in `scripts/setup_local_mysql.ps1`
or `infrastructure/aws/rds_mysql_setup.sql`), then `flask db upgrade && flask seed-db && python run.py`.

**Development demo accounts** (created only by `flask seed-db`; the command refuses to run in production):

| Role | Username | Password |
| :--- | :--- | :--- |
| Administrator | `admin` | `AdminPass123!` |
| Technician | `tech_sarah`, `tech_marcus` | `TechPass123!` |
| Employee | `emp_jordan`, `emp_elena` | `EmpPass123!` |

If `DATABASE_URL` is empty in development, the app falls back to a local SQLite file with a
warning (`ALLOW_SQLITE_FALLBACK`). Production never falls back.

### Run in GitHub Codespaces (quick demo, SQLite)

`.env` is never on GitHub, so a Codespace has no MySQL settings and uses the SQLite fallback.
A new Codespace sets itself up automatically (`.devcontainer/devcontainer.json` installs the
requirements and runs `flask db upgrade` + `flask seed-db`). Then:

```bash
python run.py
```
Open the **Ports** tab → port **5000** → *Open in Browser*, and sign in with the demo accounts below.

In a Codespace created **before** the devcontainer existed, run the setup once yourself:
```bash
pip install -r requirements.txt
python -m flask db upgrade
python -m flask seed-db
FLASK_HOST=0.0.0.0 python run.py
```
If the start-up log says *"The database has no tables yet"*, the two `flask` commands were not run.

## 4. Local MySQL with Docker Compose (alternative)

Add `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD` and `SECRET_KEY` to `.env`, set
`DATABASE_URL=mysql+pymysql://cloudops_user:<MYSQL_PASSWORD>@localhost:3306/cloudops360?charset=utf8mb4`, then:

```bash
docker compose up -d db                 # MySQL 8.0 on 127.0.0.1:3306
flask db upgrade && flask seed-db && python run.py
# or run everything in containers:
docker compose up --build               # app on http://127.0.0.1:5000
```
*Docker was not available on the development machine, so the compose file has not been run.*

## 5. Configuration

All settings are environment variables (see `.env.example`; production template
`infrastructure/aws/cloudops360.env.example`). Key ones:

| Variable | Purpose |
| :--- | :--- |
| `FLASK_ENV` | `development` / `production` |
| `SECRET_KEY` or `APP_SECRET_NAME` | Flask session key (env or Secrets Manager) |
| `DATABASE_URL` or `DB_SECRET_NAME` | MySQL/RDS connection (env or Secrets Manager); `DB_SSL_CA` enables verified TLS |
| `STORAGE_BACKEND`, `UPLOAD_FOLDER`, `EFS_MOUNT_POINT` | `local` directory or `efs` mount |
| `MAX_UPLOAD_BYTES` | per-file limit (default 10 MB) |
| `SESSION_COOKIE_SECURE`, `SESSION_IDLE_TIMEOUT_MINUTES`, `SESSION_ABSOLUTE_TIMEOUT_HOURS` | session security |
| `LOGIN_MAX_FAILED_PER_ACCOUNT`, `LOGIN_MAX_FAILED_PER_IP`, `LOGIN_LOCKOUT_WINDOW_MINUTES` | brute-force protection |
| `TRUSTED_PROXY_COUNT` | number of reverse proxies (Nginx = 1) |
| `ALLOW_SELF_REGISTRATION`, `SHOW_DEMO_ACCOUNTS` | feature flags (both forced off/secure in production defaults) |

Never commit `.env`. It is gitignored, and so are `*.db`, `uploads/` and `instance/`.

## 6. Database commands

```powershell
.venv\Scripts\flask db upgrade                 # apply migrations
.venv\Scripts\flask db downgrade               # revert the last migration
.venv\Scripts\flask db migrate -m "message"    # after changing models (review the generated file)
.venv\Scripts\flask db check                   # models and migrations in sync?
.venv\Scripts\flask seed-db                    # dev demo data (refused in production)
.venv\Scripts\flask seed-reference-data        # categories + SLA policies only (safe in production)
.venv\Scripts\flask create-admin               # interactive admin creation (production)
.venv\Scripts\flask storage-check              # verify every attachment file + SHA-256
.venv\Scripts\flask purge-login-attempts --days 30
```

## 7. Tests

```powershell
.venv\Scripts\python -m pytest -q                                            # in-memory SQLite (~50 s)
powershell -ExecutionPolicy Bypass -File scripts\run_tests_mysql.ps1 -q      # same suite on MySQL cloudops360_test (~2 min)
```

| File | Covers |
| :--- | :--- |
| `test_auth.py` | login/logout, hashing, lockout, IP throttling, deactivation, session expiry, open redirects, registration, password change |
| `test_rbac.py` | admin/technician page protection, ticket isolation, assignment rules, privilege-escalation attempts |
| `test_tickets.py` | creation (reference, SLA, history, notifications, audit), validation, filters/search/sort/pagination, persistence across restart |
| `test_workflow.py` | full lifecycle, invalid transitions, resolution summary, reopen window, assignment, priority/SLA recalculation, notifications |
| `test_internal_notes.py` | internal notes never reach employees; employees cannot create them |
| `test_attachments.py` | whitelist, magic bytes, size, traversal, EFS mount guard, authorized/unauthorized downloads, headers, delete, `storage-check` |
| `test_sla.py` | due dates, overdue, compliance metrics, admin SLA configuration |
| `test_dashboards.py` | dashboard numbers equal database counts, trends, empty states |
| `test_security.py` | CSRF, headers, cookies, secret exposure, fail-closed production config, SQL-injection inputs |
| `test_pages.py` | crawls every reachable page for each role (no server errors, no dead links) |
| `test_assignment.py` | auto-assignment rules (least busy, specialists, away, maximum, queue wait, run-now), settings limits 1–50, availability, CSAT ratings |

The suite ignores your local `.env` (`CLOUDOPS_SKIP_DOTENV=1`) so results do not depend on local settings.

## 8. AWS deployment (summary)

Full guide: **[docs/aws_deployment.md](docs/aws_deployment.md)**.

| Lab | What you do | Scripts |
| :--- | :--- | :--- |
| 1 | EC2 (Amazon Linux 2023) + Nginx + Gunicorn + MySQL-compatible DB on the instance | `ec2_bootstrap.sh`, `lab1_mariadb_on_ec2.sh` |
| 2 | Amazon RDS for MySQL (private) + Amazon EFS (TLS mount) | `rds_mysql_setup.sql`, `efs_mount_setup.sh` |
| 3 | IAM role, Secrets Manager, HTTPS, encryption, private networking, verification | `iam_*.json`, `efs_file_system_policy.json`, `tls_self_signed.sh`, `nginx_https.conf`, `verify_deployment.sh` |

Updates: `sudo bash /opt/cloudops360/infrastructure/aws/deploy_update.sh main`.

## 9. Troubleshooting (local)

| Problem | Fix |
| :--- | :--- |
| `Access denied for user 'cloudops_user'` | Re-run `scripts\setup_local_mysql.ps1` (it re-applies the password from `.env`) |
| `Can't connect to MySQL server on 'localhost'` | Start the service: `Start-Service MySQL80` (admin PowerShell) |
| App uses SQLite unexpectedly | `DATABASE_URL` missing in `.env`; the log prints a warning |
| "Too many failed sign-in attempts" | Wait 15 minutes, or `flask purge-login-attempts --days 0` in development |
| Session ends after 30 minutes | Intended idle timeout (`SESSION_IDLE_TIMEOUT_MINUTES`) |
| Upload rejected "content does not match" | The file's bytes do not match its extension (e.g. renamed `.exe`) |
| `flask` command not found | Use `.venv\Scripts\flask` or activate the venv |

## 10. Design decisions

* **No ticket deletion** — incidents are cancelled by closing them (audit trail preserved).
* **Technician visibility** — technicians see their own assignments plus the unassigned queue, not
  colleagues' tickets; administrators assign and reassign.
* **Reference numbers** derive from the primary key (`INC-YYYY-<id>`), so concurrent Gunicorn workers cannot collide.
* **Rate limiting in the database** (not process memory) so it holds across several EC2 instances.
* **Attachments**: bytes on EFS under generated names, metadata + SHA-256 in RDS; downloads always forced as attachments.

## 11. What still needs your action (AWS)

These require your AWS account and were **not** performed or verified from this repository:

1. Create the VPC/security groups, EC2 instance, RDS instance and EFS file system (console steps in the guide).
2. Run the bootstrap/mount scripts on EC2; create the first admin with `flask create-admin`.
3. Create the IAM role/instance profile and the two Secrets Manager secrets; switch the env file to `DB_SECRET_NAME`/`APP_SECRET_NAME`.
4. Enable HTTPS (certbot with a domain, or `tls_self_signed.sh`) and set `SESSION_COOKIE_SECURE=true`.
5. Run `verify_deployment.sh` and the CloudShell commands, and keep the output as evidence.
6. Stop/delete resources when finished (cost section of the guide).
