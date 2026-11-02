"""A fake ComfyUI HTTP API for tests, served through httpx.MockTransport.

Mirrors the ComfyUI 0.37.0 behaviour the app relies on: /history/{id} is empty until a prompt finishes,
errors come back as status_str "error" with an execution_error (or execution_interrupted) message,
and POST /interrupt only stops the prompt that is currently running.
"""

import functools
import io
import json
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf
from PIL import Image

from aiassetstudio.comfy.preflight import REQUIRED

ALL_NODES = {node for req in REQUIRED.values() for node in req.nodes}
ALL_MODELS: dict[str, set[str]] = {}
for _req in REQUIRED.values():
    for _folder, _names in _req.models.items():
        ALL_MODELS.setdefault(_folder, set()).update(_names)

SYSTEM_STATS = {
    "system": {"os": "win32", "ram_total": 34049220608, "ram_free": 19765604352, "comfyui_version": "0.37.0"},
    "devices": [
        {"name": "cuda:0 fake", "type": "cuda", "index": 0, "vram_total": 17170956288, "vram_free": 15715926016}
    ],
}


def parse_multipart(request: httpx.Request) -> dict[str, tuple[str, bytes]]:
    """Form fields of a multipart request: name -> (filename or "", raw value)."""
    boundary = request.headers["content-type"].split("boundary=")[1].encode()
    fields = {}
    for part in request.content.split(b"--" + boundary)[1:-1]:
        head, _, value = part.strip(b"\r\n").partition(b"\r\n\r\n")
        disposition = head.decode().split("\r\n")[0]
        name = re.search(r'name="([^"]*)"', disposition).group(1)
        filename = re.search(r'filename="([^"]*)"', disposition)
        fields[name] = (filename.group(1) if filename else "", value)
    return fields


def fake_png(size: int = 256) -> bytes:
    """RGBA PNG shaped like Qwen's transparent output: residual background alpha 2..6, an opaque square in the middle."""
    rng = np.random.default_rng(0)
    rgba = np.zeros((size, size, 4), np.uint8)
    rgba[..., :3] = (180, 170, 160)
    rgba[..., 3] = rng.integers(2, 7, (size, size))
    q = size // 4
    rgba[q : size - q, q : size - q] = (200, 40, 40, 255)
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG")
    return buf.getvalue()


def fake_flac(seconds: float, bpm: float, silence_s: float = 4.0, sr: int = 22050) -> bytes:
    """Stereo FLAC shaped like an ACE-Step song: clicks on the beat over a tone, ending `silence_s` early."""
    t = np.arange(round(max(seconds - silence_s, 0.5) * sr)) / sr
    y = 0.3 * np.sin(2 * np.pi * 220 * t)
    for i in range(0, len(y) - 200, round(60 / bpm * sr)):
        y[i : i + 200] += 0.5 * np.hanning(200)
    y = np.concatenate([y, np.zeros(round(silence_s * sr))]) + np.random.default_rng(0).normal(
        0, 1e-5, len(t) + round(silence_s * sr)
    )
    buf = io.BytesIO()
    sf.write(buf, np.stack([y, y], axis=1).astype(np.float32), sr, format="FLAC")
    return buf.getvalue()


@functools.lru_cache
def fake_mp4(frames: int = 81) -> bytes:
    """A real small H.264 clip: the app reads its frames with ffmpeg."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "clip.mp4"
        source = ["-f", "lavfi", "-i", "testsrc=size=208x156:rate=16", "-frames:v", str(frames), "-pix_fmt", "yuv420p"]
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *source, str(path)], check=True)
        return path.read_bytes()


class FakeComfy:
    def __init__(
        self,
        fail_with: str | None = None,  # None | "error" | "node_errors" | "hang"
        down: bool = False,
        nodes: set[str] | None = None,
        models: dict[str, set[str]] | None = None,
        image_size: int = 256,
        audio_seconds: float | None = None,  # song length; default: what the graph asked for
        fail_once: str | None = None,  # the next prompt of a sampler ends in this error, the ones after it run
    ):
        self.fail_with = fail_with
        self.fail_once = fail_once
        self.error_message = "CUDA out of memory."
        self.down = down
        self.nodes = set(ALL_NODES if nodes is None else nodes)
        self.models = {k: set(v) for k, v in (ALL_MODELS if models is None else models).items()}
        self.png = fake_png(image_size)
        self.audio_seconds = audio_seconds
        self.audio: dict[str, bytes] = {}  # output file name -> FLAC bytes
        self.prompts: dict[str, dict] = {}  # prompt_id -> graph, in submission order
        self.history: dict[str, dict] = {}
        self.deleted: list[str] = []
        self.interrupts: list[str | None] = []  # prompt_id per POST /interrupt (None = global)
        self.free_calls: list[dict] = []
        self.views: list[dict] = []
        self.uploads: list[dict] = []  # {"name", "subfolder", "data"}
        self.transport = httpx.MockTransport(self.handler)

    @property
    def graphs(self) -> list[dict]:
        return list(self.prompts.values())

    def running_prompt(self) -> str | None:
        return next((p for p in self.prompts if p not in self.history and p not in self.deleted), None)

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        method, path = request.method, request.url.path
        if method == "GET":
            if path == "/system_stats":
                return httpx.Response(200, json=SYSTEM_STATS)
            if path == "/object_info":
                return httpx.Response(200, json={name: {"name": name} for name in sorted(self.nodes)})
            if m := re.fullmatch(r"/models/([^/]+)", path):
                if m.group(1) not in self.models:
                    return httpx.Response(404)
                return httpx.Response(200, json=sorted(self.models[m.group(1)]))
            if m := re.fullmatch(r"/history/([^/]+)", path):
                pid = m.group(1)
                return httpx.Response(200, json={pid: self.history[pid]} if pid in self.history else {})
            if path == "/view":
                self.views.append(dict(request.url.params))
                if (name := request.url.params.get("filename", "")) in self.audio:
                    return httpx.Response(200, content=self.audio[name], headers={"Content-Type": "audio/flac"})
                if name.endswith(".mp4"):
                    return httpx.Response(200, content=fake_mp4(), headers={"Content-Type": "video/mp4"})
                return httpx.Response(200, content=self.png, headers={"Content-Type": "image/png"})
        elif method == "POST":
            if path == "/upload/image":
                fields = parse_multipart(request)
                name, data = fields["image"]
                subfolder = fields.get("subfolder", ("", b""))[1].decode()
                self.uploads.append({"name": name, "subfolder": subfolder, "data": data})
                return httpx.Response(200, json={"name": name, "subfolder": subfolder, "type": "input"})
            body = json.loads(request.content or b"{}")
            if path == "/prompt":
                return self._prompt(body)
            if path == "/free":
                self.free_calls.append(body)
                return httpx.Response(200)
            if path == "/interrupt":
                target = body.get("prompt_id")
                self.interrupts.append(target)
                running = self.running_prompt()
                if running is not None and target in (None, running):
                    self.history[running] = self._entry(running, "interrupted")
                return httpx.Response(200)
            if path == "/queue":
                self.deleted.extend(body.get("delete", []))
                return httpx.Response(200)
        return httpx.Response(404)

    def _prompt(self, body: dict) -> httpx.Response:
        if self.fail_with == "node_errors":
            return httpx.Response(
                400,
                json={
                    "error": {
                        "type": "prompt_outputs_failed_validation",
                        "message": "Prompt outputs failed validation",
                    },
                    "node_errors": {
                        "5": {
                            "errors": [{"type": "value_not_valid", "message": "Value not in list"}],
                            "dependent_outputs": ["9"],
                            "class_type": "TextEncodeQwenImage21",
                        }
                    },
                },
            )
        pid = body.get("prompt_id") or str(uuid.uuid4())
        self.prompts[pid] = body["prompt"]
        sampling = any(node["class_type"] == "KSamplerAdvanced" for node in body["prompt"].values())
        if self.fail_once and sampling:
            self.error_message, self.fail_once = self.fail_once, None
            self.history[pid] = self._entry(pid, "error")
        elif self.fail_with == "error":
            self.history[pid] = self._entry(pid, "error")
        elif self.fail_with != "hang":
            self.history[pid] = self._entry(pid, "success")
        return httpx.Response(200, json={"prompt_id": pid, "number": len(self.prompts), "node_errors": {}})

    def _song_shape(self, graph: dict) -> tuple[float, float]:
        """(seconds, bpm) of the song a music graph asks for."""
        for node in graph.values():
            if node["class_type"] == "TextEncodeAceStepAudio1.5":
                seconds, bpm = node["inputs"]["duration"], node["inputs"]["bpm"]
                break
            if node["class_type"] == "YuE2GenerateMusic":
                seconds, bpm = node["inputs"]["max_duration"], 100
                break
        else:
            seconds, bpm = 30.0, 100
        return (self.audio_seconds or seconds), bpm

    def _entry(self, pid: str, outcome: str) -> dict:
        start = ["execution_start", {"prompt_id": pid, "timestamp": 0}]
        if outcome == "success":
            outputs = {}
            for node_id, node in self.prompts[pid].items():
                if node["class_type"] == "SaveImage":
                    subfolder, _, name = node["inputs"]["filename_prefix"].rpartition("/")
                    image = {
                        "filename": f"{name}_{len(self.prompts):05}_.png",
                        "subfolder": subfolder,
                        "type": "output",
                    }
                    outputs[node_id] = {"images": [image]}
                if node["class_type"] == "SaveVideo":
                    subfolder, _, name = node["inputs"]["filename_prefix"].rpartition("/")
                    video = {
                        "filename": f"{name}_{len(self.prompts):05}_.mp4",
                        "subfolder": subfolder,
                        "type": "output",
                    }
                    outputs[node_id] = {"images": [video], "animated": [True]}
                if node["class_type"] == "SaveAudio":
                    subfolder, _, name = node["inputs"]["filename_prefix"].rpartition("/")
                    filename = f"{name}_{len(self.prompts):05}_.flac"
                    self.audio[filename] = fake_flac(*self._song_shape(self.prompts[pid]))
                    outputs[node_id] = {"audio": [{"filename": filename, "subfolder": subfolder, "type": "output"}]}
            status = {"status_str": "success", "completed": True, "messages": [start, ["execution_success", {}]]}
            return {"outputs": outputs, "status": status}
        if outcome == "interrupted":
            msg = ["execution_interrupted", {"prompt_id": pid, "node_id": "14", "node_type": "SamplerCustomAdvanced"}]
        else:
            msg = [
                "execution_error",
                {
                    "prompt_id": pid,
                    "node_id": "14",
                    "node_type": "SamplerCustomAdvanced",
                    "exception_type": "torch.OutOfMemoryError",
                    "exception_message": self.error_message,
                },
            ]
        return {"outputs": {}, "status": {"status_str": "error", "completed": False, "messages": [start, msg]}}
