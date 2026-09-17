@echo off
setlocal
cd /d "%~dp0"
echo [1/4] Python compile...
.venv\Scripts\python.exe -m compileall -q backend scripts tests || exit /b 1
echo [2/4] Python tests...
.venv\Scripts\python.exe -m pytest tests -q || exit /b 1
echo [3/4] Frontend type check and build...
pushd frontend
call npm run check || (popd & exit /b 1)
call npm run build || (popd & exit /b 1)
popd
echo [4/4] Environment preflight...
.venv\Scripts\python.exe scripts\preflight.py || exit /b 1
echo All checks passed.
