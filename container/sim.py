"""Mock training-style 2D random walk with streaming activations to S3.

Four phases with distinct dynamics — chosen so the resulting trajectory has
visible regime shifts when plotted, similar to how training metrics show
distinct phases (warmup, steady-state, LR decay, late-stage cycling).

Per phase we produce TWO objects in S3:

    checkpoint-{N}.json   small: rng state, trajectory (step,x,y), metadata.
                          Single PUT at phase end. Used for resume + view.
    phase-{N}.bin         large: per-step "activations" baggage. Streamed via
                          S3 multipart upload as the sim runs — each step
                          appends bytes to an in-memory buffer, and when the
                          buffer crosses PART_SIZE_MB the same loop blocks
                          on upload_part before continuing. That is the real
                          streaming-with-backpressure path: nothing is hidden
                          behind a thread or queue, the sim itself pauses
                          while S3 ingests the part.

Per-step record in phase-{N}.bin (little-endian, no padding):
    dim         int32           — number of activations this step
    activations float32 * dim   — payload

`dim` is jittered per step (BAGGAGE_DIM_BASE ± BAGGAGE_DIM_JITTER/2) so parts
contain different numbers of steps — the demo exercises buffer policy on
genuinely uneven records, not a fixed stride.

On startup, if `--resume-from RUN_ID:N` is passed, the sim loads the JSON
checkpoint N and continues from the start of phase N+1 with the persisted RNG
state, so resumes are deterministic. The streamed .bin files for already-
completed phases are not re-read — they're pure baggage, useful only as the
demonstration that streaming worked.
"""

import argparse
import datetime
import os
import struct
import sys
import time

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

BAGGAGE_DIM_BASE = int(os.environ.get("BAGGAGE_DIM_BASE", "8192"))
BAGGAGE_DIM_JITTER = int(os.environ.get("BAGGAGE_DIM_JITTER", "4096"))
PART_SIZE_BYTES = int(float(os.environ.get("PART_SIZE_MB", "5")) * 1024 * 1024)


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


def make_activations(rng: np.random.Generator) -> bytes:
    """One per-step record: int32 dim, then float32[dim]. Dim is jittered."""
    half = BAGGAGE_DIM_JITTER // 2
    dim = BAGGAGE_DIM_BASE + int(rng.integers(-half, half + 1))
    if dim < 1:
        dim = 1
    payload = rng.standard_normal(dim).astype(np.float32, copy=False).tobytes()
    return struct.pack("<i", dim) + payload


def flush_part(
    key: str, upload_id: str, part_number: int, buf: bytearray, parts: list
) -> None:
    """Synchronously upload one part and update /status around the call."""
    body = bytes(buf)
    server.update(mpu_state="uploading")
    t0 = time.monotonic()
    parts.append(storage.upload_part(key, upload_id, part_number, body))
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    snap = server.snapshot()
    server.update(
        mpu_state="idle",
        mpu_part_count=part_number,
        mpu_last_part_ms=elapsed_ms,
        mpu_last_part_bytes=len(body),
        mpu_bytes_total=snap.get("mpu_bytes_total", 0) + len(body),
    )
    buf.clear()


def run_phase(
    phase_idx: int,
    start_step: int,
    start_pos: np.ndarray,
    rng: np.random.Generator,
    run_id: str,
):
    phase = PHASES[phase_idx]
    server.update(
        phase=phase["name"],
        phase_index=phase_idx,
        phase_step=0,
        phase_total=phase["steps"],
        mpu_part_count=0,
        mpu_last_part_ms=0,
        mpu_last_part_bytes=0,
    )

    blob_key = storage.phase_blob_key(run_id, phase_idx + 1)
    upload_id = storage.start_multipart(blob_key)
    parts: list[dict] = []
    buf = bytearray()
    part_number = 0

    pos = start_pos.copy()
    traj = []
    try:
        for t in range(phase["steps"]):
            pos = step_position(pos, phase, t, rng)
            step = start_step + t + 1
            traj.append([step, float(pos[0]), float(pos[1])])
            buf.extend(make_activations(rng))
            server.update(step=step, phase_step=t + 1)

            if len(buf) >= PART_SIZE_BYTES:
                part_number += 1
                flush_part(blob_key, upload_id, part_number, buf, parts)

            # mock delay - 20ms/step
            time.sleep(0.02)

        # final part: any size (S3 only enforces the 5 MB minimum on non-last
        # parts). Skip if buf is empty AND we already uploaded ≥1 part.
        if buf or not parts:
            part_number += 1
            flush_part(blob_key, upload_id, part_number, buf, parts)

        storage.complete_multipart(blob_key, upload_id, parts)
    except BaseException:
        # leave no orphaned parts on the bucket if the sim dies mid-phase
        try:
            storage.abort_multipart(blob_key, upload_id)
        finally:
            raise

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
    parser = argparse.ArgumentParser(
        description="Mock training-like 2D random walk with S3 checkpointing."
    )
    parser.add_argument(
        "--resume-from",
        metavar="RUN_ID:N",
        help="Resume run RUN_ID from checkpoint N (e.g. 2026-05-06T04-43-46Z:2). "
        "Omit for a fresh run.",
    )
    args = parser.parse_args()

    if args.resume_from:
        if ":" not in args.resume_from:
            print(
                "ERROR: --resume-from must be RUN_ID:N (e.g. 2026-05-06T04-43-46Z:2)",
                file=sys.stderr,
            )
            sys.exit(2)
        run_id, n_str = args.resume_from.split(":", 1)
        try:
            resume_n = int(n_str)
        except ValueError:
            print(
                f"ERROR: checkpoint number must be an int, got {n_str!r}",
                file=sys.stderr,
            )
            sys.exit(2)
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
        run_id = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H-%M-%SZ"
        )
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
        pos, traj, step = run_phase(phase_idx, step, pos, rng, run_id)
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
