# CloudOps 360 — AWS Deployment Guide (EC2 · RDS · EFS · IAM · Secrets Manager · HTTPS)

> **Important — verification status.** **All three labs were run and verified live** on 2026-10-24 (own
> AWS account, `ap-south-1`): Lab 1 with `user_data_demo.sh`, Labs 2 and 3 with `cloudshell_lab2_lab3.sh`
> and `server_lab2_lab3.sh`; `verify_deployment.sh` printed PASS on every line, and CloudShell showed RDS
> and EFS encrypted, RDS not public and the security group rules. On a new account treat every security
> property as *unverified* until
> `verify_deployment.sh` and the CloudShell commands at the end of this guide confirm it on your
> resources. Creating these resources may incur charges; see [Cost control](#9-cost-control-and-cleanup).

Region used in examples: `us-east-1`. Replace `ACCOUNT_ID`, `REGION`, `FS_ID`, IDs and endpoints with yours.

---

## 0. Network (once)

1. **VPC** — use the default VPC for a lab, or create `cloudops360-vpc` (10.0.0.0/16) with
   two public subnets and two private subnets in two Availability Zones.
2. **Security groups** (VPC console → Security groups):

   | Name | Inbound | Source |
   | :--- | :--- | :--- |
   | `cloudops360-web` | HTTP 80, HTTPS 443 | 0.0.0.0/0 |
   | `cloudops360-web` | SSH 22 | **My IP** only (or skip SSH and use EC2 Instance Connect / Session Manager) |
   | `cloudops360-db` | MySQL/Aurora 3306 | security group `cloudops360-web` |
   | `cloudops360-efs` | NFS 2049 | security group `cloudops360-web` |

   Never add `0.0.0.0/0` to the database or EFS groups.

---

## 1. Lab 1 — Dynamic website on EC2

### 1.1 Launch the instance
* AMI **Amazon Linux 2023**, type `t2.micro`/`t3.micro`, public subnet, auto-assign public IP,
  security group `cloudops360-web`, a key pair (or Instance Connect).
* Storage: default 8 GB gp3 (**encrypted** checkbox on).
* IAM instance profile: none yet for Lab 1 (added in Lab 3; you can attach it later without restarting).

### 1.2 Bootstrap the application
```bash
sudo dnf install -y git
git clone https://github.com/Gabriel2006galaxy/CloudOps-360.git /tmp/cloudops360
sudo bash /tmp/cloudops360/infrastructure/aws/ec2_bootstrap.sh main
```
This installs Python 3.11, Nginx, efs-utils and the MariaDB client; creates the `cloudops`
service user; deploys to `/opt/cloudops360`; installs `cloudops360.service` (Gunicorn on
127.0.0.1:8000) and the Nginx site; and writes `/etc/cloudops360/cloudops360.env` (root:cloudops, 0640).

### 1.3 Database for Lab 1 (MariaDB on the instance, localhost only)
```bash
sudo bash /opt/cloudops360/infrastructure/aws/lab1_mariadb_on_ec2.sh
```
Creates the database and a least-privilege user with a random password, writes `DATABASE_URL`
to the env file, runs `flask db upgrade` and `flask seed-reference-data`, and starts the service.

### 1.4 First administrator (no default passwords in production)
```bash
cd /opt/cloudops360
sudo -u cloudops bash -c 'set -a; . /etc/cloudops360/cloudops360.env; set +a; .venv/bin/flask create-admin'
```
`flask seed-db` (demo accounts) is **refused** when `FLASK_ENV=production`. On a demo server,
`sudo bash infrastructure/aws/reset_demo_data.sh` puts the demo data back to its starting state with fresh
ticket times (run it shortly before a presentation; it deletes all tickets).

### 1.5 Check
```bash
curl -s http://127.0.0.1/health          # {"status":"healthy", ...}
sudo journalctl -u cloudops360 -n 50       # application logs
```
Open `http://<public-ip>/` in a browser. Plain HTTP is expected until Lab 3, so the env file keeps
`SESSION_COOKIE_SECURE=false` for now.

---

## 2. Lab 2 — Amazon RDS for MySQL and Amazon EFS

> **Fast path (own AWS account, about 20 minutes, mostly waiting).** Two scripts do everything in
> §2 and §3 for a server launched with the User data:
> 1. **AWS CloudShell** (same region as the instance):
>    `curl -fsSL https://raw.githubusercontent.com/Gabriel2006galaxy/CloudOps-360/main/infrastructure/aws/cloudshell_lab2_lab3.sh | bash`
>    — security groups, encrypted private RDS for MySQL 8.4, encrypted EFS + mount targets, IAM role
>    attached to the instance, EFS policy (TLS + role only) and the Secrets Manager secrets.
>    Safe to re-run if CloudShell times out while RDS is being created.
> 2. **On the instance** (EC2 Instance Connect), the command printed at the end of step 1:
>    `curl -fsSL .../server_lab2_lab3.sh -o /tmp/labs.sh && sudo bash /tmp/labs.sh <efs-id>`
>    — least-privilege DB user (REQUIRE SSL), settings from Secrets Manager, EFS mount, tables + demo
>    data on RDS, HTTPS, MariaDB stopped, and the `verify_deployment.sh` report.
>
> The manual steps below explain what the scripts do.

### 2.1 RDS for MySQL
RDS console → Create database:
* Engine **MySQL 8.0**, template **Free tier**, `db.t3.micro`/`db.t4g.micro`, 20 GB gp2/gp3.
* DB identifier `cloudops360-db`, master user `admin`, *Manage master credentials in AWS Secrets
  Manager* **or** a generated password you store yourself.
* Connectivity: your VPC, **Public access: No**, VPC security group **`cloudops360-db` only**.
* **Encryption: enabled** (default `aws/rds` KMS key). Backups: enabled (1–7 days).

Create the application database and user from the EC2 instance (the only allowed client):
```bash
sudo mkdir -p /etc/pki/rds
sudo curl -fsSo /etc/pki/rds/global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
# edit CHANGE_ME in the SQL file to a generated password first
mysql -h <rds-endpoint> -u admin -p --ssl-ca=/etc/pki/rds/global-bundle.pem \
      < /opt/cloudops360/infrastructure/aws/rds_mysql_setup.sql
```

Point the app at RDS — edit `/etc/cloudops360/cloudops360.env`:
```ini
# remove the Lab 1 MariaDB DATABASE_URL line, then:
DATABASE_URL=mysql+pymysql://cloudops_user:<password>@<rds-endpoint>:3306/cloudops360?charset=utf8mb4
DB_SSL_CA=/etc/pki/rds/global-bundle.pem
```
```bash
cd /opt/cloudops360
sudo -u cloudops bash -c 'set -a; . /etc/cloudops360/cloudops360.env; set +a; .venv/bin/flask db upgrade && .venv/bin/flask seed-reference-data && .venv/bin/flask create-admin'
sudo systemctl restart cloudops360
```
Migrating Lab 1 data is optional: `mysqldump cloudops360 | mysql -h <rds-endpoint> ... cloudops360`
(run before `flask db upgrade` on RDS). Then `sudo systemctl disable --now mariadb`.

### 2.2 EFS
EFS console → Create file system → *Customize*:
* Name `cloudops360-attachments`, **Encryption at rest: enabled**, lifecycle to IA after 30 days (optional).
* Network: mount targets in the **private** subnets, security group **`cloudops360-efs` only**.
* (Lab 3) File system policy: paste `infrastructure/aws/efs_file_system_policy.json` with your IDs —
  denies non-TLS clients and allows only the EC2 role.

Mount on **every** application instance:
```bash
# Lab 2 (before the IAM role exists):
sudo USE_IAM=no bash /opt/cloudops360/infrastructure/aws/efs_mount_setup.sh fs-0123456789abcdef0
# Lab 3 (role + file system policy in place):
sudo bash /opt/cloudops360/infrastructure/aws/efs_mount_setup.sh fs-0123456789abcdef0
```
Then in the env file:
```ini
STORAGE_BACKEND=efs
EFS_MOUNT_POINT=/mnt/efs
UPLOAD_FOLDER=/mnt/efs/cloudops360-attachments
```
`sudo systemctl restart cloudops360`. The mount is TLS-only (no plaintext NFS fallback), persisted
in `/etc/fstab` with `_netdev`, and the directory is `0750 cloudops:cloudops`. With
`STORAGE_BACKEND=efs` the app refuses uploads if `/mnt/efs` is not mounted.

### 2.3 Prove files are on EFS and shared
```bash
sudo ls -la /mnt/efs/cloudops360-attachments/$(date -u +%Y/%m)/
cd /opt/cloudops360 && sudo -u cloudops bash -c 'set -a; . /etc/cloudops360/cloudops360.env; set +a; .venv/bin/flask storage-check'
```
Second instance (optional): launch another instance in the same VPC/SG, run `ec2_bootstrap.sh`,
copy the same env file (`DATABASE_URL`, `SECRET_KEY`, storage settings), run `efs_mount_setup.sh`,
restart. Upload a file through instance A, download it through instance B, and compare
`curl http://<A>/health` vs `curl http://<B>/health` (`instance` differs, storage is shared).
Run `flask storage-check` on both: same rows, same checksums.

---

## 3. Lab 3 — Security and integration

### 3.1 IAM role for EC2 (no access keys anywhere)
```bash
# CloudShell (your admin credentials)
aws iam create-role --role-name CloudOps360-EC2-Role \
    --assume-role-policy-document file://infrastructure/aws/iam_ec2_trust_policy.json
# edit REGION / ACCOUNT_ID / FS_ID in the policy first
aws iam put-role-policy --role-name CloudOps360-EC2-Role --policy-name CloudOps360-least-privilege \
    --policy-document file://infrastructure/aws/iam_instance_profile_policy.json
aws iam create-instance-profile --instance-profile-name CloudOps360-EC2-Profile
aws iam add-role-to-instance-profile --instance-profile-name CloudOps360-EC2-Profile --role-name CloudOps360-EC2-Role
aws ec2 associate-iam-instance-profile --instance-id i-xxxxxxxx --iam-instance-profile Name=CloudOps360-EC2-Profile
```
The policy allows only `secretsmanager:GetSecretValue` on the two `cloudops360/prod/*` secrets and
`ClientMount`/`ClientWrite` on the one EFS file system. Optional: attach the AWS managed
`AmazonSSMManagedInstanceCore` policy to use Session Manager instead of SSH.

### 3.2 Secrets Manager
```bash
aws secretsmanager create-secret --name cloudops360/prod/db \
  --secret-string '{"username":"cloudops_user","password":"<db-password>","host":"<rds-endpoint>","port":3306,"dbname":"cloudops360"}'
aws secretsmanager create-secret --name cloudops360/prod/app \
  --secret-string "{\"SECRET_KEY\":\"$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')\"}"
```
Env file on each instance — **remove** `DATABASE_URL` and `SECRET_KEY`, add:
```ini
DB_SECRET_NAME=cloudops360/prod/db
APP_SECRET_NAME=cloudops360/prod/app
AWS_REGION=us-east-1
```
`sudo systemctl restart cloudops360`. If a secret cannot be read, the app **refuses to start**
(fail closed) and logs only the exception type, never the value. If you let RDS manage the master
secret instead, its JSON has no host: also set `DB_HOST=<rds-endpoint>`.

*Fallback when Secrets Manager is not permitted in your lab account:* keep `DATABASE_URL` and
`SECRET_KEY` in `/etc/cloudops360/cloudops360.env` (root:cloudops `0640`, outside the Git checkout).
Document this limitation in your report.

### 3.3 Encryption
| Layer | How | Where to check |
| :--- | :--- | :--- |
| Browser ↔ EC2 | HTTPS (3.4) | `verify_deployment.sh` (HSTS, redirect) |
| EC2 ↔ RDS | TLS with CA verification (`DB_SSL_CA`) + `REQUIRE SSL` on the DB user | `verify_deployment.sh` prints `Ssl_version` |
| EC2 ↔ EFS | efs-utils `tls` mount option; file system policy denies `aws:SecureTransport=false` | `verify_deployment.sh` |
| RDS at rest | KMS encryption chosen at creation | CloudShell command below |
| EFS at rest | Encryption at rest chosen at creation | CloudShell command below |
| EBS root volume | encrypted volume at launch | EC2 → Volumes |

### 3.4 HTTPS
*With a domain name* pointing at the instance:
```bash
sudo dnf install -y certbot python3-certbot-nginx
sudo cp /opt/cloudops360/infrastructure/aws/nginx_https.conf /etc/nginx/conf.d/cloudops360.conf
sudo certbot --nginx -d your.domain.example   # updates certificate paths in the config
```
*Without a domain* (lab demo, browser shows a warning):
```bash
sudo bash /opt/cloudops360/infrastructure/aws/tls_self_signed.sh
sudo cp /opt/cloudops360/infrastructure/aws/nginx_https.conf /etc/nginx/conf.d/cloudops360.conf
sudo nginx -t && sudo systemctl reload nginx
```
Then set `SESSION_COOKIE_SECURE=true` in the env file and `sudo systemctl restart cloudops360`.
HTTP now redirects to HTTPS, and the app adds `Strict-Transport-Security` on HTTPS responses.

### 3.5 Network restrictions
* RDS: *Public access = No*, inbound 3306 only from `cloudops360-web`.
* EFS: mount targets in private subnets, inbound 2049 only from `cloudops360-web`.
* SSH: your IP only, or removed entirely (Instance Connect / Session Manager).
* Gunicorn binds 127.0.0.1:8000; MariaDB (Lab 1) binds 127.0.0.1.

### 3.6 Demonstrations
Use `docs/lab_guides.md` → Lab 3 checklist: denied requests (403 + audit entries), protected
attachments, internal-note privacy, full lifecycle, SLA analytics.

---

## 4. Verify (collect evidence)
```bash
sudo bash /opt/cloudops360/infrastructure/aws/verify_deployment.sh | tee ~/verify-$(hostname).txt
```
Account-level settings, from **CloudShell**:
```bash
aws rds describe-db-instances --query 'DBInstances[].{id:DBInstanceIdentifier,encrypted:StorageEncrypted,public:PubliclyAccessible}' --output table
aws efs describe-file-systems --query 'FileSystems[].{id:FileSystemId,encrypted:Encrypted}' --output table
aws ec2 describe-security-groups --filters Name=group-name,Values='cloudops360-*' \
    --query 'SecurityGroups[].{name:GroupName,rules:IpPermissions[].{port:FromPort,cidr:IpRanges[].CidrIp,sg:UserIdGroupPairs[].GroupId}}' --output json
aws iam get-role-policy --role-name CloudOps360-EC2-Role --policy-name CloudOps360-least-privilege
```
Only claim a control is enabled once these outputs show it.

## 5. Updating the application
```bash
sudo bash /opt/cloudops360/infrastructure/aws/deploy_update.sh main
```
Pulls the branch, installs requirements, runs `flask db upgrade`, restarts Gunicorn and checks `/health`.

## 6. Operations
* Logs: `sudo journalctl -u cloudops360 -f`, `/var/log/nginx/access.log`, `/var/log/nginx/error.log`.
* Restart: `sudo systemctl restart cloudops360`; config test: `sudo nginx -t`.
* Housekeeping: `flask purge-login-attempts --days 30` (cron weekly).

## 7. Backup and recovery
* **RDS**: automated backups (retention 1–7 days) + manual snapshot before each lab demo:
  `aws rds create-db-snapshot --db-instance-identifier cloudops360-db --db-snapshot-identifier cloudops360-before-lab3`.
  Restore = *Restore snapshot* / *Restore to point in time* into a new instance, then update the
  `host` in the `cloudops360/prod/db` secret and restart.
* **EFS**: enable AWS Backup for the file system (EFS console → *Automatic backups*). Restores go to
  a recovery directory you copy back.
* **Consistency**: attachments rows reference EFS keys; after any restore run `flask storage-check`.
* **Code/config**: code is in GitHub; keep a copy of the env file (without secret values in Lab 3).

## 8. Troubleshooting
| Symptom | Check |
| :--- | :--- |
| 502 Bad Gateway | `systemctl status cloudops360`; `journalctl -u cloudops360` (often a missing secret or DB unreachable — the app fails closed) |
| `SecretResolutionError` in logs | instance profile attached? secret name/region correct? policy ARN matches secret ARN (`-*` suffix)? |
| Cannot connect to RDS | SG `cloudops360-db` source is the *web security group*; endpoint/port; `Public access = No` is expected |
| `Access denied ... using password: YES` with `REQUIRE SSL` | `DB_SSL_CA` set and bundle downloaded |
| EFS mount hangs | SG `cloudops360-efs` allows 2049 from web SG; mount target exists in the instance's AZ |
| EFS mount `access denied` | with `iam`: role attached and file system policy principal matches the role ARN |
| Upload refused "EFS is not mounted" | `mountpoint /mnt/efs`; fstab entry; `sudo mount -a` |
| Login loop over HTTP | `SESSION_COOKIE_SECURE=true` requires HTTPS — set `false` until Lab 3 |
| 413 on upload | file > 10 MB (app) or > 13 MB (Nginx `client_max_body_size`) |

## 9. Cost control and cleanup
* Free-tier eligible: 1 `t2/t3.micro` EC2, 1 `db.t3/t4g.micro` RDS single-AZ (750 h/month each, 12 months),
  20 GB RDS storage, 5 GB EFS standard. **Not** free: NAT Gateway, ALB, Multi-AZ RDS, public IPv4
  addresses (charged per hour since 2024), a second instance beyond the free hours, Secrets
  Manager (~USD 0.40/secret/month), extra snapshots.
* Stop (not terminate) EC2 and RDS between lab sessions; RDS restarts automatically after 7 days stopped.
* Set an AWS Budget alert (e.g. USD 5).
* **Cleanup order** after grading: terminate EC2 instances → delete EFS (mount targets first) →
  delete RDS (final snapshot optional, disable deletion protection) → delete secrets
  (`--force-delete-without-recovery` or 7-day window) → delete IAM instance profile and role →
  delete security groups → release Elastic IPs → delete snapshots/backups you no longer need.
