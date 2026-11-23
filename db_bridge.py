import sys
import csv
import re
import mysql.connector
from db_config import DB_CONFIG


def norm(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())


def connect():
    return mysql.connector.connect(**DB_CONFIG)


def resolve(cursor, table, id_col, name_col, requested):
    # Table/column names here are fixed constants, not user-provided SQL.
    cursor.execute(f"SELECT {id_col}, {name_col} FROM {table}")
    rows = cursor.fetchall()
    wanted = norm(requested)
    exact = [r for r in rows if norm(str(r[1])) == wanted]
    if len(exact) == 1:
        return exact[0]
    partial = [r for r in rows if norm(str(r[1])).startswith(wanted) or wanted.startswith(norm(str(r[1])))]
    if len(partial) == 1:
        return partial[0]
    options = ", ".join(str(r[1]) for r in rows[:12])
    raise ValueError(f"Could not uniquely match '{requested}' in {table}. Examples: {options}")


def add_task(args):
    if len(args) != 6:
        raise ValueError("Usage: add REGION ROUTE ARRIVAL BURST PRIORITY RESOURCES")
    region_name, route_name = args[0], args[1]
    arrival, burst, priority, resources = map(int, args[2:])
    if arrival < 0 or burst <= 0 or priority <= 0 or resources < 0:
        raise ValueError("Invalid task values.")
    cnx = connect()
    try:
        cur = cnx.cursor()
        region_id, actual_region = resolve(cur, "regions", "region_id", "region_name", region_name)
        route_id, actual_route = resolve(cur, "routes", "route_id", "route_name", route_name)
        cur.execute("SELECT satellite_id FROM routes WHERE route_id=%s", (route_id,))
        sat = cur.fetchone()
        satellite_id = sat[0] if sat else None
        task_name = f"{actual_region} imaging task"
        cur.execute("""INSERT INTO imaging_tasks
            (task_name, region_id, satellite_id, route_id, arrival_time,
             burst_time, priority, status, resources_required)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pending', %s)""",
            (task_name, region_id, satellite_id, route_id, arrival, burst, priority, resources))
        cnx.commit()
        print(f"Saved task to MySQL (task_id={cur.lastrowid})")
    finally:
        cnx.close()


def load_tasks():
    cnx = connect()
    try:
        cur = cnx.cursor()
        cur.execute("""SELECT it.task_id,
                COALESCE(r.region_name, it.task_name),
                COALESCE(rt.route_name, 'UnknownRoute'),
                it.arrival_time, it.burst_time, it.priority,
                COALESCE(it.resources_required, 0)
            FROM imaging_tasks it
            LEFT JOIN regions r ON it.region_id = r.region_id
            LEFT JOIN routes rt ON it.route_id = rt.route_id
            ORDER BY it.task_id""")
        with open("orbitflow_tasks.tsv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            for row in cur.fetchall():
                writer.writerow(["" if v is None else str(v).replace("\t", " ").replace("\n", " ") for v in row])
    finally:
        cnx.close()


def main():
    if len(sys.argv) < 2:
        raise ValueError("Use: py db_bridge.py load OR add ...")
    if sys.argv[1] == "load":
        load_tasks()
    elif sys.argv[1] == "add":
        add_task(sys.argv[2:])
    else:
        raise ValueError("Unknown command")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"OrbitFlow database error: {exc}", file=sys.stderr)
        sys.exit(1)
