# CloudOps 360: Secure IT Service & Incident Management Platform

> **Intelligent IT Operations. Secure by Design.**  
> *A production-ready, full-stack enterprise IT service and cloud incident operations platform engineered for the AWS Cloud Computing Lab.*

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0.3-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![MySQL](https://img.shields.io/badge/MySQL-8.0-4479A1?logo=mysql&logoColor=white)](https://www.mysql.com/)
[![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3.3-7952B3?logo=bootstrap&logoColor=white)](https://getbootstrap.com/)
[![AWS](https://img.shields.io/badge/AWS-EC2%20%7C%20RDS%20%7C%20EFS%20%7C%20Secrets%20Manager-232F3E?logo=amazon-aws&logoColor=white)](https://aws.amazon.com/)
[![Tests](https://img.shields.io/badge/pytest-20%20passed%20(100%25)-brightgreen?logo=pytest&logoColor=white)](tests/)
[![Security](https://img.shields.io/badge/Security-RBAC%20%7C%20CSRF%20%7C%20EFS%20Storage%20Isolation-success)](docs/security_checklist.md)

---

## Table of Contents
1. [Overview & Highlights](#1-overview--highlights)
2. [Fixed Technology Stack](#2-fixed-technology-stack)
3. [Project Directory Architecture](#3-project-directory-architecture)
4. [Role-Based Access Control (RBAC)](#4-role-based-access-control-rbac)
5. [Local Quickstart & Setup](#5-local-quickstart--setup)
6. [Database Migrations & Seeding](#6-database-migrations--seeding)
7. [Automated Test Suite](#7-automated-test-suite)
8. [AWS Cloud Deployment Guide (EC2 + RDS + EFS)](#8-aws-cloud-deployment-guide-ec2--rds--efs)
9. [AWS Security Controls & Governance](#9-aws-security-controls--governance)
10. [Three-Lab Demonstration Plan](#10-three-lab-demonstration-plan)

---

## 1. Overview & Highlights

**CloudOps 360** is an enterprise-grade IT Service Management (ITSM) and Cloud Incident Resolution platform modeled after modern operational command dashboards (PagerDuty, ServiceNow, Datadog). 

### Key Capabilities
- **Strict Role-Based Access Control (RBAC)**: Enforces three distinct enterprise roles (**Employee**, **Support Technician**, **Administrator**) with server-side authorization decorators and query data isolation.
- **Incident Lifecycle Management**: End-to-end incident state machine (`Open` &rarr; `Assigned` &rarr; `In Progress` &rarr; `Resolved` &rarr; `Closed`) with transition auditing and authorized reopening.
- **Amazon EFS Shared File Storage**: Abstraction layer allowing multi-instance EC2 deployments to store, share, and securely download diagnostic logs and screenshots with path-traversal prevention.
- **Amazon RDS for MySQL Persistence**: Fully relational data store managing tickets, categories, user profiles, status histories, notifications, and immutable audit logs.
- **Automated SLA Engine**: Computes priority-based response and resolution deadlines (UTC), dynamically flagging overdue incidents and calculating real-time compliance percentages.
- **Confidential Internal Technician Notes**: Allows support engineers to document root-cause hypotheses and diagnostic commands privately, completely hidden from employee views.
- **AWS Secrets Manager Integration**: Supports dynamic retrieval of production RDS credentials via EC2 IAM instance roles, eliminating hardcoded passwords.
- **Interactive Operational Dashboards**: Role-specific analytics, Chart.js telemetry (priority doughnuts, status pipelines, category distributions), notifications center, global search (`Ctrl+K`), and Dark/Light mode.

---

## 2. Fixed Technology Stack

| Layer | Component | Specification |
| :--- | :--- | :--- |
| **Frontend** | HTML5, CSS3, JavaScript ES6+ | Custom enterprise design system (Navy, Cyan, White palette), Vanilla JS interactions. |
| **Styling** | Bootstrap 5.3.3 & Icons | Responsive grid, accessible modals, collapse drawers, alert dismissals, toast notifications. |
| **Visualizations** | Chart.js 4.4.3 | Responsive doughnut and bar charts for incident volume, priority distributions, and SLA metrics. |
| **Backend** | Python Flask 3.0.3 | Application factory pattern, Flask Blueprints (`auth`, `tickets`, `dashboard`, `admin`, `technician`, `attachments`, `main`). |
| **Templating** | Jinja2 | Modular inheritance (`base.html`), custom datetime formatters, context processors. |
| **Database** | MySQL 8.0 & Amazon RDS | Flask-SQLAlchemy 3.1.1 ORM, Flask-Migrate 4.0.7 (Alembic) schema version control. |
| **Authentication** | Flask-Login & Flask-WTF | Werkzeug password hashing (Scrypt/PBKDF2), CSRF protection tokens, session cookie hardening. |
| **AWS Hosting** | Amazon EC2 Linux | Amazon Linux 2023 / Ubuntu 22.04 LTS, Gunicorn WSGI application server, Nginx reverse proxy. |
| **Shared Storage**| Amazon EFS | Network File System (NFSv4.1) POSIX mounts with TLS in-transit encryption. |
| **AWS Security** | IAM & Secrets Manager | EC2 Instance Profiles, least-privilege IAM policies, AWS KMS at-rest encryption. |
| **Testing** | pytest 8.2.2 | 20 comprehensive unit and integration tests covering auth, RBAC, uploads, SLA, and privacy. |

---

## 3. Project Directory Architecture

```text
CloudOps-360/
├── app/
│   ├── __init__.py               # Application factory, Jinja filters, context processors, CLI commands
│   ├── extensions.py             # SQLAlchemy, Flask-Migrate, LoginManager, CSRFProtect
│   ├── models.py                 # Relational schema (Users, Tickets, Categories, Comments, Attachments, etc.)
│   ├── admin/                    # Blueprint for user directory, category catalog, SLA targets, audit logs
│   ├── attachments/              # Blueprint for authorized EFS file downloads and deletion
│   ├── auth/                     # Blueprint for login, logout, registration, and user profiles
│   ├── dashboard/                # Blueprint for Employee, Technician, and Executive Admin dashboards
│   ├── main/                     # Blueprint for public landing page, health check, and notifications API
│   ├── technician/               # Blueprint for technician queue, workload, and ticket claiming
│   ├── tickets/                  # Blueprint for incident CRUD, filtering, comments, and attachments
│   ├── services/
│   │   ├── audit.py              # Enterprise audit logging service with IP & User-Agent capture
│   │   ├── notifications.py      # Database-backed in-app notification dispatcher
│   │   ├── secrets.py            # AWS Secrets Manager dynamic credential loader
│   │   ├── sla.py                # SLA target calculation, overdue detection, compliance analytics
│   │   └── storage.py            # EFS / Local filesystem storage abstraction layer
│   ├── static/
│   │   ├── css/main.css          # Premium Navy/Cyan design tokens, theme styles, card animations
│   │   └── js/
│   │       ├── charts.js         # Chart.js renderers for priority, status, and category charts
│   │       └── main.js           # Dark/Light theme, sidebar toggle, notification polling, shortcuts
│   └── templates/                # Jinja2 templates (landing, auth, tickets, dashboards, admin, errors)
├── docs/
│   ├── architecture.md           # AWS Architecture diagram (Mermaid) and component specs
│   ├── database_er.md            # Complete Database ER diagram (Mermaid) and table dictionaries
│   ├── data_flow.md              # Request & data-flow sequence diagrams (Mermaid)
│   ├── security_checklist.md     # Security verification matrix and pytest execution evidence
│   └── lab_guides.md             # Separate step-by-step Lab 1, Lab 2, and Lab 3 demonstration guides
├── infrastructure/aws/
│   ├── cloudops360.service       # Systemd unit file for Gunicorn production service
│   ├── ec2_userdata.sh           # Automated EC2 Linux instance bootstrap script
│   ├── efs_mount_setup.sh        # Amazon EFS mounting script with TLS and fstab persistence
│   ├── iam_instance_profile_policy.json # Least-privilege IAM policy for EC2 instance profile
│   ├── nginx.conf                # Nginx reverse proxy, security headers, and static caching
│   └── rds_mysql_setup.sql       # Amazon RDS MySQL initial database and user provisioning script
├── migrations/                   # Alembic schema versioning scripts (Flask-Migrate)
├── scripts/
│   └── seed_data.py              # Development and demonstration database seeder
├── tests/
│   ├── conftest.py               # Testing fixtures (app, client, runner, demo users)
│   ├── test_attachments.py       # File extension whitelist, upload limits, authorized downloads
│   ├── test_auth.py              # Login, logout, deactivated accounts, password hash validation
│   ├── test_rbac.py              # Employee isolation, admin route protection, privilege escalation prevention
│   ├── test_sla.py               # SLA target calculation, overdue detection
│   ├── test_technician_notes.py  # Internal technician note privacy verification
│   └── test_tickets.py           # Ticket CRUD, lifecycle state transitions, authorized reopening
├── .env.example                  # Environment variable template with placeholders only
├── .gitignore                    # Excludes .env, virtual environments, database binaries, uploads
├── config.py                     # Configuration classes (Development, Testing, Production)
├── docker-compose.yml            # Local MySQL 8.0 container service and optional app container
├── Dockerfile                    # Container build file for Python 3.12 application
├── pytest.ini                    # Pytest configuration settings
├── requirements.txt              # Production and development dependencies
├── run.py                        # Local development entry point
└── wsgi.py                       # Production WSGI entry point for Gunicorn
```

---

## 4. Role-Based Access Control (RBAC)

CloudOps 360 enforces strict server-side authorization across three user roles:

| Role | Operational Scope & Permissions | Restricted Operations |
| :--- | :--- | :--- |
| **Employee** | Create incidents, upload diagnostic attachments, track own tickets, view status transitions, post public comments. | **Cannot** view tickets created by other employees, **cannot** view technician internal notes, **cannot** access `/admin/*` routes. |
| **Support Technician** | Claim unassigned tickets, update incident status/priority, record resolution summaries, post public updates **and** private internal notes, manage workload queue. | **Cannot** manage system users, **cannot** modify global SLA policies, **cannot** access administrative user management. |
| **Administrator** | Full system visibility: manage users & roles, configure incident categories, customize SLA targets, inspect compliance audit logs, review system analytics. | Governed by audit logging: every role toggle, status update, and policy alteration is recorded. |

---

## 5. Local Quickstart & Setup

### Prerequisites
- Python 3.11 or 3.12
- Git
- Optional: Docker & Docker Compose (for local MySQL 8.0)

### Option A: Immediate Quickstart (Local SQLite Fallback)
The application automatically falls back to a local SQLite database (`cloudops360.db`) if no MySQL connection is configured:

```bash
# 1. Clone repository
git clone https://github.com/Gabriel2006galaxy/CloudOps-360.git
cd CloudOps-360

# 2. Create and activate Python virtual environment
python -m venv .venv

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment configuration
cp .env.example .env

# 5. Apply migrations and seed demonstration accounts
flask db upgrade
flask seed-db --no-input

# 6. Launch development server
python run.py
```
Open **`http://127.0.0.1:5000`** in your web browser.

---

### Option B: Local MySQL Setup via Docker Compose
To run against a local MySQL 8.0 instance matching Amazon RDS:

```bash
# 1. Start MySQL 8.0 container
docker compose up -d db

# 2. Update .env to connect to local MySQL
# DATABASE_URL=mysql+pymysql://cloudops_user:CloudOpsDevPassword123!@localhost:3306/cloudops360

# 3. Apply schema migrations & seed data
flask db upgrade
flask seed-db --no-input

# 4. Run application
python run.py
```

---

## 6. Database Migrations & Seeding

CloudOps 360 uses **Flask-Migrate** (Alembic) for structured database version control and an explicit seeding command:

```bash
# Apply pending migrations to database
flask db upgrade

# Generate a new migration after schema changes
flask db migrate -m "Description of changes"

# Seed reference categories, SLA policies, and realistic demo tickets
flask seed-db
```

### Pre-Configured Demonstration Accounts

| Role | Username | Password | Department | Access Level |
| :--- | :--- | :--- | :--- | :--- |
| **Administrator** | `admin` | `AdminPass123!` | Cloud Architecture & Security | System-wide analytics, user management, SLA policies, audit trail |
| **Technician** | `tech_sarah` | `TechPass123!` | Tier 2 Infrastructure Support | Workload queue, ticket claim, status updates, internal notes |
| **Technician** | `tech_marcus` | `TechPass123!` | Security & Compliance Ops | Workload queue, incident remediation, internal notes |
| **Employee** | `emp_jordan` | `EmpPass123!` | Finance & Billing Engineering | Personal service dashboard, ticket creation, attachment upload |
| **Employee** | `emp_elena` | `EmpPass123!` | Analytics & Data Pipeline | Personal service dashboard, ticket creation, attachment upload |

*Note: Default accounts and passwords are generated exclusively through explicit development seed commands and are never automatically created in production.*

---

## 7. Automated Test Suite

CloudOps 360 includes 20 comprehensive automated unit and integration tests using `pytest`:

```bash
# Run complete test suite
pytest -v

# Run specific test modules
pytest tests/test_rbac.py -v
pytest tests/test_technician_notes.py -v
pytest tests/test_attachments.py -v
```

### Verified Test Assertions
1. **Authentication**: Successful login, rejected invalid passwords, blocked deactivated accounts, secure logout.
2. **Password Security**: Password hashes are stored with cryptographic salts; plaintext passwords are never stored.
3. **RBAC Isolation**: Employees receive HTTP 403 Forbidden when attempting to view other users' tickets or administrative routes.
4. **Privilege Escalation**: Public registration and user profile updates cannot elevate role to Administrator.
5. **Technician Privacy**: Internal technician notes (`is_internal=True`) are completely filtered from Employee views.
6. **Attachment Security**: Whitelisted file extensions validated; directory traversal attacks rejected; unauthorized downloads return HTTP 403.
7. **SLA Engine**: Accurate calculation of due dates and real-time detection of overdue incidents.
8. **Ticket State Machine**: Valid status transitions enforced; authorized reopening verified.

---

## 8. AWS Cloud Deployment Guide (EC2 + RDS + EFS)

### Phase 1: Amazon EC2 Linux Instance Provisioning
1. Launch an Amazon EC2 Linux instance (`t3.micro` or `t3.small`) using Amazon Linux 2023.
2. In the **Advanced Details -> User Data** field, paste the contents of [`infrastructure/aws/ec2_userdata.sh`](infrastructure/aws/ec2_userdata.sh).
3. Associate Security Group `sg-ec2` (Inbound HTTP 80 from ALB/public, Inbound SSH 22 from admin IP).
4. Attach IAM Instance Profile `CloudOps360-EC2-Role`.

### Phase 2: Amazon RDS for MySQL Configuration
1. Create a MySQL 8.0 RDS instance in private subnets.
2. Set Security Group `sg-rds` to allow Inbound port 3306 **only from `sg-ec2`**.
3. Run the provisioning script to create database and application user:
   ```bash
   mysql -h <RDS-ENDPOINT> -u admin -p < infrastructure/aws/rds_mysql_setup.sql
   ```
4. Set the `DATABASE_URL` in `.env`:
   ```ini
   DATABASE_URL=mysql+pymysql://cloudops_user:<Password>@<RDS-ENDPOINT>:3306/cloudops360
   ```

### Phase 3: Amazon EFS Shared Storage Mounting
1. Create an Amazon EFS file system with KMS encryption enabled.
2. Create mount targets in the private subnets of your VPC with Security Group `sg-efs` (Inbound port 2049 from `sg-ec2`).
3. Run the EFS mounting helper on your EC2 instance:
   ```bash
   sudo bash infrastructure/aws/efs_mount_setup.sh <EFS-FILESYSTEM-ID> us-east-1
   ```
4. Configure `.env`:
   ```ini
   UPLOAD_FOLDER=/mnt/efs/cloudops360-attachments
   ```

### Phase 4: Nginx & Gunicorn Production Startup
```bash
# Enable and start Gunicorn service
sudo cp infrastructure/aws/cloudops360.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cloudops360

# Enable and start Nginx reverse proxy
sudo cp infrastructure/aws/nginx.conf /etc/nginx/conf.d/cloudops360.conf
sudo systemctl enable --now nginx

# Verify application health endpoint
curl http://localhost/health
```

---

## 9. AWS Security Controls & Governance

- **IAM Instance Profile**: Uses temporary security tokens automatically rotated by AWS STS. Zero permanent access keys (`AKIA...`) are stored in code or configurations.
- **AWS Secrets Manager**: Dynamically loads RDS database credentials when `AWS_SECRETS_NAME` is defined in `.env`.
- **Private Subnet Isolation**: RDS and EFS have no public IP addresses and reject all internet traffic.
- **Application Hardening**:
  - CSRF tokens validated on all state-changing HTTP requests.
  - Path-traversal sanitization on file uploads (`uuid.uuid4().hex` stored names).
  - SQLAlchemy parameterized query binding to prevent SQL injection.
  - HTTPOnly, SameSite, and Secure session cookie flags.
- **Audit Forensics**: Comprehensive audit records in the `audit_logs` table capture timestamp, actor, action code, client IP (from `X-Forwarded-For`), and user-agent string.

For full verification evidence, see the [Security Checklist](docs/security_checklist.md).

---

## 10. Three-Lab Demonstration Plan

For AWS Cloud Computing Lab evaluations, CloudOps 360 is organized into three progressive milestones:

- **[LAB 1: Dynamic Website](docs/lab_guides.md#lab-1-dynamic-website-deployment)**: Responsive UI, Flask Blueprints, authentication, local/SQLite database, ticket lifecycle, and EC2 Linux deployment.
- **[LAB 2: RDS + EFS Integration](docs/lab_guides.md#lab-2-amazon-rds--amazon-efs-integration)**: Amazon RDS MySQL migration, Amazon EFS network storage mounting, secure diagnostic file uploads, and multi-instance shared consistency.
- **[LAB 3: Security & Governance](docs/lab_guides.md#lab-3-aws-security-rbac--end-to-end-governance)**: IAM instance roles, AWS Secrets Manager integration, RBAC isolation, internal technician note privacy, SLA countdown tracking, and audit forensics.

See [docs/lab_guides.md](docs/lab_guides.md) for step-by-step presentation scripts and demonstration checklists.
