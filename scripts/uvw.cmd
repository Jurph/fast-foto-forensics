@echo off
setlocal EnableDelayedExpansion

set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"

set "UV_CACHE_DIR=%REPO_ROOT%\.uv-cache"
set "UV_PYTHON_INSTALL_DIR=%REPO_ROOT%\.uv-python"
set "UV_MANAGED_PYTHON=1"
set "REPO_SCRATCH_DIR=%REPO_ROOT%\.scratch"

if not exist "%REPO_SCRATCH_DIR%" mkdir "%REPO_SCRATCH_DIR%"

if /I "%~1"=="run" (
    if "%~2"=="" (
        call uv run --locked
    ) else (
        set "RUN_ARGS=%*"
        set "RUN_ARGS=!RUN_ARGS:* =!"
        call uv run --locked !RUN_ARGS!
    )
) else (
    uv %*
)
exit /b %ERRORLEVEL%
