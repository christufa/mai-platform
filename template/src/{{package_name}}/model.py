"""Placeholder model + data. Replace both with the real thing."""

from __future__ import annotations

import torch
from torch import nn
from torch.utils.data import Dataset

from .config import TrainConfig


def build_model(cfg: TrainConfig) -> nn.Module:
    layers: list[nn.Module] = [nn.Linear(cfg.d_in, cfg.d_hidden), nn.GELU()]
    for _ in range(cfg.n_layers - 1):
        layers += [nn.Linear(cfg.d_hidden, cfg.d_hidden), nn.GELU()]
    layers.append(nn.Linear(cfg.d_hidden, 1))
    return nn.Sequential(*layers)


class SyntheticRegression(Dataset):
    """y = sin(x @ w): learnable, deterministic, needs no files on disk."""

    def __init__(self, d_in: int, size: int = 65_536, seed: int = 1234):
        g = torch.Generator().manual_seed(seed)
        self.x = torch.randn(size, d_in, generator=g)
        w = torch.randn(d_in, 1, generator=g) / d_in**0.5
        self.y = torch.sin(self.x @ w)

    def __len__(self) -> int:
        return len(self.x)

    def __getitem__(self, i: int) -> tuple[torch.Tensor, torch.Tensor]:
        return self.x[i], self.y[i]


def build_dataset(cfg: TrainConfig) -> Dataset:
    # Real data: read from cfg.data_dir (local mount or bucket mount in the cloud).
    return SyntheticRegression(cfg.d_in)
