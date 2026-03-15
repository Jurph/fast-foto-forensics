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

& uv @CommandArgs
exit $LASTEXITCODE
