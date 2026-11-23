
"""OrbitFlow - Independent Deadlock Simulation Module"""

def detect_deadlock(available, allocation, request, task_names):
    """
    Banker's-style deadlock detection using Work/Finish logic.
    All vectors must have the same resource dimensions.
    """
    work = available.copy()
    finish = [False] * len(task_names)
    sequence = []

    # Tasks with no allocated resources can finish independently
    for i in range(len(task_names)):
        if all(x == 0 for x in allocation[i]):
            finish[i] = True

    changed = True
    while changed:
        changed = False

        for i in range(len(task_names)):
            if finish[i]:
                continue

            can_finish = all(
                request[i][j] <= work[j]
                for j in range(len(work))
            )

            if can_finish:
                work = [
                    work[j] + allocation[i][j]
                    for j in range(len(work))
                ]
                finish[i] = True
                sequence.append(task_names[i])
                changed = True

    deadlocked = [
        task_names[i]
        for i in range(len(task_names))
        if not finish[i]
    ]

    return {
        "deadlock": len(deadlocked) > 0,
        "deadlocked_tasks": deadlocked,
        "safe_sequence": sequence,
        "available_after": work
    }


def run_demo(tasks):
    """
    Uses database task names as labels for a controlled demonstration.
    Resource allocation/request vectors are simulated, not stored live allocations.
    """
    names = [t["task_name"] for t in tasks[:2]]

    if len(names) < 2:
        return {
            "error": "At least 2 tasks are required for the demo."
        }

    # Controlled 2-task circular-wait example (CPU and RAM)
    available = [0, 0]

    allocation = [
        [1, 0],  # First task holds CPU
        [0, 1],  # Second task holds RAM
    ]

    request = [
        [0, 1],  # First task requests RAM
        [1, 0],  # Second task requests CPU
    ]

    return detect_deadlock(
        available, allocation, request, names
    )
