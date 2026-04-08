@echo off
setlocal

cd /d "%~dp0"

set "CONDA_NO_PLUGINS=true"
set "AUTOPAPERS_HOST=127.0.0.1"
set "AUTOPAPERS_PORT=8876"
set "REPORTS_DIR=%CD%\reports"
set "WEB_STDOUT_LOG=%REPORTS_DIR%\web-serve.console.log"
set "WEB_STDERR_LOG=%REPORTS_DIR%\web-serve.err.log"

if not exist "%REPORTS_DIR%" mkdir "%REPORTS_DIR%"

where conda >nul 2>&1
if errorlevel 1 (
  echo [AutoPapers] conda command not found.
  echo Please open this script from a shell where conda is available.
  pause
  exit /b 1
)

echo [AutoPapers] Starting web app in Conda env "myrag"...
echo [AutoPapers] URL: http://%AUTOPAPERS_HOST%:%AUTOPAPERS_PORT%
echo [AutoPapers] Runtime log: %REPORTS_DIR%\web-serve.log
echo [AutoPapers] Console log: %WEB_STDOUT_LOG%
echo [AutoPapers] Error log: %WEB_STDERR_LOG%

start "" cmd /c "ping 127.0.0.1 -n 3 >nul && start "" http://%AUTOPAPERS_HOST%:%AUTOPAPERS_PORT%"

echo.>> "%WEB_STDOUT_LOG%"
echo ===== [%DATE% %TIME%] AutoPapers start =====>> "%WEB_STDOUT_LOG%"
echo.>> "%WEB_STDERR_LOG%"
echo ===== [%DATE% %TIME%] AutoPapers start =====>> "%WEB_STDERR_LOG%"

conda run -n myrag python -m autopapers serve --host %AUTOPAPERS_HOST% --port %AUTOPAPERS_PORT% 1>> "%WEB_STDOUT_LOG%" 2>> "%WEB_STDERR_LOG%"

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo [AutoPapers] Server exited with code %EXIT_CODE%.
  pause
)

exit /b %EXIT_CODE%
