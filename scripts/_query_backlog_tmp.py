"""Temporary script to dump full backlog."""
import os, json
from dotenv import load_dotenv
load_dotenv(".env.adk")
from supabase import create_client

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
client = create_client(url, key)

res = client.table("system_backlog").select("*").order("priority", desc=True).order("created_at", desc=True).execute()

for r in res.data:
    title = r.get("title", "?")
    desc_short = (r.get("description") or "")[:120].replace("\n", " ")
    print(f"ID={r['id']:>4} | P{r.get('priority',0):>2} | {r.get('status','?'):>12} | {r.get('category','?'):>12} | {title}")
    print(f"           {desc_short}")
    print()
