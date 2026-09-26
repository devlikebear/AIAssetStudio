"""Async client for the ComfyUI HTTP API (routes are defined in ComfyUI/server.py)."""

import asyncio
import time
import uuid
from pathlib import Path

import httpx


class ComfyError(Exception):
    """Base class for ComfyUI errors."""


class ComfyUnavailable(ComfyError):
    """ComfyUI could not be reached."""


class ComfyPromptError(ComfyError):
    """ComfyUI rejected the graph at validation time (POST /prompt)."""

    def __init__(self, error: dict | str | None, node_errors: dict):
        self.error = error
        self.node_errors = node_errors
        parts = []
        if isinstance(error, dict):
            parts.append(f"{error.get('type', 'error')}: {error.get('message', '')}".strip())
        elif error:
            parts.append(str(error))
        for node_id, info in node_errors.items():
            for err in info.get("errors", []):
                parts.append(f"node {node_id} ({info.get('class_type', '?')}): {err.get('message', '')}")
        super().__init__("; ".join(parts) or "prompt rejected by ComfyUI")


class ComfyExecutionError(ComfyError):
    """The graph failed, or was interrupted, while running."""

    def __init__(self, exception_type: str, exception_message: str, node_type: str | None = None):
        self.exception_type = exception_type
        self.exception_message = exception_message
        self.node_type = node_type
        where = f" in {node_type}" if node_type else ""
        super().__init__(f"{exception_type}{where}: {exception_message}")

    @classmethod
    def from_messages(cls, messages: list) -> "ComfyExecutionError":
        for kind, data in messages:
            if kind == "execution_error":
                return cls(
                    str(data.get("exception_type", "unknown")),
                    str(data.get("exception_message", "")).strip(),
                    data.get("node_type"),
                )
            if kind == "execution_interrupted":
                # Sent by POST /interrupt; carries no exception fields.
                return cls("interrupted", "execution was interrupted", data.get("node_type"))
        return cls("unknown", "ComfyUI reported an error without details")


class ComfyTimeout(ComfyError):
    """The prompt did not finish within the allowed time."""


def output_files(entry: dict, node_id: str, key: str = "images") -> list[dict]:
    """File records ({filename, subfolder, type}) that a node wrote, from a /history entry."""
    return list(entry.get("outputs", {}).get(node_id, {}).get(key, []))


class ComfyClient:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.client_id = uuid.uuid4().hex
        self._http = httpx.AsyncClient(
            base_url=self.base_url, transport=transport, timeout=httpx.Timeout(30.0, connect=5.0)
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return await self._http.request(method, path, **kwargs)
        except httpx.TransportError as e:
            raise ComfyUnavailable(f"ComfyUI not reachable at {self.base_url}: {e!r}") from e

    async def _json(self, method: str, path: str, **kwargs):
        r = await self._request(method, path, **kwargs)
        if r.status_code != 200:
            raise ComfyError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:500]}")
        return r.json()

    async def system_stats(self, timeout: float | None = None) -> dict:
        kwargs = {"timeout": timeout} if timeout is not None else {}
        return await self._json("GET", "/system_stats", **kwargs)

    async def is_up(self) -> bool:
        try:
            r = await self._request("GET", "/system_stats", timeout=3.0)
        except ComfyUnavailable:
            return False
        return r.status_code == 200

    async def object_info(self) -> dict:
        return await self._json("GET", "/object_info")

    async def list_models(self, folder: str) -> list[str]:
        r = await self._request("GET", f"/models/{folder}")
        if r.status_code == 404:  # folder type unknown to this ComfyUI
            return []
        if r.status_code != 200:
            raise ComfyError(f"GET /models/{folder} -> HTTP {r.status_code}")
        return list(r.json())

    async def submit(self, graph: dict, prompt_id: str | None = None) -> str:
        """Queue an API-format graph. Pass `prompt_id` (a UUID) to know the id before ComfyUI answers."""
        body: dict = {"prompt": graph, "client_id": self.client_id}
        if prompt_id is not None:
            body["prompt_id"] = prompt_id
        r = await self._request("POST", "/prompt", json=body)
        try:
            data = r.json()
        except ValueError:
            data = {}
        node_errors = data.get("node_errors") or {}
        if r.status_code == 400 or node_errors:
            raise ComfyPromptError(data.get("error"), node_errors)
        if r.status_code != 200:
            raise ComfyError(f"POST /prompt -> HTTP {r.status_code}: {r.text[:500]}")
        return data["prompt_id"]

    async def wait(self, prompt_id: str, timeout: float, poll: float = 1.0) -> dict:
        """Poll /history until the prompt finishes; return its history entry.

        /history/{id} stays empty while the prompt is queued or running. Once present, the prompt is finished:
        `status_str` is "success" or "error" (errors have `completed=False`, so do not poll on `completed`).
        """
        deadline = time.monotonic() + timeout
        while True:
            entry = (await self._json("GET", f"/history/{prompt_id}")).get(prompt_id)
            if entry is not None:
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    raise ComfyExecutionError.from_messages(status.get("messages", []))
                return entry
            if time.monotonic() >= deadline:
                raise ComfyTimeout(f"prompt {prompt_id} did not finish within {timeout:g} s")
            await asyncio.sleep(poll)

    async def upload_image(self, path: Path, name: str, subfolder: str = "aiassetstudio") -> str:
        """Upload into ComfyUI's input folder (overwriting). Returns the value LoadImage expects: "subfolder/name"."""
        files = {"image": (name, path.read_bytes(), "image/png")}
        data = {"subfolder": subfolder, "type": "input", "overwrite": "true"}
        r = await self._request("POST", "/upload/image", files=files, data=data)
        if r.status_code != 200:
            raise ComfyError(f"POST /upload/image -> HTTP {r.status_code}: {r.text[:300]}")
        body = r.json()
        return f"{body['subfolder']}/{body['name']}" if body.get("subfolder") else body["name"]

    async def fetch_output(self, filename: str, subfolder: str, type_: str = "output") -> bytes:
        params = {"filename": filename, "subfolder": subfolder, "type": type_}
        r = await self._request("GET", "/view", params=params)
        if r.status_code != 200:
            raise ComfyError(f"GET /view {subfolder}/{filename} -> HTTP {r.status_code}")
        return r.content

    async def free(self, unload_models: bool = True, free_memory: bool = True) -> None:
        # ComfyUI reads the JSON body unconditionally, so always send one.
        r = await self._request("POST", "/free", json={"unload_models": unload_models, "free_memory": free_memory})
        if r.status_code != 200:
            raise ComfyError(f"POST /free -> HTTP {r.status_code}")

    async def interrupt(self, prompt_id: str | None = None) -> None:
        """Interrupt the running prompt. With `prompt_id`, only if that prompt is the one running.

        ComfyUI is shared with other sessions; a global interrupt would stop their work, so pass the id.
        """
        body = {"prompt_id": prompt_id} if prompt_id else {}
        r = await self._request("POST", "/interrupt", json=body)
        if r.status_code != 200:
            raise ComfyError(f"POST /interrupt -> HTTP {r.status_code}")

    async def delete_queued(self, prompt_ids: list[str]) -> None:
        """Remove prompts that are still waiting in ComfyUI's queue (no effect on running ones)."""
        r = await self._request("POST", "/queue", json={"delete": prompt_ids})
        if r.status_code != 200:
            raise ComfyError(f"POST /queue -> HTTP {r.status_code}")
