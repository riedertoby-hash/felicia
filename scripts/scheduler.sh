#!/bin/sh
# Runs the recurring jobs inside the "scheduler" container:
#   every 15 minutes: daily order digests (each supplier at its chosen time), standing orders
#   once a day from 05:00: collective invoices and commission invoices
set -u
last_billing=""
while true; do
  python manage.py send_order_digests || echo "digests failed"
  python manage.py run_standing_orders || echo "standing orders failed"
  today=$(date +%F)
  hour=$(date +%H)
  if [ "$hour" -ge 5 ] && [ "$last_billing" != "$today" ]; then
    python manage.py run_billing && last_billing="$today" || echo "billing failed"
  fi
  sleep 900
done
