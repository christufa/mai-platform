"""Atomic, resumable checkpoints.

Works the same on a local disk and on a SkyPilot bucket mount (MOUNT_CACHED):
write to a temp file, then rename, so a preempted job never leaves a
half-written "latest" checkpoint behind.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import torch

_PATTERN = re.compile(r"step_(\d+)\.pt$")


def _checkpoints(run_dir: Path) -> list[tuple[int, Path]]:
    if not run_dir.exists():
        return []
    found = [(int(m.group(1)), p) for p in run_dir.iterdir() if (m := _PATTERN.search(p.name))]
    return sorted(found)


def save(run_dir: Path, step: int, state: dict[str, Any], keep_last: int = 3) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    final = run_dir / f"step_{step:08d}.pt"
    tmp = final.with_suffix(".pt.tmp")
    torch.save(state, tmp)
    os.replace(tmp, final)
    for _, old in _checkpoints(run_dir)[:-keep_last]:
        old.unlink(missing_ok=True)
    return final


def load_latest(run_dir: Path, map_location: str | torch.device = "cpu") -> dict[str, Any] | None:
    ckpts = _checkpoints(run_dir)
    if not ckpts:
        return None
    _, path = ckpts[-1]
    return torch.load(path, map_location=map_location, weights_only=False)
