@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Run setup.bat first.
  pause
  exit /b 1
)
echo OPTIONAL explicit downloader. Runtime transcription never downloads models silently.
echo Supported models: small, medium. Prepare both for the environment check.
set /p "MODEL=Enter model name [medium]: "
if "%MODEL%"=="" set MODEL=medium
if /I not "%MODEL%"=="small" if /I not "%MODEL%"=="medium" (
  echo [ERROR] Only small or medium is supported.
  pause
  exit /b 1
)
echo Destination: "%~dp0huggingface_cache"
set /p "CONFIRM=Download model now? Type YES to continue: "
if /I not "%CONFIRM%"=="YES" exit /b 0
.venv\Scripts\python.exe download_model.py %MODEL%
set RC=%ERRORLEVEL%
if not "%RC%"=="0" echo [ERROR] Download failed. Check network access and available disk space.
pause
exit /b %RC%
