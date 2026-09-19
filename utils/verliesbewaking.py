"""Verliesbewaking — ziet verlies binnen één monitorronde (plan 2026-09-15, K4/K5).

Draait als SwarmMonitor Check 24, elke 5 minuten. Leest goedkope publieke en on-chain
bronnen, vergelijkt ze met de drempels uit `config/experimenten.json` en geeft
gebeurtenissen terug: `alarm` of `kill`. De monitor stuurt ze door naar Telegram.

Opbouw:
  lees_metingen()  — IO: on-chain, API's, statebestanden. Elke meting mag None zijn.
  evalueer()       — puur: metingen + vorige toestand + register -> gebeurtenissen.
  run_check()      — lijm: brandoefening, cooldown, toestand opslaan.

De regel die dit bestand draagt: **onmeetbaar is geen "alles goed".** Een meting die
drie rondes op rij mislukt, is zelf een alarm.

Wat dit (nog) niet doet: automatisch ingrijpen. Een kill wordt gemeld met de actie uit
het register. De uitvoerende kant komt met de modules die het geld beheren (HLP in
M5, basis in M6), elk met een eigen A1-audit — een automatische order hoort niet in
een bewakingsmodule die zelf nog niet in productie bewezen is.

Brandoefening (K5, KPI H4):
    python -m utils.verliesbewaking --oefening   # vlag in data/; de volgende
                                                  # monitorronde verwerkt hem
    python -m utils.verliesbewaking --droog      # lokaal evalueren, niets versturen
"""

import argparse
import json
import logging
import math
import os
import time
import urllib.request

from utils import experimenten as exp_register
from utils import flows

logger = logging.getLogger("Verliesbewaking")

REGISTER_FILE = "config/experimenten.json"
STATE_FILE = "data/verliesbewaking_state.json"
OEFENING_FILE = "data/oefening_actief.json"
HLP_STATE_FILE = "hlp_sleeve_state.json"
SLEEVE_NAV_FILE = "data/sleeve_nav.json"
KPI_FILE = "data/kpi.json"
TREASURY_STATE_FILE = "treasury_state.json"
PROTOCOLS_FILE = "config/treasury_protocols.json"
THEMATIC_FILE = "thematic_exposure_positions.json"

ALARM_COOLDOWN_S = 6 * 3600
KILL_COOLDOWN_S = 24 * 3600
ONMEETBAAR_RONDES = 3

USDC_ARB = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
HL_INFO = "https://api.hyperliquid.xyz/info"


# ─────────────────────────────────────────────────────────────── IO-hulpjes

def _lees_json(pad, standaard):
    try:
        with open(pad, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return standaard
    except Exception as e:
        logger.warning("Verliesbewaking: %s onleesbaar (%s)", pad, e)
        return standaard


def _schrijf_json(pad, data):
    map_ = os.path.dirname(pad)
    if map_:
        os.makedirs(map_, exist_ok=True)
    with open(pad, "w", encoding="utf-8") as fh:   # in-place: data/ is een bind mount
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _http_json(url, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json", "User-Agent": "agent-trader/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _veilig(fn, *args):
    try:
        waarde = fn(*args)
    except Exception as e:
        logger.debug("Verliesbewaking: %s faalde (%s)", getattr(fn, "__name__", fn), e)
        return None
    if isinstance(waarde, float) and not math.isfinite(waarde):
        return None
    return waarde


def _getal(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ─────────────────────────────────────────────────────────────── metingen

def _aave_liquidity_index():
    """Aave v3 USDC liquidityIndex (slot 1 van getReserveData). Mag nooit dalen."""
    from utils.treasury_yield_oracle import _eth_call, _AAVE_POOL, _USDC_ARB
    raw = _eth_call(_AAVE_POOL, "0x35ea6a75" + _USDC_ARB.lower().replace("0x", "").zfill(64))
    data = bytes.fromhex(raw.removeprefix("0x"))
    if len(data) < 64:
        raise ValueError("getReserveData gaf %d bytes" % len(data))
    return int.from_bytes(data[32:64], "big") / 1e27


BENCHMARK_ID = "aave-v3-arbitrum-usdc"


def _boek_rendementsmeting(st: dict, pid: str, koers: float, nu: float) -> None:
    """Bewaart de EERSTE en de laatste koers per protocol, met tijdstempel.

    Een share price (of Aave's liquidityIndex) loopt alleen op met het rendement: stortingen
    en opnames veranderen hem niet. Twee metingen met een tijdsverschil geven dus een
    flow-gecorrigeerde APR — de meter die de M3-poort nodig heeft en die er tot 2026-09-19
    niet was (A2-audit: "geen experimentgeld vóór de meter er staat").

    De reeks staat los van `share_prices`, want dat is een lopend MAXIMUM voor de
    dalingsdetectie; een maximum is geen meetreeks.
    """
    if not koers or koers <= 0:
        return
    reeks = st.setdefault("rendement_reeks", {})
    r = reeks.setdefault(pid, {})
    if not (r.get("eerste") or {}).get("koers"):
        r["eerste"] = {"koers": float(koers), "ts": float(nu)}
    r["laatste"] = {"koers": float(koers), "ts": float(nu)}
    # Eén punt per dag, zodat ook "30 dagen onder de benchmark" (de kill-regel uit het
    # register) te meten is. Zonder reeks is dat een regel die niemand kan toetsen.
    dagen = r.setdefault("dagelijks", [])
    if not dagen or float(nu) - float(dagen[-1].get("ts", 0)) >= 86400:
        dagen.append({"koers": float(koers), "ts": float(nu)})
        del dagen[:-40]


def _erc4626_share_price(vault):
    """Prijs van één heel vault-aandeel in USDC: convertToAssets(10**decimals) / 1e6.

    Niet met een vaste 1e6: MetaMorpho-aandelen hebben 18 decimalen, dan geeft
    convertToAssets(1e6) 0 en is de check dood (A1-audit 2026-09-15). Een prijs van 0
    is onmeetbaar, geen koers.
    """
    from utils.treasury_yield_oracle import _eth_call
    decimalen = int(_eth_call(vault, "0x313ce567"), 16)
    if not 0 < decimalen <= 36:
        raise ValueError("onwaarschijnlijke decimals %r voor %s" % (decimalen, vault))
    raw = _eth_call(vault, "0x07a2d13a" + hex(10 ** decimalen)[2:].zfill(64))
    prijs = int(raw, 16) / 1e6
    if prijs <= 0:
        raise ValueError("share price 0 voor %s" % vault)
    return prijs


def _saldi_onchain(protocollen):
    """({protocol_id: USDC}, USDC op de treasury-wallet), rechtstreeks on-chain.

    Raiset bij elke mislukte uitlezing: een half gelezen potje is onmeetbaar, geen
    kleiner potje. Een geslaagde 0 is dus een échte 0 — een leeggetrokken protocol.
    """
    from utils.treasury_yield_oracle import _eth_call
    from utils.treasury_executor import _TREASURY_WALLET
    adres = _TREASURY_WALLET.lower().replace("0x", "").zfill(64)

    def uint(to, data):
        raw = _eth_call(to, data)
        if not raw or raw == "0x":
            raise ValueError("leeg antwoord van %s" % to)
        return int(raw, 16)

    saldi = {}
    for p in protocollen:
        # GEEN filter op `automated`: die vlag zegt of er automatisch geld HEEN mag, niet
        # of er geld LIGT. Een protocol dat wordt teruggezet op automated=false houdt zijn
        # saldo, en dat hoort in de bewaking te blijven (A2-audit 2026-09-15, bevinding 6).
        if p.get("type") == "aave_v3" and p.get("receipt_token"):
            saldi[p["id"]] = uint(p["receipt_token"], "0x70a08231" + adres) / 1e6
        elif p.get("type") == "erc4626" and p.get("vault_address"):
            aandelen = uint(p["vault_address"], "0x70a08231" + adres)
            saldi[p["id"]] = (uint(p["vault_address"],
                                   "0x07a2d13a" + hex(aandelen)[2:].zfill(64)) / 1e6
                              if aandelen else 0.0)
        elif p.get("vault_address") or p.get("receipt_token") or p.get("comet_address"):
            # Wél een adres, maar geen leesroute voor dit type: dat is een storing, geen nul.
            raise ValueError(
                "geen leesroute voor %s (type %s) terwijl er een adres staat"
                % (p.get("id"), p.get("type") or "onbekend"))
        else:
            # Bewust niet geconfigureerd (bv. compound zonder comet_address): geen geld, geen alarm.
            logger.debug("verliesbewaking: %s heeft geen adres — overgeslagen", p.get("id"))
    wallet = uint(USDC_ARB, "0x70a08231" + adres) / 1e6
    return saldi, wallet


def _usdc_prijs():
    d = _http_json("https://coins.llama.fi/prices/current/arbitrum:%s" % USDC_ARB)
    return float(next(iter(d["coins"].values()))["price"])


def _hlp_equity(user, vault):
    rijen = _http_json(HL_INFO, {"type": "userVaultEquities", "user": user})
    for r in rijen or []:
        if str(r.get("vaultAddress", "")).lower() == str(vault).lower():
            return float(r.get("equity"))
    # Niet gevonden is onmeetbaar, geen $0: anders een valse HLP-kill van 100%.
    raise ValueError("vault %s niet in userVaultEquities" % vault)


def lees_metingen(register, nu=None):
    """Alles wat de evaluatie nodig heeft. Een mislukte uitlezing is None, nooit 0."""
    nu = nu if nu is not None else time.time()
    m = {"ts": nu}

    m["aave_liquidity_index"] = _veilig(_aave_liquidity_index)

    # Saldi ON-CHAIN, elke ronde — niet uit treasury_state.json. Dat bestand wordt maar
    # eens per uur geschreven, en get_*_balance geeft 0.0 bij een RPC-fout. Hier raiset een
    # mislukte eth_call, dus onmeetbaar is None en een 0 is een echte 0: een leeggetrokken
    # protocol wordt binnen één ronde een KILL (A1-audit ronde 2). De wallet telt mee,
    # zodat een switch tussen protocollen het totaal niet verandert.
    lijst = (_lees_json(PROTOCOLS_FILE, {}) or {}).get("protocols") or []
    protocollen = {p.get("id"): p for p in lijst}
    onchain = _veilig(_saldi_onchain, lijst)
    if onchain is None:
        m["yield_totaal_usd"], m["yield_balances"] = None, {}
    else:
        saldi, wallet_usdc = onchain
        m["yield_balances"] = saldi
        m["yield_totaal_usd"] = round(sum(saldi.values()) + wallet_usdc, 6)

    m["share_prices"] = {}
    for pid, bal in (m.get("yield_balances") or {}).items():
        cfg = protocollen.get(pid) or {}
        if cfg.get("type") == "erc4626" and cfg.get("vault_address") and (bal or 0) > 1.0:
            m["share_prices"][pid] = _veilig(_erc4626_share_price, cfg["vault_address"])

    try:
        m["kasbeheer_onderweg"] = flows.kasbeheer_onderweg(
            _lees_json(flows.PROPOSALS_FILE, []))
    except Exception:
        m["kasbeheer_onderweg"] = True   # bij twijfel geen saldo-oordeel

    m["usdc_prijs"] = _veilig(_usdc_prijs)

    hlp = _lees_json(HLP_STATE_FILE, None)
    if isinstance(hlp, dict) and _getal(hlp.get("inleg_netto_usd")):
        m["hlp_inleg_usd"] = _getal(hlp.get("inleg_netto_usd"))
        m["hlp_equity_usd"] = _veilig(_hlp_equity, hlp.get("user"), hlp.get("vault"))

    # Stops van de dip-koper bestaan alleen in software. Werkt hij zijn open posities
    # niet meer bij, dan staat het beheer stil — zonder logregel (CLAUDE.md).
    them = _lees_json(THEMATIC_FILE, {}) or {}
    open_pos = [p for p in (them.get("positions") or {}).values()
                if isinstance(p, dict) and str(p.get("status", "")).upper() == "OPEN"]
    laatst_bij = max((flows._epoch(p.get("last_updated")) or 0.0 for p in open_pos), default=0.0)
    m["dip_koper_stilstand_min"] = ((nu - laatst_bij) / 60.0) if open_pos and laatst_bij else None

    hist = (_lees_json(SLEEVE_NAV_FILE, {}) or {}).get("history") or []
    laatste = flows._epoch(hist[-1].get("ts")) if hist else None
    m["snapshot_leeftijd_uur"] = (nu - laatste) / 3600.0 if laatste else None

    kpi = _lees_json(KPI_FILE, {}) or {}
    m["kpi_onmeetbaar"] = list((((kpi.get("laatste") or {}).get("h5") or {})
                                .get("onmeetbaar")) or [])
    return m


# ─────────────────────────────────────────────────────────────── evaluatie

def evalueer(m, state, register, stromen=(), nu=None):
    """Puur: (metingen, vorige toestand, register) -> (gebeurtenissen, nieuwe toestand)."""
    nu = nu if nu is not None else m.get("ts", time.time())
    st = json.loads(json.dumps(state or {}))
    gebeurtenissen = []
    controles = register.get("controles") or {}
    globaal = register.get("globaal") or {}
    experimenten = register.get("experimenten") or {}

    def meld(sleutel, niveau, controle, bericht, actie=None):
        gebeurtenissen.append({"sleutel": sleutel, "niveau": niveau, "controle": controle,
                               "bericht": bericht, "actie": actie})

    def onmeetbaar(sleutel, controle, waarde):
        tellers = st.setdefault("onmeetbaar", {})
        if waarde is None:
            tellers[sleutel] = tellers.get(sleutel, 0) + 1
            if tellers[sleutel] >= ONMEETBAAR_RONDES:
                meld(sleutel + "_onmeetbaar", "alarm", controle,
                     "%s is %d rondes op rij niet te meten — onmeetbaar is geen 'alles goed'"
                     % (sleutel, tellers[sleutel]))
            return True
        tellers.pop(sleutel, None)
        return False

    # ── veilig potje: integriteit van de protocollen ──────────────────────
    vi = controles.get("veilig_integriteit") or {}
    daling_toegestaan = float(vi.get("alarm_share_price_daling_pct", 0.0)) / 100.0

    idx = m.get("aave_liquidity_index")
    if not onmeetbaar("aave_liquidity_index", "veilig_integriteit", idx):
        vorige = st.get("aave_liquidity_index")
        if vorige and idx < vorige * (1 - daling_toegestaan):
            meld("aave_liquidity_index", "alarm", "veilig_integriteit",
                 "Aave liquidityIndex DAALDE van %.9f naar %.9f — dat hoort nooit te gebeuren"
                 % (vorige, idx), vi.get("kill_actie"))
        st["aave_liquidity_index"] = max(vorige or 0.0, idx)
        _boek_rendementsmeting(st, BENCHMARK_ID, idx, nu)

    koersen = st.setdefault("share_prices", {})
    for pid, prijs in (m.get("share_prices") or {}).items():
        sleutel = "share_price:%s" % pid
        if onmeetbaar(sleutel, "veilig_integriteit", prijs):
            continue
        vorige = koersen.get(pid)
        if vorige and prijs < vorige * (1 - daling_toegestaan):
            meld(sleutel, "alarm", "veilig_integriteit",
                 "Share price van %s DAALDE van %.6f naar %.6f" % (pid, vorige, prijs),
                 vi.get("kill_actie"))
        koersen[pid] = max(vorige or 0.0, prijs)
        _boek_rendementsmeting(st, pid, prijs, nu)

    totaal = m.get("yield_totaal_usd")
    vorig = st.get("yield_saldo")
    max_uit_uur = float(globaal.get("saldo_check_max_uit_uur", 6))
    if not onmeetbaar("yield_totaal_usd", "veilig_integriteit", totaal):
        if m.get("kasbeheer_onderweg"):
            # Geld onderweg (bridge, halverwege een switch): geen oordeel, en de basislijn
            # BLIJFT staan. Na de transit vergelijken we met de stand van vóór de transit
            # plus de stromen die kasbeheer inmiddels heeft geboekt. Zo verdwijnt een
            # verlies tijdens een transit niet stil in een nieuwe basislijn (A1-audit
            # ronde 2), en is er geen race met het tijdstip waarop een stroom geboekt wordt.
            if vorig:
                sinds = st.setdefault("saldo_check_uit_sinds", nu)
                uren = (nu - sinds) / 3600.0
                if uren > max_uit_uur:
                    meld("saldo_check_uit", "alarm", "veilig_integriteit",
                         "Saldo-check van het veilige potje staat al %.1f uur uit: kasbeheer "
                         "heeft geld onderweg — controleer of die transit vastzit" % uren)
        else:
            st.pop("saldo_check_uit_sinds", None)
            if vorig and vorig["usd"] > 0:
                verwacht = vorig["usd"] + flows.netto_flow(stromen, "yield_core", vorig["ts"], nu)
                daling = (verwacht - totaal) / verwacht * 100.0 if verwacht > 0 else 0.0
                if daling >= float(vi.get("kill_saldo_daling_pct", 1.0)):
                    meld("yield_saldo", "kill", "veilig_integriteit",
                         "Veilig potje %.2f%% lager dan verwacht ($%.2f i.p.v. $%.2f, na "
                         "correctie voor overboekingen)" % (daling, totaal, verwacht),
                         vi.get("kill_actie"))
                elif daling >= float(vi.get("alarm_saldo_daling_pct", 0.5)):
                    meld("yield_saldo", "alarm", "veilig_integriteit",
                         "Veilig potje %.2f%% lager dan verwacht ($%.2f i.p.v. $%.2f)"
                         % (daling, totaal, verwacht))
            st["yield_saldo"] = {"usd": totaal, "ts": nu}

    # ── USDC-peg ─────────────────────────────────────────────────────────
    peg = controles.get("usdc_peg") or {}
    prijs = m.get("usdc_prijs")
    if not onmeetbaar("usdc_prijs", "usdc_peg", prijs):
        if prijs < float(peg.get("kill_onder", 0.98)):
            meld("usdc_peg", "kill", "usdc_peg", "USDC noteert $%.4f" % prijs,
                 peg.get("kill_actie"))
        elif prijs < float(peg.get("alarm_onder", 0.995)):
            meld("usdc_peg", "alarm", "usdc_peg", "USDC noteert $%.4f" % prijs)

    # ── HLP ──────────────────────────────────────────────────────────────
    # Wat meetelt in het budget en hoe verlies heet: utils/experimenten.py (één definitie,
    # gedeeld met kpi.py H3 — die rekenden uiteen).
    verlies_experimenten = 0.0
    hlp = experimenten.get("hlp_vault") or {}
    inleg = m.get("hlp_inleg_usd")
    if inleg:
        equity = m.get("hlp_equity_usd")
        if not onmeetbaar("hlp_equity_usd", "hlp_vault", equity):
            # Drawdown op equity/inleg: robuust tegen stortingen en opnames.
            ratio = equity / inleg
            piek = max(st.get("hlp_piek_ratio") or 0.0, ratio)
            st["hlp_piek_ratio"] = piek
            dd = (piek - ratio) / piek * 100.0 if piek > 0 else 0.0
            kill_dd = float(((hlp.get("kill") or {}).get("drawdown_pct")) or 8.0)
            alarm_dd = float(((hlp.get("alarm") or {}).get("drawdown_pct")) or 3.0)
            if dd >= kill_dd:
                meld("hlp_drawdown", "kill", "hlp_vault",
                     "HLP drawdown %.1f%% (equity $%.2f op inleg $%.2f)" % (dd, equity, inleg),
                     (hlp.get("kill") or {}).get("actie"))
            elif dd >= alarm_dd:
                meld("hlp_drawdown", "alarm", "hlp_vault",
                     "HLP drawdown %.1f%% (equity $%.2f op inleg $%.2f)" % (dd, equity, inleg))
            if exp_register.telt_mee_voor_budget(hlp):
                verlies_experimenten += exp_register.verlies_usd(inleg, equity) or 0.0
        if not exp_register.telt_mee_voor_budget(hlp):
            # Geld in een experiment dat niet live staat wordt door het budget overgeslagen.
            # De stille nul in de andere richting (A1-audit 2026-09-16).
            meld("experiment_niet_live", "alarm", "hlp_vault",
                 "HLP heeft $%.2f inleg maar staat niet als live in het register — "
                 "het verliesbudget bewaakt dit niet" % inleg,
                 "status op 'live' en verlies_meten_vanaf invullen, of het geld terughalen")

    # ── basis (live vanaf M6; de module levert basis_verlies_usd) ─────────
    basis_verlies = m.get("basis_verlies_usd")
    if basis_verlies is not None and exp_register.telt_mee_voor_budget(
            experimenten.get("basis_traag")):
        verlies_experimenten += max(0.0, basis_verlies)

    # ── verliesbudget ────────────────────────────────────────────────────
    budget = float(globaal.get("verliesbudget_usd", 250))
    budget_alarm = float(globaal.get("verliesbudget_alarm_usd", budget / 2))
    if verlies_experimenten >= budget:
        meld("experimentbudget", "kill", "verliesbudget",
             "Experimentverlies $%.2f >= budget $%.0f" % (verlies_experimenten, budget),
             "alle experimenten terug naar veilig, stoppen, Bart melden")
    elif verlies_experimenten >= budget_alarm:
        meld("experimentbudget", "alarm", "verliesbudget",
             "Experimentverlies $%.2f (alarmgrens $%.0f, budget $%.0f)"
             % (verlies_experimenten, budget_alarm, budget))
    st["experimentverlies_usd"] = round(verlies_experimenten, 2)

    # ── de meting zelf ───────────────────────────────────────────────────
    leeftijd = m.get("snapshot_leeftijd_uur")
    max_leeftijd = float(globaal.get("meting_max_snapshot_leeftijd_uur", 26))
    if leeftijd is None or leeftijd > max_leeftijd:
        meld("meting_snapshot", "alarm", "meting",
             "Geen NAV-snapshot in %s uur (max %.0f)"
             % ("onbekend aantal" if leeftijd is None else "%.1f" % leeftijd, max_leeftijd))
    if m.get("kpi_onmeetbaar"):
        meld("meting_kpi", "alarm", "meting",
             "KPI's onmeetbaar: %s" % ", ".join(map(str, m["kpi_onmeetbaar"])))
    stil = m.get("dip_koper_stilstand_min")
    max_stil = float(globaal.get("dip_koper_max_stilstand_minuten", 180))
    if stil is not None and stil > max_stil:
        meld("dip_koper_stilstand", "alarm", "meting",
             "Dip-koper heeft zijn open posities %.0f min niet bijgewerkt — het beheer "
             "(stops bestaan alleen in software) staat mogelijk stil" % stil)

    return gebeurtenissen, st


# ─────────────────────────────────────────────────────────────── lijm

def formatteer(g, oefening=False):
    kop = "🔴 KILL" if g["niveau"] == "kill" else "🟠 ALARM"
    regel = "%s%s — %s: %s" % ("🧪 OEFENING " if oefening else "", kop, g["controle"], g["bericht"])
    if g.get("actie"):
        regel += " → actie: %s" % g["actie"]
    return regel


def run_check(send, nu=None, register_pad=REGISTER_FILE, state_pad=STATE_FILE,
              oefening_pad=OEFENING_FILE):
    """Eén bewakingsronde. Geeft de gebeurtenissen terug die daadwerkelijk gemeld zijn."""
    nu = nu if nu is not None else time.time()
    register = _lees_json(register_pad, None)
    if not isinstance(register, dict):
        logger.error("Verliesbewaking: register %s ontbreekt of is onleesbaar", register_pad)
        send("🟠 ALARM — verliesbewaking: register %s ontbreekt of is onleesbaar; "
             "er wordt NIETS bewaakt" % register_pad)
        return []
    state = _lees_json(state_pad, {}) or {}

    vlag = _lees_json(oefening_pad, None)
    if isinstance(vlag, dict):
        return _verwerk_oefening(vlag, register, state, send, nu, state_pad, oefening_pad)

    stromen, gebeurtenissen_extra = [], []
    try:
        stromen = flows.laad_flows()
    except flows.FlowsOnleesbaar as e:
        gebeurtenissen_extra.append({"sleutel": "flows_onleesbaar", "niveau": "alarm",
                                     "controle": "meting", "bericht": str(e), "actie": None})
    metingen = lees_metingen(register, nu)
    gebeurtenissen, nieuw = evalueer(metingen, state, register, stromen, nu)
    gebeurtenissen = gebeurtenissen_extra + gebeurtenissen

    gemeld = nieuw.setdefault("gemeld", {})
    te_melden = []
    for g in gebeurtenissen:
        sleutel = "%s:%s" % (g["sleutel"], g["niveau"])
        wacht = KILL_COOLDOWN_S if g["niveau"] == "kill" else ALARM_COOLDOWN_S
        if nu - float(gemeld.get(sleutel, 0)) < wacht:
            continue
        gemeld[sleutel] = nu
        te_melden.append(g)
    for g in te_melden:
        send(formatteer(g))
    nieuw["laatste_ronde"] = nu
    _schrijf_json(state_pad, nieuw)
    return te_melden


def _verwerk_oefening(vlag, register, state, send, nu, state_pad, oefening_pad):
    gebeurtenissen, _ = evalueer(vlag.get("metingen") or {}, vlag.get("state") or {},
                                 register, [], nu)
    gevonden = sorted("%s:%s" % (g["sleutel"], g["niveau"]) for g in gebeurtenissen)
    verwacht = sorted(vlag.get("verwacht") or [])
    aangemaakt = float(vlag.get("aangemaakt") or nu)
    detectie_min = round((nu - aangemaakt) / 60.0, 2)
    alles = set(verwacht) <= set(gevonden)
    regels = ["🧪 OEFENING verliesbewaking — %d gebeurtenissen na %.1f min, %s"
              % (len(gebeurtenissen), detectie_min,
                 "alle verwachte gevonden" if alles else
                 "GEMIST: %s" % ", ".join(sorted(set(verwacht) - set(gevonden))))]
    regels += [formatteer(g, oefening=True) for g in gebeurtenissen]
    send("\n".join(regels))
    state["laatste_oefening"] = {"aangemaakt": aangemaakt, "gedetecteerd": nu,
                                 "detectie_min": detectie_min, "gevonden": gevonden,
                                 "verwacht": verwacht, "alles_gevonden": alles}
    _schrijf_json(state_pad, state)
    try:
        os.remove(oefening_pad)
    except FileNotFoundError:
        pass
    for g in gebeurtenissen:
        g["oefening"] = True
    return gebeurtenissen


def maak_oefening(pad=OEFENING_FILE, nu=None):
    """Zet een vlag met synthetische dalingen. Raakt geen echte toestand."""
    nu = nu if nu is not None else time.time()
    vlag = {
        "aangemaakt": nu,
        "metingen": {
            "ts": nu, "aave_liquidity_index": 1.10, "yield_totaal_usd": 2400.0,
            "yield_ts": nu, "kasbeheer_onderweg": False,
            "share_prices": {"oefening-vault": 1.05}, "usdc_prijs": 0.97,
            "hlp_inleg_usd": 500.0, "hlp_equity_usd": 455.0,
            "snapshot_leeftijd_uur": 30.0, "kpi_onmeetbaar": [],
        },
        "state": {
            "aave_liquidity_index": 1.11,
            "yield_saldo": {"usd": 2490.0, "ts": nu - 3600},
            "share_prices": {"oefening-vault": 1.06},
            "hlp_piek_ratio": 1.0,
        },
        "verwacht": ["aave_liquidity_index:alarm", "share_price:oefening-vault:alarm",
                     "yield_saldo:kill", "usdc_peg:kill", "hlp_drawdown:kill",
                     "meting_snapshot:alarm"],
    }
    _schrijf_json(pad, vlag)
    return vlag


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--oefening", action="store_true",
                    help="vlag zetten; de volgende monitorronde verwerkt hem")
    ap.add_argument("--droog", action="store_true",
                    help="huidige metingen lokaal evalueren, niets versturen of opslaan")
    args = ap.parse_args()
    if args.oefening:
        maak_oefening()
        print("Oefening-vlag gezet in %s. De volgende monitorronde (<= 5 min) verwerkt hem."
              % OEFENING_FILE)
    elif args.droog:
        reg = _lees_json(REGISTER_FILE, {})
        met = lees_metingen(reg)
        print(json.dumps(met, indent=2, default=str))
        gb, _ = evalueer(met, _lees_json(STATE_FILE, {}) or {}, reg, flows.laad_flows())
        for g in gb:
            print(formatteer(g))
        print("%d gebeurtenissen" % len(gb))
    else:
        ap.print_help()
