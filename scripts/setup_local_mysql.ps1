<#
.SYNOPSIS
  Creates the local CloudOps 360 MySQL databases and application user (Windows).

.DESCRIPTION
  1. Creates .env from .env.example if it does not exist, generating a random
     SECRET_KEY and a random password for the 'cloudops_user' MySQL account.
  2. Connects to your local MySQL server as root (you are prompted for the root
     password by the mysql client - it is never stored) and creates:
       - database cloudops360       (application)
       - database cloudops360_test  (optional MySQL test run)
       - user cloudops_user with privileges on those two databases only.

  Mirrors the production layout: the app never uses the MySQL root account.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup_local_mysql.ps1
#>
param(
    [string]$MysqlExe = "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe",
    [string]$RootUser = "root",
    [string]$DbHost = "localhost",
    [int]$Port = 3306
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $ProjectRoot ".env"
$ExampleFile = Join-Path $ProjectRoot ".env.example"

function New-RandomToken([int]$Length) {
    $chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789".ToCharArray()
    $bytes = New-Object byte[] $Length
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

if (-not (Test-Path $MysqlExe)) {
    $found = Get-Command mysql -ErrorAction SilentlyContinue
    if ($found) { $MysqlExe = $found.Source } else { throw "mysql.exe not found. Pass -MysqlExe <path>." }
}

# ---- 1. .env with generated secrets (gitignored) ----
if (-not (Test-Path $EnvFile)) {
    $dbPassword = New-RandomToken 24
    $secretKey = New-RandomToken 48
    $content = Get-Content $ExampleFile -Raw
    $content = $content -replace "(?m)^SECRET_KEY=.*$", "SECRET_KEY=$secretKey"
    $content = $content -replace "(?m)^DATABASE_URL=.*$", "DATABASE_URL=mysql+pymysql://cloudops_user:$dbPassword@${DbHost}:$Port/cloudops360?charset=utf8mb4"
    $content = $content -replace "(?m)^#?\s*MYSQL_TEST_DATABASE_URL=.*$", "MYSQL_TEST_DATABASE_URL=mysql+pymysql://cloudops_user:$dbPassword@${DbHost}:$Port/cloudops360_test?charset=utf8mb4"
    [System.IO.File]::WriteAllText($EnvFile, $content, (New-Object System.Text.UTF8Encoding $false))
    Write-Host "[setup] Created .env with a generated SECRET_KEY and database password." -ForegroundColor Green
} else {
    Write-Host "[setup] Using existing .env" -ForegroundColor Yellow
}

# ---- 2. Read the app credentials back from .env ----
$dbUrlLine = Select-String -Path $EnvFile -Pattern "^DATABASE_URL=mysql\+pymysql://([^:]+):([^@]+)@" | Select-Object -First 1
if (-not $dbUrlLine) { throw "DATABASE_URL in .env must be a mysql+pymysql:// URL." }
$appUser = $dbUrlLine.Matches[0].Groups[1].Value
$appPassword = $dbUrlLine.Matches[0].Groups[2].Value

$sql = @"
CREATE DATABASE IF NOT EXISTS cloudops360 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS cloudops360_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$appUser'@'localhost' IDENTIFIED BY '$appPassword';
CREATE USER IF NOT EXISTS '$appUser'@'127.0.0.1' IDENTIFIED BY '$appPassword';
ALTER USER '$appUser'@'localhost' IDENTIFIED BY '$appPassword';
ALTER USER '$appUser'@'127.0.0.1' IDENTIFIED BY '$appPassword';
GRANT ALL PRIVILEGES ON cloudops360.* TO '$appUser'@'localhost', '$appUser'@'127.0.0.1';
GRANT ALL PRIVILEGES ON cloudops360_test.* TO '$appUser'@'localhost', '$appUser'@'127.0.0.1';
FLUSH PRIVILEGES;
SELECT 'cloudops360 databases and user are ready' AS status;
"@

Write-Host "[setup] Connecting to MySQL as '$RootUser'. Enter the MySQL root password when prompted." -ForegroundColor Cyan
$sql | & $MysqlExe -u $RootUser -p -h 127.0.0.1 -P $Port
if ($LASTEXITCODE -ne 0) { throw "mysql exited with code $LASTEXITCODE" }

Write-Host ""
Write-Host "[setup] Done. Next steps:" -ForegroundColor Green
Write-Host "  .venv\Scripts\flask db upgrade"
Write-Host "  .venv\Scripts\flask seed-db"
Write-Host "  .venv\Scripts\python run.py"
