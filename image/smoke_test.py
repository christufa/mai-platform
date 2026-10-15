"""Build-time sanity check for the mai-base image. Runs inside `docker build`;
any failure fails the build, so a broken image is never pushed.

Checks:
  1. Every package in constraints.txt is installed at exactly the locked version.
  2. Key libraries import cleanly.
  3. torch's bundled CUDA major version matches the base image's CUDA major
     (otherwise nvcc-built extensions in the dev image won't link).

No GPU is needed (CI runners have none); CUDA itself is exercised on real hardware.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from importlib import metadata
from pathlib import Path

CONSTRAINTS = Path(os.environ.get("MAI_CONSTRAINTS", "/opt/mai/constraints.txt"))
IMPORTS = ["torch", "torchvision", "transformers", "accelerate", "datasets", "numpy", "wandb"]


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def check_versions() -> list[str]:
    errors = []
    installed = {_norm(d.metadata["Name"]): d.version for d in metadata.distributions()}
    for line in CONSTRAINTS.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" not in line:
            continue
        spec, _, marker = line.partition(";")
        name, _, want = spec.strip().partition("==")
        if marker.strip():
            # crude marker evaluation is enough here: skip non-Linux / other-python entries
            from packaging.markers import Marker

            if not Marker(marker.strip()).evaluate():
                continue
        have = installed.get(_norm(name))
        if have != want.strip():
            errors.append(f"{name}: locked {want.strip()}, installed {have}")
    return errors


def check_imports() -> list[str]:
    errors = []
    for mod in IMPORTS:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # noqa: BLE001 - report everything
            errors.append(f"import {mod}: {exc!r}")
    return errors


def check_cuda() -> list[str]:
    import torch

    image_cuda = os.environ.get("CUDA_VERSION", "")
    torch_cuda = torch.version.cuda or ""
    print(
        f"python {sys.version.split()[0]} | torch {torch.__version__} "
        f"| torch CUDA {torch_cuda or 'none'} | image CUDA {image_cuda or 'unknown'}"
    )
    if not torch_cuda:
        return ["torch was installed without CUDA support"]
    if image_cuda and image_cuda.split(".")[0] != torch_cuda.split(".")[0]:
        return [f"CUDA major mismatch: image {image_cuda} vs torch {torch_cuda}"]
    return []


def main() -> int:
    errors = check_versions() + check_imports() + check_cuda()
    for e in errors:
        print(f"SMOKE FAIL: {e}", file=sys.stderr)
    if not errors:
        print("smoke test passed")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
