"""Smoke test against a running backend: two transparent sprites in project "smoke".

Start the backend first (`uv run aiassetstudio serve`), then:
    uv run python scripts/smoke_image.py
Exit code 0 when both sprites are generated and their processed borders are fully transparent.
"""

import sys
import time

import httpx

from aiassetstudio.config import load_settings
from aiassetstudio.store.files import project_dir

PROJECT = "smoke"
DESCRIPTION = "a small green slime monster with big eyes"
TERMINAL = ("done", "failed", "cancelled")


def main() -> int:
    settings = load_settings()
    base_url = f"http://{settings.host}:{settings.port}"
    with httpx.Client(base_url=base_url, timeout=90) as client:
        try:
            status = client.get("/api/status").json()
        except httpx.TransportError:
            print(f"backend not reachable at {base_url}; start it with `uv run aiassetstudio serve`")
            return 1
        print(f"backend {base_url}, ComfyUI up: {status['comfy']['up']}, queue: {status['queue']}")

        if client.get(f"/api/projects/{PROJECT}").status_code == 404:
            client.post("/api/projects", json={"slug": PROJECT, "name": "Smoke test"}).raise_for_status()
        r = client.post(
            "/api/jobs/image", json={"project": PROJECT, "kind": "sprite", "description": DESCRIPTION, "count": 2}
        )
        r.raise_for_status()
        job_id = r.json()["job_id"]
        print(f"job {job_id} queued")

        started = time.monotonic()
        while True:
            job = client.get(f"/api/jobs/{job_id}", params={"wait": 60}).json()
            print(f"  [{time.monotonic() - started:4.0f} s] {job['status']} {job['stage'] or ''}")
            if job["status"] in TERMINAL:
                break

    if job["status"] != "done":
        print(f"FAIL: job {job['status']}: {job['error']}")
        return 1
    ok = len(job["assets"]) == 2
    for asset in job["assets"]:
        stats = asset["meta"]["alpha_processed"]
        path = project_dir(settings, PROJECT) / "assets" / asset["id"] / "processed.png"
        print(f"asset {asset['id']} seed={asset['seed']} timings={asset['meta']['timings']}")
        print(f"  {path}")
        print(f"  alpha_processed={stats}")
        if stats["border_mean"] != 0:
            ok = False
            print("  FAIL: the processed image border is not fully transparent")
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
