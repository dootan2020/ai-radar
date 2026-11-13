# Run this from the permanent checkout, after reviewing its resolved paths.
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$runScript = Join-Path $PSScriptRoot 'run-newsroom-cycle.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -File "{0}"' -f $runScript) -WorkingDirectory $repo
$triggers = foreach ($hour in 0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22) {
    New-ScheduledTaskTrigger -Daily -At ("{0:D2}:00" -f $hour)
}
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName 'HalcyonNewsroomCycle' -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description 'Local newsroom every two hours around the clock (00, 02, 04, ... 22 local time); a missed run starts when the machine is available.'
