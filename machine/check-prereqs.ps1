[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$script:Failures = 0

function Write-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail)
    if ($Passed) { Write-Output "OK   $Name - $Detail" }
    else { Write-Output "FAIL $Name - $Detail"; $script:Failures++ }
}

function Test-CommandVersion {
    param([string]$Name, [string]$Argument, [version]$MinimumVersion)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) { Write-Check $Name $false 'Not found in PATH; install it and open a new PowerShell.'; return }
    try {
        $text = (& $command.Source $Argument 2>&1 | Select-Object -First 1).ToString()
        $match = [regex]::Match($text, '\d+(?:\.\d+){1,3}')
        if (-not $match.Success) { Write-Check $Name $false 'Could not read version; check installation.'; return }
        $actual = [version]$match.Value
        $ok = -not $MinimumVersion -or $actual -ge $MinimumVersion
        $requirement = if ($MinimumVersion) { " (need >= $MinimumVersion)" } else { '' }
        Write-Check $Name $ok "$actual$requirement"
    }
    catch { Write-Check $Name $false 'Command failed; check installation and PATH.' }
}

function Test-FileSetting {
    param([string]$Name, [string]$EnvironmentName, [string]$DefaultCommand, [switch]$Optional)
    $path = [Environment]::GetEnvironmentVariable($EnvironmentName)
    if (-not $path) {
        $found = Get-Command $DefaultCommand -ErrorAction SilentlyContinue
        if ($found) { Write-Check $Name $true "Found $DefaultCommand in PATH; set $EnvironmentName for a custom location." }
        elseif ($Optional) { Write-Output "SKIP $Name - optional; needed only if Remotion cannot find Chrome." }
        else { Write-Check $Name $false "Not found; set $EnvironmentName or add $DefaultCommand to PATH." }
        return
    }
    if (Test-Path -LiteralPath $path -PathType Leaf) { Write-Check $Name $true "$EnvironmentName points to an existing file." }
    else { Write-Check $Name $false "$EnvironmentName is set but the file does not exist; fix the path." }
}

function Test-DirectorySetting {
    param([string]$EnvironmentName)
    $path = [Environment]::GetEnvironmentVariable($EnvironmentName)
    if ($path -and (Test-Path -LiteralPath $path -PathType Container)) { Write-Check $EnvironmentName $true 'Directory exists.' }
    else { Write-Check $EnvironmentName $false 'Missing or not a directory; check cache location.' }
}

function Test-SecretPresence {
    param([string]$Name)
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrEmpty($value)) { Write-Output "FAIL SECRET $Name - MISSING"; $script:Failures++ }
    else { Write-Output "OK   SECRET $Name - OK" }
}

Write-Output '=== ai-radar machine prerequisites (read-only) ==='
Write-Check 'Windows' ($env:OS -eq 'Windows_NT') 'This checker targets Windows.'
Test-CommandVersion 'git' '--version'
Test-CommandVersion 'python' '--version' ([version]'3.11')
Test-CommandVersion 'node' '--version' ([version]'18.0')
Test-FileSetting 'FFmpeg' 'FFMPEG_PATH' 'ffmpeg'
$omnivoicePython = [Environment]::GetEnvironmentVariable('OMNIVOICE_PYTHON')
if ($omnivoicePython -and (Test-Path -LiteralPath $omnivoicePython -PathType Leaf)) { Write-Check 'OMNIVOICE_PYTHON' $true 'Python executable exists.' }
else { Write-Check 'OMNIVOICE_PYTHON' $false 'Missing or file not found; set the venv path described in docs/may-rieng.md.' }
Test-DirectorySetting 'OMNIVOICE_CACHE_DIR'
Test-FileSetting 'Chrome for Remotion (optional)' 'CHROME_PATH' 'chrome' -Optional

$dnsResult = $false
try { $null = Resolve-DnsName -Name 'reddit.com' -Server '1.1.1.1' -DnsOnly -ErrorAction Stop; $dnsResult = $true }
catch { $dnsResult = $false }
Write-Check 'DNS reddit.com via 1.1.1.1' $dnsResult 'Direct DNS query; on FAIL check firewall, VPN, and DNS policy.'

foreach ($name in @('YOUTUBE_API_KEY', 'GEMINI_API_KEY', 'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_AI_API_TOKEN')) { Test-SecretPresence $name }
$confirmed = [Environment]::GetEnvironmentVariable('RADAR_GEMINI_FREE_TIER_CONFIRMED') -eq '1'
Write-Check 'RADAR_GEMINI_FREE_TIER_CONFIRMED' $confirmed 'Only needed for Gemini; captain must verify free-tier billing before setting to 1.'

Write-Output 'NOTE Manually verify Task Scheduler, app sign-ins, Antigravity overages, sleep/restart after power loss, and secret-intake. This checker does not access accounts or change the machine.'
Write-Output "Result: $($script:Failures) FAIL(s)."
if ($script:Failures -gt 0) { exit 1 }
exit 0

