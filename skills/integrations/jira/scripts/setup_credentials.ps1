#Requires -Version 5.1
<#
.SYNOPSIS
    One-time credential capture for the Jira skill (Windows).
.DESCRIPTION
    Writes to ~\.config\jira\credentials.env.
    The API token is never echoed, logged, or passed on the command line.

    This script merges Jira keys into the existing file without touching
    other keys.

    Supports both Atlassian Cloud (*.atlassian.net) and Data Center.
      - Cloud auth:  Basic Auth (email + API token from id.atlassian.com)
      - DC auth:     Bearer PAT (Personal Access Token from Jira profile)
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- Config paths ------------------------------------------------------------

$ConfigDir = if ($env:XDG_CONFIG_HOME) {
    Join-Path $env:XDG_CONFIG_HOME 'jira'
} else {
    Join-Path (Join-Path $HOME '.config') 'jira'
}
$ConfigFile = Join-Path $ConfigDir 'credentials.env'

if (-not (Test-Path $ConfigDir)) {
    New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
}

# --- Collect base URL --------------------------------------------------------

Write-Host 'Jira base URL:'
Write-Host '  - Cloud example:       https://your-site.atlassian.net'
Write-Host '  - Data Center example: https://jira.corp.example.com'
$BaseUrl = (Read-Host -Prompt '>').Trim().TrimEnd('/')

if (-not $BaseUrl) {
    Write-Error 'base URL is required'
    exit 1
}
if ($BaseUrl -notmatch '^https?://') {
    Write-Error 'base URL must start with http:// or https://'
    exit 1
}

# --- Detect flavor -----------------------------------------------------------

$Host_ = ([Uri]$BaseUrl).Host.ToLower()
$Flavor = 'datacenter'
$UserEmail = ''

if ($Host_ -like '*.atlassian.net') {
    $Flavor = 'cloud'
    Write-Host "detected Atlassian Cloud ($Host_)"
    $UserEmail = (Read-Host -Prompt 'Atlassian account email').Trim()
    if (-not $UserEmail) {
        Write-Error 'email is required for Cloud auth'
        exit 1
    }
    $TokenPrompt = 'API token from https://id.atlassian.com/manage-profile/security/api-tokens'
} else {
    Write-Host "detected Data Center / Server ($Host_)"
    $TokenPrompt = 'Personal Access Token from Jira profile'
}

# --- Collect token (masked) --------------------------------------------------

$SecureToken = Read-Host -Prompt $TokenPrompt -AsSecureString
$BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureToken)
try {
    $ApiToken = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
} finally {
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)
}

if (-not $ApiToken) {
    Write-Error 'API token is required'
    exit 1
}

# --- Write credentials file --------------------------------------------------
# Preserve any non-JIRA_* lines from an existing file.

$JiraKeys = @('JIRA_BASE_URL', 'JIRA_USER_EMAIL', 'JIRA_API_TOKEN', 'JIRA_FLAVOR')
$Existing = @()
if (Test-Path $ConfigFile) {
    $Existing = Get-Content $ConfigFile | Where-Object {
        $line = $_
        -not ($JiraKeys | Where-Object { $line -match "^$_=" })
    }
}

$NewLines = @(
    "JIRA_BASE_URL=$BaseUrl",
    "JIRA_FLAVOR=$Flavor",
    "JIRA_USER_EMAIL=$UserEmail",
    "JIRA_API_TOKEN=$ApiToken"
)

$AllLines = @($Existing) + $NewLines

# Write to a temp file first, then move (atomic-ish on Windows).
$TmpFile = Join-Path $ConfigDir ('.credentials.' + [System.IO.Path]::GetRandomFileName())
try {
    $AllLines | Set-Content -Path $TmpFile -Encoding UTF8 -NoNewline:$false

    # Restrict ACL: current user only, remove inheritance.
    $Acl = Get-Acl $TmpFile
    $Acl.SetAccessRuleProtection($true, $false)
    $Acl.Access | ForEach-Object { $Acl.RemoveAccessRule($_) } | Out-Null
    $Rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
        'FullControl',
        'Allow'
    )
    $Acl.AddAccessRule($Rule)
    Set-Acl -Path $TmpFile -AclObject $Acl

    Move-Item -Path $TmpFile -Destination $ConfigFile -Force
} catch {
    if (Test-Path $TmpFile) { Remove-Item $TmpFile -Force }
    throw
}

# Clear the token from memory.
Remove-Variable -Name ApiToken -ErrorAction SilentlyContinue

Write-Host "Wrote credentials to $ConfigFile (restricted to current user)."
Write-Host 'Verify connectivity with: python scripts/jira.py check'
