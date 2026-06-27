import os
import sqlite3
import psycopg2
import psycopg2.extras
from pathlib import Path

DATABASE_URL = os.environ.get("DATABASE_URL")
SQLITE_PATH = Path("data/crm.sqlite")

if not DATABASE_URL:
    raise SystemExit("Missing DATABASE_URL environment variable.")
if not SQLITE_PATH.exists():
    raise SystemExit(f"Missing SQLite database at {SQLITE_PATH}")

schema = Path("schema.sql").read_text(encoding="utf-8")

pg = psycopg2.connect(DATABASE_URL)
pg.autocommit = False
pg_cur = pg.cursor()
pg_cur.execute(schema)
pg.commit()

sqlite = sqlite3.connect(SQLITE_PATH)
sqlite.row_factory = sqlite3.Row
s_cur = sqlite.cursor()

tables = [
    "admins",
    "members",
    "events",
    "sessions",
    "attendance",
    "surveys",
    "survey_forms",
    "survey_questions",
]

for table in tables:
    rows = s_cur.execute(f"SELECT * FROM {table}").fetchall()
    if not rows:
        print(f"{table}: 0 rows")
        continue

    cols = rows[0].keys()
    placeholders = ", ".join(["%s"] * len(cols))
    colnames = ", ".join(cols)
    updates = ", ".join([f"{c}=EXCLUDED.{c}" for c in cols if c != "id"])
    sql = f"""
        INSERT INTO {table} ({colnames})
        VALUES ({placeholders})
        ON CONFLICT (id) DO UPDATE SET {updates}
    """

    for row in rows:
        pg_cur.execute(sql, [row[c] for c in cols])
    print(f"{table}: {len(rows)} rows")

# Reset sequences
for table in tables:
    pg_cur.execute(f"""
        SELECT setval(
            pg_get_serial_sequence('{table}', 'id'),
            COALESCE((SELECT MAX(id) FROM {table}), 1),
            true
        )
    """)

pg.commit()
pg_cur.close()
pg.close()
sqlite.close()

print("Migration completed successfully.")