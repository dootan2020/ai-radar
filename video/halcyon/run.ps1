param([Parameter(Mandatory=$true)][string]$Spec, [string]$Mode = '--stills')
# Runs the Halcyon builder on a spec file. Usage: run.ps1 -Spec path\to\video.json [-Mode --stills|--render]
# The GPU interpreter comes from $env:HALCYON_PYTHON (default: .venvs\halcyon-gpu under the user profile). Prints "EXIT <code>" last.
$py = if ($env:HALCYON_PYTHON) { $env:HALCYON_PYTHON } else { Join-Path $env:USERPROFILE '.venvs\halcyon-gpu\Scripts\python.exe' }
$builder = Join-Path $PSScriptRoot 'dung-video-gpu.py'
& $py -I -X utf8 $builder $Spec $Mode 2>&1 | ForEach-Object { "$_" }
"EXIT $LASTEXITCODE"
