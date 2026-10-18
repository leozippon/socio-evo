"""Docker exec transport for proxies that cannot relay hijacked stdout streams.

Use detached exec, poll its exit status, and retrieve output through the archive API.
No host paths or sockets are mounted in the container.
"""

import io
import shlex
import tarfile
import time
import uuid
from collections import namedtuple

ExecResult = namedtuple("ExecResult", "exit_code output")


def captured_exec(container, cmd, *, timeout=60, workdir=None, user=None):
    argv = shlex.split(cmd) if isinstance(cmd, str) else cmd
    path = f"/tmp/socio-exec-{uuid.uuid4().hex}.log"
    shell = (
        f"ulimit -f 131072; timeout --kill-after=5 {int(timeout)} "
        f"{shlex.join(argv)} > {shlex.quote(path)} 2>&1"
    )
    options = {"workdir": workdir} if workdir else {}
    if user is not None:
        options["user"] = user
    api = container.client.api
    exec_id = api.exec_create(container.id, ["/bin/bash", "-c", shell], **options)["Id"]
    api.exec_start(exec_id, detach=True)
    deadline = time.monotonic() + timeout + 30
    while True:
        state = api.exec_inspect(exec_id)
        if not state["Running"] and state["ExitCode"] is not None:
            break
        if time.monotonic() > deadline:
            raise TimeoutError(f"container exec failed to finish: {container.name}")
        time.sleep(0.25)
    chunks, _ = container.get_archive(path)
    with tarfile.open(fileobj=io.BytesIO(b"".join(chunks))) as archive:
        member = archive.getmembers()[0]
        with archive.extractfile(member) as f:
            output = f.read()
    return ExecResult(state["ExitCode"], output)
