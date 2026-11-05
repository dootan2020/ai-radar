param(
    [string]$SnapshotUrl,
    # Hard limit for each git call that reaches the remote. Measured 2026-11-05: the scheduled task
    # reached the newsroom 7 seconds after its trigger, clone included.
    [int]$GitTimeoutSeconds = 180,
    # Hard limit for asking GitHub to build the site after a push; the request is best effort.
    [int]$BuildTriggerTimeoutSeconds = 60
)

$ErrorActionPreference = 'Stop'
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'Never'
# Abort any HTTP transfer slower than 1000 bytes/s for 60 seconds, lazy blob fetches included.
$env:GIT_CONFIG_COUNT = '2'
$env:GIT_CONFIG_KEY_0 = 'http.lowSpeedLimit'
$env:GIT_CONFIG_VALUE_0 = '1000'
$env:GIT_CONFIG_KEY_1 = 'http.lowSpeedTime'
$env:GIT_CONFIG_VALUE_1 = '60'
$git = (Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source

function Invoke-Bounded([string]$Program, [string[]]$Arguments, [int]$TimeoutSeconds, [string]$Name) {
    # A stalled network call must not hold the scheduled task until its 2-hour limit.
    $quoted = foreach ($argument in $Arguments) {
        if ($argument -match '[\s"]') { '"' + ($argument -replace '"', '\"') + '"' } else { $argument }
    }
    $start = New-Object Diagnostics.ProcessStartInfo $Program, ($quoted -join ' ')
    $start.UseShellExecute = $false
    $process = [Diagnostics.Process]::Start($start)
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        & taskkill.exe /PID $process.Id /T /F | Out-Null
        $process.WaitForExit()
        throw "$Name timed out after $TimeoutSeconds seconds."
    }
    return $process.ExitCode
}

function Invoke-RemoteGit([string[]]$Arguments) {
    # A stalled git call fails the run.
    return Invoke-Bounded $git $Arguments $GitTimeoutSeconds "git $($Arguments[0])"
}

function Request-SiteBuild([string]$Remote) {
    # The site build reads the newsroom-decisions branch; without a request it waits for GitHub's own cron,
    # which ran every 4-8 hours from 2026-11-02 when the 20-minute scheduler stopped dispatching. The push
    # above is the source of truth, so a failed request is logged and never fails the cycle: the next
    # scheduled build still picks the decisions up. gh uses the signed-in owner's own credentials.
    $log = Join-Path $repo 'phong-bao/cycles/build-trigger.log'
    try {
        if ($Remote -notmatch 'github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?/?$') { throw "origin is not a GitHub repository: $Remote" }
        $slug = $Matches[1]
        $gh = (Get-Command gh -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
        $env:GH_PROMPT_DISABLED = '1'
        $exitCode = Invoke-Bounded $gh @('workflow', 'run', 'update.yml', '--ref', 'main', '--repo', $slug) `
            $BuildTriggerTimeoutSeconds 'gh workflow run'
        $result = if ($exitCode -eq 0) { "requested update.yml on $slug" } else { "gh workflow run exited $exitCode" }
    } catch {
        $result = "not requested: $($_.Exception.Message)"
    }
    $line = '{0} site build {1}' -f (Get-Date).ToString('o'), $result
    Write-Output $line
    try { Add-Content -LiteralPath $log -Value $line -Encoding UTF8 } catch { Write-Warning "Cannot write $log" }
}

$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$python = (Get-Command python.exe -ErrorAction Stop).Source
$remote = (& git -C $repo remote get-url origin)
if ($LASTEXITCODE -ne 0 -or -not $remote) { throw 'Cannot resolve origin remote.' }

$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$clone = Join-Path $temporaryRoot ("newsroom-decisions-{0}" -f [guid]::NewGuid().ToString('N'))
try {
    $exitCode = Invoke-RemoteGit @('clone', '--quiet', '--no-checkout', '--filter=blob:none', '--', $remote, $clone)
    if ($exitCode -ne 0) { throw 'Cannot clone origin for newsroom decisions.' }

    $branchExists = $false
    & git -C $clone show-ref --verify --quiet refs/remotes/origin/newsroom-decisions
    if ($LASTEXITCODE -eq 0) { $branchExists = $true }
    elseif ($LASTEXITCODE -ne 1) { throw 'Cannot inspect newsroom decisions branch.' }

    if ($branchExists) {
        # A blob:none clone fetches decisions.json from the remote here.
        $exitCode = Invoke-RemoteGit @('-C', $clone, 'switch', '--quiet', '--track', '-c', 'newsroom-decisions',
                                       'origin/newsroom-decisions')
        if ($exitCode -ne 0) { throw 'Cannot check out newsroom decisions branch.' }
        $tracked = @(& git -C $clone ls-tree -r --name-only HEAD)
        if ($LASTEXITCODE -ne 0 -or @($tracked | Where-Object { $_ -ne 'decisions.json' }).Count -gt 0) {
            throw 'Newsroom decisions branch contains unexpected files.'
        }
        if (Test-Path -LiteralPath (Join-Path $clone 'decisions.json')) {
            $localPath = Join-Path $repo 'phong-bao/decisions.json'
            $branchPath = Join-Path $clone 'decisions.json'
            $copyBranch = $true
            if (Test-Path -LiteralPath $localPath) {
                $localRows = @((Get-Content -LiteralPath $localPath -Raw | ConvertFrom-Json).decisions)
                $branchRows = @((Get-Content -LiteralPath $branchPath -Raw | ConvertFrom-Json).decisions)
                $localIds = @($localRows | ForEach-Object { $_.id })
                $branchIds = @($branchRows | ForEach-Object { $_.id })
                $localOnly = @($localIds | Where-Object { $_ -cnotin $branchIds })
                $branchOnly = @($branchIds | Where-Object { $_ -cnotin $localIds })
                if ($localOnly.Count -gt 0 -and $branchOnly.Count -gt 0) {
                    throw 'Local and branch newsroom histories diverged.'
                }
                $copyBranch = $localOnly.Count -eq 0
            }
            if ($copyBranch) { Copy-Item -LiteralPath $branchPath -Destination $localPath -Force }
        }
    } else {
        & git -C $clone switch --quiet --orphan newsroom-decisions
        if ($LASTEXITCODE -ne 0) { throw 'Cannot create newsroom decisions branch.' }
        & git -C $clone read-tree --empty
        if ($LASTEXITCODE -ne 0) { throw 'Cannot clear new branch index.' }
    }

    $cycleArgs = @('-m', 'phong_bao', 'cycle')
    if ($SnapshotUrl) { $cycleArgs += @('--snapshot-url', $SnapshotUrl) }
    Push-Location $repo
    try {
        $cycleOutput = & $python @cycleArgs
        if ($LASTEXITCODE -ne 0) { throw 'Newsroom cycle failed.' }
    } finally {
        Pop-Location
    }
    $status = $cycleOutput | ConvertFrom-Json
    $cycleOutput
    if ($status.state -eq 'dry_lane') { return }

    Copy-Item -LiteralPath (Join-Path $repo 'phong-bao/decisions.json') -Destination (Join-Path $clone 'decisions.json') -Force
    & git -C $clone add -- decisions.json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot stage newsroom decisions.' }
    & git -C $clone diff --cached --quiet
    if ($LASTEXITCODE -eq 0) { return }
    if ($LASTEXITCODE -ne 1) { throw 'Cannot inspect staged newsroom decisions.' }
    & git -C $clone commit --quiet -m 'chore: publish newsroom decisions'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot commit newsroom decisions.' }
    $exitCode = Invoke-RemoteGit @('-C', $clone, 'push', 'origin', 'HEAD:refs/heads/newsroom-decisions')
    if ($exitCode -ne 0) { throw 'Cannot push newsroom decisions.' }
    Request-SiteBuild $remote
} finally {
    $resolvedClone = [IO.Path]::GetFullPath($clone)
    if ($resolvedClone.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -and
        $resolvedClone -ne $temporaryRoot -and (Test-Path -LiteralPath $resolvedClone)) {
        Remove-Item -LiteralPath $resolvedClone -Recurse -Force
    }
}
