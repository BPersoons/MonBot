# 🔐 Environment Setup Guide

## ✅ CORRECT Workflow

### 1. **ALTIJD** werk in `.env.adk` (NIET in `.env.adk.example`)

```bash
# ✅ GOED: Edit je persoonlijke .env.adk file
code .env.adk

# ❌ FOUT: NOOIT echte keys in .example files!
code .env.adk.example
```

### 2. Voeg je Supabase credentials toe aan `.env.adk`:

```bash
# --- Supabase Configuration ---

# Supabase Project URL
SUPABASE_URL=https://jouwproject.supabase.co

# Supabase API Key (anon/public key)
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...  # Jouw echte key hier

# Supabase Database Password (optioneel, voor directe PostgreSQL access)
SUPABASE_DB_PASSWORD=jouw-db-password
```

### 3. Verificatie

```bash
# Check dat .env.adk NIET in git tracked wordt:
git status

# .env.adk moet NIET verschijnen in "Changes to be committed"
# Als het WEL verschijnt, dan is de .gitignore verkeerd!
```

---

## 📂 File Structure

```
Agent_trader/
├── .env.adk.example          # Template (ALTIJD placeholders, commit to git)
├── .env.adk                  # Jouw echte keys (NOOIT committen! ✅ In .gitignore)
├── .gitignore                # Bevat: .env.adk, *.env (✅ Created)
└── main_adk.py               # Laadt .env.adk automatisch
```

---

## 🔒 Security Best Practices

### ✅ DO:
- Echte keys **alleen** in `.env.adk`
- `.env.adk` in `.gitignore` (✅ al gedaan)
- `.env.adk.example` committen met placeholders
- Keys delen via veilige kanalen (1Password, Vault)

### ❌ DON'T:
- Keys in `.env.adk.example` zetten
- `.env.adk` committen naar git
- Keys in Slack/Email plakken
- Keys in code hardcoden

---

## 🚀 Quick Start

```bash
# 1. Copy example naar je persoonlijke .env.adk (✅ al gedaan!)
# cp .env.adk.example .env.adk

# 2. Edit .env.adk met je echte credentials
code .env.adk

# 3. Vul in:
#    - SUPABASE_KEY=jouw-echte-key
#    - GOOGLE_API_KEY=jouw-google-key
#    - REDIS_PASSWORD=jouw-redis-password (indien nodig)

# 4. Start ADK orchestrator (laadt .env.adk automatisch)
python main_adk.py
```

---

## 🔍 Troubleshooting

### "ModuleNotFoundError: No module named 'supabase'"
```bash
pip install supabase
```

### "Cannot connect to Supabase"
```bash
# Check of credentials correct zijn in .env.adk:
python -c "from dotenv import load_dotenv; import os; load_dotenv('.env.adk'); print(os.getenv('SUPABASE_KEY'))"
```

### "Accidentally committed .env.adk to git!"
```bash
# Remove from git (keeps local file)
git rm --cached .env.adk
git commit -m "Remove accidentally committed .env.adk"

# Rotate ALL keys in Supabase dashboard!
```

---

## 📋 Checklist

- [x] `.gitignore` created (excludes `.env.adk`)
- [x] `.env.adk` created from example
- [ ] SUPABASE_KEY toegevoegd aan `.env.adk`
- [ ] GOOGLE_API_KEY toegevoegd (indien nodig)
- [ ] Verified: `.env.adk` NIET in `git status`
- [ ] `main_adk.py` laadt `.env.adk` automatisch

---

> **💡 TIP**: Bewaar een backup van je `.env.adk` in een password manager (1Password, Bitwarden). NOOIT in git!
