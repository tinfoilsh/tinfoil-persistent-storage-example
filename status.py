"""Poll a running sim's /status endpoint until it reports done.

python status.py                  # localhost:8080, 1s interval
python status.py --interval 0.25  # poll faster
"""

import argparse
import json
import sys
import time
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8080/status")
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args()

    last_line = None
    while True:
        try:
            with urllib.request.urlopen(args.url, timeout=2) as r:
                state = json.loads(r.read())
        except Exception as e:
            print(f"poll failed: {e}", file=sys.stderr)
            time.sleep(args.interval)
            continue

        line = (
            f"phase={state.get('phase')} "
            f"step={state.get('step')} "
            f"checkpoints={state.get('checkpoints_written')}"
        )
        if line != last_line:
            print(line, flush=True)
            last_line = line

        if state.get("done"):
            print(f"\ndone. run_id={state.get('run_id')}")
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
