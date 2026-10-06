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
#   pswpin=..|pswpout=..|psi_some_total=..|psi_full_total=..|
#   ctr_anon=..MB|ctr_swapcached=..MB|ctr_werkelijk=..MB|ctr_procs=..|
#   ctr_oom_kill=..|ctr_max=..|ballon=..
#
# ctr_werkelijk = anon + swap - swapcached (A4-audit 2026-10-05): de echte voetafdruk van
# de container. memory.current telt bestandscache mee (vrij te geven) en swapcache-pagina's
# staan zowel in RAM als in swap. Dit is de maat voor de e2-micro-poort.
# ctr_procs = aantal processen in de cgroup; ligt het boven de basislijn, dan liep er een
# `docker exec`-sessie (die telt mee in het geheugen van de container).
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
read -r ctr_anon ctr_swapcached < <(awk '/^anon /{a=$2} /^swapcached /{s=$2} END {print int(a/1048576), int(s/1048576)}' "$CG/memory.stat" 2>/dev/null)
ctr_anon=${ctr_anon:--}; ctr_swapcached=${ctr_swapcached:--}
if [ "$ctr_anon" != "-" ] && [ "$ctr_swap" != "-" ]; then
  ctr_werkelijk=$(( ctr_anon + ctr_swap - ctr_swapcached ))
else
  ctr_werkelijk="-"
fi
ctr_procs=$(wc -l < "$CG/cgroup.procs" 2>/dev/null || echo "-")
# memory.events (A2-audit 2026-10-06): een piek tússen twee metingen in is onzichtbaar
# voor ctr_werkelijk (22-09: memory.peak 398 -> 555 MiB binnen een half uur). De tellers
# oom_kill en max zijn cumulatief, dus elke stijging is een voorval dat we anders missen.
read -r ctr_oom_kill ctr_max < <(awk '/^oom_kill /{k=$2} /^max /{m=$2} END {print (k==""?"-":k), (m==""?"-":m)}' "$CG/memory.events" 2>/dev/null)
ctr_oom_kill=${ctr_oom_kill:--}; ctr_max=${ctr_max:--}
# Ballon van de hypervisor: de oorzaak van poging 1 (21-09 04:42, "Out of puff").
# Faalt journalctl, dan "-" en geen stille nul.
if kernlog=$(sudo journalctl -k -b -q --no-pager 2>/dev/null); then
  ballon=$(grep -c "Out of puff" <<< "$kernlog")
else
  ballon="-"
fi

read -r pswpin pswpout < <(awk '/^pswpin/{i=$2} /^pswpout/{o=$2} END {print i, o}' /proc/vmstat)
# De cumulatieve stall-teller, niet avg60: een gemiddelde over 60 seconden dat je elke
# 15 minuten afleest, mist per definitie bijna elk voorval.
read -r psi_some psi_full < <(awk -F'total=' '/^some/{s=$2} /^full/{f=$2} END {print s, f}' /proc/pressure/memory)

echo "$(date -u +%FT%TZ)|${S}|vm=${V}|swap_used=${swap_used}MB|swap_cached=${swap_cached_mb}MB|swap_parked=${swap_parked}MB|swap_free=${swap_free_mb}MB|ctr_mem=${ctr_mem}MB|ctr_swap=${ctr_swap}MB|ctr_peak=${ctr_peak}MB|pswpin=${pswpin}|pswpout=${pswpout}|psi_some_total=${psi_some}|psi_full_total=${psi_full}|ctr_anon=${ctr_anon}MB|ctr_swapcached=${ctr_swapcached}MB|ctr_werkelijk=${ctr_werkelijk}MB|ctr_procs=${ctr_procs}|ctr_oom_kill=${ctr_oom_kill}|ctr_max=${ctr_max}|ballon=${ballon}" >> ~/mem_history.log
