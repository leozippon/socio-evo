"""The task images: Epoch AI's prebuilt SWE-bench Verified evaluation images on ghcr.io.

SWE-bench publishes an instance's evaluation image on Docker Hub as
`swebench/sweb.eval.x86_64.<instance id>`, with the "__" of the id written "_1776_". Docker Hub
is unreachable from our machines, so the tasks use the same images as Epoch AI builds them with
its fork of the SWE-bench harness and publishes them on ghcr.io, under the instance id as it is:
`ghcr.io/epoch-research/swe-bench.eval.x86_64.<instance id>:latest` (`image_name`), labelled
`swe-bench.instance_id`. An image runs as root and holds the task's repository in /testbed at
the task's base commit, with SWE-bench's pre-install edits left uncommitted in the working tree
(astropy's pinned build requirement, for one), and the environment installed in the conda
environment `testbed`, which a login shell activates.

Docker is driven through its command line, so the current Docker context (rootless here) applies.
"""

import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed

REGISTRY = "ghcr.io/epoch-research"
PULL_COMMAND = "python -m tasks.swebench.pull"
_MANIFESTS = ", ".join(
    f"application/vnd.{kind}"
    for kind in (
        "docker.distribution.manifest.v2+json",
        "docker.distribution.manifest.list.v2+json",
        "oci.image.manifest.v1+json",
        "oci.image.index.v1+json",
    )
)


class MissingImage(RuntimeError):
    """A task's image is not on this machine."""


def image_name(instance_id: str) -> str:
    """The Epoch AI image of a SWE-bench instance."""
    return f"{REGISTRY}/swe-bench.eval.x86_64.{instance_id}:latest"


def docker(*args: str, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    """Run the Docker command line and return what it did, without raising on failure."""
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def published(image: str) -> bool:
    """Whether the registry holds `image`, asked anonymously for its manifest. Any answer other
    than found or not found raises."""
    host, _, reference = image.partition("/")
    repository, _, tag = reference.rpartition(":")
    scope = urllib.parse.urlencode({"scope": f"repository:{repository}:pull"})
    try:
        with urllib.request.urlopen(f"https://{host}/token?{scope}", timeout=60) as answer:
            token = json.load(answer)["token"]
    except urllib.error.HTTPError as error:
        if error.code == 403:  # ghcr.io denies a token for a repository that does not exist
            return False
        raise
    request = urllib.request.Request(
        f"https://{host}/v2/{repository}/manifests/{tag}",
        method="HEAD",
        headers={"Authorization": f"Bearer {token}", "Accept": _MANIFESTS},
    )
    try:
        with urllib.request.urlopen(request, timeout=60):
            return True
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise


def local(image: str) -> bool:
    """Whether `image` is on this machine; a failure of Docker itself raises."""
    result = docker("image", "inspect", "--format", "{{.Id}}", image, timeout=120)
    if result.returncode == 0:
        return True
    if "No such image" in result.stderr:
        return False
    raise RuntimeError(f"docker image inspect {image} failed: {result.stderr.strip()}")


def require(image: str) -> None:
    """Raise `MissingImage` unless `image` is on this machine."""
    if not local(image):
        raise MissingImage(f"{image} is not pulled; run `{PULL_COMMAND}` or `docker pull {image}`")


def pull(images: Sequence[str], workers: int = 8, attempts: int = 3) -> None:
    """Pull the images not yet on this machine, `workers` at a time, printing progress. An image
    whose pull fails is tried again up to `attempts` times in all, and layers a failed or
    stopped pull left behind are kept, so pulling again resumes. Raises after trying every
    image if any could not be pulled."""
    missing = [image for image in dict.fromkeys(images) if not local(image)]
    print(f"{len(images) - len(missing)} of {len(images)} images present; pulling {len(missing)}")
    started = time.monotonic()
    failed: dict[str, str] = {}
    with ThreadPoolExecutor(max(1, workers)) as pool:
        pulls = {pool.submit(_pull, image, attempts): image for image in missing}
        for done, future in enumerate(as_completed(pulls), 1):
            image, result = pulls[future], future.result()
            outcome = "pulled" if result.returncode == 0 else "FAILED"
            if result.returncode != 0:
                failed[image] = result.stderr.strip()
            minutes = (time.monotonic() - started) / 60
            print(f"[{done}/{len(missing)}, {minutes:.1f} min] {outcome} {image}", flush=True)
    print(f"Docker reports {images_disk_use()} on disk for all images of this daemon")
    if failed:
        lines = "\n".join(f"  {image}: {error}" for image, error in failed.items())
        raise RuntimeError(f"{len(failed)} images could not be pulled:\n{lines}")


def _pull(image: str, attempts: int) -> subprocess.CompletedProcess[str]:
    for _ in range(attempts):
        result = docker("pull", "--quiet", image)
        if result.returncode == 0:
            break
    return result


def images_disk_use() -> str:
    """The disk space Docker reports for all its images, shared layers counted once."""
    result = docker("system", "df", "--format", "{{json .}}", timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"docker system df failed: {result.stderr.strip()}")
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    return next(row["Size"] for row in rows if row["Type"] == "Images")
