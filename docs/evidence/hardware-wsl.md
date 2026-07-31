# WSL2 Hardware Evidence

- Collected: 2026-07-31
- Environment: WSL2
- Distribution: Ubuntu 26.04 LTS
- Architecture: x86_64

## GPU

Command:

```bash
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
```

Output:

```text
NVIDIA GeForce RTX 3060 Laptop GPU, 6144 MiB, 610.47
```

The WSL-visible GPU and VRAM meet the roadmap gate of an RTX 3060 Laptop GPU
with at least 6144 MiB VRAM.

## Operating system

Commands:

```bash
uname -a
lsb_release -ds
```

Sanitized output:

```text
Linux 6.18.33.2-microsoft-standard-WSL2 x86_64 GNU/Linux
Ubuntu 26.04 LTS
```

The hostname was omitted from the recorded `uname` output.

## Memory

Command:

```bash
free -h
```

Output:

```text
               total        used        free      shared  buff/cache   available
Mem:           7.6Gi       592Mi       6.3Gi       3.5Mi       842Mi       7.0Gi
Swap:          2.0Gi          0B       2.0Gi
```

## Root filesystem

Command:

```bash
df -h /
```

Output:

```text
Filesystem      Size  Used Avail Use% Mounted on
/dev/sdd       1007G  1.6G  955G   1% /
```

The root filesystem exceeds the roadmap gate of 25 GiB available space.

## Network sanity check

Command:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 15 https://github.com
```

Output:

```text
200
```

The initial NAT configuration could reach GitHub but timed out when connecting
to the Python and PyTorch package indexes because the Windows localhost proxy
was not mirrored into WSL. WSL was changed to mirrored networking with DNS
tunneling and automatic proxy propagation in the user-level `.wslconfig`, then
fully restarted.

Post-restart checks:

```bash
curl -sS -I -o /dev/null -w '%{http_code} %{time_total}\n' \
  --max-time 15 https://pypi.org/simple/
curl -sS -I -o /dev/null -w '%{http_code} %{time_total}\n' \
  --max-time 15 https://download.pytorch.org/whl/cu130/torch/
```

Output:

```text
200 1.413373
200 6.297547
```

The package indexes were reachable through the mirrored proxy after the WSL
restart.
