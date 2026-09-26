"""MCP server (stdio) for Claude Code. Every tool goes through the backend's HTTP API.

stdout is the MCP channel: nothing here may print. Logs go to data/logs/mcp.log.
"""

import logging
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.types import Image
from pydantic import Field

from ..config import load_settings
from ..store.files import logs_dir
from . import tools
from .studio_api import BackendError, StudioApi

INSTRUCTIONS = """\
AIAssetStudio makes game art on this PC: sprites and item icons with transparent backgrounds, background music
(looping instrumentals, or songs with vocals), and animations of sprites. Images and music use local models;
animations (generate_animation) are the one exception: they use the Codex CLI in the cloud, only where the project
allows it (animation_cloud). A project holds one game's art style and export folder, and optionally a pixel-art spec
(canvas size, color limit, palette) that every result is cleaned up to, and a reference image whose style new sprites
follow. Typical flow: studio_status -> list_projects or create_project -> generate_image (returns a job id at once)
-> get_job(job_id, wait_seconds=60) until done; it returns small previews you can look at -> set_asset_status to
pick -> export_asset to copy the processed PNG into the game. The user can also review candidates in the web gallery
(link in get_job). One job runs at a time; other requests wait in a queue. Write descriptions in English.
For music: generate_bgm -> get_job. You cannot hear audio, so the user listens in the gallery and picks.
For animation (pixel-art projects): generate_animation(asset_id of a sprite) -> get_job (a sheet of the 10 frames)
-> export_asset (the game's row PNG, a folder of frames and a JSON of the tags)."""

mcp = MCPServer("aiassetstudio", instructions=INSTRUCTIONS)
_api: StudioApi | None = None

Slug = Annotated[str, Field(description="Project slug, e.g. 'lastlight' (a-z, 0-9, '-')")]
AssetId = Annotated[str, Field(description="Asset id from get_job or list_assets")]
JobId = Annotated[str, Field(description="Job id from generate_image")]
REFERENCE_NOTE = (
    "Absolute path of a PNG or JPEG (up to 4096 px) whose art style new sprites follow; icons ignore it. "
    "The reference image must be an absolute path; it is copied into the studio and the original is only read."
)
ANIMATION_CLOUD_NOTE = (
    "Allow animation jobs to send this project's sprites to OpenAI (Codex CLI, ChatGPT subscription). Off by default."
)


async def _call(fn, *args, **kwargs):
    global _api
    if _api is None:
        _api = StudioApi.from_settings(load_settings())
    try:
        await _api.ensure_backend()
        return await fn(_api, *args, **kwargs)
    except BackendError as e:
        raise ToolError(str(e)) from e


@mcp.tool(structured_output=False)
async def studio_status() -> str:
    """Show whether the backend and ComfyUI are up, whether each model family is ready (missing nodes or model
    files are named), free VRAM/RAM, the running job and queue length, and the gallery URL."""
    return await _call(tools.studio_status)


@mcp.tool(structured_output=False)
async def list_projects() -> str:
    """List projects with their art style, export folder, pixel-art spec and reference image."""
    return await _call(tools.list_projects)


@mcp.tool(structured_output=False)
async def get_project(slug: Slug) -> str:
    """Show one project's art style, export folder, pixel-art spec and reference image."""
    return await _call(tools.get_project, slug)


@mcp.tool(structured_output=False)
async def create_project(
    slug: Slug,
    name: Annotated[str, Field(description="Display name, e.g. 'LAST LIGHT'")],
    style: Annotated[str, Field(description="Art style phrase added to every prompt, in English")] = "",
    export_dir: Annotated[
        str | None, Field(description="Absolute folder that export_asset copies into by default")
    ] = None,
    pixel_art: Annotated[
        bool,
        Field(description="Clean every result up into pixel art; needs logical_width, logical_height, max_colors"),
    ] = False,
    logical_width: Annotated[int | None, Field(description="Pixel art: sprite canvas width in pixels, 8-256")] = None,
    logical_height: Annotated[int | None, Field(description="Pixel art: sprite canvas height in pixels, 8-256")] = None,
    icon_size: Annotated[
        int | None,
        Field(description="Icon side in pixels, 8-256; any project. Pixel art defaults it to logical_width"),
    ] = None,
    max_colors: Annotated[int | None, Field(description="Pixel art: most colors per image, 2-64")] = None,
    palette: Annotated[
        list[str] | None, Field(description="Pixel art: fixed colors as '#rrggbb' (2-64); results use only these")
    ] = None,
    reference_image: Annotated[str | None, Field(description=REFERENCE_NOTE)] = None,
    animation_cloud: Annotated[bool, Field(description=ANIMATION_CLOUD_NOTE)] = False,
) -> str:
    """Create a project: one game's art style and export folder, optionally a pixel-art spec and a reference image."""
    return await _call(
        tools.create_project,
        slug,
        name,
        style,
        export_dir,
        pixel_art=pixel_art,
        logical_width=logical_width,
        logical_height=logical_height,
        icon_size=icon_size,
        max_colors=max_colors,
        palette=palette,
        reference_image=reference_image,
        animation_cloud=animation_cloud,
    )


@mcp.tool(structured_output=False)
async def update_project(
    slug: Slug,
    name: Annotated[str | None, Field(description="New display name")] = None,
    style: Annotated[str | None, Field(description="New art style phrase")] = None,
    export_dir: Annotated[str | None, Field(description="New absolute export folder; empty string clears it")] = None,
    pixel_art: Annotated[
        bool | None,
        Field(description="Turn pixel-art cleanup on or off; on needs logical_width, logical_height, max_colors"),
    ] = None,
    logical_width: Annotated[int | None, Field(description="Sprite canvas width, 8-256; 0 clears it")] = None,
    logical_height: Annotated[int | None, Field(description="Sprite canvas height, 8-256; 0 clears it")] = None,
    icon_size: Annotated[int | None, Field(description="Icon side, 8-256, any project; 0 clears it")] = None,
    max_colors: Annotated[int | None, Field(description="Most colors per image, 2-64; 0 clears it")] = None,
    palette: Annotated[
        list[str] | None, Field(description="Fixed colors as '#rrggbb' (2-64); an empty list clears it")
    ] = None,
    reference_image: Annotated[
        str | None, Field(description=REFERENCE_NOTE + " An empty string removes the reference.")
    ] = None,
    animation_cloud: Annotated[bool | None, Field(description=ANIMATION_CLOUD_NOTE)] = None,
) -> str:
    """Change a project's name, art style, export folder, pixel-art spec, reference image or whether animations may
    use the cloud. Omitted fields stay as they are. A job that already started keeps the settings it started with."""
    return await _call(
        tools.update_project,
        slug,
        name=name,
        style=style,
        export_dir=export_dir,
        pixel_art=pixel_art,
        logical_width=logical_width,
        logical_height=logical_height,
        icon_size=icon_size,
        max_colors=max_colors,
        palette=palette,
        reference_image=reference_image,
        animation_cloud=animation_cloud,
    )


@mcp.tool(structured_output=False)
async def generate_image(
    project: Slug,
    kind: Annotated[Literal["sprite", "icon"], Field(description="sprite: a character or object; icon: an item icon")],
    description: Annotated[str, Field(description="What to draw, in English, e.g. 'a skeleton warrior with a shield'")],
    count: Annotated[int, Field(ge=1, le=8, description="Number of candidates")] = 4,
    seed: Annotated[int | None, Field(ge=0, description="Seed of the first candidate; random if omitted")] = None,
) -> str:
    """Queue transparent-background candidates in the project's art style. Returns a job id immediately; then call
    get_job to wait for the results."""
    return await _call(tools.generate_image, project, kind, description, count, seed)


@mcp.tool(structured_output=False)
async def generate_bgm(
    project: Slug,
    brief: Annotated[
        str,
        Field(
            description="Mood, genre and instruments in English, e.g. 'cozy fantasy village, acoustic guitar, flute'"
        ),
    ],
    bpm: Annotated[int, Field(ge=40, le=200, description="Tempo; loops are cut on whole 4/4 bars of this tempo")],
    seconds: Annotated[float, Field(ge=30, le=240, description="Requested length in seconds")] = 90,
    loop: Annotated[bool, Field(description="Cut a seamless loop of whole bars (WAV and OGG)")] = True,
    vocal: Annotated[bool, Field(description="A song with vocals (YuE2, several minutes each); needs lyrics")] = False,
    lyrics: Annotated[
        str | None, Field(description="For vocal=true: lyrics with section tags like [Verse] and [Chorus]")
    ] = None,
    keyscale: Annotated[
        str | None, Field(description="Instrumentals: key such as 'A minor' or 'G major' (default A minor)")
    ] = None,
    count: Annotated[int, Field(ge=1, le=4, description="Number of candidate songs")] = 2,
    seed: Annotated[int | None, Field(ge=0, description="Seed of the first song; random if omitted")] = None,
) -> str:
    """Queue background music candidates: instrumentals with ACE-Step, or songs with vocals with YuE2. Returns a job
    id immediately; call get_job to wait. You cannot hear audio. After generating BGM, ask the user to listen in the
    gallery and pick one."""
    return await _call(tools.generate_bgm, project, brief, bpm, seconds, loop, vocal, lyrics, keyscale, count, seed)


@mcp.tool(structured_output=False)
async def generate_animation(
    asset_id: Annotated[str, Field(description="A sprite asset of a pixel-art project, from get_job or list_assets")],
    count: Annotated[int, Field(ge=1, le=2, description="Number of candidates")] = 1,
) -> str:
    """Queue an idle (4 frames) + walk (6 frames) animation of a sprite, in the project's pixel-art size. Sends the
    sprite (enlarged), a layout guide and a prompt to OpenAI through the Codex CLI (ChatGPT subscription); only
    projects with animation_cloud on. Takes 1-3 minutes per candidate."""
    return await _call(tools.generate_animation, asset_id, count)


@mcp.tool()
async def get_job(
    job_id: JobId,
    wait_seconds: Annotated[int, Field(ge=0, le=60, description="Wait up to this long for the job to finish")] = 30,
) -> list[str | Image]:
    """Show a job's status. Once candidates exist, returns a small preview image of each (up to 8) with its asset id,
    and a gallery link. Songs come back as text: length, tempo, loop bars and file links. Animations come back as a
    sheet of their 10 frames with their size against the base sprite."""
    return await _call(tools.get_job, job_id, wait_seconds)


@mcp.tool(structured_output=False)
async def list_assets(
    project: Slug,
    kind: Annotated[Literal["sprite", "icon", "bgm", "animation"] | None, Field(description="Only this kind")] = None,
    status: Annotated[
        Literal["candidate", "selected", "rejected"] | None, Field(description="Only this status")
    ] = None,
) -> str:
    """List a project's assets (id, kind, seed, status, job, description)."""
    return await _call(tools.list_assets, project, kind, status)


@mcp.tool(structured_output=False)
async def set_asset_status(
    asset_id: AssetId,
    status: Annotated[Literal["candidate", "selected", "rejected"], Field(description="New status")],
) -> str:
    """Mark a candidate as selected or rejected (or back to candidate). The gallery shows the same state."""
    return await _call(tools.set_asset_status, asset_id, status)


@mcp.tool(structured_output=False)
async def export_asset(
    asset_id: AssetId,
    dest_dir: Annotated[
        str | None, Field(description="Absolute folder to copy into; defaults to the project's export_dir")
    ] = None,
    name: Annotated[
        str | None, Field(description="File name without extension (a-z, 0-9, '_', '-'); default is generated")
    ] = None,
) -> str:
    """Copy the asset's processed file into a game folder: a song's WAV and OGG; an animation's <name>.png (the 10
    frames in one row), <name>/000.png-009.png and <name>.json (frame size, idle and walk tags). Never overwrites:
    adds _2, _3, ... to the name."""
    return await _call(tools.export_asset, asset_id, dest_dir, name)


@mcp.tool(structured_output=False)
async def cancel_job(job_id: JobId) -> str:
    """Cancel a queued or running job. Candidates finished before the cancel are kept."""
    return await _call(tools.cancel_job, job_id)


def main() -> None:
    log_file = logs_dir(load_settings()) / "mcp.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    # force: MCPServer already put a stderr handler on the root logger when it was created.
    logging.basicConfig(
        filename=log_file, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run(transport="stdio")
