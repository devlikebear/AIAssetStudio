"""Job runners: turn one queued job into stored assets."""

import asyncio
import io
import json
import random
import shutil
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from PIL import Image

from ..book_prompts import page_prompt, sheet_prompt
from ..comfy.client import ComfyClient, ComfyError, output_files
from ..comfy.graphs import (
    ACE_MODELS,
    ACE_OUTPUT_NODE,
    ACE_SAMPLER,
    ACE_STEPS,
    QWEN_BOOK_MODELS,
    QWEN_BOOK_STEPS,
    QWEN_MODELS,
    QWEN_OUTPUT_NODE,
    QWEN_SAMPLER,
    QWEN_TURBO_STEPS,
    YUE2_MODELS,
    YUE2_OUTPUT_NODE,
    YUE2_SAMPLER,
    YUE2_STEPS,
    Reference,
    RefMode,
    ace_music,
    qwen_book_page,
    qwen_t2i_turbo,
    qwen_text_encode,
    yue2_song,
)
from ..config import Settings
from ..post.animation import (
    FRAMES,
    NATIVE_CELL_FACTOR,
    animated_gif,
    contact_sheet,
    fit_frames,
    game_json,
    game_row,
    game_tags,
    load_frames,
    request_states,
)
from ..post.audio import (
    AudioEncodeError,
    detect_tempo,
    encode_ogg,
    load_audio,
    make_loop,
    normalize_peak,
    trim_trailing_silence,
    write_wav,
)
from ..post.book import BookPage, render_pdf
from ..post.image import (
    PIXEL_MARGIN,
    PixelSpec,
    alpha_stats,
    colors_used,
    hex_to_rgb,
    make_preview,
    postprocess_settings,
    process_image,
    processed_border_band,
    reference_ground,
    upscale_nearest,
)
from ..prompts import build_image_prompt
from ..provenance import WARN_CLASSES, license_names, license_records, worst_class
from ..spritegen.client import SpriteGen
from ..store.db import Database, new_id
from ..store.files import IMAGE_FILES, asset_dir, from_rel, to_rel
from ..store.models import Book, Job, Page, Project, Sheet

IMAGE_SIZE = 1024
# User decision 2026-09-25 (docs/plans/notes/ref-rgba-validation.md): a project's reference image goes in with its
# VAE latents ("latent"; the vision encoder alone copied the reference's subject), and only sprites use it.
REFERENCE_MODE: RefMode = "latent"
REFERENCE_KINDS = ("sprite",)

# ACE-Step instrumentals (docs/en/Tutorial.md of ACE-Step 1.5): no vocals in the tags, language "unknown". A loop gets
# section tags without an intro or outro: with them the 2026-09-24 battle theme was at full level from the first bar;
# with the documented "[Instrumental]" it opened with 8 quiet bars (about -40 dB).
BGM_TAGS = "{brief}, instrumental, no vocals, video game background music"
LOOP_SECTIONS = "[Main Theme]\n\n[Variation]\n\n[Main Theme - full]"
INSTRUMENTAL_LYRICS = "[Instrumental]"
DEFAULT_KEYSCALE = "A minor"

# Animations (sprite-gen + codex, a cloud job). The base sprite goes to sprite-gen enlarged (nearest) to about this
# side, as in the 2026-09-25 trial; both rows are generated at once.
ANIMATION_BASE_SIDE = 1024
ANIMATION_ROWS_AT_ONCE = 2
CLOUD_SENT = ["the base sprite, enlarged", "sprite-gen's layout guides", "sprite-gen's prompts"]


class JobCancelled(Exception):
    """Raised by a runner that sees the job was cancelled between steps."""


@dataclass
class RunContext:
    db: Database
    comfy: ComfyClient
    settings: Settings
    cancel_requested: Callable[[], bool]
    # ComfyUI prompt ids submitted for this job, newest last. The queue interrupts the newest on cancel/timeout.
    prompt_ids: list[str] = field(default_factory=list)
    # Set by the queue when it freed ComfyUI's memory before this job (another model family was loaded).
    freed_before: bool = False


def effective_icon_size(project: Project) -> int | None:
    """Side of the square icons are shrunk to: icon_size, which a pixel-art project defaults to logical_width.
    Projects that are not pixel art use it too (user decision (c), 2026-09-25); None keeps the icon's own size."""
    return project.icon_size or (project.logical_width if project.pixel_art else None)


def pixel_spec(project: Project, kind: str) -> PixelSpec | None:
    """The pixel-art target of this kind in the project, or None if the project is not pixel art."""
    if not project.pixel_art:
        return None
    palette = tuple(hex_to_rgb(c) for c in project.palette) if project.palette else None
    if kind == "icon":
        side = effective_icon_size(project)
        return PixelSpec(side, side, project.max_colors, palette)
    return PixelSpec(project.logical_width, project.logical_height, project.max_colors, palette)


def _postprocess_image(data: bytes, kind: str, directory: Path, pixel: PixelSpec | None, icon_size: int | None) -> dict:
    raw = Image.open(io.BytesIO(data))
    raw.load()
    (directory / "raw.png").write_bytes(data)  # ComfyUI's file as-is, including its embedded workflow
    fit: dict = {}
    processed = process_image(raw, kind, pixel=pixel, icon_size=icon_size, report=fit)
    processed.save(directory / "processed.png")
    (upscale_nearest(processed) if pixel else make_preview(processed)).save(directory / "preview.png")
    stats = {
        "alpha_raw": alpha_stats(raw),
        "alpha_processed": alpha_stats(processed, band=processed_border_band(pixel, icon_size)),
        "size_raw": list(raw.size),
        "size_processed": list(processed.size),
    }
    if pixel is not None:
        stats["pixel"] = {
            "width": pixel.width,
            "height": pixel.height,
            "max_colors": pixel.max_colors,
            "colors_used": colors_used(processed),
            "palette": postprocess_settings(kind, pixel)["pixelate"]["palette"],
            "fit": fit,  # the model's own grid at a whole factor ("native"), or stretched to the canvas and why
        }
    return stats


async def _upload_reference(ctx: RunContext, project: Project) -> tuple[Reference, dict]:
    """Upload the project's reference copy to ComfyUI's input folder, once per job. One name per project is enough:
    ComfyUI's LoadImage notices a changed file by its content."""
    path = from_rel(ctx.settings, project.reference_image)
    if not path.is_file():
        raise FileNotFoundError(f"the project's reference image is missing: {path}; set it again with update_project")
    name = await ctx.comfy.upload_image(path, f"ref_{project.slug}.png")
    return Reference(name, REFERENCE_MODE), {"mode": REFERENCE_MODE, "file": project.reference_image}


async def run_image_job(ctx: RunContext, job: Job) -> None:
    params = dict(job.params)
    kind = params["kind"]
    count = int(params.get("count", 4))
    if params.get("seed") is None:
        params["seed"] = random.randrange(2**31)
        ctx.db.update_job(job.id, params=params)  # keep the chosen seed so the job can be reproduced
    base_seed = int(params["seed"])
    project = ctx.db.get_project(job.project)
    pixel = pixel_spec(project, kind)
    icon_size = effective_icon_size(project) if kind == "icon" and pixel is None else None
    ref, ref_meta, upload_seconds = None, None, None
    if project.reference_image and kind in REFERENCE_KINDS:
        ctx.db.update_job(job.id, stage="uploading reference")
        t0 = time.monotonic()
        ref, ref_meta = await _upload_reference(ctx, project)
        upload_seconds = round(time.monotonic() - t0, 2)
        if pixel is not None:  # sprites stand on the row the reference's subject stands on
            with Image.open(from_rel(ctx.settings, project.reference_image)) as reference:
                pixel = replace(pixel, ground=reference_ground(reference, pixel.height))
    # One prompt text for every candidate, so the 8.7 GB text encoder runs once per job.
    prompt = build_image_prompt(project, kind, params["description"], reference=ref is not None)

    # Encode in a ComfyUI prompt of its own, then unload the models while keeping cached node outputs: the
    # candidates reuse the cached conditioning and the VAE decode never shares a prompt with the text encoder.
    # When it did, the decode stalled for 40 s to over 6 min in 3 of 5 runs (VRAM spill; spikes/vae_decode_test.py,
    # spikes/encode_first_test.py, 2026-09-24). The unload costs about 4 s to reload the image model.
    ctx.db.update_job(job.id, stage="encoding prompt")
    t0 = time.monotonic()
    encode_id = str(uuid.uuid4())
    ctx.prompt_ids.append(encode_id)
    await ctx.comfy.submit(qwen_text_encode(prompt, ref), prompt_id=encode_id)
    await ctx.comfy.free(unload_models=True, free_memory=False)  # applied by ComfyUI right after the encode prompt
    await ctx.comfy.wait(encode_id, timeout=ctx.settings.image_timeout)
    encode_seconds = round(time.monotonic() - t0, 2)
    timings = []

    for i in range(count):
        if ctx.cancel_requested():
            raise JobCancelled()
        seed = base_seed + i
        asset_id = new_id()
        ctx.db.update_job(job.id, stage=f"generating {i + 1}/{count}")
        t0 = time.monotonic()
        prompt_id = str(uuid.uuid4())
        ctx.prompt_ids.append(prompt_id)  # known before submitting, so a cancel mid-request can still target it
        # The same `ref` as the encode prompt: identical nodes are what lets ComfyUI reuse the cached conditioning.
        graph = qwen_t2i_turbo(
            prompt, seed, prefix=f"{project.slug}_{asset_id}", width=IMAGE_SIZE, height=IMAGE_SIZE, ref=ref
        )
        await ctx.comfy.submit(graph, prompt_id=prompt_id)
        entry = await ctx.comfy.wait(prompt_id, timeout=ctx.settings.image_timeout)
        t1 = time.monotonic()
        images = output_files(entry, QWEN_OUTPUT_NODE)
        if not images:
            raise ComfyError(f"ComfyUI returned no image for prompt {prompt_id}")
        output = images[0]
        data = await ctx.comfy.fetch_output(output["filename"], output["subfolder"], output.get("type", "output"))
        t2 = time.monotonic()

        ctx.db.update_job(job.id, stage=f"postprocess {i + 1}/{count}")
        directory = asset_dir(ctx.settings, project.slug, asset_id)
        stats = await asyncio.to_thread(_postprocess_image, data, kind, directory, pixel, icon_size)
        step = {
            "generate": round(t1 - t0, 2),
            "fetch": round(t2 - t1, 2),
            "postprocess": round(time.monotonic() - t2, 2),
        }
        timings.append(step)
        meta = {
            "description": params["description"],
            "prompt": prompt,
            "seed": seed,
            "workflow": "qwen_ref_turbo" if ref else "qwen_t2i_turbo",
            "models": QWEN_MODELS,
            "licenses": license_records(QWEN_MODELS),
            "steps": QWEN_TURBO_STEPS,
            "sampler": QWEN_SAMPLER,
            "width": IMAGE_SIZE,
            "height": IMAGE_SIZE,
            "comfy_prompt_id": prompt_id,
            "comfy_output": {"filename": output["filename"], "subfolder": output["subfolder"]},
            "postprocess": postprocess_settings(kind, pixel, icon_size),
            **stats,
            "timings": step,
        }
        if ref_meta:
            meta["reference"] = ref_meta
        files = {name: to_rel(ctx.settings, directory / f"{name}.png") for name in IMAGE_FILES}
        ctx.db.create_asset(job.id, job.project_id, kind, files=files, meta=meta, seed=seed, asset_id=asset_id)
        job_timings = {"encode": encode_seconds, "candidates": timings}
        if upload_seconds is not None:
            job_timings["upload_reference"] = upload_seconds
        ctx.db.update_job(job.id, timings=job_timings)


def _postprocess_bgm(data: bytes, directory: Path, bpm: int, loop: bool, ffmpeg: str) -> tuple[dict, dict]:
    """raw.flac as ComfyUI saved it, then loop.wav/.ogg (or full.wav/.ogg when there is no loop).
    Returns (meta stats, file role -> file name)."""
    (directory / "raw.flac").write_bytes(data)
    y, sr = load_audio(directory / "raw.flac")
    trimmed = trim_trailing_silence(y, sr)
    stats = {"sample_rate": sr, "raw_s": round(len(y) / sr, 3), "trimmed_s": round(len(trimmed) / sr, 3)}
    audio, stem = trimmed, "full"
    if loop:
        # Cut whole bars of the tempo the song actually has; ACE-Step sometimes drifts from the request.
        detected = detect_tempo(trimmed, sr, bpm)
        stats["tempo"] = {"requested": bpm, "detected": detected}  # unrounded: the loop length is bars of exactly this
        loop_bpm = detected or bpm
        try:
            result = make_loop(trimmed, sr, loop_bpm)
        except ValueError as e:  # too few whole bars: keep the whole song instead
            stats["loop_error"] = str(e)
        else:
            audio, stem = result.audio, "loop"
            stats["loop"] = {
                "bpm": loop_bpm,
                "start_s": round(result.start_s, 3),
                "end_s": round(result.end_s, 3),
                "bars": result.bars,
                "seam_ratio": round(result.seam_ratio, 4),
            }
    write_wav(directory / f"{stem}.wav", normalize_peak(audio), sr)
    stats["length_s"] = round(len(audio) / sr, 3)
    files = {"raw": "raw.flac", f"{stem}_wav": f"{stem}.wav"}
    try:
        encode_ogg(directory / f"{stem}.wav", directory / f"{stem}.ogg", ffmpeg)
        files[f"{stem}_ogg"] = f"{stem}.ogg"
    except AudioEncodeError as e:  # keep the WAV; the song took half a minute or more of GPU time
        stats["ogg_error"] = str(e)
    return stats, files


async def run_bgm_job(ctx: RunContext, job: Job) -> None:
    """Instrumentals with ACE-Step (family "ace") or songs with vocals with YuE2 (family "yue2"), one per seed."""
    params = dict(job.params)
    count = int(params.get("count", 2))
    if params.get("seed") is None:
        params["seed"] = random.randrange(2**31)
        ctx.db.update_job(job.id, params=params)
    base_seed = int(params["seed"])
    project = ctx.db.get_project(job.project)
    brief = params["brief"].strip().rstrip(".")
    bpm = int(params["bpm"])
    seconds = float(params.get("seconds", 90))
    loop = bool(params.get("loop", True))
    vocal = bool(params.get("vocal", False))
    if vocal:
        lyrics = (params.get("lyrics") or "").strip()
        if not lyrics:
            raise ValueError("a song with vocals needs lyrics")
        # YuE2 has no tempo input; the reference script put the tempo in the style text ("..., 76 BPM").
        style = f"{brief}, {bpm} BPM"
        text = {"style": style, "lyrics": lyrics}
        output_node, workflow = YUE2_OUTPUT_NODE, "yue2_song"
        model = {"models": YUE2_MODELS, "steps": YUE2_STEPS, "sampler": YUE2_SAMPLER}

        def graph_for(seed: int, prefix: str) -> dict:
            return yue2_song(style, lyrics, seed, seconds, prefix)
    else:
        tags = BGM_TAGS.format(brief=brief)
        lyrics = LOOP_SECTIONS if loop else INSTRUMENTAL_LYRICS
        keyscale = params.get("keyscale") or DEFAULT_KEYSCALE
        text = {"tags": tags, "lyrics": lyrics, "keyscale": keyscale}
        output_node, workflow = ACE_OUTPUT_NODE, "ace_music"
        model = {"models": ACE_MODELS, "steps": ACE_STEPS, "sampler": ACE_SAMPLER}

        def graph_for(seed: int, prefix: str) -> dict:
            return ace_music(tags, lyrics, bpm, seconds, keyscale, seed, prefix)

    timings = []
    for i in range(count):
        if ctx.cancel_requested():
            raise JobCancelled()
        seed = base_seed + i
        asset_id = new_id()
        ctx.db.update_job(job.id, stage=f"generating {i + 1}/{count}")
        t0 = time.monotonic()
        prompt_id = str(uuid.uuid4())
        ctx.prompt_ids.append(prompt_id)
        await ctx.comfy.submit(graph_for(seed, f"{project.slug}_{asset_id}"), prompt_id=prompt_id)
        entry = await ctx.comfy.wait(prompt_id, timeout=ctx.settings.bgm_timeout)
        t1 = time.monotonic()
        songs = output_files(entry, output_node, "audio")
        if not songs:
            raise ComfyError(f"ComfyUI returned no audio for prompt {prompt_id}")
        output = songs[0]
        data = await ctx.comfy.fetch_output(output["filename"], output["subfolder"], output.get("type", "output"))
        t2 = time.monotonic()

        ctx.db.update_job(job.id, stage=f"postprocess {i + 1}/{count}")
        directory = asset_dir(ctx.settings, project.slug, asset_id)
        stats, names = await asyncio.to_thread(_postprocess_bgm, data, directory, bpm, loop, ctx.settings.ffmpeg)
        step = {
            "generate": round(t1 - t0, 2),
            "fetch": round(t2 - t1, 2),
            "postprocess": round(time.monotonic() - t2, 2),
        }
        timings.append(step)
        meta = {
            "description": brief,
            **text,
            "bpm": bpm,
            "requested_s": seconds,
            "vocal": vocal,
            "seed": seed,
            "workflow": workflow,
            **model,
            "licenses": license_records(model["models"]),
            "comfy_prompt_id": prompt_id,
            "comfy_output": {"filename": output["filename"], "subfolder": output["subfolder"]},
            **stats,
            "timings": step,
        }
        files = {role: to_rel(ctx.settings, directory / name) for role, name in names.items()}
        ctx.db.create_asset(job.id, job.project_id, "bgm", files=files, meta=meta, seed=seed, asset_id=asset_id)
        ctx.db.update_job(job.id, timings={"candidates": timings})


def _postprocess_animation(native: Path, directory: Path, spec: PixelSpec, base: Image.Image) -> tuple[dict, dict]:
    """The frames in the project's spec, then the files: the 10-frame row, the game's JSON, a numbered contact sheet
    (the preview) and a GIF, and frames/000.png... Returns (fit report, file role -> path under `directory`)."""
    frames, fit = fit_frames(load_frames(native), spec, base)
    (directory / "frames").mkdir(exist_ok=True)
    names = [f"frames/{i:03d}.png" for i in range(len(frames))]
    for frame, name in zip(frames, names, strict=True):
        frame.save(directory / name)
    game_row(frames).save(directory / "row.png")
    info = game_json(spec.width, spec.height, "animation")  # export writes it again under the exported name
    (directory / "animation.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    contact_sheet(frames, fit["ground_row"]).save(directory / "preview.png")
    (directory / "preview.gif").write_bytes(animated_gif(frames))
    files = {"row": "row.png", "json": "animation.json", "preview": "preview.png", "gif": "preview.gif"}
    return fit | {"frame_files": names}, files | {"base": "base.png"}


async def run_animation_job(ctx: RunContext, job: Job) -> None:
    """Idle + walk frames of a sprite asset with sprite-gen and the codex CLI, one sprite-gen run per candidate.

    A cloud job: codex sends the enlarged sprite, sprite-gen's layout guides and prompts to OpenAI, so it runs only for
    projects with animation_cloud on (checked here again: it may have been turned off after the request). The rows are
    generated in the project's cell (run/gen), then extracted again in cells NATIVE_CELL_FACTOR times larger
    (run/native) so sprite-gen keeps codex's own pixel size; fit_frames shrinks each row to the base sprite's height.
    """
    params = job.params
    count = int(params.get("count", 1))
    project = ctx.db.get_project(job.project)
    if not project.animation_cloud:
        raise ValueError(
            f"animation is not allowed for this project: {project.slug} has animation_cloud off "
            "(update_project animation_cloud=true allows sending its sprites to OpenAI)"
        )
    base_asset = ctx.db.get_asset(params["asset_id"])
    if base_asset is None or base_asset.project_id != project.id or base_asset.kind != "sprite":
        raise ValueError(f"asset {params['asset_id']} is not a sprite of project {project.slug}")
    spec = pixel_spec(project, "sprite")
    if spec is None:
        raise ValueError(f"project {project.slug} is not pixel art; animations need its sprite size and colors")
    ground = PIXEL_MARGIN
    if project.reference_image:  # sprites stand where the reference's subject stands, as in run_image_job
        with Image.open(from_rel(ctx.settings, project.reference_image)) as reference:
            ground = reference_ground(reference, spec.height)
    spec = replace(spec, ground=ground)
    with Image.open(from_rel(ctx.settings, base_asset.files["processed"])) as img:
        base = img.convert("RGBA")
    description = base_asset.meta.get("description") or params.get("description") or "a game character"
    sprite_gen = SpriteGen.from_settings(ctx.settings)
    version = sprite_gen.version()
    states = request_states()
    cell = (spec.width, spec.height)
    native_cell = (spec.width * NATIVE_CELL_FACTOR, spec.height * NATIVE_CELL_FACTOR)
    character = f"asset-{base_asset.id}"
    timings = []

    for i in range(count):
        if ctx.cancel_requested():
            raise JobCancelled()
        asset_id = new_id()
        of = f" {i + 1}/{count}" if count > 1 else ""
        directory = asset_dir(ctx.settings, project.slug, asset_id)
        gen, native = directory / "run" / "gen", directory / "run" / "native"
        gen.mkdir(parents=True, exist_ok=True)
        base.save(directory / "base.png")
        big = directory / "run" / "base-large.png"  # what codex gets
        scale = max(1, ANIMATION_BASE_SIDE // max(base.size))
        base.resize((base.width * scale, base.height * scale), Image.Resampling.NEAREST).save(big)

        ctx.db.update_job(job.id, stage=f"preparing{of}")
        t0 = time.monotonic()
        await sprite_gen.prepare(gen, big, cell, spec.max_colors, description, states, character)
        ctx.db.update_job(job.id, stage=f"generating rows (codex){of}")
        t1 = time.monotonic()
        generated = await sprite_gen.gen_set(gen, concurrency=ANIMATION_ROWS_AT_ONCE)
        t2 = time.monotonic()
        ctx.db.update_job(job.id, stage=f"extracting frames{of}")
        await sprite_gen.prepare(native, big, native_cell, spec.max_colors, description, states, character)
        shutil.copytree(gen / "raw", native / "raw", dirs_exist_ok=True)  # the same rows, without the size cap
        extracted = await sprite_gen.extract(native)
        await sprite_gen.compose(native)
        inspected = await sprite_gen.inspect(native)
        t3 = time.monotonic()

        ctx.db.update_job(job.id, stage=f"postprocess {i + 1}/{count}")
        fit, names = await asyncio.to_thread(_postprocess_animation, native, directory, spec, base)
        frame_files = [to_rel(ctx.settings, directory / name) for name in fit.pop("frame_files")]
        step = {
            "prepare": round(t1 - t0, 2),
            "generate": round(t2 - t1, 2),
            "extract": round(t3 - t2, 2),
            "postprocess": round(time.monotonic() - t3, 2),
        }
        timings.append(step)
        meta = {
            "description": description,
            "base_asset": base_asset.id,
            "animation": {
                "frames": FRAMES,
                "tags": game_tags(),
                "cell": list(cell),
                "max_colors": spec.max_colors,
                "files": frame_files,
            },
            "fit": fit,
            "cloud": {"provider": "codex", "sent": CLOUD_SENT},
            "spritegen": {
                "version": version,
                "engine_revision": extracted.get("engine_revision"),
                "states": states,
                "rows": {item["state"]: item.get("elapsed_seconds") for item in generated.get("items", [])},
                "warnings": extracted.get("warnings", []),
                "inspect": {k: inspected.get(k) for k in ("ok", "errors", "warnings")},
            },
            "timings": step,
        }
        files = {role: to_rel(ctx.settings, directory / name) for role, name in names.items()}
        ctx.db.create_asset(job.id, job.project_id, "animation", files=files, meta=meta, asset_id=asset_id)
        ctx.db.update_job(job.id, timings={"candidates": timings})


def _save_picture(data: bytes, directory: Path) -> list[int]:
    """raw.png as ComfyUI saved it, processed.png and preview.png without alpha. Returns the picture's size."""
    (directory / "raw.png").write_bytes(data)
    with Image.open(io.BytesIO(data)) as raw:
        picture = raw.convert("RGB")
    picture.save(directory / "processed.png")
    make_preview(picture).save(directory / "preview.png")
    return list(picture.size)


async def _upload_sheets(ctx: RunContext, book: Book, sheets: tuple[Sheet, ...]) -> list[Reference]:
    refs = []
    for sheet in sheets:
        asset = ctx.db.get_asset(sheet.asset_id)
        path = from_rel(ctx.settings, asset.files["processed"]) if asset is not None else None
        if path is None or not path.is_file():
            raise FileNotFoundError(f"the picture of sheet {sheet.name!r} is missing; generate or set it again")
        name = await ctx.comfy.upload_image(path, f"book_{book.id}_{sheet.id}.png")
        refs.append(Reference(name, REFERENCE_MODE))
    return refs


async def run_page_image_job(ctx: RunContext, job: Job) -> None:
    """One full-page picture of a book, or one picture of a place or prop sheet. Same steps as run_image_job, including
    the encode in a prompt of its own, but opaque, in the book's shape, with up to three references. The reference
    KV cache stays in RAM. Uses the official Turbo checkpoint: 13 s a picture with three references, with no LoRA."""
    params = dict(job.params)
    if params.get("seed") is None:
        params["seed"] = random.randrange(2**31)
        ctx.db.update_job(job.id, params=params)
    seed = int(params["seed"])
    project = ctx.db.get_project(job.project)
    book = ctx.db.get_book(params["book_id"])
    page = ctx.db.get_page(params["page_id"]) if params.get("page_id") else None
    if page is not None:
        built = page_prompt(project.style, ctx.db.list_sheets(book.id), page)
        prompt, sheets = built.text, built.refs
    else:
        prompt, sheets = sheet_prompt(project.style, ctx.db.get_sheet(params["sheet_id"])), ()

    ctx.db.update_job(job.id, stage="uploading references" if sheets else "encoding prompt")
    refs = await _upload_sheets(ctx, book, sheets)
    ctx.db.update_job(job.id, stage="encoding prompt")
    t0 = time.monotonic()
    encode_id = str(uuid.uuid4())
    ctx.prompt_ids.append(encode_id)
    await ctx.comfy.submit(qwen_text_encode(prompt, refs), prompt_id=encode_id)
    await ctx.comfy.free(unload_models=True, free_memory=False)
    await ctx.comfy.wait(encode_id, timeout=ctx.settings.image_timeout)
    t1 = time.monotonic()
    if ctx.cancel_requested():
        raise JobCancelled()

    ctx.db.update_job(job.id, stage="generating")
    asset_id = new_id()
    prompt_id = str(uuid.uuid4())
    ctx.prompt_ids.append(prompt_id)
    graph = qwen_book_page(prompt, seed, f"{project.slug}_{asset_id}", book.width, book.height, refs)
    await ctx.comfy.submit(graph, prompt_id=prompt_id)
    entry = await ctx.comfy.wait(prompt_id, timeout=ctx.settings.image_timeout)
    t2 = time.monotonic()
    images = output_files(entry, QWEN_OUTPUT_NODE)
    if not images:
        raise ComfyError(f"ComfyUI returned no image for prompt {prompt_id}")
    output = images[0]
    data = await ctx.comfy.fetch_output(output["filename"], output["subfolder"], output.get("type", "output"))

    directory = asset_dir(ctx.settings, project.slug, asset_id)
    size = await asyncio.to_thread(_save_picture, data, directory)
    step = {"encode": round(t1 - t0, 2), "generate": round(t2 - t1, 2)}
    meta = {
        "book_id": book.id,
        "description": params["description"],
        "prompt": prompt,
        "seed": seed,
        "workflow": "qwen_book_page",
        "models": QWEN_BOOK_MODELS,
        "licenses": license_records(QWEN_BOOK_MODELS),
        "steps": QWEN_BOOK_STEPS,
        "sampler": QWEN_SAMPLER,
        "width": size[0],
        "height": size[1],
        "references": [{"sheet": s.name, "asset_id": s.asset_id} for s in sheets],
        "comfy_prompt_id": prompt_id,
        "timings": step,
    }
    meta |= {"page_id": page.id, "page_number": page.number} if page is not None else {"sheet_id": params["sheet_id"]}
    files = {name: to_rel(ctx.settings, directory / f"{name}.png") for name in IMAGE_FILES}
    ctx.db.create_asset(job.id, job.project_id, "page_image", files=files, meta=meta, seed=seed, asset_id=asset_id)
    ctx.db.update_job(job.id, timings=step)
    if page is None:
        sheet = ctx.db.get_sheet(params["sheet_id"])
        if sheet.asset_id is None:
            ctx.db.set_sheet_asset(sheet.id, asset_id)
    else:
        current = ctx.db.get_page(page.id)
        ctx.db.update_page(page.id, status="candidate", image_asset_id=current.image_asset_id or asset_id)


def _page_picture(ctx: RunContext, page: Page) -> Path:
    asset = ctx.db.get_asset(page.image_asset_id)
    path = from_rel(ctx.settings, asset.files["processed"]) if asset is not None else None
    if path is None or not path.is_file():
        raise FileNotFoundError(f"the picture of page {page.number} is missing")
    return path


def _colophon(book: Book, records: list[dict]) -> list[str]:
    lines = []
    if label := (book.source or {}).get("label"):
        lines.append(f"Source: {label}")
    lines.append("Pictures: " + ", ".join(license_names(records)))
    if worst_class(records) in WARN_CLASSES:
        lines.append("Made with a model whose license limits this use. Check it before sharing or selling this book.")
    return lines


async def run_book_export_job(ctx: RunContext, job: Job) -> None:
    """The book's chosen pictures and text as a PDF; a job so that it shares the queue, the status and the gallery."""
    project = ctx.db.get_project(job.project)
    book = ctx.db.get_book(job.params["book_id"])
    pages = [p for p in ctx.db.list_pages(book.id) if p.image_asset_id]
    if not pages:
        raise ValueError(f"book {book.id} has no page with a chosen picture")
    t0 = time.monotonic()
    records = []
    for page in pages:
        records.extend(ctx.db.get_asset(page.image_asset_id).meta.get("licenses", []))
    records = list({r["file"]: r for r in records}.values())
    book_pages = [
        BookPage(p.number, _page_picture(ctx, p), p.text, (p.source_refs[0].get("label", "") if p.source_refs else ""))
        for p in pages
    ]
    cover = next((b.image for b in book_pages if b.number == book.cover_page), book_pages[0].image)
    asset_id = new_id()
    directory = asset_dir(ctx.settings, project.slug, asset_id)
    ctx.db.update_job(job.id, stage="laying out")
    warnings = await asyncio.to_thread(
        render_pdf,
        directory / "book.pdf",
        book.title,
        cover,
        book_pages,
        _colophon(book, records),
        ctx.settings.book_font,
        book.height / book.width,
    )
    with Image.open(cover) as picture:
        make_preview(picture.convert("RGB")).save(directory / "preview.png")
    worst = worst_class(records)
    if worst in WARN_CLASSES:
        warnings.append(f"license: {'; '.join(license_names(records))}. Check it before sharing or selling this book.")
    meta = {
        "book_id": book.id,
        "description": book.title,
        "format": "pdf",
        "pages": [p.number for p in pages],
        "unapproved_pages": [p.number for p in pages if p.status != "approved"],
        "licenses": records,
        "license_class": worst,
        "warnings": warnings,
    }
    files = {
        "pdf": to_rel(ctx.settings, directory / "book.pdf"),
        "preview": to_rel(ctx.settings, directory / "preview.png"),
    }
    ctx.db.create_asset(job.id, job.project_id, "book_export", files=files, meta=meta, asset_id=asset_id)
    ctx.db.update_job(job.id, timings={"export": round(time.monotonic() - t0, 2)})


RUNNERS = {
    "image": run_image_job,
    "bgm": run_bgm_job,
    "animation": run_animation_job,
    "page_image": run_page_image_job,
    "book_export": run_book_export_job,
}
