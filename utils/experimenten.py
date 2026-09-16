"""Eén definitie van "experiment" en "experimentverlies" (plan 2026-09-15, H3).

`utils/kpi.py` (H3) en `utils/verliesbewaking.py` (verliesbudget) rekenden dit allebei
zelf uit, met een eigen bron voor de inleg. Dat liep uiteen, en in productie gaf H3 op
2026-09-16 **$1.087,80 verlies voor `hlp_vault`** terwijl HLP nog niet bestond: het
experiment wijst naar het potje `house` (de bestaande Hyperliquid-rekening), en de KPI
telde de hele historie van dat potje mee.

De twee regels die dat voorkomen:
1. Een experiment telt pas mee als het **live** staat in `config/experimenten.json`.
2. Het verlies wordt gemeten **vanaf de start van het experiment**, niet vanaf het begin
   van de potjesreeks. `verlies_meten_vanaf` legt die start vast bij het live gaan.
"""
import math

from utils import flows

REGISTER_FILE = "config/experimenten.json"


def telt_mee_voor_budget(exp) -> bool:
    """Alleen een live experiment dat in het register meetelt, belast het verliesbudget."""
    if not isinstance(exp, dict):
        return False
    return exp.get("status") == "live" and bool(exp.get("verliesbudget_telt_mee"))


def meet_vanaf(exp):
    """Epoch waarop het experiment begon, of None als het register dat niet vastlegt."""
    if not isinstance(exp, dict):
        return None
    return flows._epoch(exp.get("verlies_meten_vanaf"))


def verlies_usd(inleg_netto_usd, waarde_usd):
    """Verlies = netto inleg sinds de start min de huidige waarde. Nooit negatief.

    None als een van beide onmeetbaar is — onmeetbaar is geen nul (de beller markeert dat).
    """
    try:
        inleg, waarde = float(inleg_netto_usd), float(waarde_usd)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(inleg) and math.isfinite(waarde)):
        return None
    return max(0.0, inleg - waarde)
