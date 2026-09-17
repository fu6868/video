@echo off
setlocal
cd /d "%~dp0"
echo [1/5] Checking Python 3.11...
py -3.11 -c "import sys; print(sys.version)" >nul 2>&1 || (echo Python 3.11 is required. & pause & exit /b 1)
if not exist ".venv\Scripts\python.exe" (
  echo [2/5] Creating .venv...
  py -3.11 -m venv .venv || (pause & exit /b 1)
) else echo [2/5] Existing .venv kept.
echo [3/5] Installing Python dependencies without deleting user files...
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements-app.txt || (pause & exit /b 1)
echo [4/5] Building frontend...
where npm >nul 2>&1 || (echo Node.js/npm is required. & pause & exit /b 1)
pushd frontend
if exist package-lock.json (call npm ci) else (call npm install)
if errorlevel 1 (popd & pause & exit /b 1)
call npm run build
if errorlevel 1 (popd & pause & exit /b 1)
popd
echo [5/5] Running local environment check...
.venv\Scripts\python.exe scripts\preflight.py || (pause & exit /b 1)
echo.
echo Setup completed. No videos, results, databases, or model weights were deleted.
echo Double-click start.bat to launch.
pause
