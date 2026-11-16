#!/usr/bin/env bash
# Retourne 0 si le PC est sur secteur, 1 sinon.
for d in /sys/class/power_supply/*; do
  [[ "$(cat "$d/type" 2>/dev/null)" == "Mains" && "$(cat "$d/online" 2>/dev/null)" == "1" ]] && exit 0
done
for d in /sys/class/power_supply/*; do
  if [[ "$(cat "$d/type" 2>/dev/null)" == "Battery" ]]; then
    [[ "$(cat "$d/status" 2>/dev/null)" != "Discharging" ]] && exit 0
  fi
done
exit 1
