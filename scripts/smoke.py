"""Run scenes headlessly against the real stack and print the ledger scoreboard after each.

Usage: python scripts/smoke.py [--check] intro tip_over ...    (needs the show server NOT already running)
Set PAIDONCE_STUB_LLM=1 to avoid real model calls (`make scenario` does).

The scoreboard is reset first, so each run starts from zero. Chaos is seeded (the engine's seed);
ticket IDs carry a per-run prefix, so reruns never collide with earlier tickets.

--check exits non-zero if Lane 2 has any ledger violation (duplicate, missing, unapproved, stuck), if a ticket
the human or the policy said no to was not closed unpaid, if a ticket is still waiting at the end,
or if the nexus_kill scene never showed the payments-side retry it exists to show.
Lane 1 is printed for contrast but never gates the result.
"""

import json
import os
import secrets
import subprocess
import sys
import time

import httpx

from paidonce import config
from paidonce.show.procs import port_open

# PAIDONCE_SHOW_PORT. With the other PAIDONCE_*_PORT, PAIDONCE_DATA and TEMPORAL_ADDRESS a run can sit beside the demo.
PORT = config.SHOW_PORT
BASE = f"http://127.0.0.1:{PORT}"
MUST_HAVE = [
    "intro",
    "tip_over",
    "double_delivery",
    "deploy_wait",
    "payments_timeout",
    "nexus_kill",
]
FIELDS = (
    "submitted",
    "approved",
    "refunded_once",
    "duplicates",
    "missing",
    "in_flight",
    "unapproved",
    "rejected",
    "declined",
    "waiting",
)
# Each cohort carries one ticket outside the refund policy and one the human denies (Engine.submit_cohort).
NO_PER_COHORT = 2
COHORTS = {"free_roam": 4}


def wait_api(proc, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            raise SystemExit("show server exited early")
        try:
            httpx.get(f"{BASE}/api/state", timeout=1).raise_for_status()
            return
        except Exception:
            time.sleep(0.5)
    raise SystemExit("show server did not come up")


def line(lane, a, prev):
    d = {k: a[k] - prev.get(k, 0) for k in FIELDS}
    return (
        f"  {lane}: submitted={d['submitted']} approved={d['approved']} ok={d['refunded_once']} "
        f"dup={d['duplicates']} (${a['duplicate_cents'] / 100:.2f} total) "
        f"missing={d['missing']} stuck={d['in_flight']} unapproved={d['unapproved']} "
        f"none-owed: policy={d['declined']} human-no={d['rejected']}"
    )


def handler_attempts(snap):
    """Highest payments-side activity attempt among the scene's Nexus rows; caller rows must stay at attempt 1."""
    rows = snap["nexus"]
    return (
        max((r.get("handler", {}).get("peak_activity_attempt", 0) for r in rows), default=0),
        max((r["attempt"] for r in rows), default=0),
    )


def main(scenes, check):
    # Checked here too: until our server exits, wait_api could get its answer from the one already running.
    if port_open(PORT):
        raise SystemExit(f"Port {PORT} is busy: stop `make demo` (or the other show server) first.")
    # Locks the server's controls to this runner, so a browser left open on the show's port can't reset or run scenes.
    token = secrets.token_hex(8)
    headers = {"x-paidonce-scenario": token}
    srv = subprocess.Popen(
        [sys.executable, "-m", "paidonce.show"], env={**os.environ, "PAIDONCE_SCENARIO_TOKEN": token}
    )
    failures: list[str] = []
    try:
        wait_api(srv)
        time.sleep(1)
        httpx.post(f"{BASE}/api/reset", headers=headers, timeout=10).raise_for_status()
        prev = {"lane1": {}, "lane2": {}}
        for scene in scenes:
            httpx.post(f"{BASE}/api/scenes/{scene}/run", headers=headers, timeout=5).raise_for_status()
            t0 = time.time()
            peak_handler = peak_caller = 0
            while True:
                time.sleep(1)
                snap = httpx.get(f"{BASE}/api/state", timeout=5).json()
                h, c = handler_attempts(snap)
                peak_handler, peak_caller = max(peak_handler, h), max(peak_caller, c)
                if not snap["running"]:
                    break
            # The engine holds a scene open until every ticket has landed, so nothing may still be in flight here.
            snap = httpx.get(f"{BASE}/api/state", timeout=5).json()
            print(f"== {scene} ({time.time() - t0:.0f}s incl. settle)")
            for lane in ("lane1", "lane2"):
                if snap["audit"][lane]["in_flight"]:
                    failures.append(f"{scene}: {lane} still in flight when the scene ended")
            l2 = snap["audit"]["lane2"]
            closed_unpaid = (
                l2["rejected"] + l2["declined"] - prev["lane2"].get("rejected", 0) - prev["lane2"].get("declined", 0)
            )
            if closed_unpaid != NO_PER_COHORT * COHORTS.get(scene, 1):
                failures.append(f"{scene}: Lane 2 closed {closed_unpaid} denied tickets unpaid")
            for lane in ("lane1", "lane2"):
                print(line(lane, snap["audit"][lane], prev[lane]))
                prev[lane] = {k: snap["audit"][lane][k] for k in FIELDS}
            if scene == "nexus_kill":
                print(
                    f"  nexus: payments-side activity attempt peaked at {peak_handler}; "
                    f"caller operation attempt peaked at {peak_caller}"
                )
                if peak_handler < 2:
                    failures.append("nexus_kill: no payments-side retry observed")
            errs = [e for e in snap["events"] if e["kind"] == "error"]
            if errs:
                print("  ERRORS:", json.dumps(errs))
                failures.append(f"{scene}: error events")
        a = snap["audit"]["lane2"]
        print("== final ledger audit (cumulative)")
        for lane in ("lane1", "lane2"):
            x = snap["audit"][lane]
            print(
                f"  {lane}: submitted={x['submitted']} refunded_once={x['refunded_once']} "
                f"duplicates={x['duplicates']} missing={x['missing']} stuck={x['in_flight']} "
                f"unapproved={x['unapproved']} rejected={x['rejected']} declined={x['declined']} "
                f"waiting={x['waiting']}"
            )
        if a["duplicates"] or a["missing"] or a["in_flight"] or a["unapproved"]:
            failures.append("Lane 2 ledger violations")
        if a["waiting"]:
            failures.append("Lane 2: tickets still waiting for a decision")
        if a["refunded_once"] != a["approved"]:
            failures.append("Lane 2: refunded_once != approved")
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except Exception:
            srv.kill()
    if check:
        if failures:
            print("SCENARIO FAILED: " + "; ".join(failures))
            raise SystemExit(1)
        print("SCENARIO PASSED: Lane 2 held every invariant")


if __name__ == "__main__":
    args = sys.argv[1:]
    check = "--check" in args
    names = [a for a in args if a != "--check"]
    main(names or (MUST_HAVE if check else ["intro"]), check)
