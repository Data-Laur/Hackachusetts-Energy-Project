"""
log_task_completion.py — append a log row when a spec task is marked complete.

Called by the "Log task completion" agent hook whenever tasks.md is saved. It
counts completed top-level tasks ([x]) in the spec and, if that count went UP
since last time, appends a row to docs/kiro-log.md's summary table.

We track the last-seen count in a tiny state file so saving tasks.md for other
reasons (e.g. editing wording) doesn't spam the log.

Run (normally via the hook):  python scripts/log_task_completion.py
"""

import datetime as dt
import os
import re

TASKS = os.path.join(".kiro", "specs", "heat-check", "tasks.md")
LOG = os.path.join("docs", "kiro-log.md")
STATE = os.path.join(".kiro", "specs", "heat-check", ".task_count")
# Match a top-level completed task line like:  "- [x] 3. Waste detection..."
TOP_TASK = re.compile(r"^- \[x\] (\d+)\.\s+(.*)$")


def completed_top_tasks():
    """Return a list of (number, title) for completed top-level tasks."""
    if not os.path.exists(TASKS):
        return []
    out = []
    with open(TASKS, encoding="utf-8") as f:
        for line in f:
            m = TOP_TASK.match(line.strip() if line.startswith("- ") else line)
            if m:
                out.append((m.group(1), m.group(2).strip()))
    return out


def read_last_count():
    if os.path.exists(STATE):
        try:
            return int(open(STATE).read().strip())
        except ValueError:
            return 0
    return 0


def main():
    done = completed_top_tasks()
    count = len(done)
    last = read_last_count()

    if count > last:
        # One or more tasks newly completed — log the newest.
        newest = done[-1]
        time = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        row = (f"| {time} | (auto) task completed | Spec task + Hook | "
               f"Marked task {newest[0]} complete: {newest[1]} | — |\n")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(row)
        print(f"Logged completion of task {newest[0]}.")
    else:
        print("No new task completion detected; nothing logged.")

    # Update state regardless (handles un-checking too).
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        f.write(str(count))


if __name__ == "__main__":
    main()
