# Register (or update) the weekly background task for this checkout.
#   powershell -NoProfile -ExecutionPolicy Bypass -File wallpaper\register-weekly-task.ps1
# Sunday 21:00, wakes the machine when allowed, runs late if the time was missed,
# stops after two hours. Runs as the signed-in user so git can push with the
# user's stored credentials. Re-run it from another checkout to move the task there.
$ErrorActionPreference = 'Stop'
$name = 'HalcyonWallpaperWeekly'
$script = Join-Path $PSScriptRoot 'weekly.ps1'
$root = Split-Path -Parent $PSScriptRoot
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $root `
    -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $script)
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '21:00'
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew `
    -RestartCount 1 -RestartInterval (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description 'Render Halcyon daily 3D backgrounds 14 days ahead and publish them to the radar-wallpapers branch.' `
    -Force | Out-Null
Get-ScheduledTask -TaskName $name
