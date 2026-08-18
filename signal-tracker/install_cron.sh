#!/bin/bash
TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v 'signal-tracker' > $TMP
cat >> $TMP << 'CRON'
# ── Signal Tracker (30-day paper experiment, since 2026-08-18) ──
45 15 * * 1-5 cd /home/ubuntu/signal-tracker && /usr/bin/python3 record.py >> /home/ubuntu/signal-tracker/record_cron.log 2>&1
0 19 * * 1-5 cd /home/ubuntu/signal-tracker && /usr/bin/python3 record.py >> /home/ubuntu/signal-tracker/record_cron.log 2>&1
30 22 * * 1-5 cd /home/ubuntu/signal-tracker && /usr/bin/python3 settle.py >> /home/ubuntu/signal-tracker/settle_cron.log 2>&1
40 22 * * 1-5 cd /home/ubuntu/signal-tracker && /usr/bin/python3 report.py --out reports/daily_$(date +\%Y\%m\%d).md >> /home/ubuntu/signal-tracker/report_cron.log 2>&1
CRON
crontab $TMP
rm -f $TMP
echo 'installed:'
crontab -l | grep signal-tracker
