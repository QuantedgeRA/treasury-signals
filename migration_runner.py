"""
migration_runner.py — Apply and track Supabase schema migrations.

Reads migrations/*.sql in version order, applies pending ones, and records
state in a `schema_migrations` table that the runner self-bootstraps.

Two execution modes (auto-detected):

1. Auto-apply (preferred) — when DATABASE_URL is set in .env, executes SQL
   directly via psycopg2. This is the path you want once Postgres connection
   string is wired (Supabase -> Settings -> Database -> Connection string).

2. Manual fallback — when DATABASE_URL is unset, prints SQL of pending
   migrations and asks you to run them in the Supabase SQL editor, then
   `python migration_runner.py mark-applied <version>` to record application.

Commands:
    python migration_runner.py status                 # show applied vs pending
    python migration_runner.py apply                  # apply all pending
    python migration_runner.py show <version>         # print SQL of one migration
    python migration_runner.py mark-applied <version> # manually record application

The schema_migrations table itself is bootstrapped on first run via
supabase-py (which works via PostgREST and only needs the service-role key).
"""

import os
import sys
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _supabase_client():
    """Lazy import so a missing supabase-py install doesn't break --help."""
    from supabase import create_client
    if not SUPABASE_URL or not SUPABASE_KEY:
        sys.exit("ERROR: SUPABASE_URL and SUPABASE_KEY must be set in .env")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def _parse_version(filename):
    """Extract the leading numeric version from a migration filename.
    e.g. '0002_add_edgar_filings_source.sql' -> '0002'."""
    m = re.match(r"^(\d+)_", filename)
    return m.group(1) if m else None


def _list_migrations():
    """Return sorted list of (version, path) tuples for all migrations on disk."""
    if not MIGRATIONS_DIR.exists():
        return []
    files = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        v = _parse_version(p.name)
        if v:
            files.append((v, p))
    return files


def _checksum(path):
    """SHA-256 of the file contents — for future drift detection."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _bootstrap_schema_migrations(supabase):
    """
    Ensure the schema_migrations tracking table exists. Self-bootstrap problem:
    we can't run DDL via PostgREST, so we attempt a select first; if it fails
    with a "table does not exist" error, we ask the user to create it manually.
    """
    try:
        supabase.table("schema_migrations").select("version").limit(1).execute()
        return True
    except Exception as e:
        msg = str(e).lower()
        if "does not exist" in msg or "schema_migrations" in msg:
            print("ERROR: schema_migrations table does not exist yet.")
            print("Bootstrap it once by running this SQL in the Supabase SQL editor:\n")
            print("  " + BOOTSTRAP_SQL.replace("\n", "\n  "))
            print("\nThen re-run this command.")
            return False
        # Other error — re-raise
        raise


BOOTSTRAP_SQL = """CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checksum TEXT,
    filename TEXT
);"""


def _applied_versions(supabase):
    """Return set of versions already recorded as applied."""
    result = supabase.table("schema_migrations").select("version").execute()
    return {row["version"] for row in (result.data or [])}


def _record_applied(supabase, version, filename, checksum):
    """Insert a row into schema_migrations after successful application."""
    supabase.table("schema_migrations").upsert({
        "version": version,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "checksum": checksum,
        "filename": filename,
    }, on_conflict="version").execute()


def _execute_sql_via_psycopg2(sql):
    """Auto-apply path: execute SQL via direct Postgres connection."""
    try:
        import psycopg2
    except ImportError:
        sys.exit("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    finally:
        conn.close()


# ─── Commands ────────────────────────────────────────────────────────────

def cmd_status():
    """Show what's applied vs pending."""
    supabase = _supabase_client()
    if not _bootstrap_schema_migrations(supabase):
        return 1
    on_disk = _list_migrations()
    applied = _applied_versions(supabase)

    print(f"\n  Migration mode: {'AUTO (DATABASE_URL set)' if DATABASE_URL else 'MANUAL (DATABASE_URL not set)'}\n")
    print(f"  {'STATUS':<10} {'VERSION':<8} {'FILENAME'}")
    print(f"  {'-'*10} {'-'*8} {'-'*40}")
    for version, path in on_disk:
        status = "applied" if version in applied else "PENDING"
        print(f"  {status:<10} {version:<8} {path.name}")
    pending_count = sum(1 for v, _ in on_disk if v not in applied)
    print(f"\n  {len(on_disk)} total, {len(applied)} applied, {pending_count} pending")
    return 0


def cmd_apply():
    """Apply all pending migrations (auto-mode if DATABASE_URL set)."""
    supabase = _supabase_client()
    if not _bootstrap_schema_migrations(supabase):
        return 1
    on_disk = _list_migrations()
    applied = _applied_versions(supabase)
    pending = [(v, p) for v, p in on_disk if v not in applied]

    if not pending:
        print("Nothing to apply — all migrations up to date.")
        return 0

    if not DATABASE_URL:
        print(f"\n{len(pending)} pending migration(s). DATABASE_URL not set, so manual mode:\n")
        for version, path in pending:
            print(f"  ─── {path.name} ────────────")
            print(path.read_text())
            print()
        print("Copy the SQL above into the Supabase SQL editor, run it, then:")
        for version, _ in pending:
            print(f"  python migration_runner.py mark-applied {version}")
        return 0

    # Auto mode
    for version, path in pending:
        print(f"  applying {path.name}...", end=" ", flush=True)
        sql = path.read_text()
        try:
            _execute_sql_via_psycopg2(sql)
            _record_applied(supabase, version, path.name, _checksum(path))
            print("OK")
        except Exception as e:
            print(f"FAILED: {e}")
            return 1
    print(f"\n{len(pending)} migration(s) applied successfully.")
    return 0


def cmd_show(version):
    """Print the SQL of a specific migration."""
    on_disk = _list_migrations()
    match = next(((v, p) for v, p in on_disk if v == version), None)
    if not match:
        print(f"No migration found for version {version}")
        return 1
    print(match[1].read_text())
    return 0


def cmd_mark_applied(version):
    """Manually record a migration as applied (for the manual workflow)."""
    supabase = _supabase_client()
    if not _bootstrap_schema_migrations(supabase):
        return 1
    on_disk = _list_migrations()
    match = next(((v, p) for v, p in on_disk if v == version), None)
    if not match:
        print(f"No migration found for version {version}")
        return 1
    _, path = match
    _record_applied(supabase, version, path.name, _checksum(path))
    print(f"Marked {path.name} as applied.")
    return 0


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = args[0]
    if cmd == "status":
        return cmd_status()
    if cmd == "apply":
        return cmd_apply()
    if cmd == "show" and len(args) >= 2:
        return cmd_show(args[1])
    if cmd == "mark-applied" and len(args) >= 2:
        return cmd_mark_applied(args[1])
    print(f"Unknown command: {cmd}")
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
