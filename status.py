"""Watch a running sim through /status with a colored per-phase progress bar.

    python status.py                     # localhost:8080
    python status.py --interval 1.0      # poll less often
"""

import argparse
import json
import sys
import time
import urllib.request

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

console = Console()


def poll(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return json.loads(r.read())
    except Exception:
        return None


def make_progress() -> Progress:
    return Progress(
        TextColumn("  "),
        BarColumn(bar_width=42, complete_style="cyan", finished_style="green"),
        TextColumn("[bold]{task.percentage:>3.0f}%[/]"),
        TextColumn("[dim]({task.completed:>4}/{task.total})[/]"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8080/status")
    ap.add_argument("--interval", type=float, default=0.25)
    args = ap.parse_args()

    state = None
    while state is None or state.get("total_steps") is None:
        if state is None:
            console.print("[dim]waiting for sim to come up…[/]")
        time.sleep(args.interval)
        state = poll(args.url)

    console.print()
    console.print("[bold cyan]== Starting Mock ML ==[/]")
    console.print(f"Storing in [yellow]{state['run_id']}[/]")
    console.print()

    seen_phase: str | None = None
    progress: Progress | None = None
    task_id = None

    def finalize(final_state: dict) -> None:
        """Cap the bar at 100%, stop it, and announce the saved checkpoint."""
        nonlocal progress, task_id
        if progress is None or task_id is None:
            return
        total = final_state.get("phase_total")
        if total:
            progress.update(task_id, completed=total)
        progress.stop()
        progress = None
        task_id = None
        n = final_state.get("checkpoints_written", 0)
        run_id = final_state.get("run_id", "")
        console.print(
            f"[green]✓[/] Completed phase [bold]{seen_phase}[/]. "
            f"Saved to [dim]{run_id}/checkpoint-{n}.json[/]"
        )
        console.print()

    while True:
        new_state = poll(args.url)
        if new_state is not None:
            state = new_state
        current_phase = state.get("phase")

        if current_phase != seen_phase:
            finalize(state)
            if current_phase and not state.get("done"):
                phase_idx = state.get("phase_index", 0)
                console.print(
                    f"[bold magenta]Phase {phase_idx + 1}: {current_phase}[/]"
                )
                progress = make_progress()
                progress.start()
                task_id = progress.add_task("", total=state.get("phase_total") or 1)
            seen_phase = current_phase

        if progress is not None and task_id is not None:
            progress.update(task_id, completed=state.get("phase_step") or 0)

        if state.get("done"):
            finalize(state)
            console.print("[bold green]== Run complete ==[/]")
            console.print(
                f"  {state.get('checkpoints_written')} checkpoint(s), "
                f"{state.get('step')} steps"
            )
            return 0

        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
