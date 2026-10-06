from scripts.e2micro_poort import toets as _toets

V = "2026-10-10T00:00:00Z"


def toets(regels, vanaf, tot=None, nu=None):
    """Zonder expliciete `nu` eindigt het venster bij de laatste regel en begint het bij de
    eerste, zodat losse toetsen niet op volledigheid stuklopen."""
    regels = list(regels)
    if nu is None and tot is None:
        nu = max((r[:20] for r in regels if r[:4] == "2026"), default=vanaf)
    if vanaf == V and regels and regels[0][:4] == "2026":
        vanaf = regels[0][:20]
    return _toets(regels, vanaf, tot=tot, nu=nu)


def _ts(minuut):
    return f"2026-10-10T{minuut // 60:02d}:{minuut % 60:02d}:00Z"


def _r(minuut, werkelijk=250, procs=1, psi=0, swap_free=900, oom=0, mx=0, peak=300):
    return (f"{_ts(minuut)}|200MiB / 1GiB|20%|1%|vm=400/960MB|swap_used=0MB|swap_free={swap_free}MB|"
            f"psi_some_total={psi}|psi_full_total=0|ctr_anon=200MB|ctr_swapcached=0MB|"
            f"ctr_werkelijk={werkelijk}MB|ctr_procs={procs}|ctr_oom_kill={oom}|ctr_max={mx}|ctr_peak={peak}MB|ballon=0")


def _reeks(n, afwijking=None):
    """n metingen om de 15 min; afwijking={index: {veld: waarde}}."""
    return [_r(i * 15, **(afwijking or {}).get(i, {})) for i in range(n)]


def test_onder_de_grens_is_gehaald():
    ok, bev, _ = toets([_r(0), _r(15, werkelijk=399, psi=1_000_000)], V)
    assert ok and not bev


def test_400_raakt_de_poort():
    ok, bev, _ = toets([_r(0, werkelijk=400)], V)
    assert not ok and "400" in bev[0]


def test_een_exec_meting_telt_niet_mee():
    ok, _, s = toets(_reeks(30, {3: {"werkelijk": 450, "procs": 2}}), V)
    assert ok and "1 met exec" in s


def test_te_veel_exec_metingen_is_onmeetbaar():
    ok, bev, _ = toets([_r(i * 15, werkelijk=900, procs=3) for i in range(5)], V)
    assert not ok and any("exec" in b for b in bev)


def test_psi_interval_boven_1_procent_raakt():
    # 9 s stall in 15 min = 1,0%
    ok, bev, _ = toets([_r(0), _r(15, psi=9_000_000)], V)
    assert not ok and "PSI" in bev[0]


def test_teruglopende_psi_teller_raakt():
    ok, bev, _ = toets([_r(0, psi=5_000_000), _r(15, psi=0)], V)
    assert not ok and "terug" in bev[0]


def test_onmeetbaar_werkelijk_is_geen_pass():
    ok, bev, _ = toets([_r(0, werkelijk="-")], V)
    assert not ok and "onmeetbaar" in bev[0]


def test_onmeetbaar_procs_is_geen_pass():
    ok, bev, _ = toets([_r(0, werkelijk=900, procs="-")], V)
    assert not ok and "ctr_procs" in bev[0]


def test_ontbrekende_psi_is_geen_pass():
    regel = _r(0).replace("psi_some_total=0|", "")
    ok, bev, _ = toets([regel], V)
    assert not ok and "psi_some_total" in bev[0]


def test_regel_zonder_nieuwe_velden_in_het_venster_is_een_gat():
    oud = f"{_ts(15)}|200MiB / 1GiB|20%|1%|vm=400/960MB"
    ok, bev, _ = toets([_r(0), oud, _r(30)], V)
    assert not ok and any("onmeetbaar" in b for b in bev)


def test_gat_tussen_metingen_raakt():
    ok, bev, _ = toets([_r(0), _r(360)], V)
    assert not ok and "gat" in bev[0]


def test_log_die_te_vroeg_stopt_raakt():
    ok, bev, _ = toets(_reeks(8), V, tot=_ts(600))
    assert not ok and any("stopt" in b for b in bev)


def test_te_weinig_metingen_tot_het_eind_raakt():
    # loopt door tot het eind, maar met een gat van 15 min per uur: 1 op de 4 ontbreekt
    regels = [_r(m) for m in range(0, 615, 15) if m % 60 != 30]
    ok, bev, _ = toets(regels, V, tot=_ts(600))
    assert not ok and any("verwacht" in b for b in bev)


def test_leeg_venster_is_geen_pass():
    ok, bev, _ = _toets(["2026-10-09T08:00:00Z|x"], V, nu=_ts(600))
    assert not ok and "geen metingen" in bev[0]


def test_swap_free_onder_400_raakt():
    ok, bev, _ = toets([_r(0, swap_free=400)], V)
    assert not ok and "swap_free" in bev[0]


def test_stijgende_oom_kill_raakt():
    ok, bev, _ = toets([_r(0), _r(15, oom=1)], V)
    assert not ok and "oom_kill" in bev[0]


def test_memory_max_geraakt_raakt():
    ok, bev, _ = toets([_r(0), _r(15, mx=2)], V)
    assert not ok and "memory.max" in bev[0]


def test_trend_van_50_per_dag_raakt():
    regels = []
    for d in range(6):  # dag 0 en de laatste vallen weg als onvolledig
        regels.append(f"2026-10-1{d}T12:00:00Z" + _r(0, werkelijk=200 + 50 * d)[20:])
    ok, bev, _ = toets(regels, V)
    assert any("trend" in b for b in bev)


def test_vlakke_trend_raakt_niet():
    regels = [f"2026-10-1{d}T12:00:00Z" + _r(0)[20:] for d in range(6)]
    _, bev, _ = toets(regels, V)
    assert not any("trend" in b for b in bev)


def test_gat_aan_het_begin_van_het_venster_raakt():
    # log begint 8 uur na de herstart en is daarna volledig
    regels = [_r(m) for m in range(480, 1440, 15)]
    ok, bev, _ = _toets(regels, V, tot=_ts(1425))
    assert not ok and "gat" in bev[0]


def test_dagelijkse_run_zonder_tot_ziet_een_gestopte_log():
    ok, bev, _ = _toets(_reeks(8), V, nu=_ts(600))
    assert not ok and any("stopt" in b for b in bev)


def test_dalende_peak_is_een_herstart():
    ok, bev, _ = toets([_r(0, peak=300), _r(15, peak=120)], V)
    assert not ok and "herstart" in bev[0]


def test_dalende_oom_teller_is_een_herstart():
    ok, bev, _ = toets([_r(0, oom=2), _r(15, oom=0)], V)
    assert not ok and any("herstart" in b for b in bev)


def test_geen_proces_in_de_container_raakt():
    ok, bev, _ = toets([_r(0, procs=0)], V)
    assert not ok and "geen proces" in bev[0]


def test_onvolledige_eerste_dag_telt_niet_mee_in_de_trend():
    # herstart laat op 10-10 met een lage piek, daarna vlak op 300: geen trend
    regels = ["2026-10-10T23:45:00Z" + _r(0, werkelijk=100)[20:]]
    regels += [f"2026-10-1{d}T12:00:00Z" + _r(0, werkelijk=300)[20:] for d in range(1, 6)]
    _, bev, _ = _toets(regels, "2026-10-10T23:40:00Z", nu="2026-10-16T00:00:00Z")
    assert not any("trend" in b for b in bev)
