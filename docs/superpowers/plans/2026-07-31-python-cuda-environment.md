# Python and CUDA Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete roadmap stages 0.2 and 0.3 with sanitized hardware evidence, a locked Python 3.11 dependency graph, and a verified CUDA-enabled QLoRA development environment.

**Architecture:** Keep the existing Conda environment `sft` as the only project environment. Install `uv` as a standalone user tool, point `UV_PROJECT_ENVIRONMENT` at `$CONDA_PREFIX`, lock dependencies in `uv.lock`, and synchronize the dedicated Conda environment from that lock.

**Tech Stack:** WSL2 Ubuntu 26.04, Conda 26.5.3, Python 3.11, uv, PyTorch 2.12.1 CUDA 13.0 wheels, Transformers, TRL, PEFT, Datasets, Accelerate, bitsandbytes, Pytest, Ruff.

## Global Constraints

- Use the existing Conda environment named `sft`; do not create `.venv`.
- Require Python `>=3.11,<3.12`.
- Install `torch==2.12.1` only from `https://download.pytorch.org/whl/cu130`.
- Install no system CUDA Toolkit.
- Download no model weights, datasets, adapters, or checkpoints.
- Record no device serial number, Windows username, public IP, secret, or token.
- Stop on a failed dependency lock, failed import, unavailable CUDA device, incorrect GPU, or bitsandbytes backend failure.
- Commit exact resolved versions in `uv.lock`.

---

### Task 1: Close the WSL2 hardware gate

**Files:**
- Modify: `ROADMAP.md`
- Verify: `docs/evidence/hardware-wsl.md`

**Interfaces:**
- Consumes: Fresh WSL2 GPU, distribution, memory, disk, and HTTPS checks.
- Produces: A tracked, sanitized hardware evidence file and completed roadmap stage 0.2 checkboxes.

- [ ] **Step 1: Re-run the hardware gate**

Run from PowerShell:

```powershell
wsl.exe -d Ubuntu --exec /bin/bash -lc 'nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader'
wsl.exe -d Ubuntu --exec lsb_release -ds
wsl.exe -d Ubuntu --exec free -h
wsl.exe -d Ubuntu --exec df -h /
wsl.exe -d Ubuntu --exec curl -sS -o /dev/null -w '%{http_code}\n' --max-time 15 https://github.com
```

Expected:

```text
NVIDIA GeForce RTX 3060 Laptop GPU, 6144 MiB, 610.47
Ubuntu 26.04 LTS
Root filesystem available space greater than 25 GiB
HTTPS status 200
```

- [ ] **Step 2: Validate the evidence file**

Run:

```powershell
rg -n "RTX 3060|6144 MiB|Ubuntu 26.04|955G|HTTP" docs/evidence/hardware-wsl.md
Select-String -Path docs/evidence/hardware-wsl.md -SimpleMatch $env:USERNAME
Select-String -Path docs/evidence/hardware-wsl.md -Pattern '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
```

Expected: the first command finds the recorded gate facts; the second finds no
private identifier.

- [ ] **Step 3: Mark stage 0.2 complete**

In `ROADMAP.md`, change the four checkboxes under `### 0.2 WSL2 GPU 门禁` from
`[ ]` to `[x]`. Do not mark any stage 0.3 item complete yet.

- [ ] **Step 4: Verify the documentation diff**

Run:

```powershell
git diff --check -- ROADMAP.md docs/evidence/hardware-wsl.md
git diff -- ROADMAP.md docs/evidence/hardware-wsl.md
```

Expected: only the four stage 0.2 checkboxes and the new sanitized evidence
file appear.

---

### Task 2: Declare and lock the Python dependency graph

**Files:**
- Create: `pyproject.toml`
- Create: `uv.lock`

**Interfaces:**
- Consumes: Python 3.11 in the `sft` Conda environment and the official PyTorch CUDA 13.0 wheel index.
- Produces: Project metadata and a complete exact dependency lock.

- [ ] **Step 1: Install standalone uv**

Run from PowerShell:

```powershell
wsl.exe -d Ubuntu --exec curl --proto =https --tlsv1.2 -fLsS --retry 3 -o /tmp/uv-installer.sh https://astral.sh/uv/install.sh
wsl.exe -d Ubuntu --exec env UV_NO_MODIFY_PATH=1 sh /tmp/uv-installer.sh
wsl.exe -d Ubuntu --exec /bin/bash -lc '~/.local/bin/uv --version'
wsl.exe -d Ubuntu --exec rm /tmp/uv-installer.sh
```

Expected: `uv --version` prints a version and the temporary installer is
removed after a successful install.

- [ ] **Step 2: Create `pyproject.toml`**

Create exactly:

```toml
[project]
name = "agent-toolcall-sft"
version = "0.1.0"
description = "Safety-focused tool-routing SFT and paired evaluation for Qwen3-1.7B"
requires-python = ">=3.11,<3.12"
dependencies = [
    "accelerate",
    "bitsandbytes",
    "datasets",
    "jsonschema",
    "numpy",
    "peft",
    "pydantic",
    "pyyaml",
    "torch==2.12.1",
    "transformers",
    "trl",
]

[dependency-groups]
dev = [
    "pytest",
    "ruff",
]

[tool.uv]
package = false
environments = [
    "sys_platform == 'linux' and platform_machine == 'x86_64'",
]
required-environments = [
    "sys_platform == 'linux' and platform_machine == 'x86_64'",
]

[tool.uv.sources]
torch = { index = "pytorch-cu130" }

[[tool.uv.index]]
name = "pytorch-cu130"
url = "https://download.pytorch.org/whl/cu130"
explicit = true

[tool.ruff]
target-version = "py311"
line-length = 88
```

- [ ] **Step 3: Generate the universal lock**

Run from WSL with `sft` activated:

```bash
conda activate sft
cd /mnt/d/Code/Projects/agent-toolcall-sft
export UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX"
~/.local/bin/uv lock
```

Expected: `uv.lock` is created and contains `torch` version `2.12.1` from the
`cu130` index.

- [ ] **Step 4: Verify the lock without changing it**

Run:

```bash
~/.local/bin/uv lock --check
grep -n 'name = "torch"' uv.lock
grep -n '2.12.1' uv.lock
grep -n 'download.pytorch.org/whl/cu130' uv.lock
```

Expected: `uv lock --check` exits 0 and every PyTorch assertion is found.

---

### Task 3: Synchronize and verify the CUDA environment

**Files:**
- Modify: `$CONDA_PREFIX` outside Git
- Verify: `pyproject.toml`
- Verify: `uv.lock`

**Interfaces:**
- Consumes: The exact dependency graph from `uv.lock`.
- Produces: An importable QLoRA stack in Conda `sft` with a working CUDA backend.

- [ ] **Step 1: Synchronize the locked environment**

Run:

```bash
conda activate sft
cd /mnt/d/Code/Projects/agent-toolcall-sft
export UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX"
export UV_NO_PROGRESS=1
~/.local/bin/uv sync --locked
```

Expected: the command exits 0 and no `.venv` directory is created.

- [ ] **Step 2: Verify all required imports**

Run:

```bash
UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX" ~/.local/bin/uv run \
  python -c "import accelerate, bitsandbytes, datasets, jsonschema, numpy, peft, pydantic, torch, transformers, trl, yaml; print('imports_ok')"
```

Expected:

```text
imports_ok
```

- [ ] **Step 3: Run the CUDA smoke test**

Run:

```bash
UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX" ~/.local/bin/uv run python - <<'PY'
import torch

print("torch:", torch.__version__)
print("torch_cuda:", torch.version.cuda)
print("cuda_available:", torch.cuda.is_available())
print(
    "device:",
    torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
)
print(
    "vram_gib:",
    round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2)
    if torch.cuda.is_available()
    else None,
)
PY
```

Expected:

```text
torch: 2.12.1+cu130
torch_cuda: 13.0
cuda_available: True
device: NVIDIA GeForce RTX 3060 Laptop GPU
vram_gib: 6.0
```

- [ ] **Step 4: Verify the bitsandbytes CUDA backend**

Run:

```bash
UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX" ~/.local/bin/uv run \
  python -m bitsandbytes
```

Expected: the diagnostics identify CUDA and do not report a missing CUDA
binary or CPU-only fallback.

- [ ] **Step 5: Verify environment isolation**

Run:

```bash
test "$CONDA_DEFAULT_ENV" = "sft"
test -x "$UV_PROJECT_ENVIRONMENT/bin/python"
test ! -e .venv
python -c "import sys; print(sys.executable)"
```

Expected:

```text
$CONDA_PREFIX/bin/python
```

---

### Task 4: Record completion and commit the environment bootstrap

**Files:**
- Modify: `ROADMAP.md`
- Verify: `docs/evidence/hardware-wsl.md`
- Verify: `pyproject.toml`
- Verify: `uv.lock`
- Modify: `docs/superpowers/specs/2026-07-31-python-cuda-environment-design.md`
- Verify: `docs/superpowers/plans/2026-07-31-python-cuda-environment.md`

**Interfaces:**
- Consumes: Successful dependency, import, CUDA, bitsandbytes, and repository checks.
- Produces: Completed stage 0.3 roadmap evidence and a reproducible Git commit.

- [ ] **Step 1: Adapt and complete stage 0.3**

In `ROADMAP.md`:

- Replace the `.venv` wording with the approved `sft` Conda environment plus
  standalone uv workflow.
- Change all five stage 0.3 checkboxes to `[x]`.
- Change the smoke-test invocation to set
  `UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX"` before `uv run`.
- Keep the prohibition on installing a complete system CUDA Toolkit.

- [ ] **Step 2: Run repository checks**

Run:

```powershell
git diff --check
git status --short
git diff --stat
Get-ChildItem -Recurse -File | Where-Object Length -gt 10MB
```

Expected: no whitespace errors, no `.venv`, no model artifacts, and no new
file larger than 10 MiB.

- [ ] **Step 3: Re-run final environment verification**

Run from WSL:

```bash
conda activate sft
cd /mnt/d/Code/Projects/agent-toolcall-sft
export UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX"
~/.local/bin/uv lock --check
~/.local/bin/uv run python -c \
  "import torch; assert torch.cuda.is_available(); assert 'RTX 3060' in torch.cuda.get_device_name(0); print(torch.__version__, torch.version.cuda)"
```

Expected: lock check exits 0 and Python prints PyTorch 2.12.1 with CUDA 13.0.

- [ ] **Step 4: Commit the verified bootstrap**

Run:

```powershell
git add -- ROADMAP.md docs/evidence/hardware-wsl.md pyproject.toml uv.lock docs/superpowers/specs/2026-07-31-python-cuda-environment-design.md docs/superpowers/plans/2026-07-31-python-cuda-environment.md
git diff --cached --check
git diff --cached --stat
git commit -m "chore: bootstrap reproducible Python environment"
```

Expected: the commit succeeds and contains only the six listed paths.

- [ ] **Step 5: Verify final Git state**

Run:

```powershell
git log -2 --oneline
git status --short --branch
```

Expected: the design and bootstrap commits are present and the working tree is
clean.
