"""
Migration: Add missing columns to swarm_health table.
Connects directly to Supabase Postgres and runs ALTER TABLE statements.
"""
import psycopg2
import sys

# Supabase direct Postgres connection
# Format: postgresql://postgres.[project-ref]:[password]@[host]:5432/postgres
DB_HOST = "db.dptgookslirycireidbp.supabase.co"
DB_PORT = 5432
DB_NAME = "postgres"
DB_USER = "postgres"
DB_PASS = "2umNQ2t0bOr4T0fJ"

MIGRATIONS = [
    "ALTER TABLE swarm_health ADD COLUMN IF NOT EXISTS current_task TEXT DEFAULT NULL;",
    "ALTER TABLE swarm_health ADD COLUMN IF NOT EXISTS current_reasoning_snippet TEXT DEFAULT NULL;",
    # Notify PostgREST to reload its schema cache
    "NOTIFY pgrst, 'reload schema';",
]

def main():
    print("🔧 Connecting to Supabase Postgres...")
    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASS,
            sslmode="require"
        )
        conn.autocommit = True
        cur = conn.cursor()

        for sql in MIGRATIONS:
            print(f"  ▶ {sql.strip()[:80]}...")
            cur.execute(sql)
            print(f"    ✅ Done")

        cur.close()
        conn.close()
        print("\n✅ All migrations applied successfully!")
        return 0
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
