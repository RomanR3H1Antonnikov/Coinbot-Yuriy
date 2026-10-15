@echo off
rem Registers a Windows Task Scheduler job: Avito scrape every 2 hours (runs while the PC is on and you are logged in).
rem Remove with: schtasks /Delete /TN "Coinbot-Avito" /F
schtasks /Create /TN "Coinbot-Avito" /TR "\"%~dp0run_avito_local.bat\"" /SC HOURLY /MO 2 /F
schtasks /Query /TN "Coinbot-Avito"
