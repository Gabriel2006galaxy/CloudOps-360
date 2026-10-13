<#
.SYNOPSIS
  Runs the pytest suite against the local MySQL test database (cloudops360_test).

.DESCRIPTION
  Reads MYSQL_TEST_DATABASE_URL from .env (created by setup_local_mysql.ps1) and
  exposes it as TEST_DATABASE_URL for the duration of the run. Tables are created
  and dropped by the test fixtures; never point this at a database with real data.
  Any arguments are passed straight to pytest.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\run_tests_mysql.ps1 -q
#>
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$line = Select-String -Path (Join-Path $ProjectRoot ".env") -Pattern "^MYSQL_TEST_DATABASE_URL=(.+)$" | Select-Object -First 1
if (-not $line) { throw "MYSQL_TEST_DATABASE_URL is not set in .env (run scripts\setup_local_mysql.ps1)." }
$url = $line.Matches[0].Groups[1].Value.Trim()
if ($url -notmatch "_test") { throw "Refusing to run: MYSQL_TEST_DATABASE_URL must point at a *_test database." }

$env:TEST_DATABASE_URL = $url
try {
    & (Join-Path $ProjectRoot ".venv\Scripts\python.exe") -m pytest @args
} finally {
    Remove-Item Env:\TEST_DATABASE_URL -ErrorAction SilentlyContinue
}
