"""Remove the task containers whose process has ended, such as one that was killed.

python -m tasks.swebench.cleanup
"""

import os

from tasks.swebench.images import docker
from tasks.swebench.workspace import LABEL


def running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def main() -> None:
    listed = docker(
        "ps",
        "--all",
        "--filter",
        f"label={LABEL}",
        "--format",
        f'{{{{.Names}}}} {{{{.Label "{LABEL}"}}}}',
        timeout=120,
    )
    if listed.returncode != 0:
        raise RuntimeError(f"docker ps failed: {listed.stderr.strip()}")
    owners = dict(line.split() for line in listed.stdout.splitlines())
    orphans = [name for name, pid in owners.items() if not running(int(pid))]
    if orphans:
        removed = docker("rm", "--force", *orphans, timeout=600)
        if removed.returncode != 0:
            raise RuntimeError(f"docker rm failed: {removed.stderr.strip()}")
    print(f"removed {len(orphans)} orphaned containers; {len(owners) - len(orphans)} in use")


if __name__ == "__main__":
    main()
