# Python and CUDA Environment Design

## Goal

Complete roadmap stages 0.2 and 0.3 with a reproducible Python 3.11 toolchain
that can use the RTX 3060 Laptop GPU from WSL2, while retaining the existing
Conda environment named `sft` and producing the required `pyproject.toml` and
`uv.lock`.

## Current state

- The repository contains only the roadmap, `.gitignore`, and the untracked
  hardware evidence document.
- WSL2 runs Ubuntu 26.04 LTS.
- WSL2 sees an NVIDIA GeForce RTX 3060 Laptop GPU with 6144 MiB VRAM.
- The NVIDIA driver is 610.47 and reports CUDA UMD 13.3 capability.
- Miniconda 26.5.3 is installed under `/home/mdiven/miniconda3`.
- The project environment is named `sft` and contains Python 3.11.15 and pip,
  but no project or training dependencies.

## Chosen approach

Keep `sft` as the single project environment and install `uv` as a standalone
user tool outside that environment. Set `UV_PROJECT_ENVIRONMENT` to the active
Conda prefix whenever running project-oriented `uv` commands:

```bash
export UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX"
```

This lets `uv lock`, `uv sync`, and `uv run` operate on the dedicated Conda
environment without creating a second `.venv`. The `sft` environment is
dedicated to this repository, so `uv sync` is allowed to remove packages that
are not declared in `pyproject.toml`.

## Alternatives considered

1. Use a separate `.venv` exactly as the original roadmap states. This follows
   uv's default workflow, but duplicates the already-created Conda environment
   and makes interpreter selection less clear.
2. Use Conda alone with `environment.yml`. This is simple, but does not produce
   the roadmap-required universal `uv.lock`.
3. Use the existing Conda environment as uv's project environment. This retains
   the user's chosen workflow and still produces `pyproject.toml` and
   `uv.lock`. This is the selected option.

## Dependency model

`pyproject.toml` will define:

- Project name: `agent-toolcall-sft`
- Project version: `0.1.0`
- Python requirement: `>=3.11,<3.12`
- Packaging mode: disabled until the source package is created in phase A
- Runtime dependencies:
  - `torch==2.12.1`
  - `transformers`
  - `trl`
  - `peft`
  - `datasets`
  - `accelerate`
  - `bitsandbytes`
  - `pydantic`
  - `PyYAML`
  - `jsonschema`
  - `numpy`
- Development dependencies:
  - `pytest`
  - `ruff`

PyTorch will come from the official CUDA 13.0 wheel index:

```text
https://download.pytorch.org/whl/cu130
```

PyTorch 2.12.1 publishes an official CUDA 13.0 wheel, and the installed NVIDIA
driver reports CUDA 13.3 capability. Current bitsandbytes Linux wheels support
CUDA 13.0 and the RTX 3060's `sm86` architecture. No system CUDA Toolkit will
be installed.

Direct dependencies other than PyTorch will resolve to the newest mutually
compatible releases available during this bootstrap. `uv.lock` will record the
exact direct and transitive versions, so subsequent syncs use the frozen
resolution.

## Repository changes

- Modify `ROADMAP.md` to mark all stage 0.2 checks complete and to document the
  approved Conda-plus-uv adaptation in stage 0.3.
- Retain `docs/evidence/hardware-wsl.md` as the sanitized hardware gate record.
- Create `pyproject.toml` with project metadata, dependencies, the explicit
  PyTorch index, and Ruff/Pytest configuration.
- Create `uv.lock` from `pyproject.toml`.
- Do not commit Conda files, model weights, caches, generated datasets, or
  checkpoints.

## Execution flow

1. Commit the design specification separately.
2. Update the roadmap and validate the hardware evidence.
3. Install standalone uv using Astral's official installer.
4. Activate `sft` and set `UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX"`.
5. Create `pyproject.toml`.
6. Generate `uv.lock`.
7. Synchronize the locked dependencies into `sft`.
8. Run dependency imports and the CUDA smoke test.
9. Confirm no `.venv` was created and no large artifacts entered Git.
10. Commit the environment bootstrap as
    `chore: bootstrap reproducible Python environment`.

## Failure handling

- Stop if the PyTorch CUDA wheel cannot resolve from the official index.
- Stop if dependency resolution cannot satisfy Python 3.11.
- Stop if `torch.cuda.is_available()` is false.
- Stop if PyTorch reports a different GPU or less VRAM than the hardware
  evidence.
- Stop if bitsandbytes cannot import or cannot detect its CUDA backend.
- Do not install a system CUDA Toolkit as a workaround.
- Do not download the Qwen base model during environment bootstrap.

## Verification

The completed environment must pass:

```bash
conda run -n sft python --version
uv lock --check
UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX" uv sync --locked
UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX" uv run python -c \
  "import torch, transformers, trl, peft, datasets, accelerate, bitsandbytes"
```

The CUDA smoke test must report:

- `cuda_available: True`
- Device name containing `NVIDIA GeForce RTX 3060 Laptop GPU`
- Total VRAM approximately 6 GiB
- A CUDA runtime supplied by the PyTorch wheel

Repository checks must pass:

```bash
git diff --check
git status --short
```

No `.venv`, model weights, checkpoints, or generated datasets may appear in
the tracked changes.
