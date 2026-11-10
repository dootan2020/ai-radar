# Weekly job: render the next 14 days of backgrounds, then publish them.
# Run by the HalcyonWallpaperWeekly scheduled task (register-weekly-task.ps1).
# A failed render or check publishes nothing, so the site keeps its last good set.
# Log: wallpaper/logs/weekly-<date>.log. Windows PowerShell 5.1 compatible.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$log = Join-Path $logs ('weekly-{0}.log' -f (Get-Date -Format 'yyyy-MM-dd_HHmm'))
$python = (Get-Command python -ErrorAction Stop).Source

function Write-Log([string]$text) {
    $line = '{0} {1}' -f (Get-Date -Format 's'), $text
    Add-Content -Path $log -Value $line -Encoding UTF8
}

function Invoke-Step([string]$name, [string[]]$arguments) {
    Write-Log "START $name"
    $out = Join-Path $logs 'step.out'
    $err = Join-Path $logs 'step.err'
    $process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $root -NoNewWindow `
        -PassThru -Wait -RedirectStandardOutput $out -RedirectStandardError $err
    Get-Content $out, $err -ErrorAction SilentlyContinue | Add-Content -Path $log -Encoding UTF8
    Remove-Item $out, $err -ErrorAction SilentlyContinue
    Write-Log "END $name exit $($process.ExitCode)"
    return $process.ExitCode
}

Write-Log "Halcyon weekly backgrounds from $root"
$code = Invoke-Step 'render-ahead' @('wallpaper/daily.py', '--ahead', '14')
if ($code -ne 0) {
    Write-Log 'Render failed; nothing published, the site keeps its last good set.'
    exit $code
}
$code = Invoke-Step 'publish' @('wallpaper/publish.py')
# Old logs: keep the last twelve weeks.
Get-ChildItem -Path $logs -Filter 'weekly-*.log' | Sort-Object Name -Descending | Select-Object -Skip 12 |
    Remove-Item -ErrorAction SilentlyContinue
exit $code
