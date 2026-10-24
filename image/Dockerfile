# syntax=docker/dockerfile:1.7
# =============================================================================
# mai-base: one Dockerfile, two targets
#
#   runtime : slim CUDA image for cloud/batch jobs (SkyPilot, CI)
#             docker build --target runtime --build-arg BASE_VARIANT=base .
#   dev     : runtime + nvcc, shell tooling, Jupyter, Claude Code, SkyPilot CLI
#             docker build --target dev .                      (default variant: devel)
#
# Python comes from uv (not conda) and is installed from uv.lock, so every
# build of a given commit yields the same environment.
# =============================================================================

ARG CUDA_VERSION=13.2.0
ARG UBUNTU_VERSION=24.04
# "base" = CUDA runtime only (torch wheels bundle cuDNN/NCCL etc.)
# "devel" = adds nvcc + headers, needed to compile custom CUDA extensions
ARG BASE_VARIANT=devel
ARG UV_VERSION=0.13.1

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# -----------------------------------------------------------------------------
# common: OS, user, locked Python environment
# -----------------------------------------------------------------------------
FROM nvidia/cuda:${CUDA_VERSION}-${BASE_VARIANT}-ubuntu${UBUNTU_VERSION} AS common

ARG PYTHON_VERSION=3.12
ARG USERNAME=devuser
ARG UID=1000
ARG GID=1000

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    # uv: managed Python lives in /opt/python, the shared env in /opt/venv
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:/home/${USERNAME}/.local/bin:${PATH} \
    MAI_CONSTRAINTS=/opt/mai/constraints.txt

COPY --from=uv /uv /uvx /usr/local/bin/

# Fail a RUN if any command in a pipe fails (e.g. curl | bash)
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# `upgrade` patches packages already in the NVIDIA base; weekly CI rebuilds
# run with no cache so this actually re-executes and picks up security fixes.
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl wget git openssh-client rsync \
        sudo unzip zip bzip2 xz-utils jq less procps \
    && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 images ship a default "ubuntu" user on UID 1000; remove it so
# our user can take that UID (matches typical host UID for bind mounts).
RUN (userdel -r ubuntu 2>/dev/null || true) \
    && groupadd --gid ${GID} ${USERNAME} \
    && useradd --uid ${UID} --gid ${GID} -m -s /bin/bash ${USERNAME} \
    && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME} \
    && chmod 0440 /etc/sudoers.d/${USERNAME} \
    && mkdir -p /opt/python /opt/venv /opt/mai /workspace \
    && chown -R ${USERNAME}:${USERNAME} /opt/python /opt/venv /opt/mai /workspace

# Make the venv visible to login shells too (SSH sessions, SkyPilot setup/run)
RUN printf 'export VIRTUAL_ENV=/opt/venv\nexport PATH=/opt/venv/bin:$HOME/.local/bin:$PATH\nexport MAI_CONSTRAINTS=/opt/mai/constraints.txt\n' \
        > /etc/profile.d/mai.sh

USER ${USERNAME}
WORKDIR /opt/mai
COPY --chown=${UID}:${GID} pyproject.toml uv.lock smoke_test.py ./

RUN --mount=type=cache,target=/home/${USERNAME}/.cache/uv,uid=${UID},gid=${GID} \
    uv python install ${PYTHON_VERSION} \
    && UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --locked --no-install-project --no-dev --python ${PYTHON_VERSION} \
    && uv export --locked --no-dev --no-hashes --no-emit-project --no-header -o constraints.txt \
    && python smoke_test.py

WORKDIR /workspace
CMD ["bash"]

# -----------------------------------------------------------------------------
# runtime: what cloud jobs run on
# -----------------------------------------------------------------------------
FROM common AS runtime
LABEL org.opencontainers.image.description="mai-base runtime: CUDA + locked PyTorch stack"

# -----------------------------------------------------------------------------
# dev: interactive development (devcontainer, cloud dev boxes)
# -----------------------------------------------------------------------------
FROM common AS dev
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG PYTHON_VERSION=3.12
ARG USERNAME=devuser
ARG UID=1000
ARG GID=1000
ARG SKYPILOT_EXTRAS="aws,gcp,azure,kubernetes,lambda,runpod"

USER root
# git-lfs is dev-only: Ubuntu's binary is built with an old Go (go1.22.2) that
# Grype flags, and cloud jobs fetch models/data over HTTP (HF Hub), not LFS.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config zsh tmux vim nano htop nvtop tree git-lfs \
        libssl-dev libffi-dev libhdf5-dev \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install --system \
    && chsh -s /bin/zsh ${USERNAME} \
    && git config --system core.editor vim \
    && git config --system pull.rebase false

USER ${USERNAME}

# Dev dependency group (Jupyter, ruff, pytest, plotting) on top of the base set,
# then re-export constraints so project installs respect them too.
WORKDIR /opt/mai
RUN --mount=type=cache,target=/home/${USERNAME}/.cache/uv,uid=${UID},gid=${GID} \
    UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --locked --no-install-project --python ${PYTHON_VERSION} \
    && uv export --locked --no-hashes --no-emit-project --no-header -o constraints.txt \
    && python smoke_test.py

# CLI tools in their own isolated envs (not part of the lock on purpose)
RUN --mount=type=cache,target=/home/${USERNAME}/.cache/uv,uid=${UID},gid=${GID} \
    uv tool install "skypilot[${SKYPILOT_EXTRAS}]" \
    && uv tool install copier

# Shell niceties + Claude Code
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended \
    && echo 'source /etc/profile.d/mai.sh' >> ~/.zshrc \
    && (curl -fsSL https://claude.ai/install.sh | bash || echo "WARN: Claude Code install failed") \
    && python /opt/mai/smoke_test.py   # tools above must not have disturbed /opt/venv

WORKDIR /workspace
CMD ["sleep", "infinity"]
