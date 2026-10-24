#!/bin/bash
# ==============================================================================
# CloudOps 360 - create the AWS resources for Lab 2 and Lab 3.
# Run in AWS CloudShell (console, top bar ">_" icon), in the region of the EC2
# instance, as the account owner:
#
#   curl -fsSL https://raw.githubusercontent.com/Gabriel2006galaxy/CloudOps-360/main/infrastructure/aws/cloudshell_lab2_lab3.sh | bash
#
# Creates (skips anything that already exists, so it is safe to run again):
#   Lab 2  security groups cloudops360-db (3306) and cloudops360-efs (2049), open
#          only to the web server's security group; Amazon RDS for MySQL 8.4
#          (private, encrypted, 1-day backups); Amazon EFS (encrypted) with mount targets.
#   Lab 3  IAM role CloudOps360-EC2-Role (read 2 secrets + mount 1 file system)
#          attached to the instance; EFS policy (TLS only, this role only);
#          Secrets Manager secrets cloudops360/prod/db and cloudops360/prod/app.
# The RDS master password is stored in Secrets Manager (cloudops360/admin/rds-master),
# which the web server can NOT read; it is shown once at the end for the server step.
# ==============================================================================
set -euo pipefail
shopt -s inherit_errexit   # errors inside $(...) stop the script too
REPO_RAW=https://raw.githubusercontent.com/Gabriel2006galaxy/CloudOps-360/main/infrastructure/aws
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-south-1}}"
export AWS_DEFAULT_REGION="$REGION" AWS_PAGER=""
INSTANCE_NAME="${INSTANCE_NAME:-cloudops360-web}"
DB_ID=cloudops360-db
DB_SUBNET_GROUP=cloudops360-db-subnets
FS_NAME=cloudops360-attachments
ROLE=CloudOps360-EC2-Role
PROFILE=CloudOps360-EC2-Profile
MASTER_SECRET=cloudops360/admin/rds-master
DB_SECRET=cloudops360/prod/db
APP_SECRET=cloudops360/prod/app

log() { echo -e "\n[cloudops360] $*"; }
die() { echo -e "\n[cloudops360] ERROR: $*" >&2; exit 1; }
rand() { python3 -c "import secrets,string; a=string.ascii_letters+string.digits; print(''.join(secrets.choice(a) for _ in range($1)))"; }
secret_exists() { aws secretsmanager describe-secret --secret-id "$1" >/dev/null 2>&1; }

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
log "Account $ACCOUNT_ID, region $REGION"

# ---------- the web server ----------
read -r INSTANCE_ID VPC_ID WEB_SG AZ <<<"$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$INSTANCE_NAME" "Name=instance-state-name,Values=running" \
    --query 'Reservations[0].Instances[0].[InstanceId,VpcId,SecurityGroups[0].GroupId,Placement.AvailabilityZone]' \
    --output text)"
[ -n "${INSTANCE_ID:-}" ] && [ "$INSTANCE_ID" != "None" ] \
    || die "No running EC2 instance named '$INSTANCE_NAME' in $REGION. Switch CloudShell to the instance's region."
log "Web server $INSTANCE_ID (security group $WEB_SG, $AZ, VPC $VPC_ID)"

# ---------- Lab 2: security groups that only admit the web server ----------
ensure_sg() {  # name description port -> prints the group id
    local id
    id=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$1" "Name=vpc-id,Values=$VPC_ID" \
        --query 'SecurityGroups[0].GroupId' --output text)
    if [ "$id" = "None" ]; then
        id=$(aws ec2 create-security-group --group-name "$1" --description "$2" --vpc-id "$VPC_ID" \
            --query GroupId --output text)
        aws ec2 authorize-security-group-ingress --group-id "$id" \
            --ip-permissions "IpProtocol=tcp,FromPort=$3,ToPort=$3,UserIdGroupPairs=[{GroupId=$WEB_SG}]" >/dev/null
    fi
    echo "$id"
}
DB_SG=$(ensure_sg cloudops360-db "CloudOps 360 RDS - MySQL only from the web servers" 3306)
EFS_SG=$(ensure_sg cloudops360-efs "CloudOps 360 EFS - NFS only from the web servers" 2049)
log "Security groups: database $DB_SG (3306), EFS $EFS_SG (2049) - source: web server group only"

SUBNETS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" --query 'Subnets[].SubnetId' --output text)

# ---------- Lab 2: Amazon RDS for MySQL ----------
if aws rds describe-db-instances --db-instance-identifier "$DB_ID" >/dev/null 2>&1; then
    log "RDS instance $DB_ID already exists"
else
    aws rds describe-db-subnet-groups --db-subnet-group-name "$DB_SUBNET_GROUP" >/dev/null 2>&1 \
        || aws rds create-db-subnet-group --db-subnet-group-name "$DB_SUBNET_GROUP" \
            --db-subnet-group-description "CloudOps 360 database subnets" --subnet-ids $SUBNETS >/dev/null
    VERSION=$(aws rds describe-db-engine-versions --engine mysql \
        --query "DBEngineVersions[?starts_with(EngineVersion,'8.4.')].EngineVersion" --output text \
        | tr '\t' '\n' | sort -V | tail -1)
    [ -n "$VERSION" ] || die "No MySQL 8.4 engine version is offered in $REGION."
    if secret_exists "$MASTER_SECRET"; then
        MASTER_PW=$(aws secretsmanager get-secret-value --secret-id "$MASTER_SECRET" --query SecretString --output text \
            | python3 -c 'import json,sys; print(json.load(sys.stdin)["password"])')
    else
        MASTER_PW=$(rand 32)
        # Saved BEFORE the database is created, so the password can never be lost
        aws secretsmanager create-secret --name "$MASTER_SECRET" \
            --description "CloudOps 360 RDS master user - setup only, the web server cannot read it" \
            --secret-string "{\"username\":\"admin\",\"password\":\"$MASTER_PW\"}" >/dev/null
    fi
    log "Creating RDS for MySQL $VERSION (db.t3.micro, 20 GB, encrypted, private) - AWS needs about 10-15 minutes"
    aws rds create-db-instance --db-instance-identifier "$DB_ID" \
        --engine mysql --engine-version "$VERSION" --db-instance-class db.t3.micro \
        --allocated-storage 20 --storage-type gp2 --storage-encrypted \
        --master-username admin --master-user-password "$MASTER_PW" \
        --db-subnet-group-name "$DB_SUBNET_GROUP" --vpc-security-group-ids "$DB_SG" \
        --availability-zone "$AZ" --no-publicly-accessible --no-multi-az \
        --backup-retention-period 1 --no-deletion-protection \
        --tags Key=Project,Value=CloudOps360 >/dev/null
fi

# ---------- Lab 2: Amazon EFS ----------
FS_ID=$(aws efs describe-file-systems --query "FileSystems[?Name=='$FS_NAME'].FileSystemId | [0]" --output text)
if [ "$FS_ID" = "None" ]; then
    FS_ID=$(aws efs create-file-system --creation-token cloudops360-attachments --encrypted \
        --performance-mode generalPurpose --throughput-mode bursting \
        --tags "Key=Name,Value=$FS_NAME" --query FileSystemId --output text)
    log "Created EFS $FS_ID (encrypted at rest)"
else
    log "EFS $FS_ID already exists"
fi
until [ "$(aws efs describe-file-systems --file-system-id "$FS_ID" --query 'FileSystems[0].LifeCycleState' --output text)" = "available" ]; do
    sleep 5
done
for subnet in $SUBNETS; do
    if [ "$(aws efs describe-mount-targets --file-system-id "$FS_ID" --query "length(MountTargets[?SubnetId=='$subnet'])" --output text)" = "0" ]; then
        aws efs create-mount-target --file-system-id "$FS_ID" --subnet-id "$subnet" --security-groups "$EFS_SG" >/dev/null 2>&1 \
            && echo "  mount target created in $subnet" || echo "  (no mount target in $subnet - another one covers its zone)"
    fi
done

# ---------- Lab 3: IAM role for the web server (no access keys anywhere) ----------
TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
    aws iam create-role --role-name "$ROLE" --assume-role-policy-document "$TRUST" \
        --description "CloudOps 360 web server: read its 2 secrets and mount its EFS, nothing else" >/dev/null
    log "Created IAM role $ROLE"
fi
fill() { sed "s/REGION/$REGION/g; s/ACCOUNT_ID/$ACCOUNT_ID/g; s/FS_ID/$FS_ID/g"; }
aws iam put-role-policy --role-name "$ROLE" --policy-name CloudOps360-least-privilege \
    --policy-document "$(curl -fsSL "$REPO_RAW/iam_instance_profile_policy.json" | fill)"
if ! aws iam get-instance-profile --instance-profile-name "$PROFILE" >/dev/null 2>&1; then
    aws iam create-instance-profile --instance-profile-name "$PROFILE" >/dev/null
    aws iam add-role-to-instance-profile --instance-profile-name "$PROFILE" --role-name "$ROLE"
fi
CURRENT=$(aws ec2 describe-iam-instance-profile-associations \
    --filters "Name=instance-id,Values=$INSTANCE_ID" "Name=state,Values=associating,associated" \
    --query 'IamInstanceProfileAssociations[0].IamInstanceProfile.Arn' --output text)
if [ "${CURRENT##*/}" != "$PROFILE" ]; then
    [ "$CURRENT" = "None" ] || die "The instance already has another IAM role ($CURRENT). Remove it in the EC2 console first."
    for attempt in 1 2 3 4 5 6 7 8; do   # a new instance profile takes a few seconds to become usable
        aws ec2 associate-iam-instance-profile --instance-id "$INSTANCE_ID" \
            --iam-instance-profile "Name=$PROFILE" >/dev/null 2>&1 && break
        [ "$attempt" = 8 ] && die "Could not attach $PROFILE to $INSTANCE_ID."
        sleep 10
    done
fi
log "IAM role $ROLE is attached to $INSTANCE_ID"

for attempt in 1 2 3 4 5 6; do   # the new role must be visible to EFS before it can be named in the policy
    aws efs put-file-system-policy --file-system-id "$FS_ID" \
        --policy "$(curl -fsSL "$REPO_RAW/efs_file_system_policy.json" | fill)" >/dev/null 2>&1 && break
    [ "$attempt" = 6 ] && die "Could not apply the EFS file system policy."
    sleep 10
done
log "EFS policy applied: TLS required, only $ROLE may mount"

# ---------- Lab 3: Secrets Manager ----------
if ! secret_exists "$APP_SECRET"; then
    aws secretsmanager create-secret --name "$APP_SECRET" --description "CloudOps 360 Flask session key" \
        --secret-string "{\"SECRET_KEY\":\"$(rand 64)\"}" >/dev/null
    log "Created secret $APP_SECRET"
fi

log "Waiting for the RDS database to be ready (checking every 30 s; usually 10-15 minutes)..."
while :; do
    STATUS=$(aws rds describe-db-instances --db-instance-identifier "$DB_ID" --query 'DBInstances[0].DBInstanceStatus' --output text)
    echo "  $(date -u +%H:%M:%S) RDS status: $STATUS"
    [ "$STATUS" = "available" ] && break
    case "$STATUS" in failed|incompatible-*|storage-full) die "RDS instance is '$STATUS'." ;; esac
    sleep 30
done
DB_HOST=$(aws rds describe-db-instances --db-instance-identifier "$DB_ID" --query 'DBInstances[0].Endpoint.Address' --output text)

if secret_exists "$DB_SECRET"; then
    NEW=$(aws secretsmanager get-secret-value --secret-id "$DB_SECRET" --query SecretString --output text \
        | python3 -c 'import json,sys; s=json.load(sys.stdin); s["host"]=sys.argv[1]; print(json.dumps(s))' "$DB_HOST")
    aws secretsmanager put-secret-value --secret-id "$DB_SECRET" --secret-string "$NEW" >/dev/null
else
    aws secretsmanager create-secret --name "$DB_SECRET" \
        --description "CloudOps 360 application database user (least privilege, TLS required)" \
        --secret-string "{\"username\":\"cloudops_user\",\"password\":\"$(rand 32)\",\"host\":\"$DB_HOST\",\"port\":3306,\"dbname\":\"cloudops360\"}" >/dev/null
    log "Created secret $DB_SECRET"
fi

MASTER_PW=$(aws secretsmanager get-secret-value --secret-id "$MASTER_SECRET" --query SecretString --output text \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["password"])')
cat <<DONE

==============================================================================
 AWS resources are ready
   RDS endpoint : $DB_HOST   (private, encrypted)
   EFS          : $FS_ID   (encrypted, TLS + role only)
   IAM role     : $ROLE   (attached to $INSTANCE_ID)
   Secrets      : $DB_SECRET, $APP_SECRET
------------------------------------------------------------------------------
 RDS master password (needed ONCE in the next step; also saved in
 Secrets Manager as $MASTER_SECRET):

   $MASTER_PW

 NEXT: open the EC2 instance -> Connect -> EC2 Instance Connect, and run:

   curl -fsSL $REPO_RAW/server_lab2_lab3.sh -o /tmp/labs.sh && sudo bash /tmp/labs.sh $FS_ID
==============================================================================
DONE
