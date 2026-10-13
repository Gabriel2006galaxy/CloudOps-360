from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models import (
    User, UserRole, TicketCategory, SLAPolicy,
    Ticket, TicketStatus, TicketPriority, Comment,
    TicketStatusHistory, AuditLog, Notification
)
from app.services.sla import calculate_sla_due_dates


def seed_database():
    """Seeds baseline reference data, demo users, realistic incident tickets, and SLA targets."""
    print("[Seed] Initializing database tables...")
    db.create_all()

    # 1. Seed Categories
    categories_data = [
        ("Cloud Infrastructure (AWS EC2/S3/VPC)", "Issues regarding compute instances, elastic load balancers, auto-scaling and VPCs."),
        ("Network & Connectivity (VPN/DNS)", "Corporate VPN connections, Route53, NAT Gateways, Direct Connect."),
        ("Identity & Access (IAM/SSO)", "IAM roles, permission boundaries, single sign-on, and credential rotators."),
        ("Database & Storage (RDS/EFS)", "Amazon RDS Aurora/MySQL engine, backups, read replicas, and Amazon EFS shared mounts."),
        ("Security & Compliance", "Security groups, AWS WAF, GuardDuty alerts, and vulnerability remediation."),
        ("Software & DevOps Tooling", "CI/CD pipelines, Docker environments, and internal service management tools.")
    ]

    category_map = {}
    for name, desc in categories_data:
        cat = TicketCategory.query.filter_by(name=name).first()
        if not cat:
            cat = TicketCategory(name=name, description=desc, is_active=True)
            db.session.add(cat)
            db.session.flush()
        category_map[name] = cat

    # 2. Seed SLA Policies
    sla_data = [
        (TicketPriority.CRITICAL, 1, 4, "Critical business service disruption requiring immediate 24x7 resolution."),
        (TicketPriority.HIGH, 4, 12, "Major feature impaired or system degradation with significant operational impact."),
        (TicketPriority.MEDIUM, 8, 24, "Standard IT service request or moderate issue with operational workaround."),
        (TicketPriority.LOW, 24, 72, "Minor cosmetic inquiry, non-urgent maintenance, or planned provisioning.")
    ]

    for priority, resp_h, resol_h, desc in sla_data:
        policy = SLAPolicy.query.filter_by(priority=priority).first()
        if not policy:
            policy = SLAPolicy(
                priority=priority,
                response_time_hours=resp_h,
                resolution_time_hours=resol_h,
                description=desc
            )
            db.session.add(policy)

    db.session.commit()

    # 3. Seed Demo Users
    users_data = [
        {
            'username': 'admin',
            'email': 'admin@cloudops360.internal',
            'full_name': 'Alex Mercer',
            'role': UserRole.ADMIN,
            'department': 'Cloud Architecture & Security',
            'password': 'AdminPass123!'
        },
        {
            'username': 'tech_sarah',
            'email': 'tech.sarah@cloudops360.internal',
            'full_name': 'Sarah Connor',
            'role': UserRole.TECHNICIAN,
            'department': 'Tier 2 Cloud Infrastructure Support',
            'password': 'TechPass123!'
        },
        {
            'username': 'tech_marcus',
            'email': 'tech.marcus@cloudops360.internal',
            'full_name': 'Marcus Vance',
            'role': UserRole.TECHNICIAN,
            'department': 'Security & Compliance Operations',
            'password': 'TechPass123!'
        },
        {
            'username': 'emp_jordan',
            'email': 'emp.jordan@cloudops360.internal',
            'full_name': 'Jordan Hayes',
            'role': UserRole.EMPLOYEE,
            'department': 'Finance & Billing Engineering',
            'password': 'EmpPass123!'
        },
        {
            'username': 'emp_elena',
            'email': 'emp.elena@cloudops360.internal',
            'full_name': 'Elena Rostova',
            'role': UserRole.EMPLOYEE,
            'department': 'Analytics & Data Pipeline',
            'password': 'EmpPass123!'
        }
    ]

    user_map = {}
    for udata in users_data:
        user = User.query.filter_by(username=udata['username']).first()
        if not user:
            user = User(
                username=udata['username'],
                email=udata['email'],
                full_name=udata['full_name'],
                role=udata['role'],
                department=udata['department'],
                is_active=True
            )
            user.set_password(udata['password'])
            db.session.add(user)
            db.session.flush()
        user_map[udata['username']] = user

    db.session.commit()

    # 4. Seed Realistic Incident Tickets
    now = datetime.now(timezone.utc)
    
    # Check if tickets already exist
    if Ticket.query.count() == 0:
        tickets_info = [
            {
                'ref': 'INC-2026-00001',
                'title': 'Production EC2 Cluster CPU Throttling and Latency Spike',
                'description': 'Automated CloudWatch alarm triggered. EC2 instances in us-east-1a web tier experiencing >92% sustained CPU utilization. HTTP 504 gateway timeouts observed across client endpoints.',
                'cat': 'Cloud Infrastructure (AWS EC2/S3/VPC)',
                'priority': TicketPriority.CRITICAL,
                'status': TicketStatus.IN_PROGRESS,
                'creator': user_map['emp_jordan'],
                'tech': user_map['tech_sarah'],
                'system': 'aws-ec2-prod-web-asg',
                'dept': 'Finance & Billing Engineering',
                'created_offset_h': 2,
                'resolved': False
            },
            {
                'ref': 'INC-2026-00002',
                'title': 'Corporate IPsec VPN Tunnel Handshake Failures',
                'description': 'Remote branch offices unable to establish Phase 2 IKE Security Associations with AWS Virtual Private Gateway. Border routers failing traffic forwarding.',
                'cat': 'Network & Connectivity (VPN/DNS)',
                'priority': TicketPriority.HIGH,
                'status': TicketStatus.ASSIGNED,
                'creator': user_map['emp_elena'],
                'tech': user_map['tech_marcus'],
                'system': 'vpn-gw-vpg-03918a',
                'dept': 'Analytics & Data Pipeline',
                'created_offset_h': 3,
                'resolved': False
            },
            {
                'ref': 'INC-2026-00003',
                'title': 'Amazon RDS MySQL Replication Lag Exceeding 180s',
                'description': 'Reporting replica db-analytics-ro-1 shows seconds_behind_master of 245 seconds during heavy batch ETL query processing. Impacting financial billing generation.',
                'cat': 'Database & Storage (RDS/EFS)',
                'priority': TicketPriority.MEDIUM,
                'status': TicketStatus.OPEN,
                'creator': user_map['emp_jordan'],
                'tech': None,
                'system': 'rds-mysql-prod-replica-01',
                'dept': 'Finance & Billing Engineering',
                'created_offset_h': 1,
                'resolved': False
            },
            {
                'ref': 'INC-2026-00004',
                'title': 'SSL/TLS Certificate Renewal for API Gateway Domains',
                'description': 'Annual TLS wildcard certificate renewal verification across Route53 and ACM endpoints. Verification tested and completed.',
                'cat': 'Security & Compliance',
                'priority': TicketPriority.MEDIUM,
                'status': TicketStatus.RESOLVED,
                'creator': user_map['emp_elena'],
                'tech': user_map['tech_sarah'],
                'system': 'api.cloudops360.internal',
                'dept': 'Analytics & Data Pipeline',
                'created_offset_h': 48,
                'resolved': True,
                'resolution_summary': 'Successfully renewed via AWS Certificate Manager (ACM) DNS validation. Validated across CloudFront distributions with zero downtime.'
            },
            {
                'ref': 'INC-2026-00005',
                'title': 'Legacy S3 Bucket Public Access Block Audit Remediation',
                'description': 'Automated compliance scan flagged an unencrypted legacy archive bucket missing the S3 Account Public Access Block. Needs emergency hardening.',
                'cat': 'Security & Compliance',
                'priority': TicketPriority.CRITICAL,
                'status': TicketStatus.IN_PROGRESS,
                'creator': user_map['emp_jordan'],
                'tech': user_map['tech_marcus'],
                'system': 's3-legacy-financial-archive-bucket',
                'dept': 'Finance & Billing Engineering',
                'created_offset_h': 36,  # 36h ago -> Resolution SLA is 4h -> This ticket is OVERDUE!
                'resolved': False
            }
        ]

        for tdata in tickets_info:
            created_at = now - timedelta(hours=tdata['created_offset_h'])
            resp_due, resol_due = calculate_sla_due_dates(tdata['priority'], created_at)

            ticket = Ticket(
                reference_id=tdata['ref'],
                title=tdata['title'],
                description=tdata['description'],
                category_id=category_map[tdata['cat']].id,
                priority=tdata['priority'],
                status=tdata['status'],
                creator_id=tdata['creator'].id,
                technician_id=tdata['tech'].id if tdata['tech'] else None,
                affected_system=tdata['system'],
                department=tdata['dept'],
                created_at=created_at,
                updated_at=created_at + timedelta(minutes=15),
                response_due_at=resp_due,
                resolution_due_at=resol_due,
                first_responded_at=created_at + timedelta(minutes=20) if tdata['status'] != TicketStatus.OPEN else None
            )

            if tdata['resolved']:
                ticket.resolved_at = created_at + timedelta(hours=6)
                ticket.resolution_summary = tdata.get('resolution_summary')

            db.session.add(ticket)
            db.session.flush()

            # Add initial status history
            hist1 = TicketStatusHistory(
                ticket_id=ticket.id,
                changed_by_id=tdata['creator'].id,
                old_status='None',
                new_status=TicketStatus.OPEN,
                notes='Incident reported.',
                created_at=created_at
            )
            db.session.add(hist1)

            if tdata['tech']:
                hist2 = TicketStatusHistory(
                    ticket_id=ticket.id,
                    changed_by_id=user_map['admin'].id,
                    old_status=TicketStatus.OPEN,
                    new_status=ticket.status,
                    notes=f"Assigned to technician {tdata['tech'].full_name}.",
                    created_at=created_at + timedelta(minutes=10)
                )
                db.session.add(hist2)

            # Comments on Ticket 1 (including internal note test)
            if tdata['ref'] == 'INC-2026-00001':
                c1 = Comment(
                    ticket_id=ticket.id,
                    user_id=user_map['emp_jordan'].id,
                    content="CloudWatch graph shows request volume doubled within 15 minutes. Seeing intermittent 504 gateway timeout errors on checkout API.",
                    is_internal=False,
                    created_at=created_at + timedelta(minutes=10)
                )
                c2 = Comment(
                    ticket_id=ticket.id,
                    user_id=user_map['tech_sarah'].id,
                    content="Incident acknowledged. Reviewing Auto Scaling Group target tracking metrics and CloudWatch access logs now.",
                    is_internal=False,
                    created_at=created_at + timedelta(minutes=25)
                )
                # CRITICAL INTERNAL NOTE FOR TESTING RBAC
                c3_internal = Comment(
                    ticket_id=ticket.id,
                    user_id=user_map['tech_sarah'].id,
                    content="[INTERNAL TECHNICIAN NOTE - CONFIDENTIAL] Root cause suspected to be unindexed SQL query in release v2.4.1 hammering MySQL thread pool. Scaling ASG to 8 instances as temporary cushion while DBA prepares hotfix index.",
                    is_internal=True,
                    created_at=created_at + timedelta(minutes=30)
                )
                db.session.add_all([c1, c2, c3_internal])

        # Baseline audit logs
        log1 = AuditLog(
            user_id=user_map['admin'].id,
            action='SYSTEM_SEED_INITIALIZED',
            entity_type='System',
            entity_id='1',
            details='CloudOps 360 baseline schema, categories, SLA policies, and seed users initialized.',
            ip_address='127.0.0.1',
            created_at=now - timedelta(hours=50)
        )
        db.session.add(log1)
        db.session.commit()
        print("[Seed] Realistic incident tickets and comments populated successfully.")
    else:
        print("[Seed] Existing tickets found. Seed reference data confirmed.")

    print("\n=======================================================")
    print(" CloudOps 360 Demonstration Accounts Initialized:")
    print("-------------------------------------------------------")
    print(" Administrator: admin / AdminPass123!")
    print(" Technician:    tech_sarah / TechPass123!")
    print(" Technician:    tech_marcus / TechPass123!")
    print(" Employee:      emp_jordan / EmpPass123!")
    print(" Employee:      emp_elena / EmpPass123!")
    print("=======================================================\n")
