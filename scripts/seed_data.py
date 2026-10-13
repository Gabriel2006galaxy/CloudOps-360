"""Seed data for CloudOps 360.

* seed_reference_data(): categories + SLA policies. Creates no users; safe anywhere.
* seed_database():       reference data + DEVELOPMENT demo accounts and incidents.
                          Run explicitly with `flask seed-db`; refused in production.

Demo incidents are inserted as real database rows (with SLA targets, history,
comments and an internal note) so dashboards show genuine computed metrics.
"""
import random
from datetime import timedelta

from app.extensions import db
from app.models import (
    AuditLog, Comment, SLAPolicy, Ticket, TicketCategory, TicketPriority, TicketStatus,
    TicketStatusHistory, User, UserRole, utcnow,
)
from app.services.sla import calculate_sla_due_dates

CATEGORIES = [
    ("Cloud Infrastructure (EC2/VPC)", "Compute instances, load balancers, auto scaling and VPC networking."),
    ("Network & Connectivity", "Corporate VPN, DNS, NAT gateways and remote connectivity."),
    ("Identity & Access (IAM/SSO)", "Accounts, IAM roles, MFA, single sign-on and access requests."),
    ("Database & Storage (RDS/EFS)", "Amazon RDS MySQL, backups, Amazon EFS shared storage."),
    ("Security & Compliance", "Security groups, vulnerabilities, alerts and compliance findings."),
    ("End-User Computing", "Laptops, peripherals, email and productivity software."),
]

SLA_POLICIES = [
    (TicketPriority.CRITICAL, 1, 4, "Business-critical outage; immediate 24x7 response."),
    (TicketPriority.HIGH, 4, 12, "Major degradation with significant operational impact."),
    (TicketPriority.MEDIUM, 8, 24, "Standard incident with a workaround available."),
    (TicketPriority.LOW, 24, 72, "Minor issue, question or planned request."),
]

DEMO_USERS = [
    # username, email, full name, role, department, password (DEVELOPMENT ONLY)
    ('admin', 'admin@cloudops360.local', 'Alex Mercer', UserRole.ADMIN, 'Cloud Architecture & Security', 'AdminPass123!'),
    ('tech_sarah', 'sarah@cloudops360.local', 'Sarah Connor', UserRole.TECHNICIAN, 'Tier 2 Infrastructure Support', 'TechPass123!'),
    ('tech_marcus', 'marcus@cloudops360.local', 'Marcus Vance', UserRole.TECHNICIAN, 'Security Operations', 'TechPass123!'),
    ('emp_jordan', 'jordan@cloudops360.local', 'Jordan Hayes', UserRole.EMPLOYEE, 'Finance & Billing', 'EmpPass123!'),
    ('emp_elena', 'elena@cloudops360.local', 'Elena Rostova', UserRole.EMPLOYEE, 'Data Analytics', 'EmpPass123!'),
]

# title, description, category index, priority, final status, creator, technician, affected system, hours ago, resolve hours (None=open)
DEMO_TICKETS = [
    ("Production web tier CPU saturation and 504 errors",
     "CloudWatch alarm: web tier EC2 instances above 92% CPU. Customers receive HTTP 504 from the checkout API.",
     0, TicketPriority.CRITICAL, TicketStatus.IN_PROGRESS, 'emp_jordan', 'tech_sarah', 'ec2-prod-web-asg', 2, None),
    ("Branch office VPN tunnel fails to establish",
     "Remote office cannot complete IPsec phase 2 negotiation with the virtual private gateway since 08:00.",
     1, TicketPriority.HIGH, TicketStatus.ASSIGNED, 'emp_elena', 'tech_marcus', 'vpn-gw-branch-03', 3, None),
    ("RDS read replica lag above 180 seconds",
     "Reporting replica shows replication lag of ~245s during nightly ETL, delaying invoice generation.",
     3, TicketPriority.MEDIUM, TicketStatus.OPEN, 'emp_jordan', None, 'rds-mysql-replica-01', 1, None),
    ("Renew TLS certificate for internal API domain",
     "Certificate for the internal API expires in 10 days. Request renewal and validation.",
     4, TicketPriority.MEDIUM, TicketStatus.RESOLVED, 'emp_elena', 'tech_sarah', 'api.internal', 50, 6),
    ("Legacy S3 bucket missing public access block",
     "Compliance scan flagged a legacy archive bucket without the account-level public access block.",
     4, TicketPriority.CRITICAL, TicketStatus.IN_PROGRESS, 'emp_jordan', 'tech_marcus', 's3-legacy-archive', 30, None),
    ("Laptop cannot connect to corporate Wi-Fi",
     "After the OS update the laptop no longer authenticates to the corporate WPA2-Enterprise network.",
     5, TicketPriority.LOW, TicketStatus.CLOSED, 'emp_elena', 'tech_sarah', 'LT-0442', 200, 20),
    ("MFA device lost - need reset",
     "Employee lost their phone and cannot complete MFA for SSO. Identity verified by manager.",
     2, TicketPriority.HIGH, TicketStatus.CLOSED, 'emp_jordan', 'tech_marcus', 'sso-portal', 120, 3),
    ("EFS mount slow on analytics instance",
     "Listing the shared attachments directory takes > 20 seconds on one instance.",
     3, TicketPriority.MEDIUM, TicketStatus.RESOLVED, 'emp_elena', 'tech_sarah', 'efs-attachments', 90, 30),
    ("Request access to billing dashboard",
     "Need read-only access to the billing analytics dashboard for the quarterly review.",
     2, TicketPriority.LOW, TicketStatus.OPEN, 'emp_elena', None, 'billing-dashboard', 5, None),
    ("Security group allows SSH from 0.0.0.0/0",
     "Audit found a security group with SSH open to the internet on a staging instance.",
     4, TicketPriority.HIGH, TicketStatus.RESOLVED, 'emp_jordan', 'tech_marcus', 'sg-staging-bastion', 160, 5),
    ("Outlook keeps asking for password",
     "Desktop mail client prompts for credentials every few minutes since yesterday.",
     5, TicketPriority.LOW, TicketStatus.CLOSED, 'emp_jordan', 'tech_sarah', 'LT-0310', 300, 40),
    ("Auto scaling group not launching new instances",
     "Scaling activity fails with 'insufficient capacity' in us-east-1a during peak hours.",
     0, TicketPriority.HIGH, TicketStatus.CLOSED, 'emp_elena', 'tech_sarah', 'ec2-batch-asg', 240, 9),
]


def seed_reference_data():
    """Categories and SLA policies (idempotent)."""
    db.create_all()
    categories = {}
    for name, desc in CATEGORIES:
        cat = TicketCategory.query.filter_by(name=name).first()
        if not cat:
            cat = TicketCategory(name=name, description=desc, is_active=True)
            db.session.add(cat)
            db.session.flush()
        categories[name] = cat
    for priority, resp, resol, desc in SLA_POLICIES:
        if not SLAPolicy.query.filter_by(priority=priority).first():
            db.session.add(SLAPolicy(priority=priority, response_time_hours=resp,
                                     resolution_time_hours=resol, description=desc))
    db.session.commit()
    return [categories[name] for name, _ in CATEGORIES]


def _seed_users():
    users = {}
    for username, email, full_name, role, dept, password in DEMO_USERS:
        user = User.query.filter_by(username=username).first()
        if not user:
            user = User(username=username, email=email, full_name=full_name, role=role,
                        department=dept, is_active=True)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
        users[username] = user
    db.session.commit()
    return users


def _seed_tickets(categories, users):
    rng = random.Random(360)
    now = utcnow()
    path = [TicketStatus.OPEN, TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED, TicketStatus.CLOSED]
    for (title, desc, cat_idx, priority, final_status, creator_name, tech_name, system,
         hours_ago, resolve_hours) in DEMO_TICKETS:
        creator, tech = users[creator_name], users.get(tech_name) if tech_name else None
        created = now - timedelta(hours=hours_ago, minutes=rng.randint(0, 50))
        resp_due, resol_due = calculate_sla_due_dates(priority, created)
        ticket = Ticket(reference_id=f"SEED-{rng.getrandbits(48):x}", title=title, description=desc,
                        category_id=categories[cat_idx].id, priority=priority, status=final_status,
                        creator_id=creator.id, technician_id=tech.id if tech else None,
                        affected_system=system, department=creator.department,
                        created_at=created, updated_at=created,
                        response_due_at=resp_due, resolution_due_at=resol_due)
        db.session.add(ticket)
        db.session.flush()
        ticket.reference_id = f"INC-{created.year}-{ticket.id:05d}"

        # Replay the lifecycle so status history is consistent with the final state
        steps = path[:path.index(final_status) + 1]
        moment = created
        db.session.add(TicketStatusHistory(ticket_id=ticket.id, changed_by_id=creator.id, old_status='New',
                                           new_status=TicketStatus.OPEN, notes='Incident reported.', created_at=created))
        total = timedelta(hours=resolve_hours) if resolve_hours else timedelta(hours=hours_ago) * 0.6
        for prev, nxt in zip(steps, steps[1:]):
            if nxt == TicketStatus.ASSIGNED:
                moment = created + timedelta(minutes=rng.randint(10, 40))
                actor, note = users['admin'], f"Assigned to {tech.full_name}."
            elif nxt == TicketStatus.IN_PROGRESS:
                moment = created + total * 0.2
                actor, note = tech, 'Investigation started.'
                ticket.first_responded_at = moment
            elif nxt == TicketStatus.RESOLVED:
                moment = created + total
                actor, note = tech, 'Root cause identified and fix applied.'
                ticket.resolved_at = moment
                ticket.resolution_summary = (f"Resolved by {tech.full_name}: root cause identified on {system}, "
                                             "corrective change applied and verified with the reporter.")
            else:  # CLOSED
                moment = moment + timedelta(hours=rng.randint(2, 20))
                actor, note = creator, 'Resolution confirmed by reporter.'
                ticket.closed_at = moment
            db.session.add(TicketStatusHistory(ticket_id=ticket.id, changed_by_id=actor.id, old_status=prev,
                                               new_status=nxt, notes=note, created_at=moment))
        ticket.updated_at = moment

        if tech and final_status != TicketStatus.ASSIGNED:
            db.session.add(Comment(ticket_id=ticket.id, user_id=tech.id, is_internal=False,
                                   content='Acknowledged - investigating now. I will post updates here.',
                                   created_at=created + total * 0.2))
            db.session.add(Comment(ticket_id=ticket.id, user_id=tech.id, is_internal=True,
                                   content=f"[Internal] Checked CloudWatch metrics and recent change log for {system}. "
                                           "Suspect a configuration drift from last deploy; do not share until confirmed.",
                                   created_at=created + total * 0.3))
    db.session.add(AuditLog(user_id=users['admin'].id, action='SYSTEM_SEED_INITIALIZED', entity_type='System',
                            entity_id='seed', details='Development seed data created via flask seed-db', created_at=now))
    db.session.commit()


def seed_database(with_demo_tickets=True):
    """Reference data + development demo users (+ demo incidents when the table is empty)."""
    categories = seed_reference_data()
    users = _seed_users()
    if with_demo_tickets and Ticket.query.count() == 0:
        _seed_tickets(categories, users)
        print(f"[Seed] {len(DEMO_TICKETS)} demo incidents created.")
    else:
        print("[Seed] Tickets already present (or skipped); reference data and users verified.")

    print("\n=============================================================")
    print(" DEVELOPMENT demo accounts (never use these in production):")
    print("-------------------------------------------------------------")
    for username, _, _, role, _, password in DEMO_USERS:
        print(f"  {role:<11} {username:<12} / {password}")
    print("=============================================================\n")
