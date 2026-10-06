"""Toetst de e2-micro-poort (tweede poging) op ~/mem_history.log van de VM.

De poort ligt vast vóór het verkleinen (claimblad docs/audits/2026-10-06-e2micro.md):
  a. ctr_werkelijk < 400 MiB bij elke meting zonder exec-sessie (ctr_procs = 1)
  b. PSI-stall (some) < 1% in elk meetinterval (cumulatieve teller, niet avg60), ongeacht
     de oorzaak: ook een ballon van de hypervisor telt (A2 06-10, vooraf besloten)
  c. onmeetbaar = geraakt: een regel zonder de velden, een gat > 20 min, een teruglopende
     PSI-teller (reboot), te weinig metingen tot --tot, of > 5% exec-metingen
  d. swap_free > 400 MB op de host
  e. trend: dagpiek van ctr_werkelijk stijgt over 3 dagen < 50 MiB per dag
  f. ctr_oom_kill stijgt niet (OOM van een kindproces). De container heeft geen
     memory.max, dus de `max`-teller vangt in de praktijk niets; een piek tussen twee
     metingen zonder OOM ziet alleen de PSI-teller (b). Een teller die DAALT (oom_kill,
     max, peak) betekent een nieuwe cgroup = de container is herstart: ook geraakt.
OOM in de kernellog over alle boots, herstarts, CYCLE_FROZEN en dashboard 200 toetst het
claimblad apart.

Gebruik op de VM:
  python3 - --vanaf 2026-10-10T08:00:00Z --tot 2026-10-17T08:00:00Z < ~/mem_history.log
"""
import argparse
import sys
from datetime import datetime, timezone

GRENS_MIB = 400
PSI_GRENS = 0.01
BASIS_PROCS = 1
MAX_GAT_S = 20 * 60
MAX_EXEC_FRACTIE = 0.05
SWAP_FREE_MIN_MB = 400
TREND_MAX_MIB_PER_DAG = 50
TREND_DAGEN = 3
METING_S = 15 * 60
VELDEN = ("ctr_werkelijk", "ctr_procs", "psi_some_total", "swap_free", "ctr_oom_kill", "ctr_max",
          "ctr_peak")


def _velden(regel):
    delen = regel.strip().split("|")
    v = {"ts": delen[0]}
    for d in delen[1:]:
        if "=" in d:
            k, w = d.split("=", 1)
            v[k] = w
    return v


def _getal(w):
    """'228MB' -> 228.0; '-', leeg of ontbrekend -> None (onmeetbaar is geen nul)."""
    if w is None:
        return None
    try:
        return float(w.replace("MB", "").strip())
    except ValueError:
        return None


def _seconden(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").timestamp()


def _nu():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def toets(regels, vanaf, tot=None, nu=None):
    """Geeft (geslaagd, bevindingen, samenvatting). `vanaf` is verplicht: zonder begin
    van het venster tellen regels van vóór de nieuwe meter mee als gat. Zonder `tot`
    (de dagelijkse run) toetst de volledigheid tot `nu`, zodat een gestopte cron niet
    dagenlang als 'gehaald' doorgaat."""
    eind = tot or nu or _nu()
    bevindingen = []
    n = n_exec = 0
    piek = None
    vorige = None  # (t, psi, oom_kill, max)
    # Begin bij `vanaf`: een log die pas uren na de herstart begint, is een gat.
    laatste_t = _seconden(vanaf)
    psi_max = 0.0
    dagpiek = {}
    for regel in regels:
        if not regel.strip():
            continue
        ts = regel[:20]
        if ts < vanaf or (tot and ts > tot):
            continue
        v = _velden(regel)
        n += 1
        w = {k: _getal(v.get(k)) for k in VELDEN}
        try:
            t = _seconden(v["ts"])
        except ValueError:
            bevindingen.append(f"{v['ts']}: onleesbare tijd")
            continue
        if t - laatste_t > MAX_GAT_S:
            bevindingen.append(f"{v['ts']}: gat van {(t - laatste_t) / 60:.0f} min zonder metingen")
        laatste_t = t
        ontbreekt = [k for k, x in w.items() if x is None]
        if ontbreekt:
            bevindingen.append(f"{v['ts']}: onmeetbaar ({', '.join(ontbreekt)} ontbreekt)")
            vorige = None
            continue
        if w["ctr_procs"] < BASIS_PROCS:
            bevindingen.append(f"{v['ts']}: geen proces in de container")
        elif w["ctr_procs"] > BASIS_PROCS:
            n_exec += 1
        else:
            if w["ctr_werkelijk"] >= GRENS_MIB:
                bevindingen.append(f"{v['ts']}: ctr_werkelijk {w['ctr_werkelijk']:.0f} MiB >= {GRENS_MIB}")
            if piek is None or w["ctr_werkelijk"] > piek[0]:
                piek = (w["ctr_werkelijk"], v["ts"])
            dag = v["ts"][:10]
            dagpiek[dag] = max(dagpiek.get(dag, 0.0), w["ctr_werkelijk"])
        if w["swap_free"] <= SWAP_FREE_MIN_MB:
            bevindingen.append(f"{v['ts']}: swap_free {w['swap_free']:.0f} MB <= {SWAP_FREE_MIN_MB}")
        if vorige is not None:
            dt = t - vorige[0]
            if w["psi_some_total"] < vorige[1]:
                bevindingen.append(f"{v['ts']}: PSI-teller liep terug (reboot?)")
            elif dt > 0:
                frac = (w["psi_some_total"] - vorige[1]) / 1e6 / dt
                psi_max = max(psi_max, frac)
                if frac >= PSI_GRENS:
                    bevindingen.append(f"{v['ts']}: PSI-stall {frac:.2%} in {dt / 60:.0f} min")
            if w["ctr_oom_kill"] > vorige[2]:
                bevindingen.append(f"{v['ts']}: oom_kill steeg naar {w['ctr_oom_kill']:.0f}")
            if w["ctr_max"] > vorige[3]:
                bevindingen.append(f"{v['ts']}: container raakte memory.max ({w['ctr_max']:.0f}x)")
            if (w["ctr_oom_kill"] < vorige[2] or w["ctr_max"] < vorige[3]
                    or w["ctr_peak"] < vorige[4]):
                bevindingen.append(f"{v['ts']}: cgroup-teller daalde: container herstart")
        vorige = (t, w["psi_some_total"], w["ctr_oom_kill"], w["ctr_max"], w["ctr_peak"])

    if n == 0:
        bevindingen.append("geen metingen in het venster")
    else:
        verwacht = (_seconden(eind) - _seconden(vanaf)) / METING_S
        if n < 0.95 * verwacht:
            bevindingen.append(f"{n} metingen, verwacht ~{verwacht:.0f} tot {eind}")
        if _seconden(eind) - laatste_t > MAX_GAT_S:
            bevindingen.append(f"log stopt {(_seconden(eind) - laatste_t) / 60:.0f} min vóór {eind}")
    if n and n_exec / n > MAX_EXEC_FRACTIE:
        bevindingen.append(f"{n_exec}/{n} metingen met exec (> {MAX_EXEC_FRACTIE:.0%}): onmeetbaar")
    # Alleen hele dagen: de dag van de herstart en de dag van `eind` zijn onvolledig.
    dagen = [d for d in sorted(dagpiek) if vanaf[:10] < d < eind[:10]]
    for i in range(len(dagen) - TREND_DAGEN):
        stijging = (dagpiek[dagen[i + TREND_DAGEN]] - dagpiek[dagen[i]]) / TREND_DAGEN
        if stijging >= TREND_MAX_MIB_PER_DAG:
            bevindingen.append(f"trend {dagen[i]}..{dagen[i + TREND_DAGEN]}: +{stijging:.0f} MiB/dag")

    samenvatting = (f"{n} metingen ({n_exec} met exec), piek zonder exec "
                    f"{piek[0]:.0f} MiB om {piek[1]}, hoogste PSI-interval {psi_max:.3%}"
                    if piek else f"{n} metingen, geen bruikbare piek")
    return not bevindingen, bevindingen, samenvatting


def _iso(ts):
    _seconden(ts)  # ValueError -> argparse weigert; tekstvergelijking vraagt exact dit formaat
    return ts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vanaf", required=True, type=_iso, help="UTC, JJJJ-MM-DDTHH:MM:SSZ: begin van het venster")
    p.add_argument("--tot", default=None, type=_iso, help="UTC, zelfde vorm: eind (standaard: nu)")
    a = p.parse_args()
    geslaagd, bevindingen, samenvatting = toets(sys.stdin, a.vanaf, a.tot)
    print(samenvatting)
    for b in bevindingen:
        print("  RAAKT:", b)
    print("POORT:", "gehaald" if geslaagd else "GERAAKT -> terugdraaien")
    sys.exit(0 if geslaagd else 1)


if __name__ == "__main__":
    main()
