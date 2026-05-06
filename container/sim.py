"""Mock training-style 2D random walk.

Four phases with distinct dynamics — chosen so the resulting trajectory has
visible regime shifts when plotted, similar to how training metrics show
distinct phases (warmup, steady-state, LR decay, late-stage cycling).

A checkpoint is written to S3 at each phase boundary. On startup, if
RESUME_FROM_CHECKPOINT and RUN_ID are set, the sim loads that checkpoint and
continues from the start of the next phase using the persisted RNG state, so
runs are deterministic across resumes.
"""

import os
import sys
import time
import uuid

import numpy as np
import server
import storage

PHASES = [
    {"name": "explore", "kind": "explore", "steps": 2500, "noise": 1.0},
    {
        "name": "drift",
        "kind": "drift",
        "steps": 2500,
        "noise": 0.3,
        "drift": [0.06, 0.03],
    },
    {
        "name": "converge",
        "kind": "converge",
        "steps": 2500,
        "noise": 0.4,
        "pull": 0.005,
    },
    {
        "name": "oscillate",
        "kind": "oscillate",
        "steps": 2500,
        "noise": 0.1,
        "amp": 0.15,
        "period": 400,
    },
]


def step_position(
    pos: np.ndarray, phase: dict, t_in_phase: int, rng: np.random.Generator
) -> np.ndarray:
    delta = rng.standard_normal(2) * phase["noise"]
    kind = phase["kind"]
    if kind == "drift":
        delta += np.array(phase["drift"])
    elif kind == "converge":
        delta += -pos * phase["pull"]
    elif kind == "oscillate":
        amp = phase["amp"]
        period = phase["period"]
        omega = 2 * np.pi * t_in_phase / period
        delta += np.array([amp * np.sin(omega), amp * np.cos(omega)])
    return pos + delta


def run_phase(
    phase_idx: int, start_step: int, start_pos: np.ndarray, rng: np.random.Generator
):
    phase = PHASES[phase_idx]
    server.update(phase=phase["name"], phase_index=phase_idx)
    pos = start_pos.copy()
    traj = []
    for t in range(phase["steps"]):
        pos = step_position(pos, phase, t, rng)
        step = start_step + t + 1
        traj.append([step, float(pos[0]), float(pos[1])])
        server.update(step=step)
        # mock delay - 20ms/step
        time.sleep(0.02)
    return pos, traj, start_step + phase["steps"]


def make_checkpoint(
    run_id: str,
    n: int,
    phase_idx: int,
    step: int,
    pos: np.ndarray,
    rng: np.random.Generator,
    traj: list,
) -> dict:
    return {
        "run_id": run_id,
        "checkpoint_number": n,
        "phase_completed_index": phase_idx,
        "phase_completed": PHASES[phase_idx]["name"],
        "step": step,
        "position": [float(pos[0]), float(pos[1])],
        "rng_state": rng.bit_generator.state,
        "trajectory": traj,
    }


def restore_rng(state: dict) -> np.random.Generator:
    rng = np.random.default_rng()
    rng.bit_generator.state = state
    return rng


def main() -> None:
    storage.bucket()  # fail fast if S3_BUCKET is missing

    resume_n_raw = os.environ.get("RESUME_FROM_CHECKPOINT", "").strip()
    run_id = os.environ.get("RUN_ID", "").strip() or None

    if resume_n_raw:
        if not run_id:
            print("ERROR: RESUME_FROM_CHECKPOINT requires RUN_ID", file=sys.stderr)
            sys.exit(2)
        resume_n = int(resume_n_raw)
        ckpt = storage.load_checkpoint(run_id, resume_n)
        start_phase_idx = ckpt["phase_completed_index"] + 1
        start_step = ckpt["step"]
        start_pos = np.array(ckpt["position"], dtype=float)
        rng = restore_rng(ckpt["rng_state"])
        n_written = resume_n
        next_phase = (
            PHASES[start_phase_idx]["name"]
            if start_phase_idx < len(PHASES)
            else "(none)"
        )
        print(
            f"resumed run_id={run_id} from checkpoint {resume_n}, "
            f"step={start_step}, next phase={next_phase}",
            flush=True,
        )
    else:
        run_id = run_id or str(uuid.uuid4())
        start_phase_idx = 0
        start_step = 0
        start_pos = np.zeros(2)
        seed_raw = os.environ.get("SEED", "").strip()
        seed = int(seed_raw) if seed_raw else None
        rng = np.random.default_rng(seed)
        n_written = 0
        print(f"started fresh run_id={run_id}", flush=True)

    total_steps = sum(p["steps"] for p in PHASES)
    server.update(
        run_id=run_id,
        step=start_step,
        checkpoints_written=n_written,
        done=False,
        total_steps=total_steps,
    )
    port = int(os.environ.get("PORT", "8080"))
    server.serve_in_thread(port)

    pos = start_pos
    step = start_step

    if start_phase_idx >= len(PHASES):
        print("nothing to do, all phases already completed", flush=True)
        server.update(done=True)
        _grace_then_exit()
        return

    for phase_idx in range(start_phase_idx, len(PHASES)):
        pos, traj, step = run_phase(phase_idx, step, pos, rng)
        n_written += 1
        ckpt = make_checkpoint(run_id, n_written, phase_idx, step, pos, rng, traj)
        storage.write_checkpoint(run_id, n_written, ckpt)
        server.update(checkpoints_written=n_written)
        print(
            f"wrote checkpoint {n_written} (phase={PHASES[phase_idx]['name']}, step={step})",
            flush=True,
        )

    server.update(done=True)
    print(f"sim complete. run_id={run_id}, total checkpoints={n_written}", flush=True)
    _grace_then_exit()


def _grace_then_exit() -> None:
    # brief window so the last /status poll lands before the HTTP server dies
    time.sleep(5)


if __name__ == "__main__":
    main()
