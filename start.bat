@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe scripts\start.py
if errorlevel 1 pause
