# Project Review — Periodieke onderhoud-check

Audit de projectdocumentatie, memory, skills/hooks en sessie-learnings. Rapporteer wat verouderd, missend of toe te voegen is. **Voert geen wijzigingen uit** — alleen voorstellen ter goedkeuring.

## Arguments
$ARGUMENTS — optional: `full` (default), `docs`, `memory`, `skills`, `learnings`

## Stap 1: CLAUDE.md accuracy check (`docs`)

Vergelijk CLAUDE.md met de actuele codebase:

1. **Runtime State Files tabel**: glob voor `*.json` in project root + `config/` + `core/`. Vergelijk met wat in de tabel staat. Rapporteer missende of verouderde entries.
2. **Architecture sectie**: glob voor `agents/*.py`, `utils/*.py`, `core/*.py`. Check of de diagram en beschrijvingen kloppen.
3. **Secrets tabel**: lees `utils/gcp_secrets.py` en vergelijk met de Secrets tabel in CLAUDE.md.
4. **Development Commands**: check of de genoemde commando's nog werken (syntax check, niet uitvoeren).

Rapporteer per sectie: ✅ up to date, ⚠️ incomplete, ❌ incorrect.

## Stap 2: Memory staleness check (`memory`)

Lees alle `.md` files in de memory directory (pad uit MEMORY.md).

Per memory file:
- Check of genoemde file-paden nog bestaan (glob)
- Check of genoemde functies/klassen nog bestaan (grep)
- Check of de beschrijving nog klopt met de huidige code
- Beoordeel of de memory nog relevant is (projectgeheugen veroudert sneller dan feedback)

Rapporteer per file: ✅ valid, ⚠️ possibly stale, ❌ outdated (met reden).

## Stap 3: Session learnings capture (`learnings`)

Analyseer de huidige sessie voor niet-vastgelegde kennis:

1. Bekijk `git diff` (uncommitted) en `git log --oneline -20` (recente commits)
2. Scan voor patronen die als memory opgeslagen moeten worden:
   - Bug-fixes met non-obvious root cause
   - Nieuwe operationele kennis (exchange quirks, API gedrag)
   - User feedback/preferences die niet eerder vastgelegd zijn
   - Conventies die gevolgd moeten worden
3. Check bestaande memories om duplicaten te voorkomen

**Stel concrete memory entries voor** met:
- Voorgestelde filename
- Type (user/feedback/project/reference)
- Inhoud (incl. frontmatter)

**Sla NIETS automatisch op** — presenteer ter goedkeuring.

## Stap 4: Skills & hooks audit (`skills`)

1. Lees alle `.claude/commands/*.md` en `.claude/hooks/*`
2. Per skill: check of genoemde scripts/paden nog bestaan
3. Identificeer repetitieve patronen in de sessie die een nieuwe skill/hook rechtvaardigen
4. Check of hook-triggers nog correct zijn (matchers in settings.local.json vs. hook-code)

Rapporteer: ✅ valid, ⚠️ needs update, 💡 new suggestion.

## Stap 5: CLAUDE.md update voorstel

Op basis van stap 1-4, genereer een concrete lijst van edits voor CLAUDE.md:
- Alleen toevoegen wat NIET uit code af te leiden is
- Focus op: Common Pitfalls, Runtime State Files, Conventions
- Geef de exacte tekst die toegevoegd moet worden

## Output formaat

```
## Review Report — YYYY-MM-DD

### 📄 CLAUDE.md
- ✅/⚠️/❌ per sectie met details

### 🧠 Memory
- ✅/⚠️/❌ per memory file

### 💡 Session Learnings
- Voorgestelde nieuwe memories (ter goedkeuring)

### 🔧 Skills & Hooks
- ✅/⚠️/❌ per skill/hook
- 💡 Nieuwe suggesties

### ✏️ Voorgestelde CLAUDE.md Edits
- Concrete tekst per wijziging
```

## Wanneer te gebruiken

- Aan het **einde van een sessie** met significante wijzigingen
- **Wekelijks** als maintenance check
- Na een **grote refactor** of nieuwe feature
- Wanneer je twijfelt of documentatie nog klopt
