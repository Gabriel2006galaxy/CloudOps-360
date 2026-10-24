# CloudOps 360 — Lab 1 / Lab 2 / Lab 3 Demonstration Guides

All three labs use the **same repository and code**; each lab only changes configuration and AWS
resources. Previous-lab functionality keeps working. Detailed AWS steps: `docs/aws_deployment.md`.

Prepare before every demo:
* Local: `flask seed-db` gives demo accounts (`admin`, `tech_sarah`, `tech_marcus`, `emp_jordan`, `emp_elena`).
* AWS class demo: the 2-line User data (`user_data_demo.sh`, see `docs/CHEAT_SHEET.md`) installs the
  latest code **and** seeds the demo accounts with one-click sign-in buttons.
* Real (non-demo) server: demo accounts are **not** seeded in production. Create users with
  `flask create-admin`, then add technicians and employees in *Users & Roles*.

Tick each box only after you have seen it work.

---

## Lab 1 — Dynamic website

**Goal:** responsive Flask site with authentication, roles, MySQL persistence and the ticket workflow, deployed on EC2.

Setup: `ec2_bootstrap.sh` → `lab1_mariadb_on_ec2.sh` → `flask create-admin` (aws_deployment.md §1).

| ✓ | Demonstration | How |
| :-: | :--- | :--- |
| ☐ | Site live on EC2 | Open `http://<public-ip>/` — landing page loads; `curl http://<public-ip>/health` → `healthy`, `engine: mysql` |
| ☐ | Responsive UI | Resize / phone: sidebar collapses to a menu; light/dark toggle persists |
| ☐ | Authentication | Wrong password → error; 5 wrong attempts → "Too many failed sign-in attempts" (429) |
| ☐ | Role dashboards | Sign in as admin, technician, employee → three different dashboards |
| ☐ | Create ticket | Employee: *Report Incident* → reference `INC-2026-000NN`, SLA deadline shown, automatically assigned to the least busy technician (reason in *Activity history*) |
| ☐ | Listing & filters | *My Tickets*: search, status/priority/category/date filters, sort by column, pagination |
| ☐ | Status updates | Technician (from the notification): *Start Work* → *Resolve* (summary required) → employee *Confirm & Close* → star rating |
| ☐ | Persistence | Refresh; `sudo systemctl restart cloudops360`; reboot the instance → tickets still there |
| ☐ | Data in MySQL | `mysql -u cloudops_user -p -h 127.0.0.1 cloudops360 -e "SELECT reference_id,status FROM tickets;"` |
| ☐ | Nginx + Gunicorn | `systemctl status nginx cloudops360`; `ss -ltn` shows Gunicorn only on 127.0.0.1:8000 |

---

## Lab 2 — Amazon RDS + Amazon EFS

**Goal:** move data to RDS for MySQL and attachments to EFS; metadata in RDS, bytes on EFS.

Setup: aws_deployment.md §2 (RDS → `DATABASE_URL` + `DB_SSL_CA`; EFS → `efs_mount_setup.sh`, `STORAGE_BACKEND=efs`).

| ✓ | Demonstration | How |
| :-: | :--- | :--- |
| ☐ | App runs on RDS | `/health` → database `connected`; `verify_deployment.sh` prints the RDS host resolving to a **private** IP |
| ☐ | CRUD on RDS | Create, update, comment, resolve a ticket; show rows from the instance: `mysql -h <rds-endpoint> -u cloudops_user -p --ssl-ca=/etc/pki/rds/global-bundle.pem cloudops360 -e "SELECT reference_id,status,technician_id FROM tickets ORDER BY id DESC LIMIT 5;"` |
| ☐ | RDS not public | RDS console: *Publicly accessible: No*; security group source = web SG |
| ☐ | EFS mounted with TLS | `findmnt /mnt/efs` (type `nfs4` via efs-utils, `tls` in `/etc/fstab`) |
| ☐ | Secure upload | Upload a PNG screenshot and a `.log` file to a ticket |
| ☐ | Invalid uploads rejected | Rename an `.exe` to `.png` → "content does not match"; file > 10 MB → rejected |
| ☐ | Metadata in RDS | `SELECT id,original_filename,storage_path,file_size,checksum_sha256 FROM attachments;` |
| ☐ | File on EFS | `sudo ls -l /mnt/efs/cloudops360-attachments/<YYYY>/<MM>/` shows `<uuid>.png` (no user filename) |
| ☐ | Integrity | `flask storage-check` → `N ok, 0 missing, 0 checksum mismatches` |
| ☐ | Authorized download | Creator / assigned technician / admin download works; another employee gets **403** |
| ☐ | (Optional) two instances share files | Upload via instance A, download via instance B; `/health` shows different `instance`, same files; `storage-check` OK on both |

---

## Lab 3 — Security + integration

**Goal:** IAM role, Secrets Manager, encryption, HTTPS, private networking, RBAC, audit logs, SLA tracking and analytics.

Setup: aws_deployment.md §3. Then run `verify_deployment.sh` and keep its output.

| ✓ | Demonstration | How |
| :-: | :--- | :--- |
| ☐ | IAM role, no keys | `verify_deployment.sh`: role attached, *no static AWS access keys*; show the least-privilege policy JSON |
| ☐ | Secrets Manager | env file has `DB_SECRET_NAME`/`APP_SECRET_NAME` and **no** `DATABASE_URL`/`SECRET_KEY`; app still connects |
| ☐ | Fail closed | Temporarily set a wrong `DB_SECRET_NAME` → service fails to start, log shows `SecretResolutionError` (no secret values); restore |
| ☐ | HTTPS | `https://` loads; `http://` redirects; `Strict-Transport-Security` header present; `SESSION_COOKIE_SECURE=true` |
| ☐ | TLS to RDS | `verify_deployment.sh` → `database connection encrypted: TLSv1.2/1.3` |
| ☐ | Encryption at rest | CloudShell: RDS `StorageEncrypted: true`, EFS `Encrypted: true` |
| ☐ | Private networking | Security-group rules: 3306 and 2049 only from web SG; SSH from one IP |
| ☐ | Denied: employee → other's ticket | As `employee A`, open employee B's ticket URL → **403** |
| ☐ | Denied: employee → admin pages | `/admin/users` → **403** |
| ☐ | Denied: privilege escalation | Browser dev tools: add `role=admin` to the profile form → still employee |
| ☐ | Denied: protected attachment | Copy an attachment URL, open as another employee → **403** |
| ☐ | Denied: invalid transition | Technician on someone else's ticket cannot act; resolving without summary is refused |
| ☐ | Internal notes private | Technician posts internal note → visible to staff, invisible to the employee |
| ☐ | Audit trail | *Audit Trail*: filter `TICKET_UNAUTHORIZED_ACCESS`, `ATTACHMENT_UNAUTHORIZED_DOWNLOAD`, `ACCESS_DENIED_RBAC`, `ADMIN_ROLE_CHANGE`, `AUTH_LOGIN_LOCKED`; export CSV |
| ☐ | Full lifecycle | Open → Assigned (admin assigns) → In Progress → Resolved → Closed → Reopen; status history on the ticket |
| ☐ | SLA tracking | Critical ticket shows countdown; *Overdue Incidents* list; change SLA policy with "recalculate active tickets" |
| ☐ | Analytics | Admin dashboard and *Analytics*: trend, priority, status, category, technician workload — numbers match `SELECT` counts |
| ☐ | Notifications | Assignment, comment and status change create notifications; unread badge; mark all read |

---

## Local rehearsal (before each lab)
```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\flask seed-db
.venv\Scripts\python run.py     # http://127.0.0.1:5000
```
