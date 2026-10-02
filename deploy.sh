#!/bin/bash
# Run on VPS once: bash deploy.sh
set -e

REPO_DIR=/root/Coinbot-Yuriy

cd $REPO_DIR

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

mkdir -p logs

# Copy systemd service
cp coinbot.service /etc/systemd/system/coinbot.service
systemctl daemon-reload
systemctl enable coinbot
systemctl restart coinbot

echo "Bot service started."
systemctl status coinbot --no-pager

# Setup cron (remove old entries first)
crontab -l 2>/dev/null | grep -v 'scraper_run.py' | crontab -

# Add cron jobs
(crontab -l 2>/dev/null; echo "*/30 * * * * /root/Coinbot-Yuriy/.venv/bin/python /root/Coinbot-Yuriy/scraper_run.py --source meshok >> /root/Coinbot-Yuriy/logs/scraper.log 2>&1") | crontab -
(crontab -l 2>/dev/null; echo "0 * * * * /root/Coinbot-Yuriy/.venv/bin/python /root/Coinbot-Yuriy/scraper_run.py --source auction >> /root/Coinbot-Yuriy/logs/scraper.log 2>&1") | crontab -

echo "Cron jobs set:"
crontab -l
