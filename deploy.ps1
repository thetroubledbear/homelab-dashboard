<#
.SYNOPSIS
    Deploy einkdash from this folder to the Proxmox LXC in one command.

.DESCRIPTION
    Zips every file here that belongs on the server, ships it to the
    Proxmox host, and runs deploy.sh there. That script installs into the
    container, compile-checks, test-renders, restarts, health-checks, and
    rolls back automatically if anything fails.

.EXAMPLE
    .\deploy.ps1
    .\deploy.ps1 -Preview          # also pull back the rendered PNG and open it
    .\deploy.ps1 -PveHost 192.168.1.232 -Ctid 200
#>

param(
    [string]$PveHost = "192.168.1.232",
    [int]$Ctid       = 102,
    [switch]$Preview,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Say  ($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok   ($m) { Write-Host "  ok $m" -ForegroundColor Green }
function Fail ($m) { Write-Host "!!  $m" -ForegroundColor Red; exit 1 }

# Anything matching these goes to the server. Add a new .py module and it
# is picked up automatically -- no edits needed here.
$patterns = @("*.py", "einkdash-server.service", "config.ini.example")

$files = @()
foreach ($p in $patterns) {
    $files += Get-ChildItem -File -Filter $p -ErrorAction SilentlyContinue
}
# preview.py and dashboard.py belong to the Waveshare build, not the server
$files = $files | Where-Object { $_.Name -notin @("preview.py", "dashboard.py", "render.py") }

if (-not $files) { Fail "no deployable files found in $PSScriptRoot" }

Say "packaging $($files.Count) files"
$files | ForEach-Object { Write-Host "     $($_.Name)" }

if ($WhatIf) { Ok "dry run - nothing sent"; exit 0 }

$zip = Join-Path $env:TEMP "einkdash.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path $files.FullName -DestinationPath $zip -Force
Ok "built $zip"

Say "uploading to $PveHost"
& scp -q $zip "root@${PveHost}:/tmp/einkdash.zip"
if ($LASTEXITCODE -ne 0) { Fail "scp of payload failed" }

& scp -q ".\deploy.sh" "root@${PveHost}:/tmp/deploy.sh"
if ($LASTEXITCODE -ne 0) { Fail "scp of deploy.sh failed" }
Ok "uploaded"

# Strip CRLF before running - PowerShell and git both like to add it, and
# /bin/bash will not forgive it.
Say "running remote deploy (container $Ctid)"
& ssh "root@${PveHost}" "sed -i 's/\r`$//' /tmp/deploy.sh && CTID=$Ctid bash /tmp/deploy.sh"
if ($LASTEXITCODE -ne 0) { Fail "remote deploy failed - see output above" }

if ($Preview) {
    $out = Join-Path $PSScriptRoot "preview.png"
    & scp -q "root@${PveHost}:/tmp/einkdash-preview.png" $out
    if ($LASTEXITCODE -eq 0) {
        Ok "preview saved to $out"
        Start-Process $out
    } else {
        Write-Host "  !! could not fetch preview" -ForegroundColor Yellow
    }
}

Write-Host ""
Ok "deployed. The Kindle picks it up on its next wake."
