"""Eén pre-deploy-poort (plan 2026-09-15, S4). Faalt luid.

    python scripts/predeploy.py          # alles, vóór elke deploy
    python scripts/predeploy.py --snel   # zonder check_pipeline (lokaal itereren)

Waarom: de checks stonden los — in een &&-keten, in CLAUDE.md of in iemands hoofd.
Twee keer belandde er een syntaxfout in main met een groene CI, en dertien
statebestanden driftten uit de mount-lijst zonder dat iemand het zag. Deze poort
doet alles in vaste volgorde en stopt niet bij de eerste fout, zodat je in één run
alles ziet wat er mis is.
"""

import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Gemount maar bewust NIET in STATE_FILES: deploy_update.sh behandelt ze apart
# (eigen backup-regel, chmod, en voor config/ de seeding-lus).
EIGEN_BEHANDELING = {
    "dashboard.json", "trade_log.json", "active_assets.json", "pnl_snapshots.json",
    "config/auto_params.json", "config/thematic_exposure_themes.json",
    "config/conviction_core.json", "config/barbell_targets.json",
    "config/broker_holdings.json",
}


def state_audit(compose_tekst, deploy_tekst):
    """Vergelijkt de compose-mounts met STATE_FILES. Geeft een lijst fouten (leeg = goed)."""
    mounts = set(re.findall(r"^\s*-\s*\./([^:\s]+\.json):/app/", compose_tekst, re.M))
    m = re.search(r'^STATE_FILES="([^"]*)"', deploy_tekst, re.M)
    if not m:
        return ["STATE_FILES niet gevonden in scripts/deploy_update.sh"]
    state = set(m.group(1).split())
    fouten = []
    for f in sorted(state - mounts):
        fouten.append("%s staat in STATE_FILES maar is niet gemount — overleeft geen recreate" % f)
    for f in sorted(mounts - state - EIGEN_BEHANDELING):
        fouten.append("%s is gemount maar staat niet in STATE_FILES — geen backup, geen restore" % f)
    for f in sorted(EIGEN_BEHANDELING & mounts):
        # Moet minstens in de backup-lus én de chmod-regel staan.
        if deploy_tekst.count(f) < 2:
            fouten.append("%s is gemount maar ontbreekt in backup-lus of chmod van deploy_update.sh" % f)
    return fouten


def _lees(pad):
    with open(os.path.join(REPO, pad), encoding="utf-8") as fh:
        return fh.read()


def main(argv):
    snel = "--snel" in argv
    resultaten = []

    print("== state-audit (compose vs STATE_FILES) ==")
    fouten = state_audit(_lees("docker-compose.prod.yml"), _lees("scripts/deploy_update.sh"))
    for f in fouten:
        print("  FOUT  " + f)
    resultaten.append(("state-audit", not fouten))

    stappen = [
        ("syntax", [sys.executable, "-m", "tests.pre_flight.check_syntax"]),
        ("pytest", [sys.executable, "-m", "pytest", "tests/", "-m", "not integration", "-q"]),
    ]
    if not snel:
        stappen.append(("pipeline", [sys.executable, "-m", "tests.pre_flight.check_pipeline"]))

    for naam, cmd in stappen:
        print("== %s ==" % naam)
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        staart = (proc.stdout + proc.stderr).strip().splitlines()[-6:]
        for regel in staart:
            print("  " + regel)
        resultaten.append((naam, proc.returncode == 0))

    print("\n== uitslag ==")
    for naam, ok in resultaten:
        print("  %-12s %s" % (naam, "ok" if ok else "FAALT"))
    if all(ok for _, ok in resultaten):
        print("Pre-deploy-poort: GROEN.")
        return 0
    print("Pre-deploy-poort: ROOD — niet deployen.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
