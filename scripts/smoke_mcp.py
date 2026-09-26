"""Smoke test of the MCP server over stdio, the way Claude Code runs it.

Starts `python -m aiassetstudio mcp`, lists the tools and calls studio_status; the server starts the backend if it
is not running. With --generate it also makes one icon through the whole flow (uses the GPU) and exports it.
With --pixel it makes a 32x32, 12-color pixel-art project with that reference image, then 4 sprites and 1 icon,
and checks the exported files (Phase 3 end-to-end check). With --bgm it makes two 90 s, 96 BPM village themes
and exports both (WAV and OGG, loop length checked); --vocal adds a short song with Korean lyrics (YuE2, minutes).
The exported files are printed for scripts/vocal_check.py (Phase 4 end-to-end check).
With --animation it makes a 32x32 pixel-art project with that reference image, one sprite (GPU), and an idle + walk
animation of it with sprite-gen and codex (this sends the sprite, enlarged, and sprite-gen's layout guides and prompts
to OpenAI), then checks the game-format export (animation Phase 1 end-to-end check). Run it on a test port and data
folder: AIAS_PORT=8766 and a temporary AIAS_DATA_DIR.
    uv run python scripts/smoke_mcp.py
    uv run python scripts/smoke_mcp.py --generate
    uv run python scripts/smoke_mcp.py --pixel C:\\path\\to\\reference.png
    uv run python scripts/smoke_mcp.py --bgm --vocal
    uv run python scripts/smoke_mcp.py --animation C:\\path\\to\\reference.png
AIAS_* environment variables (AIAS_PORT, AIAS_DATA_DIR, ...) pass through to the server and the backend it starts.
Exit code 0 when every step works.

The MCP server starts the backend outside this script's processes (aiassetstudio.detach), so it would keep running
after the script ends, as it does for Claude Code. A backend this script caused to start is stopped at the end, and
ComfyUI's models are freed if nothing else is queued there; --keep-backend leaves it running (to check that it
survives the script).
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from PIL import Image

from aiassetstudio.config import REPO_ROOT, load_settings
from aiassetstudio.post.image import reference_ground

PROJECT = "smoke-mcp"
PIXEL_PROJECT = "smoke-pixel"
PIXEL_SPEC = {"pixel_art": True, "logical_width": 32, "logical_height": 32, "max_colors": 12, "icon_size": 16}
BGM_PROJECT = "smoke-bgm"
ANIMATION_PROJECT = "smoke-anim"
ANIMATION_SPEC = {"pixel_art": True, "logical_width": 32, "logical_height": 32, "max_colors": 12}
ANIMATION_TAGS = [
    {"name": "idle", "from": 0, "to": 3, "duration": 0.18},
    {"name": "walk", "from": 4, "to": 9, "duration": 0.1},
]
VILLAGE = {
    "brief": "cozy fantasy village, acoustic guitar, flute, pizzicato strings, light hand percussion, warm and peaceful",
    "bpm": 96,
    "seconds": 90,
    "keyscale": "G major",
    "count": 2,
}
KOREAN_LYRICS = """[Verse]
창가에 스친 빗소리
조용히 너를 부르네

[Chorus]
괜찮아 오늘 밤은
별빛이 우릴 비출 거야"""


class SmokeFailure(Exception):
    pass


def texts(content: list) -> list[str]:
    return [c.text for c in content if c.type == "text"]


async def call(session: ClientSession, tool: str, /, **arguments) -> list:
    result = await session.call_tool(tool, arguments)
    if result.is_error:
        raise SmokeFailure(f"{tool} failed: {' '.join(texts(result.content))}")
    return result.content


async def wait_job(session: ClientSession, queued: list) -> tuple[list[str], list, list[str]]:
    """Wait on get_job until the job ends; returns (asset ids, preview images, the asset lines Claude reads)."""
    job_id = queued[0].text.split()[2]
    print(f"job {job_id} queued")
    while True:
        content = await call(session, "get_job", job_id=job_id, wait_seconds=60)
        print(" ", content[0].text)
        if not any("Still in progress" in t for t in texts(content)):
            break
    images = [c for c in content if c.type == "image"]
    lines = [t for t in texts(content) if t.startswith("asset ")]
    assets = [t.split()[1] for t in lines]
    print(f"previews: {len(images)} ({', '.join(c.mime_type for c in images)}), assets: {assets}")
    if "-> done" not in content[0].text:
        raise SmokeFailure(f"job did not finish: {content[0].text}")
    return assets, images, lines


def check_pixel_file(path: Path, size: tuple[int, int], max_colors: int) -> str:
    img = Image.open(path)
    rgba = np.asarray(img.convert("RGBA"))
    alpha = np.unique(rgba[..., 3]).tolist()
    colors = len(np.unique(rgba[rgba[..., 3] > 0][:, :3], axis=0))
    problems = []
    if img.size != size:
        problems.append(f"size {img.size} != {size}")
    if not set(alpha) <= {0, 255}:
        problems.append(f"alpha values {alpha[:8]}")
    if colors > max_colors:
        problems.append(f"{colors} colors > {max_colors}")
    if problems:
        raise SmokeFailure(f"{path}: {'; '.join(problems)}")
    return f"{path.name}: {img.size[0]}x{img.size[1]}, {colors} colors, alpha 0/255"


async def run_icon(session: ClientSession) -> None:
    if PROJECT not in (await call(session, "list_projects"))[0].text:
        await call(session, "create_project", slug=PROJECT, name="MCP smoke test", style="hand-painted fantasy")
    queued = await call(
        session, "generate_image", project=PROJECT, kind="icon", description="a steel short sword", count=1
    )
    assets, images, _ = await wait_job(session, queued)
    if len(images) != 1:
        raise SmokeFailure("expected one preview")
    await call(session, "set_asset_status", asset_id=assets[0], status="selected")
    dest = str(load_settings().data_dir / "exports" / PROJECT)
    print((await call(session, "export_asset", asset_id=assets[0], dest_dir=dest))[0].text)


async def run_pixel(session: ClientSession, reference: Path) -> None:
    """Phase 3 end to end: a pixel-art project with a reference image, sprites and an icon, exports checked."""
    settings = load_settings()
    fields = {**PIXEL_SPEC, "reference_image": str(reference)}
    if PIXEL_PROJECT in (await call(session, "list_projects"))[0].text:
        text = (await call(session, "update_project", slug=PIXEL_PROJECT, **fields))[0].text
    else:
        text = (await call(session, "create_project", slug=PIXEL_PROJECT, name="Pixel smoke test", **fields))[0].text
    print(text)
    if "pixel art: sprites 32x32, icons 16x16, at most 12 colors" not in text:
        raise SmokeFailure("the project does not show the pixel-art spec")

    queued = await call(
        session, "generate_image", project=PIXEL_PROJECT, kind="sprite", description="a small slime monster", count=4
    )
    sprites, images, lines = await wait_job(session, queued)
    if len(sprites) != 4 or len(images) != 4:
        raise SmokeFailure("expected 4 sprites with previews")
    for line in lines:
        print(" ", line)
    if not all(", pixel art: " in line for line in lines):
        raise SmokeFailure("get_job must say how each pixel-art candidate was fitted")
    queued = await call(
        session, "generate_image", project=PIXEL_PROJECT, kind="icon", description="a red health potion", count=1
    )
    icons, _, _ = await wait_job(session, queued)

    async with httpx.AsyncClient(base_url=f"http://{settings.host}:{settings.port}", timeout=10) as http:
        for asset_id in sprites:
            meta = (await http.get(f"/api/assets/{asset_id}")).raise_for_status().json()["meta"]
            if meta.get("reference", {}).get("mode") != "latent":
                raise SmokeFailure(f"sprite {asset_id} was not made with the reference: {meta.get('reference')}")
            if meta["pixel"].get("fit", {}).get("fit") not in ("native", "stretch"):
                raise SmokeFailure(f"sprite {asset_id} has no pixel fit report: {meta['pixel']}")
            print(f"  {asset_id}: {meta['pixel']}, raw border alpha mean {meta['alpha_raw']['border_mean']}")
        icon_meta = (await http.get(f"/api/assets/{icons[0]}")).raise_for_status().json()["meta"]
        if "reference" in icon_meta:
            raise SmokeFailure("icons must not use the reference image")

    dest = settings.data_dir / "exports" / PIXEL_PROJECT
    for asset_id, size in ((sprites[0], (32, 32)), (icons[0], (16, 16))):
        await call(session, "set_asset_status", asset_id=asset_id, status="selected")
        exported = (await call(session, "export_asset", asset_id=asset_id, dest_dir=str(dest)))[0].text
        print(" ", check_pixel_file(Path(exported.splitlines()[1]), size, PIXEL_SPEC["max_colors"]))


def feet_row(path: Path) -> int:
    ys, _ = np.nonzero(np.asarray(Image.open(path).convert("RGBA"))[..., 3])
    return int(ys.max())


async def run_animation(session: ClientSession, reference: Path) -> None:
    """Animation Phase 1 end to end (cloud): refused while animation_cloud is off, then one animation of a new sprite,
    exported the game's way: <name>.png 320x32, <name>/000-009.png 32x32, <name>.json; alpha 0/255, 12 colors at
    most, feet on the reference's row."""
    settings = load_settings()
    fields = {**ANIMATION_SPEC, "reference_image": str(reference), "animation_cloud": False}
    if ANIMATION_PROJECT in (await call(session, "list_projects"))[0].text:
        text = (await call(session, "update_project", slug=ANIMATION_PROJECT, **fields))[0].text
    else:
        text = (await call(session, "create_project", slug=ANIMATION_PROJECT, name="Animation smoke", **fields))[0].text
    if "animation: off" not in text:
        raise SmokeFailure("a new project must show animations off")
    queued = await call(
        session,
        "generate_image",
        project=ANIMATION_PROJECT,
        kind="sprite",
        description="a creeping shadow creature enemy with two glowing eyes",
        count=1,
    )
    [sprite], _, _ = await wait_job(session, queued)

    refused = await session.call_tool("generate_animation", {"asset_id": sprite})
    if not refused.is_error or "does not allow animations" not in " ".join(texts(refused.content)):
        raise SmokeFailure(f"an animation must be refused while animation_cloud is off: {texts(refused.content)}")
    print("refused while animation_cloud is off:", texts(refused.content)[0][:120])

    print(f"sends to OpenAI through the Codex CLI: sprite {sprite} (enlarged), sprite-gen's layout guides and prompts")
    await call(session, "update_project", slug=ANIMATION_PROJECT, animation_cloud=True)
    queued = await call(session, "generate_animation", asset_id=sprite)
    [animation], images, lines = await wait_job(session, queued)
    print(" ", lines[0].replace("\n", "\n  "))
    if len(images) != 1 or "made with codex (cloud)" not in lines[0]:
        raise SmokeFailure("get_job must show the animation's frame sheet and say it was made with codex")

    await call(session, "set_asset_status", asset_id=animation, status="selected")
    dest = settings.data_dir / "exports" / ANIMATION_PROJECT
    exported = (await call(session, "export_asset", asset_id=animation, dest_dir=str(dest), name="shadow_anim"))[0].text
    row, info_path, folder = (Path(line) for line in exported.splitlines()[1:])
    print(" ", check_pixel_file(row, (320, 32), ANIMATION_SPEC["max_colors"]))
    frames = sorted(folder.glob("*.png"))
    if [f.name for f in frames] != [f"{i:03d}.png" for i in range(10)]:
        raise SmokeFailure(f"expected 000.png-009.png in {folder}, got {[f.name for f in frames]}")
    for frame in frames:
        check_pixel_file(frame, (32, 32), ANIMATION_SPEC["max_colors"])
    feet = {feet_row(frame) for frame in frames}
    with Image.open(reference) as ref:
        expected = 32 - reference_ground(ref, 32) - 1  # the row the project's sprites stand on
    if feet != {expected}:
        raise SmokeFailure(f"frames stand on rows {sorted(feet)}, not the reference's row {expected}")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    if info.get("tags") != ANIMATION_TAGS or info.get("image") != row.name:
        raise SmokeFailure(f"{info_path}: unexpected {info}")
    print(f"  {folder.name}/000-009.png: 32x32, alpha 0/255, feet on row {expected}; {info_path.name}: {info['tags']}")


def song_ids(content: list) -> list[str]:
    return [t.split()[1] for t in texts(content) if t.startswith("asset ")]


async def export_song(session: ClientSession, asset_id: str, dest: Path, name: str) -> list[Path]:
    await call(session, "set_asset_status", asset_id=asset_id, status="selected")
    exported = (await call(session, "export_asset", asset_id=asset_id, dest_dir=str(dest), name=name))[0].text
    return [Path(line) for line in exported.splitlines()[1:]]


async def wait_songs(session: ClientSession, queued: list) -> list:
    job_id = queued[0].text.split()[2]
    print(f"job {job_id} queued")
    while True:
        content = await call(session, "get_job", job_id=job_id, wait_seconds=60)
        print(" ", content[0].text)
        if not any("Still in progress" in t for t in texts(content)):
            break
    if "-> done" not in content[0].text:
        raise SmokeFailure(f"job did not finish: {content[0].text}")
    if any(c.type == "image" for c in content):
        raise SmokeFailure("songs must come back as text only")
    for line in texts(content)[1:]:
        print("   ", line.replace("\n", "\n    "))
    return content


async def run_bgm(session: ClientSession, vocal: bool) -> None:
    """Phase 4 end to end: two looping village themes, one exported as WAV + OGG; optionally a YuE2 vocal song."""
    settings = load_settings()
    dest = settings.data_dir / "exports" / BGM_PROJECT
    if BGM_PROJECT not in (await call(session, "list_projects"))[0].text:
        await call(session, "create_project", slug=BGM_PROJECT, name="BGM smoke test", export_dir=str(dest))
    queued = await call(session, "generate_bgm", project=BGM_PROJECT, **VILLAGE)
    if "You cannot hear audio" not in queued[0].text:
        raise SmokeFailure("generate_bgm must remind Claude that it cannot hear audio")
    content = await wait_songs(session, queued)
    songs = song_ids(content)
    if len(songs) != 2 or not all("seamless loop of" in t for t in texts(content) if t.startswith("asset ")):
        raise SmokeFailure("expected two looping songs")
    exported = []
    async with httpx.AsyncClient(base_url=f"http://{settings.host}:{settings.port}", timeout=10) as http:
        for i, song in enumerate(songs):
            loop = (await http.get(f"/api/assets/{song}")).raise_for_status().json()["meta"]["loop"]
            paths = await export_song(session, song, dest, f"village_{i + 1}")
            suffixes = sorted(p.suffix for p in paths)
            if suffixes != [".ogg", ".wav"] or len({p.stem for p in paths}) != 1:
                raise SmokeFailure(f"expected one WAV and one OGG with the same name, got {paths}")
            wav = next(p for p in paths if p.suffix == ".wav")
            info = sf.info(str(wav))
            bar = 60 / loop["bpm"] * 4 * info.samplerate  # the song's own tempo when it was detected
            if abs(info.frames - loop["bars"] * bar) > 1:
                raise SmokeFailure(f"{wav}: {info.frames} frames is not {loop['bars']} bars of {loop['bpm']} BPM")
            ogg = sf.info(str(next(p for p in paths if p.suffix == ".ogg")))
            print(
                f"  {wav.name}: {info.duration:.2f} s = {loop['bars']} bars at {loop['bpm']} BPM; OGG {ogg.duration:.2f} s"
            )
            exported.append(wav)

    if vocal:
        queued = await call(
            session,
            "generate_bgm",
            project=BGM_PROJECT,
            brief="Korean emotional ballad, warm female vocal, acoustic piano and soft strings",
            bpm=76,
            seconds=60,
            loop=False,
            vocal=True,
            lyrics=KOREAN_LYRICS,
            count=1,
        )
        content = await wait_songs(session, queued)
        [song] = song_ids(content)
        paths = await export_song(session, song, dest, "ballad")
        if sorted(p.suffix for p in paths) != [".ogg", ".wav"]:
            raise SmokeFailure(f"expected the vocal song as WAV and OGG, got {paths}")
        print(f"  {paths[0].stem}: {sf.info(str(paths[0])).duration:.1f} s")
        exported.append(next(p for p in paths if p.suffix == ".wav"))
    print("for scripts/vocal_check.py:", " ".join(str(p) for p in exported))


def backend_up(settings) -> bool:
    try:
        return httpx.get(f"http://{settings.host}:{settings.port}/api/health", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


def stop_backend(settings) -> None:
    """Stop the backend serving settings.port (found by the --port on its command line), then free ComfyUI's models
    if its queue is empty: a stopped backend cannot run its idle /free."""
    if sys.platform != "win32":
        print(f"stop the backend on port {settings.port} yourself")
        return
    script = (
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'aiassetstudio serve' -and "
        "$_.CommandLine -match ('--port ' + $env:SMOKE_PORT + '( |$)') } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }"
    )
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env=os.environ | {"SMOKE_PORT": str(settings.port)},
        capture_output=True,
        text=True,
        check=False,
    )
    print(f"stopped the backend on port {settings.port} (pids {' '.join(done.stdout.split()) or 'none'})")
    try:
        queue = httpx.get(f"{settings.comfy_url}/queue", timeout=3).json()
        if not queue["queue_running"] and not queue["queue_pending"]:
            httpx.post(f"{settings.comfy_url}/free", json={"unload_models": True, "free_memory": True}, timeout=10)
    except httpx.HTTPError:
        pass


async def run(
    generate: bool,
    pixel_reference: Path | None,
    bgm: bool = False,
    vocal: bool = False,
    keep_backend: bool = False,
    animation_reference: Path | None = None,
) -> int:
    settings = load_settings()
    started_here = not backend_up(settings)
    try:
        return await session_steps(generate, pixel_reference, bgm, vocal, animation_reference)
    finally:
        if started_here and not keep_backend and backend_up(settings):
            stop_backend(settings)


async def session_steps(
    generate: bool, pixel_reference: Path | None, bgm: bool, vocal: bool, animation_reference: Path | None = None
) -> int:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "aiassetstudio", "mcp"], env=dict(os.environ), cwd=REPO_ROOT
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = (await session.list_tools()).tools
        print("tools:", ", ".join(t.name for t in tools))
        try:
            print((await call(session, "studio_status"))[0].text)
            if generate:
                await run_icon(session)
            if pixel_reference is not None:
                await run_pixel(session, pixel_reference)
            if bgm or vocal:
                await run_bgm(session, vocal)
            if animation_reference is not None:
                await run_animation(session, animation_reference)
        except SmokeFailure as e:
            print(f"FAIL: {e}")
            return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--generate", action="store_true", help="also generate and export one icon (uses the GPU)")
    parser.add_argument(
        "--pixel", type=Path, metavar="REFERENCE", help="pixel-art project with this reference image (uses the GPU)"
    )
    parser.add_argument("--bgm", action="store_true", help="two looping instrumentals, exported (uses the GPU)")
    parser.add_argument("--vocal", action="store_true", help="with --bgm: also a YuE2 song with Korean lyrics")
    parser.add_argument(
        "--animation",
        type=Path,
        metavar="REFERENCE",
        help="a sprite of a pixel-art project with this reference, then its animation (GPU, and codex in the cloud)",
    )
    parser.add_argument(
        "--keep-backend", action="store_true", help="leave a backend this script caused to start running"
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.generate, args.pixel, args.bgm, args.vocal, args.keep_backend, args.animation)))


if __name__ == "__main__":
    main()
