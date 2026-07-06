@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Run npm run setup first. >&2
  exit /b 1
)
".venv\Scripts\python.exe" "mcp\server.py"