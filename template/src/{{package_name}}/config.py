"""Typed run config: YAML file + `key=value` CLI overrides.

Paths that differ between laptop and cloud (data, checkpoints) come from the
environment (DATA_DIR, CKPT_DIR) so the same config file runs everywhere.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TrainConfig:
    run_name: str = "default"
    seed: int = 0

    # model
    d_in: int = 64
    d_hidden: int = 512
    n_layers: int = 4

    # optimisation
    max_steps: int = 1000
    batch_size: int = 256
    lr: float = 3e-4
    weight_decay: float = 0.01
    warmup_steps: int = 100
    grad_clip: float = 1.0
    precision: str = "bf16"  # bf16 | fp16 | fp32
    compile: bool = False

    # bookkeeping
    log_every: int = 50
    ckpt_every: int = 500
    keep_last: int = 3
    wandb: bool = False

    # resolved from env when not given explicitly
    data_dir: str = field(default_factory=lambda: os.environ.get("DATA_DIR", "data"))
    ckpt_dir: str = field(default_factory=lambda: os.environ.get("CKPT_DIR", "outputs/checkpoints"))

    @property
    def run_dir(self) -> Path:
        return Path(self.ckpt_dir) / self.run_name


def _coerce(name: str, raw: str, current: object) -> object:
    value = yaml.safe_load(raw)
    if isinstance(current, float) and isinstance(value, int):
        value = float(value)
    if current is not None and not isinstance(value, type(current)):
        raise TypeError(f"{name}: expected {type(current).__name__}, got {raw!r}")
    return value


def load_config(argv: list[str] | None = None) -> TrainConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="YAML config file")
    parser.add_argument("overrides", nargs="*", help="key=value overrides")
    args = parser.parse_args(argv)

    values: dict = {}
    if args.config:
        values.update(yaml.safe_load(args.config.read_text()) or {})

    known = {f.name for f in dataclasses.fields(TrainConfig)}
    unknown = set(values) - known
    if unknown:
        raise KeyError(f"Unknown config keys in {args.config}: {sorted(unknown)}")

    cfg = TrainConfig(**values)
    for item in args.overrides:
        key, sep, raw = item.partition("=")
        if not sep or key not in known:
            raise KeyError(f"Bad override {item!r}; valid keys: {sorted(known)}")
        setattr(cfg, key, _coerce(key, raw, getattr(cfg, key)))
    return cfg
