"""Run scenes headlessly against the real stack and print the ledger scoreboard after each.

Usage: python scripts/smoke.py intro tip_over ...    (needs the show server NOT already running)
Set RACCOON_STUB_LLM=1 to avoid real model calls while testing.
"""

import json
import subprocess
import sys
import time

import httpx

BASE = "http://127.0.0.1:8100"


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


def summarize(snap):
    out = []
    for lane in ("lane1", "lane2"):
        a = snap["audit"][lane]
        out.append(
            f"  {lane}: submitted={a['submitted']} approved={a['approved']} ok={a['refunded_once']} "
            f"dup={a['duplicates']} (${a['duplicate_cents'] / 100:.2f}) missing={a['missing']} "
            f"in_flight={a['in_flight']} unapproved={a['unapproved']}"
        )
    return "\n".join(out)


def main(scenes):
    srv = subprocess.Popen([sys.executable, "-m", "raccoon.show"])
    try:
        wait_api(srv)
        time.sleep(1)
        for scene in scenes:
            httpx.post(f"{BASE}/api/scenes/{scene}/run", timeout=5).raise_for_status()
            t0 = time.time()
            while True:
                time.sleep(1)
                snap = httpx.get(f"{BASE}/api/state", timeout=5).json()
                if not snap["running"]:
                    break
            # let the settle window elapse so "missing" is decided
            time.sleep(21)
            snap = httpx.get(f"{BASE}/api/state", timeout=5).json()
            print(f"== {scene} ({time.time() - t0:.0f}s incl. settle)")
            print(summarize(snap))
            errs = [e for e in snap["events"] if e["kind"] == "error"]
            if errs:
                print("  ERRORS:", errs)
            if snap["nexus"]:
                print("  nexus:", json.dumps(snap["nexus"][:2]))
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except Exception:
            srv.kill()


if __name__ == "__main__":
    main(sys.argv[1:] or ["intro"])
