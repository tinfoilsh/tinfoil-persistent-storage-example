"""Poll a running sim's /status endpoint and show a progress bar.

python status.py                  # localhost:8080, 0.5s polling
python status.py --interval 1.0   # slower polls
"""

import argparse
import json
import sys
import time
import urllib.request

from tqdm import tqdm


def poll(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return json.loads(r.read())
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8080/status")
    ap.add_argument("--interval", type=float, default=0.5)
    args = ap.parse_args()

    # wait for the sim to come up + report total_steps
    state = None
    while state is None or state.get("total_steps") is None:
        state = poll(args.url)
        if state is None:
            print("waiting for sim to come up…", file=sys.stderr)
        time.sleep(args.interval)

    total = state["total_steps"]
    print(f"run_id={state.get('run_id')}", flush=True)

    bar = tqdm(total=total, unit="step", dynamic_ncols=True)
    try:
        while True:
            state = poll(args.url) or state
            bar.n = state.get("step", 0)
            bar.set_postfix(
                phase=state.get("phase") or "—",
                ckpts=state.get("checkpoints_written", 0),
            )
            bar.refresh()
            if state.get("done"):
                bar.n = total
                bar.set_postfix(phase="done", ckpts=state.get("checkpoints_written", 0))
                bar.refresh()
                break
            time.sleep(args.interval)
    finally:
        bar.close()

    print(f"done. run_id={state.get('run_id')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
