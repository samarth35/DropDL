@echo off
setlocal
cd /d "%~dp0"
title DropDL
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
if errorlevel 1 (
  echo.
  echo DropDL could not start. See the message above for the next step.
  pause
  exit /b 1
)
exit /b 0
