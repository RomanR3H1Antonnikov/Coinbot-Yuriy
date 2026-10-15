@echo off
rem Run in a terminal on Windows: avito.ru must be reachable via a Russian IP from THIS terminal.
rem Loops every 120 min; stop with Ctrl+C.
cd /d "%~dp0"
".venv\Scripts\python.exe" scraper_run.py --source avito --loop 120
