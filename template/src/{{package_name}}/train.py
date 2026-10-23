"""Training entrypoint. Same script from 1 CPU to N nodes x M GPUs:

    python -m <pkg>.train --config configs/smoke.yaml               # single process
    torchrun --standalone --nproc-per-node=4 -m <pkg>.train ...       # one machine, 4 GPUs
    sky jobs launch sky/train.yaml                                    # cloud, spot, auto-resume

Resumes automatically from the newest checkpoint in CKPT_DIR/<run_name>.
"""

from __future__ import annotations

import contextlib
import math
import os
import signal
import time
import uuid

import torch
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data import DataLoader, DistributedSampler

from . import checkpoint
from .config import TrainConfig, check_resumable, load_config
from .model import build_dataset, build_model

_DTYPES = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}


class _Preemption:
    """SIGTERM (spot reclaim, `sky jobs cancel`) -> checkpoint at next step, then exit."""

    def __init__(self) -> None:
        self.requested = False
        with contextlib.suppress(ValueError):  # not main thread (e.g. some test runners)
            signal.signal(signal.SIGTERM, self._handle)

    def _handle(self, *_: object) -> None:
        self.requested = True


def _any_rank(flag: bool, world: int, device: torch.device) -> bool:
    """True on every rank if any rank says so. Ranks get SIGTERM at different
    steps; acting on a local flag would leave one rank in the checkpoint barrier
    while the others wait in DDP's gradient sync, and the job hangs."""
    if world == 1:
        return flag
    t = torch.tensor(float(flag), device=device)
    dist.all_reduce(t, op=dist.ReduceOp.MAX)
    return bool(t.item())


def _setup_distributed() -> tuple[int, int, torch.device]:
    if "RANK" not in os.environ:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        return 0, 1, device
    backend = "nccl" if torch.cuda.is_available() else "gloo"
    dist.init_process_group(backend)
    rank, world = dist.get_rank(), dist.get_world_size()
    if torch.cuda.is_available():
        local_rank = int(os.environ["LOCAL_RANK"])
        torch.cuda.set_device(local_rank)
        device = torch.device("cuda", local_rank)
    else:
        device = torch.device("cpu")
    return rank, world, device


def _lr_lambda(cfg: TrainConfig):
    def fn(step: int) -> float:
        if step < cfg.warmup_steps:
            return (step + 1) / max(1, cfg.warmup_steps)
        progress = (step - cfg.warmup_steps) / max(1, cfg.max_steps - cfg.warmup_steps)
        return 0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(progress, 1.0)))

    return fn


def _init_wandb(cfg: TrainConfig, rank: int, run_id: str):
    if rank != 0 or not cfg.wandb or not os.environ.get("WANDB_API_KEY"):
        return None
    try:
        import wandb
    except ImportError:
        return None
    # The id is stored in the checkpoint, so a resumed spot job keeps logging to
    # the same W&B run, while a fresh run that reuses a run_name gets a new one.
    return wandb.init(
        project=os.environ.get("WANDB_PROJECT"),
        entity=os.environ.get("WANDB_ENTITY") or None,
        name=cfg.run_name,
        id=run_id,
        resume="allow",
        config=vars(cfg),
    )


def train(cfg: TrainConfig) -> dict[str, float]:
    rank, world, device = _setup_distributed()
    is_main = rank == 0
    torch.manual_seed(cfg.seed + rank)

    dtype = _DTYPES[cfg.precision]
    if device.type == "cpu" and dtype is torch.float16:
        dtype = torch.float32  # fp16 autocast is a GPU feature
    use_amp = dtype is not torch.float32

    model = build_model(cfg).to(device)
    raw_model = model  # un-wrapped reference for state_dict()
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, _lr_lambda(cfg))
    scaler = torch.amp.GradScaler(device.type, enabled=dtype is torch.float16)

    step = 0
    run_id = uuid.uuid4().hex[:12]
    state = checkpoint.load_latest(cfg.run_dir, map_location=device)
    if state is not None:
        check_resumable(state["config"], cfg)
        raw_model.load_state_dict(state["model"])
        opt.load_state_dict(state["optimizer"])
        sched.load_state_dict(state["scheduler"])
        scaler.load_state_dict(state["scaler"])
        step = state["step"]
        run_id = state.get("run_id", run_id)
        if is_main:
            print(f"Resumed from step {step} ({cfg.run_dir})", flush=True)
    elif is_main:
        print(f"Starting {cfg.run_name} from scratch ({cfg.run_dir})", flush=True)

    if cfg.compile:
        model = torch.compile(model)
    if world > 1:
        model = DDP(model, device_ids=[device.index] if device.type == "cuda" else None)

    dataset = build_dataset(cfg)
    sampler = DistributedSampler(dataset, shuffle=True, seed=cfg.seed) if world > 1 else None
    loader = DataLoader(
        dataset,
        batch_size=cfg.batch_size,
        sampler=sampler,
        shuffle=sampler is None,
        drop_last=True,
        num_workers=2 if device.type == "cuda" else 0,
        pin_memory=device.type == "cuda",
        persistent_workers=device.type == "cuda",
    )
    steps_per_epoch = len(loader)

    run = _init_wandb(cfg, rank, run_id)
    preempt = _Preemption()

    def save_ckpt() -> None:
        if is_main:
            checkpoint.save(
                cfg.run_dir,
                step,
                {
                    "step": step,
                    "run_id": run_id,
                    "model": raw_model.state_dict(),
                    "optimizer": opt.state_dict(),
                    "scheduler": sched.state_dict(),
                    "scaler": scaler.state_dict(),
                    "config": vars(cfg),
                },
                keep_last=cfg.keep_last,
            )
        if world > 1:
            dist.barrier()

    model.train()
    loss_val = float("nan")
    preempted = False
    t0 = time.perf_counter()
    while step < cfg.max_steps and not preempted:
        epoch = step // steps_per_epoch
        if sampler is not None:
            sampler.set_epoch(epoch)
        for x, y in loader:
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            with torch.autocast(device.type, dtype=dtype, enabled=use_amp):
                loss = torch.nn.functional.mse_loss(model(x).float(), y)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
            scaler.step(opt)
            scaler.update()
            sched.step()
            step += 1

            if step % cfg.log_every == 0 or step == cfg.max_steps:
                loss_val = loss.detach().float()
                if world > 1:
                    dist.all_reduce(loss_val, op=dist.ReduceOp.AVG)
                loss_val = loss_val.item()
                if is_main:
                    dt = time.perf_counter() - t0
                    lr = sched.get_last_lr()[0]
                    msg = f"step {step:>7} | loss {loss_val:.5f} | lr {lr:.2e} | {dt:.1f}s"
                    print(msg, flush=True)
                    if run:
                        run.log({"loss": loss_val, "lr": lr}, step=step)

            # Every rank must make the same stop decision at the same step.
            preempted = _any_rank(preempt.requested, world, device)
            stop = preempted or step >= cfg.max_steps
            if step % cfg.ckpt_every == 0 or stop:
                save_ckpt()
            if stop:
                break

    if preempted and is_main:
        print(f"SIGTERM: checkpointed at step {step}, exiting for recovery", flush=True)

    if run:
        run.finish()
    if world > 1:
        dist.destroy_process_group()
    return {"step": step, "loss": loss_val}


def main(argv: list[str] | None = None) -> None:
    train(load_config(argv))


if __name__ == "__main__":
    main()
