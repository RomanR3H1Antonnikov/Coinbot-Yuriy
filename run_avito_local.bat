@echo off
rem Local Avito run (Avito blocks datacenter and non-Russian IPs, so this is not run on the VPS).
rem avito.ru must go through a Russian IP (VPN split tunnel for avito.ru / this python.exe).
cd /d "%~dp0"
".venv\Scripts\python.exe" scraper_run.py --source avito 2>>logs\avito_local.err.log
