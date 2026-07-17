#!/bin/bash
# One-off, 2026-07-16 (vervolg op recover_state_20260716.sh).
# Archiveert de verouderde state-kopie in de SA-home en verwijdert daar het
# compose-bestand als struikeldraad: elke toekomstige docker-compose-aanroep
# vanuit die directory faalt dan LUID ("no such file") in plaats van stil de
# container aan verouderde bestanden te hangen. De canonieke compose-dir is
# vanaf nu gepind in deploy_update.sh zelf (CANONICAL_DIR) — dit archief is
# de verdedigingslaag voor het geval iemand tóch handmatig in de SA-home gaat
# draaien.
set -e

SA=/home/sa_116183673897831795495
ARCHIVE="$SA/stale_state_archive_20260716"

echo "=== Archiveer verouderde SA-home state (tripwire) ==="
sudo mkdir -p "$ARCHIVE/config" "$ARCHIVE/data"

# Alles wat een compose-run vanuit deze dir zou kunnen mounten gaat de kluis in.
cd "$SA"
for f in *.json config/*.json data/*.json docker-compose.prod.yml deploy_update.sh; do
    if sudo test -e "$f"; then
        sudo mv "$f" "$ARCHIVE/$f"
        echo "archived: $f"
    fi
done

sudo tee "$SA/README_DEPLOY_MOVED.txt" > /dev/null <<'EOF'
2026-07-16: Deploy draait NIET meer vanuit deze directory.

De canonieke compose/working-directory is /home/bartpersoons_gmail_com/ en is
gepind in scripts/deploy_update.sh (CANONICAL_DIR) — dat script verhuist
zichzelf automatisch, waar het ook gestart wordt (CI of handmatig).

De verouderde state-bestanden van vóór 2026-07-16 12:56 staan in
./stale_state_archive_20260716/ (bewaard voor forensiek; NIET terugzetten —
de live data staat in de canonieke dir en loopt door).

Achtergrond: zie CLAUDE.md pitfall "VM has TWO compose home-dirs" en
roadmap.json changelog 2026-07-16.
EOF
echo "README geplaatst."

echo "=== Klaar — inhoud SA-home nu: ==="
sudo ls -la "$SA" | head -15
