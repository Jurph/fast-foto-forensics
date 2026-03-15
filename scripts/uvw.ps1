param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArgs
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

$env:UV_CACHE_DIR = Join-Path $repoRoot ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $repoRoot ".uv-python"
$env:UV_MANAGED_PYTHON = "1"
$env:REPO_SCRATCH_DIR = Join-Path $repoRoot ".scratch"

if (-not (Test-Path $env:REPO_SCRATCH_DIR)) {
    New-Item -ItemType Directory -Path $env:REPO_SCRATCH_DIR | Out-Null
}

$uvArgs = $CommandArgs
if ($CommandArgs.Count -gt 0 -and $CommandArgs[0] -eq "run") {
    $remainingArgs = if ($CommandArgs.Count -gt 1) { $CommandArgs[1..($CommandArgs.Count - 1)] } else { @() }
    $uvArgs = @("run", "--locked") + $remainingArgs
}

& uv @uvArgs
exit $LASTEXITCODE
