#!/bin/bash
# Bemonstert geheugen van de swarm-container en de VM. Draait op de VM via cron
# (*/15 * * * *) en schrijft naar ~/mem_history.log.
#
# Waarom de extra velden (A2-audit 2026-09-20): `docker stats` en `free` tellen
# UITGEPLAATSTE pagina's niet mee. Vult swap zich, dan DALEN die twee cijfers terwijl
# het juist slechter gaat — de dagpiek van de container zakte van 359,8 naar 258,5 MiB
# terwijl er 242 MB naar swap verhuisde. Zonder swap-, druk- en verkeersvelden is geen
# enkel nazorgcriterium toetsbaar.
#
# Let op: `free` telt SwapCached mee, en die pagina's staan óók nog in RAM (gratis terug
# te lezen). Wat telt is SwapTotal - SwapFree - SwapCached = echt geparkeerd.
#
# Regelformaat (de eerste vier velden zijn ongewijzigd, zodat oude analyses blijven werken):
#   ts|MemUsage|MemPerc|CPUPerc|vm=used/totalMB|swap_used=..MB|swap_cached=..MB|
#   swap_parked=..MB|swap_free=..MB|ctr_mem=..MB|ctr_swap=..MB|ctr_peak=..MB|
#   pswpin=..|pswpout=..|psi_some_total=..|psi_full_total=..
set -u

S=$(sudo docker stats --no-stream --format "{{.MemUsage}}|{{.MemPerc}}|{{.CPUPerc}}" agent_trader_swarm 2>/dev/null)
V=$(free -m | awk 'NR==2{print $3"/"$2"MB"}')

# /proc/meminfo in kB
read -r swap_total swap_free swap_cached < <(awk '
  /^SwapTotal:/  {t=$2}
  /^SwapFree:/   {f=$2}
  /^SwapCached:/ {c=$2}
  END {print t, f, c}' /proc/meminfo)
swap_used=$(( (swap_total - swap_free) / 1024 ))
swap_cached_mb=$(( swap_cached / 1024 ))
swap_parked=$(( swap_used - swap_cached_mb ))
swap_free_mb=$(( swap_free / 1024 ))

# cgroup van de container: RSS, wat ervan in swap staat, en de piek sinds de start.
# Host-side lezen (geen `docker exec`), want zo'n sessie telt zelf mee in memory.peak.
CG=$(sudo find /sys/fs/cgroup/system.slice -maxdepth 1 -name 'docker-*.scope' -printf '%p\n' 2>/dev/null | head -1)
lees() { [ -r "$1" ] && echo $(( $(cat "$1") / 1048576 )) || echo "-"; }
ctr_mem=$(lees "$CG/memory.current")
ctr_swap=$(lees "$CG/memory.swap.current")
ctr_peak=$(lees "$CG/memory.peak")

read -r pswpin pswpout < <(awk '/^pswpin/{i=$2} /^pswpout/{o=$2} END {print i, o}' /proc/vmstat)
# De cumulatieve stall-teller, niet avg60: een gemiddelde over 60 seconden dat je elke
# 15 minuten afleest, mist per definitie bijna elk voorval.
read -r psi_some psi_full < <(awk -F'total=' '/^some/{s=$2} /^full/{f=$2} END {print s, f}' /proc/pressure/memory)

echo "$(date -u +%FT%TZ)|${S}|vm=${V}|swap_used=${swap_used}MB|swap_cached=${swap_cached_mb}MB|swap_parked=${swap_parked}MB|swap_free=${swap_free_mb}MB|ctr_mem=${ctr_mem}MB|ctr_swap=${ctr_swap}MB|ctr_peak=${ctr_peak}MB|pswpin=${pswpin}|pswpout=${pswpout}|psi_some_total=${psi_some}|psi_full_total=${psi_full}" >> ~/mem_history.log
