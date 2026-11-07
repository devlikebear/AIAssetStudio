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
-> export_asset (the game's row PNG, a folder of frames and a JSON of the tags).

For a picture book made from a work: read the work where it lives (for a Linetta work, with its linetta_* tools) and
never invent. Studio does not reach that system. create_project (its style) -> create_book -> describe the people,
places and props once with set_book_sheets. Draw each person with generate_image(kind="sprite") and link the chosen
asset_id; draw each place with generate_sheet. A place picture must be empty: its camera and objects come back in
every page that uses it. -> set_book_pages: text in the work's own words, nothing the source does not say, and
source_refs naming the scenes it rests on with their content_version -> generate_pages -> ask the user to review in the
gallery; only they approve -> get_book shows their redo notes -> fix the prompt, generate_pages again -> export_book.
Writing image_prompt, in English: say how many people are in the picture. Turn a person so the trait that matters can
be seen. Give minor characters their own look and keep them small, or they take on a reference's face. Name a prop's
shape and make it large enough to read. A small color detail may not hold; say so to the user rather than retrying.

For an audiobook of that book: list_packs shows whether the speech pack is installed. If a pack is missing, ask the
person to agree to its license in the gallery; it installs there or with `aiassetstudio pack install <id>`. You cannot
agree or install from here. set_book_terms for names a narrator misreads -> generate_narration -> ask the user to listen
in the gallery; only they approve -> get_book shows their notes -> change the text or terms, generate_narration(pages)
-> export_book(format="mp3").

For a moving picture book of that book: set_page_motion on each page with its picture approved -> generate_clips ->
look at each clip's last frame, then ask the user to play them in the gallery and pick how each page is shown -> their
approval, picture and narration -> export_book(format="mp4"). Writing motion_prompt, in English: one small movement
(water, wind, a hand), never a story. A negative prompt does nothing here, so keep motion_still on unless someone must
really move. Clips can lose small traits and let people drift late: if a small trait matters to the story on that
page, set clip_method "still", which shows the approved picture slowly zooming. With model "wan", a picture with empty
space beside one or two people gets strangers walking into it from about 1.5 s, and saying not to does not help; LTX
(the default) did not do this. A clip plays once and its last frame holds for the rest of the page, so that frame must be
good; if only the start is good, use "head"."""

mcp = MCPServer("aiassetstudio", instructions=INSTRUCTIONS)
_api: StudioApi | None = None

Slug = Annotated[str, Field(description="Project slug, e.g. 'lastlight' (a-z, 0-9, '-')")]
AssetId = Annotated[str, Field(description="Asset id from get_job or list_assets")]
JobId = Annotated[str, Field(description="Job id from generate_image")]
BookId = Annotated[str, Field(description="Book id from create_book")]
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
    kind: Annotated[
        Literal["sprite", "icon", "bgm", "animation", "page_image", "narration", "clip", "book_export"] | None,
        Field(description="Only this kind"),
    ] = None,
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


@mcp.tool(structured_output=False)
async def create_book(
    project: Slug,
    title: Annotated[str, Field(description="The book's title")],
    source: Annotated[
        dict | None,
        Field(description="Where the work comes from: {'system', 'work_id', 'label'}. Shown, never fetched"),
    ] = None,
    width: Annotated[int | None, Field(description="Picture width, 512-1536, a multiple of 16; default 1184")] = None,
    height: Annotated[int | None, Field(description="Picture height, 512-1536, a multiple of 16; default 880")] = None,
) -> str:
    """Start a picture book in a project, whose style every page uses."""
    return await _call(tools.create_book, project, title, source, width, height)


@mcp.tool()
async def get_book(book_id: BookId) -> list[str | Image]:
    """Show a book: each page's status, chosen picture, source and the person's redo notes, the sheets, a warning if the
    license limits sharing, and previews of pictures waiting for review. Read it before regenerating anything."""
    return await _call(tools.get_book, book_id)


@mcp.tool(structured_output=False)
async def set_book_pages(
    book_id: BookId,
    pages: Annotated[
        list[dict],
        Field(
            description="Pages by number; pages not listed stay. Each: number, text (the page's words), image_prompt "
            "(the scene, in English), people (names of character sheets, most important first; two become references), "
            "props (prop sheet names or plain English), place (a place sheet name or plain English), source_refs "
            "[{node_id, content_version, label}]. Changing what a page shows sends it back to draft; changing only "
            "its text keeps the picture."
        ),
    ],
) -> str:
    """Add or change a book's pages."""
    return await _call(tools.set_book_pages, book_id, pages)


@mcp.tool(structured_output=False)
async def set_book_sheets(
    book_id: BookId,
    sheets: Annotated[
        list[dict],
        Field(
            description="Each: kind (character, place or prop), name, description (in English), asset_id (a sprite "
            "for a character, from generate_image). Omitting asset_id keeps the sheet's picture."
        ),
    ],
) -> str:
    """Add or change the people, places and props that must stay the same across pages."""
    return await _call(tools.set_book_sheets, book_id, sheets)


@mcp.tool(structured_output=False)
async def set_book_terms(
    book_id: BookId,
    terms: Annotated[list[dict], Field(description="Each: term, spoken (how to write it so a narrator says it right)")],
) -> str:
    """Replace the book's list of pronunciations. Narration reads each term as spoken; the PDF keeps the page's text."""
    return await _call(tools.set_book_terms, book_id, terms)


@mcp.tool(structured_output=False)
async def set_book_cover(
    book_id: BookId, page: Annotated[int, Field(ge=1, description="The page whose picture is the cover")]
) -> str:
    """Choose the page whose picture is the cover; by default the first."""
    return await _call(tools.set_book_cover, book_id, page)


@mcp.tool(structured_output=False)
async def generate_sheet(
    sheet_id: Annotated[str, Field(description="A place or prop sheet, from get_book")],
    seed: Annotated[int | None, Field(ge=0, description="Random if omitted")] = None,
) -> str:
    """Queue an opaque picture of a place or prop sheet. A place comes out empty. Characters are drawn with
    generate_image(kind="sprite") instead."""
    return await _call(tools.generate_sheet, sheet_id, seed)


@mcp.tool(structured_output=False)
async def generate_pages(
    book_id: BookId,
    pages: Annotated[list[int] | None, Field(description="Page numbers; omit for every page in draft or redo")] = None,
    seed: Annotated[int | None, Field(ge=0, description="Random per page if omitted")] = None,
) -> str:
    """Queue one full-page picture per page, about 30 s each. A new picture joins the page's candidates; the choice
    already made stays."""
    return await _call(tools.generate_pages, book_id, pages, seed)


@mcp.tool(structured_output=False)
async def set_page(
    page_id: Annotated[str, Field(description="The page's id, from the book")],
    image_asset_id: Annotated[str | None, Field(description="Choose this candidate")] = None,
    status: Annotated[
        Literal["redo", "draft"] | None,
        Field(description="Send a page back. Only the person approves pages, in the gallery"),
    ] = None,
    note: Annotated[str | None, Field(description="Why, for whoever works on it next")] = None,
) -> str:
    """Choose a candidate for a page or send it back."""
    return await _call(tools.set_page, page_id, image_asset_id, status, note)


@mcp.tool(structured_output=False)
async def check_book_sources(
    book_id: BookId,
    versions: Annotated[dict[str, int], Field(description="Each source node id -> its content_version now")],
) -> str:
    """Find pages whose source changed since they were written. Read the current versions from the work's own system
    first: Studio cannot."""
    return await _call(tools.check_book_sources, book_id, versions)


@mcp.tool(structured_output=False)
async def export_book(
    book_id: BookId,
    allow_draft: Annotated[bool, Field(description="Include pages nobody approved; for a proof")] = False,
    format: Annotated[
        Literal["pdf", "mp3", "mp4"],
        Field(description="pdf: the book; mp3: its narration; mp4: pictures or clips with narration and subtitles"),
    ] = "pdf",
) -> str:
    """Queue the book's PDF (real text under each picture, a cover and a colophon naming the models), its narration as
    one MP3, or its video. Needs every page's picture, narration, or narration and way of showing approved unless
    allow_draft. Call get_job for the result, and pass on any license warning to the user."""
    return await _call(tools.export_book, book_id, allow_draft, format)


@mcp.tool(structured_output=False)
async def generate_narration(
    book_id: BookId,
    pages: Annotated[list[int] | None, Field(description="Page numbers; omit for every page in draft or redo")] = None,
    seed: Annotated[int | None, Field(ge=0, description="Random per page if omitted")] = None,
) -> str:
    """Queue a narrator reading each page's text, with the book's terms applied. Needs the speech pack. A new take joins
    the page's takes; the choice already made stays. You cannot hear audio: ask the user to listen in the gallery."""
    return await _call(tools.generate_narration, book_id, pages, seed)


@mcp.tool(structured_output=False)
async def set_page_motion(
    page_id: Annotated[str, Field(description="The page's id, from the book")],
    motion_prompt: Annotated[str | None, Field(description="What moves in the clip, in English")] = None,
    motion_still: Annotated[
        bool | None, Field(description="Tell the people to stay where they are; on by default")
    ] = None,
    clip_method: Annotated[
        Literal["full", "head", "still"] | None,
        Field(description="full: the whole clip; head: its first seconds; still: no clip, the picture zooming slowly"),
    ] = None,
    clip_head_s: Annotated[float | None, Field(ge=0.5, le=5, description="Seconds of the clip that head uses")] = None,
    clip_asset_id: Annotated[str | None, Field(description="Choose this clip of the page")] = None,
) -> str:
    """Set what moves on a page and how the page is shown in the video. Changing the motion makes its clip out of date.
    The person approves it in the gallery."""
    return await _call(
        tools.set_page_motion, page_id, motion_prompt, motion_still, clip_method, clip_head_s, clip_asset_id
    )


@mcp.tool(structured_output=False)
async def generate_clips(
    book_id: BookId,
    pages: Annotated[
        list[int] | None,
        Field(description="Page numbers; omit for every page in draft or redo with an approved picture and a motion"),
    ] = None,
    seed: Annotated[int | None, Field(ge=0, description="Random per page if omitted")] = None,
    model: Annotated[
        Literal["ltx", "wan"], Field(description="ltx: LTX-2.5, 1024x768 at 24 fps; wan: Wan 2.2, 832x624, 5 s only")
    ] = "ltx",
    seconds: Annotated[float, Field(ge=3, le=10, description="Clip length; longer leaves less of the page held")] = 5,
) -> str:
    """Queue a clip from each page's approved picture: with LTX about 1.5 minutes for 5 s. A new clip joins the page's
    clips; the choice already made stays. You cannot play video: look at the last frames, and ask the user to review."""
    return await _call(tools.generate_clips, book_id, pages, seed, model, seconds)


@mcp.tool(structured_output=False)
async def list_packs() -> str:
    """Show the feature packs (the speech pack for audiobooks), whether each is installed, and the gallery link where a
    person agrees to its license. Installing is not done from here."""
    return await _call(tools.list_packs)


def main() -> None:
    log_file = logs_dir(load_settings()) / "mcp.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    # force: MCPServer already put a stderr handler on the root logger when it was created.
    logging.basicConfig(
        filename=log_file, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run(transport="stdio")
