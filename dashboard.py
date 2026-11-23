"""OrbitFlow Mission Control - FastAPI + MySQL.  Run: uvicorn dashboard:app --reload"""
import threading
import time
from datetime import datetime
from pathlib import Path
from deadlock_sim import run_demo

import mysql.connector
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

import scheduler
from db_config import DB_CONFIG

BASE = Path(__file__).resolve().parent
PREVIEW_DIR = BASE / "dataset" / "previews"
TOTAL_RESOURCES = 5          # same simulated pool as main.cpp
SECONDS_PER_UNIT = 0.4       # simulation speed: 1 burst unit = 0.4 s

app = FastAPI(title="OrbitFlow Mission Control")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------- database helpers (parameterized only) ----------
def q(sql, params=()):
    cnx = mysql.connector.connect(**DB_CONFIG)
    try:
        cur = cnx.cursor(dictionary=True)
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cnx.close()


def ex(sql, params=()):
    cnx = mysql.connector.connect(**DB_CONFIG)
    try:
        cur = cnx.cursor()
        cur.execute(sql, params)
        cnx.commit()
        return cur.lastrowid
    finally:
        cnx.close()


def log(event, message):
    try:
        ex("INSERT INTO activity_log (logged_at, event_type, message) VALUES (%s,%s,%s)",
           (datetime.now(), event, message[:500]))
    except Exception as e:  # logging must never break the simulation
        print("log error:", e)


def write_scheduling_log(algo, quantum, summary, n_tasks):
    """Best-effort insert into the existing scheduling_logs table, matching columns by name."""
    try:
        cols = q("SELECT COLUMN_NAME AS n, DATA_TYPE AS t, IS_NULLABLE AS nul, COLUMN_DEFAULT AS d, EXTRA AS x "
                 "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='scheduling_logs'",
                 (DB_CONFIG["database"],))
        vals = {}
        for c in cols:
            k = c["n"].lower()
            if "auto_increment" in (c["x"] or ""):
                continue
            if "algo" in k: v = algo
            elif "quantum" in k: v = quantum
            elif "wait" in k: v = summary["avg_waiting"]
            elif "turn" in k: v = summary["avg_turnaround"]
            elif "resp" in k: v = summary["avg_response"]
            elif "complet" in k or "makespan" in k: v = summary["completion_time"]
            elif "count" in k or k in ("tasks", "total_tasks"): v = n_tasks
            elif c["t"] in ("datetime", "timestamp", "date"): v = datetime.now()
            else: v = None
            if v is None and c["nul"] == "NO" and c["d"] is None:
                log("WARNING", f"scheduling_logs not written: cannot fill required column '{c['n']}'")
                return
            if v is not None:
                vals[c["n"]] = v
        if vals:
            ex(f"INSERT INTO scheduling_logs ({','.join('`'+k+'`' for k in vals)}) "
               f"VALUES ({','.join(['%s']*len(vals))})", tuple(vals.values()))
    except Exception as e:
        log("WARNING", f"scheduling_logs not written: {e}")


def ensure_schema():
    """Additive, idempotent: one column + one table. Nothing is dropped or modified."""
    cols = {r["c"] for r in q("SELECT COLUMN_NAME AS c FROM information_schema.COLUMNS "
                              "WHERE TABLE_SCHEMA=%s AND TABLE_NAME='imaging_tasks'", (DB_CONFIG["database"],))}
    if "progress" not in cols:
        ex("ALTER TABLE imaging_tasks ADD COLUMN progress INT NOT NULL DEFAULT 0")
    ex("CREATE TABLE IF NOT EXISTS activity_log (log_id INT AUTO_INCREMENT PRIMARY KEY, "
       "logged_at DATETIME NOT NULL, event_type VARCHAR(40) NOT NULL, message VARCHAR(500) NOT NULL)")
    img = {r["c"] for r in q("SELECT COLUMN_NAME AS c FROM information_schema.COLUMNS "
                             "WHERE TABLE_SCHEMA=%s AND TABLE_NAME='dataset_images'", (DB_CONFIG["database"],))}
    for col, ddl in (("region_name", "VARCHAR(100) NULL"), ("task_id", "INT NULL")):
        if col not in img:
            ex(f"ALTER TABLE dataset_images ADD COLUMN {col} {ddl}")
    # Recover from a server stop mid-run: unfinished work returns to Pending.
    ex("UPDATE imaging_tasks SET status='Pending', progress=0 WHERE status IN ('Scheduled','Processing')")


TASK_SQL = """SELECT it.task_id, it.task_name, it.region_id, r.region_name, it.satellite_id,
       it.route_id, rt.route_name, it.arrival_time, it.burst_time, it.priority,
       COALESCE(it.resources_required,0) AS resources_required, it.status, it.progress
    FROM imaging_tasks it LEFT JOIN regions r ON it.region_id=r.region_id
    LEFT JOIN routes rt ON it.route_id=rt.route_id"""


def sched_input(only_pending=False):
    where = "WHERE LOWER(status)='pending'" if only_pending else ""
    return q(f"SELECT task_id AS id, arrival_time AS arrival, burst_time AS burst, priority, "
             f"COALESCE(resources_required,0) AS res FROM imaging_tasks {where} ORDER BY task_id")


# ---------- mission (controlled simulation) ----------
LOCK = threading.Lock()
M = {"running": False, "stop": False, "algo": None, "quantum": 2, "queue": [], "current": None,
     "progress": 0, "done": [], "total": 0, "allocated": 0, "started": None, "finished": None}


def mission(algo, quantum):
    try:
        tasks = sched_input(only_pending=True)
        res = {t["id"]: t["res"] for t in tasks}
        plan = scheduler.run(tasks, algo, quantum)
        order = [r["id"] for r in plan["rows"]]
        log("SCHEDULER", f"{algo} scheduling started for {len(order)} pending tasks"
            + (f" (quantum={quantum})" if algo == "RR" else ""))
        for tid in order:
            ex("UPDATE imaging_tasks SET status='Scheduled', progress=0 WHERE task_id=%s", (tid,))
            log("SCHEDULED", f"Task {tid} scheduled")
        with LOCK:
            M.update(queue=list(order), done=[], total=len(order), allocated=0)
        for r in plan["rows"]:
            tid, burst = r["id"], r["burst"]
            if M["stop"]:
                break
            need = res[tid]
            if need > TOTAL_RESOURCES:      # deterministic rule: request can never be satisfied
                ex("UPDATE imaging_tasks SET status='Failed', progress=0 WHERE task_id=%s", (tid,))
                log("ERROR", f"Task {tid} failed: requests {need} units, pool is {TOTAL_RESOURCES} (simulated)")
                with LOCK:
                    M["queue"] = [x for x in M["queue"] if x != tid]
                continue
            with LOCK:
                M.update(current=tid, progress=0, allocated=need,
                         queue=[x for x in M["queue"] if x != tid])
            ex("UPDATE imaging_tasks SET status='Processing' WHERE task_id=%s", (tid,))
            log("PROCESSING", f"Task {tid} processing started (burst={burst})")
            log("RESOURCE", f"Allocated {need}/{TOTAL_RESOURCES} simulated resource units to task {tid}")
            for u in range(1, burst + 1):
                time.sleep(SECONDS_PER_UNIT)
                pct = int(u * 100 / burst)
                ex("UPDATE imaging_tasks SET progress=%s WHERE task_id=%s", (pct, tid))
                with LOCK:
                    M["progress"] = pct
            ex("UPDATE imaging_tasks SET status='Completed', progress=100 WHERE task_id=%s", (tid,))
            log("COMPLETED", f"Task {tid} completed; released {need} resource units")
            with LOCK:
                M["done"].append({"id": tid, "start": r["start"], "end": r["completion"]})
                M.update(current=None, allocated=0)
        left = q("SELECT task_id FROM imaging_tasks WHERE status='Scheduled'")
        for x in left:
            ex("UPDATE imaging_tasks SET status='Pending', progress=0 WHERE task_id=%s", (x["task_id"],))
        if not M["stop"]:
            write_scheduling_log(algo, quantum if algo == "RR" else None, plan["summary"], len(order))
        log("SCHEDULER", "Mission stopped by operator" if M["stop"] else
            f"Scheduling run completed: {len(M['done'])} tasks finished")
    except Exception as e:
        log("ERROR", f"Mission failed: {e}")
    finally:
        with LOCK:
            M.update(running=False, current=None, finished=datetime.now().isoformat(timespec="seconds"))


class MissionIn(BaseModel):
    algorithm: str = "FCFS"
    quantum: int = Field(2, gt=0, le=100)


@app.post("/api/mission/start")
def mission_start(body: MissionIn):
    algo = body.algorithm.upper()
    if algo not in scheduler.ALGOS:
        raise HTTPException(400, "Unknown algorithm")
    with LOCK:
        if M["running"]:
            raise HTTPException(409, "A mission is already running")
        if not q("SELECT 1 AS x FROM imaging_tasks WHERE LOWER(status)='pending' LIMIT 1"):
            raise HTTPException(400, "No pending tasks to process")
        M.update(running=True, stop=False, algo=algo, quantum=body.quantum, progress=0,
                 started=datetime.now().isoformat(timespec="seconds"), finished=None, done=[], queue=[])
    threading.Thread(target=mission, args=(algo, body.quantum), daemon=True).start()
    return {"started": True}


@app.post("/api/mission/stop")
def mission_stop():
    M["stop"] = True
    return {"stopping": True}


@app.get("/api/mission/state")
def mission_state():
    with LOCK:
        s = dict(M)
    s["pending"] = q("SELECT COUNT(*) AS n FROM imaging_tasks WHERE LOWER(status)='pending'")[0]["n"]
    s["completed_total"] = q("SELECT COUNT(*) AS n FROM imaging_tasks WHERE LOWER(status)='completed'")[0]["n"]
    s["current_task"] = (q(TASK_SQL + " WHERE it.task_id=%s", (s["current"],)) or [None])[0] if s["current"] else None
    return s


# ---------- data endpoints ----------
@app.get("/api/overview")
def overview():
    try:
        n = lambda t: q(f"SELECT COUNT(*) AS n FROM `{t}`")[0]["n"]
        st = {r["s"].lower(): r["n"] for r in q(
            "SELECT COALESCE(status,'unknown') AS s, COUNT(*) AS n FROM imaging_tasks GROUP BY s")}
        sats = q("SELECT COUNT(DISTINCT satellite_id) AS n FROM imaging_tasks WHERE satellite_id IS NOT NULL")[0]["n"]
        return {"connected": True, "time": datetime.now().isoformat(timespec="seconds"),
                "counts": {"tasks": n("imaging_tasks"), "satellites": n("satellites"), "active_satellites": sats,
                           "regions": n("regions"), "routes": n("routes"), "images": n("dataset_images"),
                           "runs": q("SELECT COUNT(*) AS n FROM activity_log WHERE message LIKE 'Scheduling run completed%%'")[0]["n"]},
                "status": st, "mission_running": M["running"], "allocated": M["allocated"],
                "total_resources": TOTAL_RESOURCES}
    except mysql.connector.Error as e:
        return {"connected": False, "error": str(e)}


@app.get("/api/lookups")
def lookups():
    return {"regions": q("SELECT region_id, region_name FROM regions ORDER BY region_name"),
            "routes": q("SELECT route_id, route_name, satellite_id FROM routes ORDER BY route_name"),
            "satellites": [r["satellite_id"] for r in q("SELECT satellite_id FROM satellites ORDER BY satellite_id")]}


SORTS = {"task_id": "it.task_id", "arrival": "it.arrival_time", "burst": "it.burst_time", "priority": "it.priority"}


@app.get("/api/tasks")
def tasks(q_: str = "", status: str = "", priority: int = 0, region: int = 0, satellite: int = 0,
          sort: str = "task_id", dir: str = "desc", page: int = 1, size: int = 25):
    where, p = [], []
    if q_:
        where.append("(it.task_name LIKE %s OR r.region_name LIKE %s OR rt.route_name LIKE %s OR CAST(it.task_id AS CHAR)=%s)")
        p += [f"%{q_}%"] * 3 + [q_]
    if status:
        where.append("LOWER(it.status)=%s"); p.append(status.lower())
    if priority:
        where.append("it.priority=%s"); p.append(priority)
    if region:
        where.append("it.region_id=%s"); p.append(region)
    if satellite:
        where.append("it.satellite_id=%s"); p.append(satellite)
    w = (" WHERE " + " AND ".join(where)) if where else ""
    order = f"ORDER BY {SORTS.get(sort, 'it.task_id')} {'ASC' if dir == 'asc' else 'DESC'}, it.task_id"
    size = max(1, min(size, 200))
    total = q("SELECT COUNT(*) AS n FROM imaging_tasks it LEFT JOIN regions r ON it.region_id=r.region_id "
              "LEFT JOIN routes rt ON it.route_id=rt.route_id" + w, p)[0]["n"]
    rows = q(f"{TASK_SQL}{w} {order} LIMIT %s OFFSET %s", p + [size, (max(page, 1) - 1) * size])
    return {"total": total, "page": page, "size": size, "rows": rows}


@app.get("/api/tasks/{task_id}")
def task_detail(task_id: int):
    rows = q(TASK_SQL + " WHERE it.task_id=%s", (task_id,))
    if not rows:
        raise HTTPException(404, "Task not found")
    sched = {}
    for a, res in scheduler.compare(sched_input()).items():
        mine = next((r for r in res["rows"] if r["id"] == task_id), None)
        if mine:
            sched[a] = {k: mine[k] for k in ("start", "waiting", "response", "completion", "turnaround")}
    return {"task": rows[0], "scheduling_all_tasks_quantum2": sched}


class TaskIn(BaseModel):
    region_id: int
    route_id: int
    arrival_time: int = Field(ge=0, le=100000)
    burst_time: int = Field(gt=0, le=1000)
    priority: int = Field(gt=0, le=100)
    resources_required: int = Field(ge=0, le=100)


@app.post("/api/tasks")
def add_task(t: TaskIn):
    reg = q("SELECT region_name FROM regions WHERE region_id=%s", (t.region_id,))
    rt = q("SELECT satellite_id FROM routes WHERE route_id=%s", (t.route_id,))
    if not reg or not rt:
        raise HTTPException(400, "Unknown region or route")
    tid = ex("""INSERT INTO imaging_tasks (task_name, region_id, satellite_id, route_id, arrival_time,
                burst_time, priority, status, resources_required) VALUES (%s,%s,%s,%s,%s,%s,%s,'Pending',%s)""",
             (f"{reg[0]['region_name']} imaging task", t.region_id, rt[0]["satellite_id"], t.route_id,
              t.arrival_time, t.burst_time, t.priority, t.resources_required))
    log("TASK_CREATED", f"New imaging task {tid} created for {reg[0]['region_name']}")
    log("QUEUE", f"Task {tid} added to queue (Pending)")
    return {"task_id": tid}


class SchedIn(BaseModel):
    algorithm: str = "FCFS"
    quantum: int = Field(2, gt=0, le=100)
    scope: str = "all"


@app.post("/api/schedule")
def run_schedule(b: SchedIn):
    data = sched_input(only_pending=(b.scope == "pending"))
    if not data:
        raise HTTPException(400, "No tasks in the selected set")
    try:
        sel = scheduler.run(data, b.algorithm, b.quantum)
    except ValueError as e:
        raise HTTPException(400, str(e))
    cmp_ = {a: r["summary"] for a, r in scheduler.compare(data, b.quantum).items()}
    return {"selected": sel, "comparison": cmp_, "task_count": len(data)}


@app.get("/api/resources")
def resources():
    demand = q("SELECT task_id, COALESCE(resources_required,0) AS need, status FROM imaging_tasks ORDER BY task_id")
    avail, blocked = TOTAL_RESOURCES, 0     # same sequential demo as main.cpp resourceSimulation()
    for d in demand:
        if d["need"] <= avail:
            avail -= d["need"]
        else:
            blocked += 1
    try:
        events = q("SELECT * FROM resource_logs ORDER BY 1 DESC LIMIT 50")
    except mysql.connector.Error:
        events = []
    live = q("SELECT message, logged_at FROM activity_log WHERE event_type='RESOURCE' ORDER BY log_id DESC LIMIT 30")
    return {"simulated": True, "total": TOTAL_RESOURCES, "allocated": M["allocated"],
            "available": TOTAL_RESOURCES - M["allocated"], "demand": demand,
            "demo_unallocated": avail, "demo_blocked": blocked, "resource_logs": events, "live_events": live}

@app.get("/api/deadlock")
def deadlock():
    tasks = q("""
        SELECT task_id, task_name, status
        FROM imaging_tasks
        ORDER BY task_id DESC
        LIMIT 20
    """)

    result = run_demo(tasks)

    return {
        "source": "OrbitFlow Database Tasks",
        "tasks_checked": len(tasks),
        "result": result
    }

@app.get("/api/satellites")
def satellites():
    sats = q("SELECT * FROM satellites")
    assign = q("""SELECT it.satellite_id, it.region_id, r.region_name, rt.route_name, COUNT(*) AS n
        FROM imaging_tasks it LEFT JOIN regions r ON it.region_id=r.region_id
        LEFT JOIN routes rt ON it.route_id=rt.route_id GROUP BY it.satellite_id, it.region_id, r.region_name, rt.route_name""")
    return {"satellites": sats, "assignments": assign, "routes": q("SELECT * FROM routes"), "regions": q("SELECT * FROM regions")}


@app.get("/api/images")
def images():
    return q("SELECT * FROM dataset_images ORDER BY image_id")


@app.get("/api/logs")
def logs(limit: int = 150):
    return q("SELECT log_id, logged_at, event_type, message FROM activity_log ORDER BY log_id DESC LIMIT %s",
             (max(1, min(limit, 500)),))


@app.get("/api/image/{image_id}")
def get_image(image_id: int):
    rows = q("SELECT image_path FROM dataset_images WHERE image_id=%s", (image_id,))
    if not rows:
        raise HTTPException(404, "Image record not found")
    p = Path(rows[0]["image_path"])
    p = (p if p.is_absolute() else BASE / p).resolve()
    if not p.is_file():
        raise HTTPException(404, "Image file missing")
    if p.suffix.lower() in (".tif", ".tiff"):        # browsers cannot show GeoTIFF: cache a PNG preview
        out = PREVIEW_DIR / f"{p.stem}_gallery.png"
        if not out.exists():
            import numpy as np, rasterio
            from PIL import Image
            PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
            with rasterio.open(p) as src:
                d = src.read(masked=True).astype("float32").filled(np.nan)
            ch = d[:3] if d.shape[0] >= 3 else d[:1]
            out_ch = []
            for b in ch:
                ok = np.isfinite(b)
                lo, hi = np.percentile(b[ok], [2, 98]) if ok.any() else (0, 1)
                out_ch.append(np.where(ok, np.clip((b - lo) / ((hi - lo) or 1), 0, 1), 0))
            arr = (np.dstack(out_ch if len(out_ch) == 3 else out_ch * 3) * 255).astype("uint8")
            Image.fromarray(arr).save(out)
        return FileResponse(str(out))
    return FileResponse(str(p))


@app.on_event("startup")
def startup():
    ensure_schema()


@app.get("/", response_class=HTMLResponse)
def home():
    return HTML


HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>OrbitFlow | Mission Control</title>
<style>
:root{
    --bg:#090A10;
    --p:#111827;
    --p2:#17233B;
    --b:#293957;
    --t:#F2F3F5;
    --m:#A6CFD5;
    --c:#A6CFD5;
    --g:#C2E7D9;
    --o:#8FADEB;
    --y:#C2E7D9;
    --r:#E78C98;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
    font:13px 'Segoe UI',Arial,sans-serif;
    background:var(--bg);
    color:var(--t);
    display:flex;
    min-height:100vh;
    position:relative;
    isolation:isolate;
}
/* Full-page starfield: decorative only, never blocks clicks */
body::before{
    content:"";
    position:fixed;
    inset:0;
    z-index:-1;
    pointer-events:none;
    background-color:#090A10;
    background-image:
        radial-gradient(1px 1px at 10% 15%, #F2F3F5 99%, transparent),
        radial-gradient(1.5px 1.5px at 25% 75%, #A6CFD5 99%, transparent),
        radial-gradient(1px 1px at 42% 30%, #FFFFFF 99%, transparent),
        radial-gradient(2px 2px at 65% 65%, #A6CFD5 99%, transparent),
        radial-gradient(1px 1px at 82% 20%, #FFFFFF 99%, transparent),
        radial-gradient(1.5px 1.5px at 92% 82%, #C2E7D9 99%, transparent),
        radial-gradient(1px 1px at 55% 90%, #FFFFFF 99%, transparent),
        radial-gradient(1px 1px at 15% 48%, #A6CFD5 99%, transparent);
    background-size:300px 300px,400px 400px,350px 350px,450px 450px,
                    300px 300px,400px 400px,350px 350px,450px 450px;
    animation:starGlow 6s ease-in-out infinite alternate;
}
/* A very faint blue atmospheric glow behind the interface */
body::after{
    content:"";
    position:fixed;
    inset:0;
    z-index:-1;
    pointer-events:none;
    background:
        radial-gradient(ellipse at 78% 12%, rgba(38,64,139,.16), transparent 38%),
        radial-gradient(ellipse at 18% 82%, rgba(15,8,75,.20), transparent 42%);
}
@keyframes starGlow{
    from{opacity:.42;}
    to{opacity:.95;}
}
aside{width:220px;background:rgba(5,6,15,.94);border-right:1px solid var(--b);padding:20px 12px;flex-shrink:0;position:sticky;top:0;height:100vh;overflow:hidden}
aside:before{content:"";position:absolute;inset:0;pointer-events:none;opacity:.25;background-image:radial-gradient(1px 1px at 18% 14%,#F2F3F5 99%,transparent),radial-gradient(1px 1px at 74% 22%,#A6CFD5 99%,transparent),radial-gradient(1px 1px at 38% 38%,#F2F3F5 99%,transparent),radial-gradient(1px 1px at 86% 52%,#F2F3F5 99%,transparent),radial-gradient(1px 1px at 22% 67%,#A6CFD5 99%,transparent),radial-gradient(1px 1px at 65% 81%,#F2F3F5 99%,transparent),radial-gradient(1px 1px at 45% 92%,#F2F3F5 99%,transparent)}
aside>*{position:relative;z-index:1}.logo{font-weight:800;font-size:19px;color:#fff;letter-spacing:2px}.sub{font-size:9px;color:var(--m);letter-spacing:2px;margin:4px 0 24px}
aside a{display:block;padding:10px 12px;margin:3px 0;color:var(--m);text-decoration:none;border-left:2px solid transparent;cursor:pointer;transition:.15s}aside a:before{content:"✦";font-size:9px;color:#cad9eb;opacity:.55;margin-right:8px}aside a:hover{color:#fff;background:var(--p2)}aside a.on{color:#fff;border-left-color:var(--c);background:rgba(23,35,59,.92);box-shadow:inset 0 0 16px #A6CFD50b}
main{flex:1;padding:22px 26px;min-width:0}.top{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:18px}h1{font-size:20px;font-weight:600;color:#fff}h2{font-size:12px;text-transform:uppercase;letter-spacing:1.5px;color:#A6CFD5;margin-bottom:12px;font-weight:600}
.pill{display:inline-block;padding:3px 9px;border-radius:3px;font-size:11px;border:1px solid var(--b)}.ok{color:var(--g);border-color:#1d5a45}.bad{color:var(--r);border-color:#6b2a2a}.warn{color:var(--o);border-color:#6b4219}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-bottom:16px}.card,.panel{background:rgba(17,24,39,.88);border:1px solid rgba(166,207,213,.18);border-radius:8px;padding:14px;backdrop-filter:blur(5px)}.panel{margin-bottom:14px}.card small{color:var(--m);display:block;font-size:11px}.card b{font-size:24px;display:block;margin-top:6px;font-weight:600;color:#fff}
table{width:100%;border-collapse:collapse}th{color:#cad9eb;text-align:left;padding:8px;background:var(--p2);font-weight:600;font-size:11px}td{padding:8px;border-bottom:1px solid var(--b)}tr.cl{cursor:pointer}tr.cl:hover td{background:var(--p2)}.wrap{overflow-x:auto}
input,select,button{background:var(--p2);color:var(--t);border:1px solid var(--b);padding:7px 10px;border-radius:3px;font:inherit}button{background:#26408B;border-color:#4969A9;cursor:pointer;transition:.15s}button:hover{background:#3457A0}button.sec{background:var(--p2);border-color:var(--b)}button:disabled{opacity:.5;cursor:default}.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.pb{height:8px;background:var(--p2);border-radius:2px;overflow:hidden;min-width:70px}.pb i{display:block;height:100%;background:var(--c);transition:width .4s}.sk{height:60px;background:linear-gradient(90deg,var(--p) 25%,var(--p2) 50%,var(--p) 75%);background-size:200%;animation:sk 1.2s infinite;border-radius:4px}@keyframes sk{to{background-position:-200% 0}}
.st-pending{color:var(--y)}.st-scheduled{color:var(--o)}.st-processing{color:var(--c)}.st-completed{color:var(--g)}.gantt{display:flex;height:34px;position:relative;margin:6px 0}.gantt div{height:100%;font-size:9px;color:#06101c;display:flex;align-items:center;justify-content:center;overflow:hidden;border-right:1px solid #0006}.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:12px}.row{display:flex;align-items:center;gap:8px;margin:6px 0}.row span:first-child{width:75px;color:var(--m)}.row .pb{flex:1;height:16px}.row .pb i{display:flex;align-items:center;justify-content:flex-end;padding-right:4px;font-size:10px;color:#06101c}
.gal{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}.gi{background:var(--p);border:1px solid var(--b);cursor:pointer}.gi img{width:100%;height:140px;object-fit:cover;background:var(--p2);display:block}.gi div{padding:8px}.modal{position:fixed;inset:0;background:#000b;display:none;align-items:center;justify-content:center;z-index:9}.modal.on{display:flex}.mb{background:var(--p);border:1px solid var(--b);padding:20px;max-width:min(900px,92vw);max-height:90vh;overflow:auto;width:560px}.mb img{max-width:100%;max-height:70vh;display:block;margin:auto}.chip{display:inline-block;background:var(--p2);border:1px solid var(--b);padding:2px 7px;margin:2px;border-radius:3px}section.sec{display:none}section.sec.on{display:block}#err{color:var(--r);margin-bottom:10px}
@media(max-width:760px){body{display:block}aside{width:100%;height:auto;position:static;display:flex;flex-wrap:wrap;padding:10px}aside a{padding:7px 9px}.logo,.sub{display:none}main{padding:14px}}
</style></head><body>
<aside><div class="logo">◉ ORBITFLOW</div><div class="sub">MISSION CONTROL</div>
<a data-p="overview">▦ Command Center</a><a data-p="tasks">▤ Imaging Tasks</a><a data-p="sched">⏱ Process Scheduling</a>
<a data-p="live">◉ Live Processing</a><a data-p="res">⚙ Resource Management</a><a data-p="sat">✦ Satellite &amp; Routes</a>
<a data-p="gallery">▧ Dataset Gallery</a><a data-p="logs">≡ Activity Logs</a></aside>
<main>
<div class="top"><h1 id="title"></h1><div><span class="pill" id="db">DB …</span> <span class="pill" id="api">API …</span>
<span class="pill" id="upd">—</span> <button class="sec" onclick="refresh(true)">↻ Refresh</button></div></div><div id="err"></div>

<section class="sec" id="overview"><div class="grid" id="cards"><div class="sk"></div><div class="sk"></div><div class="sk"></div><div class="sk"></div></div>
<div class="panel"><h2>Resource utilization (simulated pool)</h2><div class="pb" style="height:14px"><i id="ru" style="width:0"></i></div><p id="rut" style="margin-top:6px;color:var(--m)"></p></div>
<div class="panel"><h2>Task status distribution</h2><div id="dist"></div></div></section>

<section class="sec" id="tasks"><div class="panel"><div class="bar">
<input id="f_q" placeholder="Search name / region / route / ID"><select id="f_s"><option value="">All status</option><option>pending</option><option>scheduled</option><option>processing</option><option>completed</option></select>
<input id="f_p" type="number" min="1" placeholder="Priority" style="width:90px"><select id="f_r"></select><select id="f_sat"></select>
<select id="f_sort"><option value="task_id">Sort: Task ID</option><option value="arrival">Arrival</option><option value="burst">Burst</option><option value="priority">Priority</option></select>
<select id="f_dir"><option value="desc">Desc</option><option value="asc">Asc</option></select><button onclick="pg=1;loadTasks()">Apply</button></div>
<div class="wrap"><table><thead><tr><th>ID</th><th>Task</th><th>Region</th><th>Sat</th><th>Route</th><th>Arrival</th><th>Burst</th><th>Prio</th><th>Res</th><th>Status</th><th>Progress</th></tr></thead><tbody id="trows"></tbody></table></div>
<div class="bar" style="margin-top:10px"><button class="sec" onclick="pg=Math.max(1,pg-1);loadTasks()">‹ Prev</button><span id="pginfo"></span><button class="sec" onclick="pg++;loadTasks()">Next ›</button></div></div>
<div class="panel"><h2>Add imaging task</h2><div class="bar"><select id="a_reg"></select><select id="a_rt"></select>
<input id="a_ar" type="number" min="0" placeholder="Arrival" style="width:90px"><input id="a_bu" type="number" min="1" placeholder="Burst" style="width:90px">
<input id="a_pr" type="number" min="1" placeholder="Priority" style="width:90px"><input id="a_rs" type="number" min="0" placeholder="Resources" style="width:100px"><button onclick="addTask()">Add task</button></div><div id="amsg"></div></div></section>

<section class="sec" id="sched"><div class="panel"><div class="bar"><select id="s_alg"><option value="FCFS">FCFS</option><option value="SJF">SJF</option><option value="PRIORITY">Priority</option><option value="RR">Round Robin</option></select>
<label>Quantum <input id="s_q" type="number" min="1" value="2" style="width:70px"></label><select id="s_sc"><option value="all">All tasks</option><option value="pending">Pending tasks only</option></select><button onclick="runSched()">Run Scheduling</button></div>
<div id="sres" style="color:var(--m)">Choose an algorithm and run scheduling. Results are computed from the tasks in MySQL (time units).</div></div></section>

<section class="sec" id="live"><div class="panel"><div class="bar"><select id="l_alg"><option value="FCFS">FCFS</option><option value="SJF">SJF</option><option value="PRIORITY">Priority</option><option value="RR">Round Robin</option></select>
<label>Quantum <input id="l_q" type="number" min="1" value="2" style="width:70px"></label><button id="startb" onclick="startMission()">▶ Run Mission</button><button class="sec" onclick="api('/api/mission/stop',{method:'POST'})">■ Stop</button></div>
<p style="color:var(--m)">Controlled simulation: each burst unit takes 0.4 s. No real satellite communication occurs.</p></div><div class="panel" id="livebox"></div></section>

<section class="sec" id="res"><div class="panel" id="resbox"></div></section>
<section class="sec" id="sat"><div class="panel" id="satbox"></div></section>
<section class="sec" id="gallery"><div class="panel"><div class="bar"><input id="g_q" placeholder="Search images" oninput="drawGal()"><select id="g_t" onchange="drawGal()"></select></div><div class="gal" id="galbox"></div></div></section>
<section class="sec" id="logs"><div class="panel"><div class="wrap"><table><thead><tr><th>Time</th><th>Event</th><th>Message</th></tr></thead><tbody id="logrows"></tbody></table></div></div></section>
</main><div class="modal" id="modal" onclick="if(event.target===this)this.classList.remove('on')"><div class="mb" id="mbody"></div></div>
<script>
const $=s=>document.querySelector(s),esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const api=async(u,o)=>{const r=await fetch(u,o);const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(typeof j.detail==="string"?j.detail:JSON.stringify(j.detail||r.statusText));return j};
const TITLES={overview:"Command Center",tasks:"Imaging Tasks",sched:"Process Scheduling",live:"Live Processing",res:"Resource Management",sat:"Satellite & Routes",gallery:"Dataset Gallery",logs:"Activity Logs"};
const col=id=>`hsl(${(id*47)%360},70%,62%)`,ALG={FCFS:"FCFS",SJF:"SJF",PRIORITY:"Priority",RR:"Round Robin"};
let page="overview",pg=1,IMGS=[],busy=false,DEADLOCK_RESULT=null;
const st=s=>`<span class="st-${String(s).toLowerCase()}">${esc(s)}</span>`;
function go(p){page=p;document.querySelectorAll("section.sec").forEach(e=>e.classList.toggle("on",e.id===p));
 document.querySelectorAll("aside a").forEach(a=>a.classList.toggle("on",a.dataset.p===p));$("#title").textContent=TITLES[p];location.hash=p;refresh(true)}
document.querySelectorAll("aside a").forEach(a=>a.onclick=()=>go(a.dataset.p));
async function refresh(force){if(busy&&!force)return;busy=true;$("#err").textContent="";
 try{const o=await api("/api/overview");$("#db").textContent=o.connected?"● MySQL connected":"● MySQL down";$("#db").className="pill "+(o.connected?"ok":"bad");
  $("#api").textContent="● Backend operational";$("#api").className="pill ok";$("#upd").textContent="Updated "+new Date().toLocaleTimeString();
  if(!o.connected)throw new Error(o.error);
  if(page==="overview")drawOverview(o);if(page==="tasks")await loadTasks();if(page==="live")await drawLive();
  if(page==="res")await drawRes();if(page==="sat")await drawSat();if(page==="gallery")await loadGal();if(page==="logs")await drawLogs();
 }catch(e){$("#err").textContent="Error: "+e.message;$("#api").textContent="● Backend error";$("#api").className="pill bad"}busy=false}
function drawOverview(o){const c=o.counts,s=o.status,n=k=>s[k]||0,items=[["Imaging tasks",c.tasks],["Pending",n("pending")],["Scheduled",n("scheduled")],["Processing",n("processing")],["Completed",n("completed")],["Failed",n("failed")],
 ["Active satellites",c.active_satellites+" / "+c.satellites],["Regions",c.regions],["Routes",c.routes],["Dataset images",c.images],["Scheduling runs",c.runs]];
 $("#cards").innerHTML=items.map(x=>`<div class="card"><small>${x[0]}</small><b>${esc(x[1])}</b></div>`).join("");
 const pct=Math.round(o.allocated*100/o.total_resources);$("#ru").style.width=pct+"%";$("#rut").textContent=`${o.allocated}/${o.total_resources} units allocated (${pct}%) — ${o.mission_running?"mission running":"idle"}`;
 const mx=Math.max(1,...Object.values(s));$("#dist").innerHTML=Object.entries(s).map(([a,b])=>`<div class="row"><span>${esc(a)}</span><div class="pb"><i style="width:${b*100/mx}%"></i></div><span>${b}</span></div>`).join("")}
async function fillLookups(){if(window.LK)return;LK=await api("/api/lookups");
 $("#f_r").innerHTML='<option value="0">All regions</option>'+LK.regions.map(r=>`<option value="${r.region_id}">${esc(r.region_name)}</option>`).join("");
 $("#f_sat").innerHTML='<option value="0">All satellites</option>'+LK.satellites.map(r=>`<option value="${r}">Sat ${r}</option>`).join("");
 $("#a_reg").innerHTML=LK.regions.map(r=>`<option value="${r.region_id}">${esc(r.region_name)}</option>`).join("");
 $("#a_rt").innerHTML=LK.routes.map(r=>`<option value="${r.route_id}">${esc(r.route_name)}</option>`).join("")}
async function loadTasks(){await fillLookups();const p=new URLSearchParams({q_:$("#f_q").value,status:$("#f_s").value,priority:$("#f_p").value||0,region:$("#f_r").value,satellite:$("#f_sat").value,sort:$("#f_sort").value,dir:$("#f_dir").value,page:pg,size:25});
 const d=await api("/api/tasks?"+p),last=Math.max(1,Math.ceil(d.total/d.size));if(pg>last){pg=last;return loadTasks()}
 $("#pginfo").textContent=`Page ${pg} / ${last} — ${d.total} tasks`;
 $("#trows").innerHTML=d.rows.map(t=>`<tr class="cl" onclick="taskModal(${t.task_id})"><td>${t.task_id}</td><td>${esc(t.task_name)}</td><td>${esc(t.region_name)}</td><td>${esc(t.satellite_id)}</td><td>${esc(t.route_name)}</td><td>${t.arrival_time}</td><td>${t.burst_time}</td><td>${t.priority}</td><td>${t.resources_required}</td><td>${st(t.status)}</td><td><div class="pb"><i style="width:${t.progress||0}%"></i></div></td></tr>`).join("")||'<tr><td colspan="11">No matching tasks</td></tr>'}
async function taskModal(id){const d=await api("/api/tasks/"+id),t=d.task;
 $("#mbody").innerHTML=`<h2>Task ${t.task_id} — ${esc(t.task_name)}</h2><table>${["region_name","satellite_id","route_name","arrival_time","burst_time","priority","resources_required","status","progress"].map(k=>`<tr><td style="color:var(--m)">${k.replace(/_/g," ")}</td><td>${esc(t[k])}</td></tr>`).join("")}</table>
 <h2 style="margin-top:14px">Scheduling info (all DB tasks, RR quantum 2)</h2><table><tr><th>Algo</th><th>Start</th><th>Wait</th><th>Resp</th><th>Done</th><th>TAT</th></tr>${Object.entries(d.scheduling_all_tasks_quantum2).map(([a,r])=>`<tr><td>${ALG[a]}</td><td>${r.start}</td><td>${r.waiting}</td><td>${r.response}</td><td>${r.completion}</td><td>${r.turnaround}</td></tr>`).join("")}</table>`;$("#modal").classList.add("on")}
async function addTask(){const v=i=>$(i).value,b={region_id:+v("#a_reg"),route_id:+v("#a_rt"),arrival_time:+v("#a_ar"),burst_time:+v("#a_bu"),priority:+v("#a_pr"),resources_required:+v("#a_rs")};
 const bad=[v("#a_ar"),v("#a_bu"),v("#a_pr"),v("#a_rs")].some(x=>x===""||!Number.isInteger(+x))||b.arrival_time<0||b.burst_time<1||b.priority<1||b.resources_required<0;
 if(bad){$("#amsg").innerHTML='<span style="color:var(--r)">Arrival ≥ 0, burst ≥ 1, priority ≥ 1, resources ≥ 0 (whole numbers).</span>';return}
 try{const r=await api("/api/tasks",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)});$("#amsg").innerHTML=`<span style="color:var(--g)">Saved task ${r.task_id} to MySQL.</span>`;pg=1;loadTasks()}catch(e){$("#amsg").innerHTML=`<span style="color:var(--r)">${esc(e.message)}</span>`}}
function gantt(segs){const end=Math.max(...segs.map(s=>s.end)),sc=Math.max(10,Math.min(40,1100/end));let t=0,h="";
 for(const s of segs){if(s.start>t)h+=`<div style="width:${(s.start-t)*sc}px;background:#1f2c47" title="idle"></div>`;h+=`<div style="width:${(s.end-s.start)*sc}px;background:${col(s.id)}" title="Task ${s.id}: ${s.start}–${s.end}">${s.id}</div>`;t=s.end}
 return `<div class="wrap"><div class="gantt" style="width:${end*sc}px">${h}</div><div style="color:var(--m);font-size:10px">time 0 → ${end} units (hover a block for its interval)</div></div>`}
function chart(title,key,cmp,unit){const mx=Math.max(1,...Object.values(cmp).map(x=>x[key]));
 return `<div class="card"><h2>${title}</h2>${Object.entries(cmp).map(([a,x])=>`<div class="row"><span>${ALG[a]}</span><div class="pb"><i style="width:${x[key]*100/mx}%">${x[key]}</i></div></div>`).join("")}<small>Y: algorithm · X: ${unit}</small></div>`}
async function runSched(){try{const d=await api("/api/schedule",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({algorithm:$("#s_alg").value,quantum:+$("#s_q").value,scope:$("#s_sc").value})});
 const s=d.selected,m=s.summary;$("#sres").innerHTML=`<div class="grid">${[["Avg waiting",m.avg_waiting],["Avg turnaround",m.avg_turnaround],["Avg response",m.avg_response],["Completion time",m.completion_time]].map(x=>`<div class="card"><small>${x[0]} (units)</small><b>${x[1]}</b></div>`).join("")}</div>
 <h2>Gantt — ${ALG[s.algorithm]}${s.quantum?" (quantum "+s.quantum+", one block per time slice)":""} · ${d.task_count} tasks</h2>${gantt(s.segments)}
 <h2 style="margin-top:14px">Algorithm comparison (RR quantum ${$("#s_q").value})</h2><div class="charts">${chart("Average waiting time","avg_waiting",d.comparison,"time units")}${chart("Average turnaround time","avg_turnaround",d.comparison,"time units")}${chart("Average response time","avg_response",d.comparison,"time units")}${chart("Completion time","completion_time",d.comparison,"time units")}</div>
 <h2 style="margin-top:14px">Execution order &amp; task metrics</h2><div class="wrap"><table><tr><th>#</th><th>Task</th><th>Arrival</th><th>Burst</th><th>Prio</th><th>Start</th><th>Waiting</th><th>Response</th><th>Completion</th><th>Turnaround</th></tr>${s.rows.map((r,i)=>`<tr><td>${i+1}</td><td>${r.id}</td><td>${r.arrival}</td><td>${r.burst}</td><td>${r.priority}</td><td>${r.start}</td><td>${r.waiting}</td><td>${r.response}</td><td>${r.completion}</td><td>${r.turnaround}</td></tr>`).join("")}</table></div>`}
 catch(e){$("#sres").innerHTML=`<span style="color:var(--r)">${esc(e.message)}</span>`}}
async function startMission(){try{await api("/api/mission/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({algorithm:$("#l_alg").value,quantum:+$("#l_q").value})});drawLive()}catch(e){$("#err").textContent=e.message}}
async function drawLive(){const s=await api("/api/mission/state");$("#startb").disabled=s.running;const c=s.current_task;
 $("#livebox").innerHTML=`<div class="grid"><div class="card"><small>State</small><b style="font-size:16px">${s.running?"RUNNING":"IDLE"}</b></div><div class="card"><small>Algorithm</small><b style="font-size:16px">${s.algo?ALG[s.algo]:"—"}</b></div><div class="card"><small>Completed (all time)</small><b>${s.completed_total}</b></div><div class="card"><small>Remaining pending</small><b>${s.pending}</b></div><div class="card"><small>This run</small><b>${s.done.length}/${s.total}</b></div></div>
 <h2>Running task</h2>${c?`<p>Task ${c.task_id} — ${esc(c.task_name)} · burst ${c.burst_time} · ${st(c.status)}</p><div class="pb" style="height:14px"><i style="width:${s.progress}%"></i></div><p>${s.progress}%</p>`:'<p style="color:var(--m)">No task executing.</p>'}
 <h2 style="margin-top:14px">Processing queue (Scheduled → next)</h2><div>${s.queue.slice(0,40).map(i=>`<span class="chip st-scheduled">${i}</span>`).join("")||"—"}${s.queue.length>40?" …+"+(s.queue.length-40):""}</div>
 <h2 style="margin-top:14px">Execution timeline (this run)</h2>${s.done.length?gantt(s.done):'<p style="color:var(--m)">Empty until tasks complete.</p>'}`}
async function drawRes(){
 const r=await api("/api/resources"),pct=Math.round(r.allocated*100/r.total);

 $("#resbox").innerHTML=`
 <p class="pill warn">SIMULATED resource pool (same model as main.cpp: ${r.total} units)</p>

 <div class="grid" style="margin-top:12px">
  <div class="card"><small>Total</small><b>${r.total}</b></div>
  <div class="card"><small>Available</small><b>${r.available}</b></div>
  <div class="card"><small>Allocated</small><b>${r.allocated}</b></div>
  <div class="card"><small>Utilization</small><b>${pct}%</b></div>
 </div>

 <div class="pb" style="height:14px">
  <i style="width:${pct}%"></i>
 </div>

 <h2 style="margin:16px 0 8px">C++ demo allocation over all tasks</h2>
 <p>${r.demand.length} tasks · ${r.demo_blocked} would wait for resources · ${r.demo_unallocated} units unallocated</p>

 <h2 style="margin:16px 0 8px">Allocation events (live)</h2>
 ${r.live_events.map(e=>`<div>${esc(e.logged_at)} — ${esc(e.message)}</div>`).join("")||"<p style='color:var(--m)'>None yet — run a mission.</p>"}

 <h2 style="margin:16px 0 8px">Resource demand per task (top 30 by need)</h2>
 <div class="wrap">
  <table>
   <tr><th>Task</th><th>Units</th><th>Status</th></tr>
   ${[...r.demand].sort((a,b)=>b.need-a.need).slice(0,30).map(d=>`<tr><td>${d.task_id}</td><td>${d.need}</td><td>${st(d.status)}</td></tr>`).join("")}
  </table>
 </div>

 <h2 style="margin:16px 0 8px">Resource logs (latest 50)</h2>
 ${tbl(r.resource_logs)}

 <div style="border:1px solid var(--b);border-radius:8px;padding:15px;margin-top:18px;background:var(--p2)">
  <h2>Multi-Resource Deadlock Detection</h2>
  <p style="color:var(--m);margin-bottom:12px">
   Controlled CPU/RAM deadlock demonstration using task names from MySQL.
   Resource allocation and requests are simulated.
  </p>

  <button onclick="runDeadlock()">▶ Run Deadlock Simulation</button>

  <div id="deadlockbox" style="margin-top:15px">
   ${DEADLOCK_RESULT ? deadlockHTML(DEADLOCK_RESULT) :
   '<p style="color:var(--m)">Click the button to run the simulation.</p>'}
  </div>
 </div>`;
}

function deadlockHTML(d){
 const r=d.result;
 if(r.error)return `<p style="color:var(--r)">${esc(r.error)}</p>`;

 return `
 <div class="grid" style="margin-top:12px">
  <div class="card">
   <small>Detection Status</small>
   <b style="font-size:17px;color:${r.deadlock?'var(--r)':'var(--g)'}">
    ${r.deadlock?'DEADLOCK DETECTED':'NO DEADLOCK'}
   </b>
  </div>
  <div class="card">
   <small>Tasks Checked</small>
   <b>${d.tasks_checked}</b>
  </div>
  <div class="card">
   <small>Simulated Available CPU</small>
   <b>${r.available_after[0]}</b>
  </div>
  <div class="card">
   <small>Simulated Available RAM</small>
   <b>${r.available_after[1]}</b>
  </div>
 </div>

 <h2 style="margin-top:12px">Deadlocked Tasks</h2>
 ${r.deadlocked_tasks.length
  ? r.deadlocked_tasks.map(t=>`<span class="chip" style="color:var(--r)">${esc(t)}</span>`).join("")
  : '<p style="color:var(--g)">No deadlocked tasks.</p>'}

 <h2 style="margin-top:12px">Safe Sequence</h2>
 ${r.safe_sequence.length
  ? r.safe_sequence.map(t=>`<span class="chip" style="color:var(--g)">${esc(t)}</span>`).join(" → ")
  : '<p style="color:var(--m)">No safe sequence found for the current simulated state.</p>'}

 <p style="color:var(--m);margin-top:12px;font-size:11px">
 CPU and RAM allocation/request vectors are controlled demo values, not live allocations from MySQL.
 </p>`;
}

async function runDeadlock(){
 const box=$("#deadlockbox");
 box.innerHTML='<p style="color:var(--m)">Running deadlock detection…</p>';

 try{
  const d=await api("/api/deadlock");
  DEADLOCK_RESULT=d;
  box.innerHTML=deadlockHTML(d);
 }catch(e){
  box.innerHTML=`<p style="color:var(--r)">Simulation error: ${esc(e.message)}</p>`;
 }
}

function tbl(rows){if(!rows.length)return"<p style='color:var(--m)'>No rows.</p>";const k=Object.keys(rows[0]);return `<div class="wrap"><table><tr>${k.map(x=>`<th>${esc(x)}</th>`).join("")}</tr>${rows.map(r=>`<tr>${k.map(x=>`<td>${esc(r[x])}</td>`).join("")}</tr>`).join("")}</table></div>`}
async function drawSat(){const d=await api("/api/satellites"),by={};d.assignments.forEach(a=>(by[a.satellite_id]??=[]).push(a));
 const sids=[...new Set(d.assignments.map(a=>a.satellite_id))],rg=[...new Set(d.assignments.map(a=>a.region_name))],H=Math.max(sids.length,rg.length)*34+20,mxn=Math.max(...d.assignments.map(a=>a.n));
 const sy=i=>20+i*(H-30)/Math.max(1,sids.length-1||1)*(sids.length>1?1:0)+(sids.length>1?0:(H-30)/2),ry=i=>20+i*(H-30)/Math.max(1,rg.length-1)+(rg.length>1?0:0);
 const agg={};d.assignments.forEach(a=>{const k=a.satellite_id+"|"+a.region_name;agg[k]=(agg[k]||0)+a.n});
 const viz=`<svg viewBox="0 0 640 ${H}" style="width:100%;max-width:720px">${Object.entries(agg).map(([k,n])=>{const[s,r]=k.split("|");return `<line x1="150" y1="${sy(sids.indexOf(+s)>=0?sids.indexOf(+s):sids.map(String).indexOf(s))}" x2="470" y2="${ry(rg.indexOf(r))}" stroke="#38bdf8" stroke-opacity=".55" stroke-width="${1+n*5/mxn}"><title>Sat ${s} → ${r}: ${n} tasks</title></line>`}).join("")}
 ${sids.map((s,i)=>`<text x="140" y="${sy(i)+4}" text-anchor="end" fill="#dbe5f5">🛰 Sat ${s}</text>`).join("")}${rg.map((r,i)=>`<text x="480" y="${ry(i)+4}" fill="#dbe5f5">${esc(r)}</text>`).join("")}</svg>`;
 const orb=`<svg viewBox="-110 -110 220 220" style="width:200px">${[40,70,100].map(r=>`<circle r="${r}" fill="none" stroke="#1f2c47"/>`).join("")}<circle r="14" fill="#0e4a6b"/>
 ${sids.slice(0,12).map((s,i)=>{const r=[40,70,100][i%3];return `<g><animateTransform attributeName="transform" type="rotate" from="${i*37}" to="${i*37+360}" dur="${20+r/2}s" repeatCount="indefinite"/><circle cx="${r}" r="5" fill="#34d399"/><text x="${r+8}" y="4" font-size="9" fill="#dbe5f5">${esc(s)}</text></g>`}).join("")}</svg>`;
 $("#satbox").innerHTML=`<h2>Satellite → region task assignments (line width = task count)</h2><div class="bar" style="align-items:flex-start">${viz}<div><div>${orb}</div><small style="color:var(--o)">Conceptual simulation — not real orbital positions or telemetry.</small></div></div><h2 style="margin-top:16px">Satellites</h2>${tbl(d.satellites)}<h2 style="margin:16px 0 8px">Satellite → region assignments (task counts)</h2>${Object.entries(by).map(([s,a])=>{const tot=a.reduce((x,y)=>x+y.n,0);return `<div style="margin:8px 0"><b>Satellite ${esc(s)}</b> · ${tot} tasks<br>${a.map(x=>`<span class="chip">${esc(x.region_name)} via ${esc(x.route_name)}: ${x.n}</span>`).join("")}</div>`}).join("")}
 <h2 style="margin:16px 0 8px">Routes</h2>${tbl(d.routes)}<h2 style="margin:16px 0 8px">Regions</h2>${tbl(d.regions)}`}
async function loadGal(){IMGS=await api("/api/images");const t=[...new Set(IMGS.map(i=>i.image_type))];const cur=$("#g_t").value;$("#g_t").innerHTML='<option value="">All types</option>'+t.map(x=>`<option>${esc(x)}</option>`).join("");$("#g_t").value=cur;drawGal()}
function drawGal(){const q=$("#g_q").value.toLowerCase(),t=$("#g_t").value;const l=IMGS.filter(i=>(!t||i.image_type===t)&&(!q||JSON.stringify(i).toLowerCase().includes(q)));
 $("#galbox").innerHTML=l.map(i=>`<div class="gi" onclick="imgModal(${i.image_id})"><img loading="lazy" src="/api/image/${i.image_id}" alt="" onerror="this.outerHTML='<div style=&quot;height:140px;display:flex;align-items:center;justify-content:center;color:var(--m)&quot;>Image missing</div>'"><div><b>${esc(i.image_name)}</b><br><small style="color:var(--m)">${esc(i.image_type)}${i.region_name?" · "+esc(i.region_name):""}${i.task_id?" · Task "+esc(i.task_id):""}</small></div></div>`).join("")||"No images match."}

function suggestPriority(type){
 const t=String(type||"").toLowerCase();
 if(t.includes("flood")||t.includes("fire")||t.includes("cems"))return 1;
 if(t.includes("radar")||t.includes("satellite"))return 2;
 if(t.includes("traffic")||t.includes("dlr-mvda"))return 3;
 return 2;
}
function priorityLabel(p){
 return p===1?"High — Emergency":p===2?"Medium — Monitoring":"Routine";
}
function useImagePriority(p){
 $("#a_pr").value=p;
 $("#amsg").innerHTML=`<span style="color:var(--g)">Image-based priority suggestion applied: Priority ${p} (${priorityLabel(p)}). You can change it manually.</span>`;
 $("#modal").classList.remove("on");
 go("tasks");
}

function imgModal(id){
 const i=IMGS.find(x=>x.image_id===id);
 if(!i)return;
 const p=suggestPriority(i.image_type);
 $("#mbody").innerHTML=`
 <h2>${esc(i.image_name)} — ${esc(i.image_type)}</h2>
 <img src="/api/image/${id}" alt="">
 <p style="color:var(--m);margin-top:8px">${esc(i.image_path)}</p>
 <div class="card" style="margin-top:14px">
   <h3>Image-Based Priority Recommendation</h3>
   <p>Category: <b>${esc(i.image_type)}</b></p>
   <p>Suggested Priority: <b>${p} — ${priorityLabel(p)}</b></p>
   <small>Suggestion is based on dataset category, not AI visual recognition.</small>
   <div class="bar" style="margin-top:12px">
     <button onclick="useImagePriority(${p})">Use Suggested Priority</button>
     <button class="sec" onclick="$('#modal').classList.remove('on')">Cancel</button>
   </div>
 </div>`;
 $("#modal").classList.add("on");
}

async function drawLogs(){const l=await api("/api/logs");$("#logrows").innerHTML=l.map(x=>`<tr><td>${esc(x.logged_at)}</td><td><span class="pill">${esc(x.event_type)}</span></td><td>${esc(x.message)}</td></tr>`).join("")||'<tr><td colspan="3">No events yet</td></tr>'}
setInterval(()=>refresh(false),page==="live"?1000:1000);
go(TITLES[location.hash.slice(1)]?location.hash.slice(1):"overview");
</script></body></html>
"""
