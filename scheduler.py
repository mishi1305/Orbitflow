"""OrbitFlow scheduling engine.

Python port of the algorithms in main.cpp (FCFS, SJF, Priority: non-preemptive;
Round Robin) with identical tie-breaking, plus Gantt segments for the UI.
Input tasks: dicts with id, arrival, burst, priority.
"""

ALGOS = ("FCFS", "SJF", "PRIORITY", "RR")


def _summary(rows):
    n = len(rows) or 1
    return {
        "avg_waiting": round(sum(r["waiting"] for r in rows) / n, 2),
        "avg_turnaround": round(sum(r["turnaround"] for r in rows) / n, 2),
        "avg_response": round(sum(r["response"] for r in rows) / n, 2),
        "completion_time": max((r["completion"] for r in rows), default=0),
    }


def _non_preemptive(tasks, mode):
    pending, t, rows, segs = list(tasks), 0, [], []
    while pending:
        ready = [p for p in pending if p["arrival"] <= t]
        if not ready:
            t = min(p["arrival"] for p in pending)
            continue
        key = {"FCFS": lambda p: (p["arrival"], p["id"]),
               "SJF": lambda p: (p["burst"], p["arrival"], p["id"]),
               "PRIORITY": lambda p: (p["priority"], p["arrival"], p["id"])}[mode]
        p = min(ready, key=key)
        pending.remove(p)
        end = t + p["burst"]
        rows.append({**p, "start": t, "response": t - p["arrival"],
                     "waiting": t - p["arrival"], "completion": end,
                     "turnaround": end - p["arrival"]})
        segs.append({"id": p["id"], "start": t, "end": end})
        t = end
    return rows, segs


def _round_robin(tasks, quantum):
    order = sorted(range(len(tasks)), key=lambda i: (tasks[i]["arrival"], tasks[i]["id"]))
    rem = [p["burst"] for p in tasks]
    first, comp = [-1] * len(tasks), [0] * len(tasks)
    ready, segs, t, nxt, done = [], [], 0, 0, 0
    while done < len(tasks):
        while nxt < len(order) and tasks[order[nxt]]["arrival"] <= t:
            ready.append(order[nxt]); nxt += 1
        if not ready:
            t = max(t, tasks[order[nxt]]["arrival"])
            continue
        i = ready.pop(0)
        if first[i] == -1:
            first[i] = t
        run = min(quantum, rem[i])
        segs.append({"id": tasks[i]["id"], "start": t, "end": t + run})
        t += run
        rem[i] -= run
        while nxt < len(order) and tasks[order[nxt]]["arrival"] <= t:
            ready.append(order[nxt]); nxt += 1
        if rem[i] > 0:
            ready.append(i)
        else:
            comp[i] = t
            done += 1
    rows = []
    for i, p in enumerate(tasks):
        tat = comp[i] - p["arrival"]
        rows.append({**p, "start": first[i], "response": first[i] - p["arrival"],
                     "completion": comp[i], "turnaround": tat, "waiting": tat - p["burst"]})
    return rows, segs


def run(tasks, mode, quantum=2):
    mode = mode.upper()
    if mode not in ALGOS:
        raise ValueError(f"Unknown algorithm '{mode}'")
    if mode == "RR" and quantum <= 0:
        raise ValueError("Time quantum must be positive")
    rows, segs = _round_robin(tasks, quantum) if mode == "RR" else _non_preemptive(tasks, mode)
    rows.sort(key=lambda r: (r["start"], r["id"]))   # execution order, as in main.cpp
    return {"algorithm": mode, "quantum": quantum if mode == "RR" else None,
            "rows": rows, "segments": segs, "summary": _summary(rows)}


def compare(tasks, quantum=2):
    return {a: run(tasks, a, quantum) for a in ALGOS}
