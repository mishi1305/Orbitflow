"""Read-only: prints every table's columns, row count and 2 sample rows. Run: py inspect_db.py"""
import mysql.connector
from db_config import DB_CONFIG

cnx = mysql.connector.connect(**DB_CONFIG)
cur = cnx.cursor()
cur.execute("SHOW TABLES")
for (t,) in cur.fetchall():
    cur.execute(f"DESCRIBE `{t}`")
    cols = cur.fetchall()
    cur.execute(f"SELECT COUNT(*) FROM `{t}`")
    print(f"\n== {t} ({cur.fetchone()[0]} rows)")
    for c in cols:
        print(f"   {c[0]:<24}{c[1]:<18}null={c[2]:<4}key={c[3]}")
    cur.execute(f"SELECT * FROM `{t}` LIMIT 2")
    for r in cur.fetchall():
        print("   sample:", r)
cnx.close()
