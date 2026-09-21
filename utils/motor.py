"""De motor zichtbaar maken: wat staat op welke trede, en beweegt er genoeg?

    python -m utils.motor

Treden, spelregels en ritme: docs/MOTOR.md. De stand staat in config/experimenten.json
(velden `trede`, `sinds`, `volgende_stap`).

De motor moet blijven lopen (Bart, 21-09). Deze module meldt daarom niet alleen de stand,
maar ook wat stilstaat: een idee dat langer dan een week niet van trede is veranderd, een
trede zonder inhoud, en meer dan drie experimenten tegelijk op de proeftuin-trede.
"""

import json
import sys
from datetime import date

REGISTER_FILE = "config/experimenten.json"
TREDEN = {0: "idee", 1: "papier", 2: "schaduw", 3: "proeftuin", 4: "schalen"}
MAX_PROEFTUIN = 3            # docs/MOTOR.md, spelregel 2
STIL_NA_DAGEN = 7            # het weekritme: elke week minstens één stap
# Trede 1 kan terecht wachten (op een marktregime, op Bart); die tellen niet als stilstand
# zolang de status dat zegt.
WACHTSTATUSSEN = {"wacht_op_regime", "gepland"}
# Een vooruitmeting (trede 2) kan alleen verder als er nieuwe data komt, bijvoorbeeld een
# maandslot. Ze telt niet als stilstand, maar MOET een herzien-datum dragen; daarna meldt
# de motor haar weer, zodat niets ongemerkt eeuwig in de schaduw blijft staan.
VOORUITMETING = "meet_vooruit"
GESTOPT = "gestopt"


def _dagen_sinds(tekst, vandaag):
    try:
        return (vandaag - date.fromisoformat(str(tekst)[:10])).days
    except (TypeError, ValueError):
        return None


def stand(register: dict, vandaag: date | None = None) -> dict:
    """{'per_trede': {trede: [...]}, 'gestopt': [...], 'signalen': [...], 'zonder_trede': [...]}."""
    vandaag = vandaag or date.today()
    per_trede = {t: [] for t in TREDEN}
    zonder, signalen, gestopt = [], [], []
    for naam, e in (register.get("experimenten") or {}).items():
        if not isinstance(e, dict):
            continue
        # Een gestopt experiment is een uitkomst, geen voorraad: het staat niet stil en het
        # vult geen trede (anders lijkt de motor te lopen terwijl er niets meer op papier ligt).
        if e.get("status") == GESTOPT:
            gestopt.append(naam)
            continue
        trede = e.get("trede")
        if trede not in TREDEN:
            zonder.append(naam)
            continue
        dagen = _dagen_sinds(e.get("sinds"), vandaag)
        per_trede[trede].append({"naam": naam, "status": e.get("status"), "dagen": dagen,
                                 "soort": e.get("soort"), "volgende_stap": e.get("volgende_stap")})
        if e.get("status") == VOORUITMETING:
            herzien = _dagen_sinds(e.get("herzien"), vandaag)
            if herzien is None:
                signalen.append("%s meet vooruit maar heeft geen 'herzien'-datum" % naam)
            elif herzien > 0:
                signalen.append("%s: herzien-datum %s is voorbij — een stap verder of stoppen"
                                % (naam, e.get("herzien")))
        elif trede in (0, 1, 2) and e.get("status") not in WACHTSTATUSSEN:
            if dagen is None:
                signalen.append("%s: geen datum bij 'sinds' — stilstand niet te meten" % naam)
            elif dagen > STIL_NA_DAGEN:
                signalen.append("%s staat %d dagen op trede %d (%s) — een stap verder of stoppen"
                                % (naam, dagen, trede, TREDEN[trede]))
        # Een IDEE houdt geen geld, dus een potje is daar altijd fout. Geplande experimenten
        # (trede 1+) dragen bewust hun doelpotje; of daar ongeoorloofd geld in staat, meet
        # utils/kpi.py met de echte saldi (H5: experiment_niet_live).
        if trede == 0 and e.get("sleeve"):
            signalen.append("%s is een idee maar heeft een potje (%s) — ideeën houden geen geld, "
                            "en een potje met geld geeft een vals H5-signaal" % (naam, e.get("sleeve")))

    if len(per_trede[3]) > MAX_PROEFTUIN:
        signalen.append("%d experimenten op de proeftuin, maximaal %d — het verliesbudget wordt te dun"
                        % (len(per_trede[3]), MAX_PROEFTUIN))
    for t in (0, 1):
        if not per_trede[t]:
            signalen.append("trede %d (%s) is leeg — de motor loopt droog" % (t, TREDEN[t]))
    for naam in zonder:
        signalen.append("%s heeft geen geldige trede" % naam)
    return {"per_trede": per_trede, "gestopt": gestopt, "signalen": signalen, "zonder_trede": zonder}


def rapport(register: dict | None = None, vandaag: date | None = None) -> int:
    if register is None:
        with open(REGISTER_FILE, encoding="utf-8") as fh:
            register = json.load(fh)
    s = stand(register, vandaag)
    for t, naam in TREDEN.items():
        items = s["per_trede"][t]
        print("\n%d · %s (%d)" % (t, naam, len(items)))
        for e in items:
            dagen = "?" if e["dagen"] is None else "%dd" % e["dagen"]
            print("  - %-26s %-16s %5s  %s" % (e["naam"], e["status"] or "", dagen,
                                               (e["volgende_stap"] or "")[:90]))
    if s["gestopt"]:
        print()
        print("gestopt (%d): %s" % (len(s["gestopt"]), ", ".join(s["gestopt"])))
    print()
    if s["signalen"]:
        print("SIGNALEN")
        for sig in s["signalen"]:
            print("  ! " + sig)
        return 1
    print("De motor loopt: geen signalen.")
    return 0


if __name__ == "__main__":
    sys.exit(rapport())
