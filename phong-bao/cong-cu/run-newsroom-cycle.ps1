param(
    [string]$SnapshotUrl
)

$ErrorActionPreference = 'Stop'
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'Never'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$python = (Get-Command python.exe -ErrorAction Stop).Source
$remote = (& git -C $repo remote get-url origin)
if ($LASTEXITCODE -ne 0 -or -not $remote) { throw 'Cannot resolve origin remote.' }

$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$clone = Join-Path $temporaryRoot ("newsroom-decisions-{0}" -f [guid]::NewGuid().ToString('N'))
try {
    & git clone --quiet --no-checkout --filter=blob:none -- $remote $clone
    if ($LASTEXITCODE -ne 0) { throw 'Cannot clone origin for newsroom decisions.' }

    $branchExists = $false
    & git -C $clone show-ref --verify --quiet refs/remotes/origin/newsroom-decisions
    if ($LASTEXITCODE -eq 0) { $branchExists = $true }
    elseif ($LASTEXITCODE -ne 1) { throw 'Cannot inspect newsroom decisions branch.' }

    if ($branchExists) {
        & git -C $clone switch --quiet --track -c newsroom-decisions origin/newsroom-decisions
        if ($LASTEXITCODE -ne 0) { throw 'Cannot check out newsroom decisions branch.' }
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
    & git -C $clone push origin HEAD:refs/heads/newsroom-decisions
    if ($LASTEXITCODE -ne 0) { throw 'Cannot push newsroom decisions.' }
} finally {
    $resolvedClone = [IO.Path]::GetFullPath($clone)
    if ($resolvedClone.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -and
        $resolvedClone -ne $temporaryRoot -and (Test-Path -LiteralPath $resolvedClone)) {
        Remove-Item -LiteralPath $resolvedClone -Recurse -Force
    }
}
