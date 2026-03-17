import os, json
from supabase import create_client

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
client = create_client(url, key)

res = client.table("system_backlog").select("id,priority,title,status,category,description").order("priority", desc=True).order("created_at", desc=True).execute()

for r in res.data:
    title = r.get("title", "?")
    desc = (r.get("description") or "")[:200].replace("\n", " ")
    sid = r["id"]
    pri = r.get("priority", 0)
    status = r.get("status", "?")
    cat = r.get("category", "?")
    print(f"ID={sid} | P{pri} | {status} | {cat} | {title}")
    print(f"  DESC: {desc}")
    print()
