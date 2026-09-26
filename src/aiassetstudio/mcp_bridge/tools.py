"""MCP tool logic, kept apart from the server wiring so tests can call it directly. Text is for Claude to read."""

from mcp.server.mcpserver.utilities.types import Image

from .studio_api import StudioApi

MAX_PREVIEWS = 8
MAX_WAIT_SECONDS = 60
MAX_LISTED_ASSETS = 100
FAMILY_LABELS = {
    "qwen": "image models (Qwen-Image-2.1)",
    "ace": "music models (ACE-Step)",
    "yue2": "vocal models (YuE2)",
}


def _project_text(p: dict) -> str:
    lines = [
        f"{p['slug']}: {p['name']}",
        f"  style: {p['style'] or '(none)'}",
        f"  export_dir: {p['export_dir'] or '(none; pass dest_dir to export_asset)'}",
    ]
    if p["pixel_art"]:
        icon = p["icon_size"] or p["logical_width"]
        lines.append(
            f"  pixel art: sprites {p['logical_width']}x{p['logical_height']}, icons {icon}x{icon}, "
            f"at most {p['max_colors']} colors"
        )
    else:
        lines.append("  pixel art: no")
        if p["icon_size"]:
            lines.append(f"  icon size: {p['icon_size']}x{p['icon_size']}")
    if p["palette"]:
        lines.append(f"  palette: {' '.join(p['palette'])}")
    reference = p["reference_image"]
    lines.append(
        f"  reference image: {f'{reference} (studio copy; sets the style of sprites)' if reference else '(none)'}"
    )
    if p.get("animation_cloud"):
        lines.append("  animation: allowed (sends sprites to OpenAI via codex)")
    else:
        lines.append("  animation: off (update_project animation_cloud=true to allow; it sends sprites to OpenAI)")
    return "\n".join(lines)


def _job_line(job: dict) -> str:
    params = job["params"]
    kind = params.get("kind", job["kind"])
    what = f"{params.get('count', '?')} x {kind}: {params.get('description') or params.get('brief', '')}"
    state = job["status"]
    if job["status"] == "running" and job.get("stage"):
        state += f" ({job['stage']})"
    if job.get("error"):
        state += f": {job['error']}"
    return f"job {job['id']} [{job['project']}] {what} -> {state}"


def _song_text(api: StudioApi, a: dict) -> str:
    """One BGM candidate for Claude, who cannot hear it: length, tempo, loop and where to listen."""
    m = a["meta"]
    kind = "song with vocals" if m.get("vocal") else "instrumental"
    if loop := m.get("loop"):
        tempo = loop.get("bpm", m["bpm"])
        played = f"{m['bpm']} BPM" if abs(tempo - m["bpm"]) < 0.05 else f"{tempo:.1f} BPM (asked for {m['bpm']})"
        shape = (
            f"seamless loop of {loop['bars']} bars at {played} = {m['length_s']:.1f} s "
            f"(song {loop['start_s']:.1f}-{loop['end_s']:.1f} s, seam ratio {loop['seam_ratio']})"
        )
    else:
        shape = f"{m['length_s']:.1f} s at {m['bpm']} BPM, not looped"
        if m.get("loop_error"):
            shape += f" ({m['loop_error']})"
    lines = [f"asset {a['id']} seed={a['seed']} status={a['status']}: {kind}, {shape}"]
    lines += [f"  {role}: {api.base_url}{url}" for role, url in sorted(a["files"].items()) if role != "raw"]
    if m.get("ogg_error"):
        lines.append(f"  no OGG: {m['ogg_error']}")
    return "\n".join(lines)


def _pixel_note(m: dict) -> str:
    """How a pixel-art candidate was fitted to its canvas; a stretched one can have pixels of two sizes."""
    fit = (m.get("pixel") or {}).get("fit")
    if not fit:
        return ""
    if fit["fit"] == "native":
        w, h = fit["native_size"]
        return f", pixel art: the model's own {w}x{h} pixels at {fit['scale']}x"
    return f", pixel art: stretched to fit ({fit.get('reason', 'no grid')}), pixels may differ in size"


def _animation_text(a: dict) -> str:
    """One animation candidate: its frames, their size against the base sprite, feet row, colors and warnings."""
    m = a["meta"]
    fit = m.get("fit") or {}
    anim = m.get("animation") or {}
    cell = anim.get("cell") or ["?", "?"]
    tags = ", ".join(f"{t['name']} {t['to'] - t['from'] + 1} at {t['duration']:g} s" for t in anim.get("tags", []))

    def size(key: str) -> str:
        w, h = fit.get(key) or ("?", "?")
        return f"{w:g}x{h:g}" if isinstance(w, int | float) else f"{w}x{h}"

    frames = f"{anim.get('frames', '?')} frames of {cell[0]}x{cell[1]} ({tags})"
    lines = [f"asset {a['id']} status={a['status']}: animation, {frames} of sprite {m.get('base_asset', '?')}"]
    lines[0] += ", made with codex (cloud)"
    sizes = f"idle {size('idle_size')}, walk {size('walk_size')} vs base {size('base_size')}"
    if fit.get("size_ok"):
        lines.append(f"  size: {sizes}")
    else:
        lines.append(f"  frames differ in size from the base sprite ({sizes})")
    lines.append(f"  feet on row {fit.get('ground_row', '?')}, {fit.get('colors_used', '?')} colors (the base's)")
    lines += [f"  warning: {w}" for w in fit.get("warnings", [])]
    inspect = (m.get("spritegen") or {}).get("inspect") or {}
    if inspect.get("ok") is False:
        lines.append(f"  sprite-gen inspect found: {'; '.join(map(str, inspect.get('errors') or []))[:300]}")
    return "\n".join(lines)


def _asset_line(a: dict) -> str:
    return f"asset {a['id']} {a['kind']} seed={a['seed']} status={a['status']} job={a['job_id']}"


async def studio_status(api: StudioApi) -> str:
    s = await api.status()
    comfy = s["comfy"]
    lines = ["backend: ok"]
    if comfy["up"]:
        lines.append(f"ComfyUI: up (free VRAM {comfy['vram_free_mb']} MB, free RAM {comfy['ram_free_mb']} MB)")
    else:
        lines.append("ComfyUI: down; the next generation request starts it (up to 2 min)")
        if comfy.get("error"):
            lines.append(f"  last start error: {comfy['error']}")
    for family, st in s["preflight"].items():
        label = FAMILY_LABELS.get(family, family)
        if st["ok"]:
            lines.append(f"{label}: ready")
        elif st.get("reason"):
            lines.append(f"{label}: not checked ({st['reason']})")
        else:
            lines.append(f"{label}: MISSING {', '.join(st['missing_nodes'] + st['missing_models'])}")
    if animation := s.get("animation"):
        ready = "ready" if animation["ok"] else f"not ready ({animation['reason']})"
        lines.append(f"animation (sprite-gen + codex, cloud): {ready}")
    current = s["queue"].get("current")
    if current:
        lines.append(
            f"running: job {current['id']} [{current['project']}] {current['stage']}, {current['elapsed_s']} s"
        )
    else:
        lines.append("running: nothing")
    lines.append(f"queued: {s['queue']['queued']}")
    lines.append(f"gallery: {s['gallery_url']}")
    return "\n".join(lines)


async def list_projects(api: StudioApi) -> str:
    projects = await api.list_projects()
    if not projects:
        return "No projects yet. Create one with create_project."
    return "\n\n".join(_project_text(p) for p in projects)


async def get_project(api: StudioApi, slug: str) -> str:
    return _project_text(await api.get_project(slug))


async def create_project(
    api: StudioApi, slug: str, name: str, style: str = "", export_dir: str | None = None, **spec
) -> str:
    """`spec`: pixel_art, logical_width, logical_height, icon_size, max_colors, palette, reference_image,
    animation_cloud."""
    return "Created project\n" + _project_text(await api.create_project(slug, name, style, export_dir, **spec))


# In update_project, None (omitted) leaves a field as it is. These values clear one instead. Never the booleans:
# False == 0, so pixel_art=False or animation_cloud=False would clear the field instead of turning it off.
CLEARED_BY_ZERO = ("logical_width", "logical_height", "icon_size", "max_colors")


async def update_project(api: StudioApi, slug: str, **changes) -> str:
    """`changes`: name, style, export_dir, pixel_art, logical_width, logical_height, icon_size, max_colors, palette,
    reference_image, animation_cloud. 0 clears a size or color count, [] the palette, "" export_dir or
    reference_image."""
    fields = {}
    for key, value in changes.items():
        if value is None:
            continue
        if (key in CLEARED_BY_ZERO and value == 0) or (key == "palette" and not value):
            value = None
        fields[key] = value
    if not fields:
        return "Nothing to change.\n" + _project_text(await api.get_project(slug))
    return "Updated project\n" + _project_text(await api.update_project(slug, **fields))


async def generate_image(
    api: StudioApi, project: str, kind: str, description: str, count: int = 4, seed: int | None = None
) -> str:
    job_id = await api.create_image_job(project, kind, description, count, seed)
    return (
        f"Queued job {job_id} ({count} x {kind}). Each image takes about 10-20 s; the first job after a pause "
        f"can take up to a minute longer while models load (or two if ComfyUI has to start).\n"
        f"Call get_job(job_id='{job_id}', wait_seconds=60) to wait for the candidates."
    )


async def generate_animation(api: StudioApi, asset_id: str, count: int = 1) -> str:
    job_id = await api.create_animation_job(asset_id, count)
    return (
        f"Queued job {job_id} ({count} x animation of sprite {asset_id}: idle 4 + walk 6 frames). It sends the sprite "
        f"(enlarged), a layout guide and a prompt to OpenAI through the Codex CLI; 1-3 minutes per candidate, and "
        f"other jobs wait meanwhile.\nCall get_job(job_id='{job_id}', wait_seconds=60) until it is done."
    )


async def get_job(api: StudioApi, job_id: str, wait_seconds: int = 30) -> list[str | Image]:
    job = await api.get_job(job_id, wait=max(0, min(MAX_WAIT_SECONDS, wait_seconds)))
    out: list[str | Image] = [_job_line(job)]
    if job["status"] in ("queued", "running"):
        out.append("Still in progress; call get_job again to keep waiting.")
    assets = job.get("assets", [])
    for a in assets[:MAX_PREVIEWS]:
        if a["kind"] == "bgm":
            out.append(_song_text(api, a))
            continue
        if a["kind"] == "animation":
            out.append(_animation_text(a))
        else:
            out.append(f"asset {a['id']} seed={a['seed']} status={a['status']}{_pixel_note(a['meta'])}")
        if "preview" in a["files"]:
            out.append(Image(data=await api.get_file(a["id"], "preview"), format="png"))
    if len(assets) > MAX_PREVIEWS:
        out.append(f"{len(assets) - MAX_PREVIEWS} more candidates are only in the gallery.")
    if any(a["kind"] == "bgm" for a in assets):
        out.append(
            "You cannot hear these. Ask the user to listen in the gallery (loop playback and a 'listen to the seam' "
            "button) and tell you which to keep; then set_asset_status and export_asset (copies the WAV and OGG)."
        )
    elif any(a["kind"] == "animation" for a in assets):
        out.append(
            "Each sheet shows the 10 frames (idle 1-4, walk 1-6) with a red line under the feet row; the user can play "
            "them in the gallery. To use one: set_asset_status(asset_id, 'selected'), then export_asset(asset_id, "
            "name=...) writes <name>.png (the frames in one row), <name>/000.png-009.png and <name>.json."
        )
    elif assets:
        out.append("To use one: set_asset_status(asset_id, 'selected'), then export_asset(asset_id).")
    out.append(f"Gallery: {api.base_url}/#/jobs/{job_id}")
    return out


async def generate_bgm(
    api: StudioApi,
    project: str,
    brief: str,
    bpm: int,
    seconds: float = 90,
    loop: bool = True,
    vocal: bool = False,
    lyrics: str | None = None,
    keyscale: str | None = None,
    count: int = 2,
    seed: int | None = None,
) -> str:
    job_id = await api.create_bgm_job(
        project,
        brief,
        bpm,
        seconds=seconds,
        loop=loop,
        vocal=vocal,
        lyrics=lyrics,
        keyscale=keyscale,
        count=count,
        seed=seed,
    )
    pace = (
        "YuE2 needs several minutes per song with vocals"
        if vocal
        else f"ACE-Step needs about {max(20, round(seconds * 0.4))} s per {seconds:g} s song"
    )
    return (
        f"Queued job {job_id} ({count} x {'song with vocals' if vocal else 'instrumental'}, {bpm} BPM, "
        f"{seconds:g} s). {pace}, plus about a minute to load the music models after images.\n"
        f"Call get_job(job_id='{job_id}', wait_seconds=60) until it is done. You cannot hear audio: then ask the "
        f"user to listen in the gallery ({api.base_url}/#/jobs/{job_id}) and pick one."
    )


async def list_assets(api: StudioApi, project: str, kind: str | None = None, status: str | None = None) -> str:
    assets = await api.list_assets(project=project, kind=kind, status=status)
    if not assets:
        return "No assets match."
    lines = [f"{_asset_line(a)} - {a['meta'].get('description', '')}" for a in assets[-MAX_LISTED_ASSETS:]]
    if len(assets) > MAX_LISTED_ASSETS:
        lines.insert(0, f"(showing the newest {MAX_LISTED_ASSETS} of {len(assets)})")
    return "\n".join(lines)


async def set_asset_status(api: StudioApi, asset_id: str, status: str) -> str:
    asset = await api.set_asset_status(asset_id, status)
    return f"asset {asset['id']} is now {asset['status']}"


async def export_asset(api: StudioApi, asset_id: str, dest_dir: str | None = None, name: str | None = None) -> str:
    paths = await api.export_asset(asset_id, dest_dir, name)
    return "Exported:\n" + "\n".join(paths)


async def cancel_job(api: StudioApi, job_id: str) -> str:
    job = await api.cancel_job(job_id)
    note = "" if job["status"] == "cancelled" else " (it had already finished, so nothing was cancelled)"
    return _job_line(job) + note
