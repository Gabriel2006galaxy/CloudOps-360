# CloudOps 360 — Three-Lab Implementation & Demonstration Guides

This guide provides step-by-step walkthroughs, exact commands, and presentation checklists for each session of the **AWS Cloud Computing Lab (CCLab)** project.

---

# LAB 1: Dynamic Website Deployment

### Lab 1 Objectives
1. Build and run the responsive Flask web application locally and on an Amazon EC2 Linux instance.
2. Demonstrate authentication, role routing, and persistent ticket operations (Create, List, Detail, Status Updates).
3. Prove that tickets and user sessions persist across page refreshes and server restarts.

### Lab 1 Step-by-Step Setup
1. **Launch EC2 Instance**:
   - AMI: Amazon Linux 2023 (Free-tier eligible, `t3.micro`).
   - Security Group: Allow Inbound `TCP 80` (HTTP) from `0.0.0.0/0`, `TCP 22` (SSH) from your IP.
2. **Connect via SSH & Clone Repository**:
   ```bash
   ssh -i your-key.pem ec2-user@<EC2-PUBLIC-IP>
   sudo dnf update -y
   sudo dnf install -y git python3.11 python3.11-pip nginx
   git clone https://github.com/Gabriel2006galaxy/CloudOps-360.git /var/www/cloudops-360
   cd /var/www/cloudops-360
   ```
3. **Configure Environment & Dependencies**:
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   cp .env.example .env
   # Generate secret key
   python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))" >> .env
   ```
4. **Initialize Database & Seed Demonstration Accounts**:
   ```bash
   flask db upgrade
   flask seed-db --no-input
   ```
5. **Configure Gunicorn Systemd Service & Nginx**:
   ```bash
   sudo cp infrastructure/aws/cloudops360.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now cloudops360
   sudo cp infrastructure/aws/nginx.conf /etc/nginx/conf.d/cloudops360.conf
   sudo systemctl enable --now nginx
   ```

### Lab 1 Demonstration Checklist
- [ ] Open browser to `http://<EC2-PUBLIC-IP>/` and show the branded CloudOps 360 landing page.
- [ ] Log in as Employee (`emp_jordan` / `EmpPass123!`) and show the Employee IT Service Dashboard.
- [ ] Create a new incident ticket (e.g. `INC-2026-00006`: *"EC2 Latency in us-east-1"* with Medium priority).
- [ ] Show the generated ticket reference and initial `Open` status badge.
- [ ] Log out and log in as Support Technician (`tech_sarah` / `TechPass123!`).
- [ ] Navigate to **Technician Center -> Queue & Workload** and claim the newly created ticket.
- [ ] Change the status to `In Progress` and add a comment.
- [ ] Refresh the browser and restart the service (`sudo systemctl restart cloudops360`) to prove persistence.

---

# LAB 2: Amazon RDS + Amazon EFS Integration

### Lab 2 Objectives
1. Migrate database storage from local SQLite to a managed **Amazon RDS MySQL** instance.
2. Mount **Amazon EFS** on the EC2 instance for shared diagnostic file attachments.
3. Demonstrate secure file uploads, download verification, metadata storage in RDS, and physical existence of attachments on EFS.
4. Demonstrate multi-instance shared consistency (files uploaded on Instance 1 accessible from Instance 2).

### Lab 2 Step-by-Step Setup
1. **Create Amazon RDS for MySQL**:
   - Engine: MySQL 8.0 Community Edition.
   - DB Instance Class: `db.t3.micro` (Free-tier eligible).
   - Storage: 20 GB gp3 SSD.
   - Master username: `admin`, Master password: `<YourPassword>`.
   - Security Group `sg-rds`: Allow Inbound `TCP 3306` from `sg-ec2`.
2. **Initialize RDS Database**:
   - Connect from EC2 using mysql client:
     ```bash
     mysql -h <RDS-ENDPOINT> -u admin -p < infrastructure/aws/rds_mysql_setup.sql
     ```
3. **Create Amazon EFS File System**:
   - Name: `cloudops360-attachments-efs`.
   - Performance: General Purpose.
   - Encryption: KMS Enabled.
   - Mount Targets: Create in same subnets as EC2 instances.
   - Security Group `sg-efs`: Allow Inbound `TCP 2049` (NFS) from `sg-ec2`.
4. **Mount EFS on EC2**:
   ```bash
   sudo dnf install -y amazon-efs-utils
   sudo bash infrastructure/aws/efs_mount_setup.sh <EFS-FILESYSTEM-ID> us-east-1
   ```
5. **Update EC2 `.env`**:
   ```ini
   DATABASE_URL=mysql+pymysql://cloudops_user:<YourPassword>@<RDS-ENDPOINT>:3306/cloudops360
   UPLOAD_FOLDER=/mnt/efs/cloudops360-attachments
   ```
6. **Migrate & Seed RDS**:
   ```bash
   flask db upgrade
   flask seed-db --no-input
   sudo systemctl restart cloudops360
   ```

### Lab 2 Demonstration Checklist
- [ ] Show `df -h /mnt/efs/cloudops360-attachments` proving active Amazon EFS mount on EC2.
- [ ] Open CloudOps 360 in browser, log in as `emp_jordan`, and open an incident ticket.
- [ ] Upload a screenshot or log file (`diagnostic_trace.log`).
- [ ] Show the attachment record in the web interface with sanitized metadata and size.
- [ ] In the EC2 terminal, run `ls -la /mnt/efs/cloudops360-attachments/` to display the actual encrypted UUID file stored on EFS.
- [ ] In the MySQL terminal, run `SELECT id, filename, original_filename, storage_path FROM attachments;` proving metadata is stored in RDS.
- [ ] Click **Download** in the browser to prove safe streaming with download headers.
- [ ] If 2 EC2 instances are configured, open the file download link on Instance 2 to prove both instances read the same EFS store.

---

# LAB 3: AWS Security, RBAC & End-to-End Governance

### Lab 3 Objectives
1. Configure IAM instance role (`CloudOps360-EC2-Role`) and remove all local database credentials using **AWS Secrets Manager**.
2. Configure TLS/HTTPS and verify least-privilege network security groups.
3. Demonstrate strict server-side **Role-Based Access Control (RBAC)**:
   - Denied unauthorized ticket access.
   - Confidentiality of Technician Private Internal Notes.
   - Denial of unauthorized attachment downloads.
   - Denial of unauthorized admin elevation.
4. Demonstrate real-time **SLA deadline monitoring**, overdue ticket alerting, and compliance audit trail.

### Lab 3 Step-by-Step Setup
1. **Store RDS Credentials in AWS Secrets Manager**:
   - Secret Name: `cloudops360/production/db-secret`.
   - Secret Type: Credentials for Amazon RDS database.
   - Keys: `username`, `password`, `host`, `port`, `dbname`.
2. **Attach IAM Role to EC2**:
   - Create IAM Role `CloudOps360-EC2-Role` using `infrastructure/aws/iam_instance_profile_policy.json`.
   - In AWS Console, select EC2 instance -> **Actions -> Security -> Modify IAM Role** -> select `CloudOps360-EC2-Role`.
3. **Configure Secrets Manager Resolution in `.env`**:
   ```ini
   AWS_REGION=us-east-1
   AWS_SECRETS_NAME=cloudops360/production/db-secret
   # Remove or comment out raw DATABASE_URL
   ```
4. **Verify Application Resolves DB Credentials from IAM & Secrets Manager**:
   ```bash
   sudo systemctl restart cloudops360
   sudo journalctl -u cloudops360 -n 20 --no-pager
   ```
5. **Run Automated Test Suite**:
   ```bash
   pytest -v
   ```

### Lab 3 Demonstration Checklist
- [ ] **Secrets Manager Verification**: Show EC2 logs demonstrating database URI dynamically fetched via AWS SDK without hardcoded credentials in `.env`.
- [ ] **RBAC Isolation Demo**:
  - Log in as Employee 1 (`emp_jordan`). Note reference `INC-2026-00001`.
  - Log out and log in as Employee 2 (`emp_elena`).
  - Attempt to navigate directly to `http://<IP>/tickets/INC-2026-00001`.
  - Show that CloudOps 360 blocks access with **HTTP 403 Forbidden**.
- [ ] **Internal Technician Note Privacy Demo**:
  - Log in as Technician (`tech_sarah`) and view `INC-2026-00001`.
  - Show the amber-bordered private internal note: *"[INTERNAL TECHNICIAN NOTE - CONFIDENTIAL] Root cause suspected to be unindexed SQL query..."*.
  - Log in as Employee (`emp_jordan`) and view the same ticket.
  - Prove that the internal technician note is completely absent from the Employee view.
- [ ] **SLA Engine & Overdue Detection**:
  - Log in as Administrator (`admin` / `AdminPass123!`).
  - View the **Admin Dashboard** and **SLA Policies**.
  - Show the pulsing red **SLA OVERDUE** badge on `INC-2026-00005`.
  - Show the SLA Compliance Rate calculation and breakdown charts.
- [ ] **Audit Trail Forensics**:
  - Open **Administration -> Audit Trail**.
  - Show logged audit events with timestamps, actor IDs, client IP addresses, and action codes (`AUTH_LOGIN_SUCCESS`, `TICKET_CLAIM`, `ATTACHMENT_DOWNLOAD`).
