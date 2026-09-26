import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from fakes import FakeComfy
from PIL import Image

from aiassetstudio.comfy.client import ComfyClient, ComfyExecutionError
from aiassetstudio.config import Settings
from aiassetstudio.jobs.runners import (
    LOOP_SECTIONS,
    JobCancelled,
    RunContext,
    run_animation_job,
    run_bgm_job,
    run_image_job,
)
from aiassetstudio.post.image import alpha_stats
from aiassetstudio.prompts import RGBA_PREFIX, RGBA_SUFFIX
from aiassetstudio.spritegen.client import SpriteGenError
from aiassetstudio.store.db import Database, new_id
from aiassetstudio.store.files import asset_dir, from_rel, to_rel
from aiassetstudio.store.reference import store_reference

FAKE_SPRITEGEN = Path(__file__).parent / "fake_spritegen.py"


@pytest.fixture
async def env(tmp_path):
    made = []

    async def make(fail_with=None, cancel_after_assets=None, audio_seconds=None, ffmpeg="ffmpeg"):
        fake = FakeComfy(fail_with=fail_with, audio_seconds=audio_seconds)
        comfy = ComfyClient("http://comfy.test", transport=fake.transport)
        db = Database(tmp_path / "studio.db")
        settings = Settings(
            data_dir=tmp_path,
            image_timeout=5,
            bgm_timeout=5,
            ffmpeg=ffmpeg,
            sprite_gen=str(FAKE_SPRITEGEN),  # never the real sprite-gen (or codex) in tests
            codex_dir=str(tmp_path / "codex-app"),
        )
        project = db.create_project("demo", "Demo", style="cute chibi")

        def cancel_requested():
            return cancel_after_assets is not None and len(db.list_assets()) >= cancel_after_assets

        ctx = RunContext(db, comfy, settings, cancel_requested=cancel_requested)
        made.append((comfy, db))
        return SimpleNamespace(fake=fake, db=db, ctx=ctx, settings=settings, project=project)

    yield make
    for comfy, db in made:
        await comfy.aclose()
        db.close()


def image_job(e, **params):
    return e.db.create_job(e.project.id, "image", "qwen", {"kind": "sprite", "description": "a green slime", **params})


async def test_generates_candidates(env):
    e = await env()
    job = image_job(e, count=2, seed=100)
    await run_image_job(e.ctx, job)

    assets = e.db.list_assets(job_id=job.id)
    assert [a.seed for a in assets] == [100, 101]
    encode, *candidates = e.fake.graphs
    assert "PreviewAny" in {node["class_type"] for node in encode.values()}  # text encoding runs on its own first
    assert e.fake.free_calls == [{"unload_models": True, "free_memory": False}]  # unload, keep cached conditioning
    assert [g["11"]["inputs"]["noise_seed"] for g in candidates] == [100, 101]
    assert all(g["5"] == encode["5"] for g in candidates)  # identical node -> ComfyUI reuses the conditioning
    assert "Art style: cute chibi." in encode["5"]["inputs"]["prompt"]

    for asset in assets:
        assert asset.kind == "sprite" and asset.status == "candidate"
        paths = {name: from_rel(e.settings, rel) for name, rel in asset.files.items()}
        assert set(paths) == {"raw", "processed", "preview"}
        assert all(p.is_file() for p in paths.values())
        assert paths["raw"].parent.name == asset.id
        processed = Image.open(paths["processed"])
        assert processed.mode == "RGBA"
        assert alpha_stats(processed)["border_max"] == 0

        meta = asset.meta
        for key in ("prompt", "seed", "models", "comfy_prompt_id", "alpha_raw", "alpha_processed", "timings"):
            assert key in meta
        assert meta["steps"] == 6 and meta["sampler"] == "euler"
        assert meta["models"]["lora"].startswith("Qwen-Image-2.1-viggle-turbo")
        assert meta["comfy_prompt_id"] in e.fake.prompts
        assert meta["alpha_raw"]["border_mean"] > 0
        assert meta["alpha_processed"]["border_mean"] == 0
        assert meta["postprocess"]["alpha_threshold"] == 16
        assert set(meta["timings"]) == {"generate", "fetch", "postprocess"}

    job = e.db.get_job(job.id)
    assert job.stage == "postprocess 2/2"
    assert len(job.timings["candidates"]) == 2
    assert job.timings["encode"] >= 0
    assert e.ctx.prompt_ids == list(e.fake.prompts)  # encode prompt first, then one per candidate


async def test_random_seed_is_recorded(env):
    e = await env()
    job = image_job(e, count=2)
    await run_image_job(e.ctx, job)
    seed = e.db.get_job(job.id).params["seed"]
    assert isinstance(seed, int)
    assert [a.seed for a in e.db.list_assets(job_id=job.id)] == [seed, seed + 1]


async def test_icon_is_square(env):
    e = await env()
    job = image_job(e, kind="icon", description="a red potion", count=1, seed=1)
    await run_image_job(e.ctx, job)
    [asset] = e.db.list_assets(job_id=job.id)
    processed = Image.open(from_rel(e.settings, asset.files["processed"]))
    assert processed.width == processed.height
    assert asset.meta["postprocess"]["icon_pad_ratio"] == 0.06


async def test_cancel_between_candidates(env):
    e = await env(cancel_after_assets=1)
    job = image_job(e, count=3, seed=1)
    with pytest.raises(JobCancelled):
        await run_image_job(e.ctx, job)
    assert len(e.db.list_assets(job_id=job.id)) == 1
    assert len(e.fake.prompts) == 2  # the encode prompt and one candidate


async def test_execution_error_propagates(env):
    e = await env(fail_with="error")
    job = image_job(e, count=2, seed=1)
    with pytest.raises(ComfyExecutionError):
        await run_image_job(e.ctx, job)
    assert e.db.list_assets(job_id=job.id) == []
    assert e.ctx.prompt_ids == list(e.fake.prompts)


PIXEL = {"pixel_art": True, "logical_width": 32, "logical_height": 24, "max_colors": 12}


def processed_of(e, asset) -> Image.Image:
    return Image.open(from_rel(e.settings, asset.files["processed"]))


async def test_pixel_sprite(env):
    e = await env()
    e.db.update_project("demo", **PIXEL, palette=["#c83228", "#101010"])
    job = image_job(e, count=1, seed=5)
    await run_image_job(e.ctx, job)
    [asset] = e.db.list_assets(job_id=job.id)
    processed = processed_of(e, asset)
    assert processed.size == (32, 24)
    alpha = np.asarray(processed)[..., 3]
    assert set(np.unique(alpha)) <= {0, 255}
    assert Image.open(from_rel(e.settings, asset.files["preview"])).size == (256, 192)  # x8, nearest
    assert asset.meta["pixel"] == {
        "width": 32,
        "height": 24,
        "max_colors": 12,
        "colors_used": 1,  # FakeComfy draws one red square: it snaps to the palette's red
        "palette": ["#c83228", "#101010"],
        "fit": {"fit": "stretch", "reason": "no grid"},  # a plain square has no block grid
    }
    assert asset.meta["postprocess"]["pixelate"]["anchor"] == "bottom"
    assert asset.meta["alpha_processed"]["border_band"] == 1
    assert asset.meta["alpha_processed"]["border_max"] == 0
    assert asset.meta["size_processed"] == [32, 24]
    assert e.fake.graphs[0]["5"]["inputs"]["prompt"].endswith(
        "Pixel art, crisp hard-edged pixels, limited palette, no anti-aliasing." + RGBA_SUFFIX
    )


async def test_pixel_icon_size(env):
    e = await env()
    e.db.update_project("demo", **PIXEL)
    job = image_job(e, kind="icon", description="a key", count=1, seed=1)
    await run_image_job(e.ctx, job)
    [asset] = e.db.list_assets(job_id=job.id)
    assert processed_of(e, asset).size == (32, 32)  # no icon_size: logical_width
    e.db.update_project("demo", icon_size=16)
    job = image_job(e, kind="icon", description="a key", count=1, seed=1)
    await run_image_job(e.ctx, job)
    [asset] = e.db.list_assets(job_id=job.id)
    assert processed_of(e, asset).size == (16, 16)
    assert asset.meta["postprocess"]["pixelate"]["anchor"] == "center"


async def test_icon_size_without_pixel_art(env):
    # User decision (c), 2026-09-25: icon_size shrinks the icons of projects that are not pixel art too.
    e = await env()
    e.db.update_project("demo", icon_size=64)
    job = image_job(e, kind="icon", description="a key", count=1, seed=1)
    await run_image_job(e.ctx, job)
    [asset] = e.db.list_assets(job_id=job.id)
    assert processed_of(e, asset).size == (64, 64)
    assert asset.meta["postprocess"]["icon_size"] == 64
    assert "pixel" not in asset.meta
    sprite_job = image_job(e, count=1, seed=1)
    await run_image_job(e.ctx, sprite_job)
    [sprite] = e.db.list_assets(job_id=sprite_job.id)
    assert processed_of(e, sprite).size != (64, 64)  # sprites keep their trimmed size


async def test_reference_for_sprites(env):
    e = await env()
    reference = store_reference(e.settings, "demo", Image.new("RGBA", (32, 32), (10, 20, 30, 255)))
    e.db.update_project("demo", reference_image=reference)
    job = image_job(e, count=2, seed=1)
    await run_image_job(e.ctx, job)

    [upload] = e.fake.uploads  # once per job, not per candidate
    assert (upload["subfolder"], upload["name"]) == ("aiassetstudio", "ref_demo.png")
    encode, *candidates = e.fake.graphs
    assert encode["15"] == {"class_type": "LoadImage", "inputs": {"image": "aiassetstudio/ref_demo.png"}}
    assert encode["5"]["inputs"]["images.image_1"] == ["16", 0]
    assert encode["5"]["inputs"]["vae"] == ["4", 0]  # latent mode
    assert all(g["5"] == encode["5"] and g["15"] == encode["15"] for g in candidates)
    assert encode["5"]["inputs"]["prompt"].startswith(RGBA_PREFIX + "Replace the subject of picture 1 with a green")
    for asset in e.db.list_assets(job_id=job.id):
        assert asset.meta["reference"] == {"mode": "latent", "file": reference}
        assert asset.meta["workflow"] == "qwen_ref_turbo"
    assert "upload_reference" in e.db.get_job(job.id).timings

    icon_job = image_job(e, kind="icon", description="a key", count=1, seed=1)
    await run_image_job(e.ctx, icon_job)
    assert len(e.fake.uploads) == 1  # icons ignore the reference (user decision 2026-09-25)
    icon_graph = e.fake.graphs[-1]
    assert "15" not in icon_graph and "images.image_1" not in icon_graph["5"]["inputs"]
    assert "reference" not in e.db.list_assets(job_id=icon_job.id)[0].meta


async def test_pixel_sprites_stand_where_the_reference_stands(env):
    e = await env()
    keeper = np.zeros((32, 32, 4), np.uint8)
    keeper[3:29, 7:25] = (60, 70, 90, 255)  # stands on row 28 of 32, like the LAST LIGHT keeper
    reference = store_reference(e.settings, "demo", Image.fromarray(keeper, "RGBA"))
    e.db.update_project(
        "demo", pixel_art=True, logical_width=32, logical_height=32, max_colors=12, reference_image=reference
    )
    job = image_job(e, count=1, seed=5)
    await run_image_job(e.ctx, job)
    [asset] = e.db.list_assets(job_id=job.id)
    ys, _ = np.nonzero(np.asarray(processed_of(e, asset))[..., 3])
    assert ys.max() == 28  # not on the 1-cell margin (row 30)
    assert asset.meta["postprocess"]["pixelate"]["ground"] == 3


async def test_missing_reference_file(env):
    e = await env()
    e.db.update_project("demo", reference_image="projects/demo/reference/gone.png")
    with pytest.raises(FileNotFoundError, match="set it again with update_project"):
        await run_image_job(e.ctx, image_job(e, count=1, seed=1))
    assert not e.fake.prompts  # failed before anything reached ComfyUI


# --- BGM ---------------------------------------------------------------------------------------------------------

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def bgm_job(e, family="ace", **params):
    return e.db.create_job(e.project.id, "bgm", family, {"brief": "cozy village theme, flute", "bpm": 100, **params})


def bgm_files(e, asset) -> dict:
    return {role: from_rel(e.settings, rel) for role, rel in asset.files.items()}


async def test_bgm_loops(env):
    e = await env()
    job = bgm_job(e, seconds=30, count=2, seed=5)
    await run_bgm_job(e.ctx, job)

    graphs = e.fake.graphs
    assert [g["94"]["inputs"]["seed"] for g in graphs] == [5, 6]
    encode = graphs[0]["94"]["inputs"]
    assert encode["tags"] == "cozy village theme, flute, instrumental, no vocals, video game background music"
    assert encode["lyrics"] == LOOP_SECTIONS  # section tags: no quiet intro
    assert (encode["bpm"], encode["duration"], encode["keyscale"]) == (100, 30.0, "A minor")

    assets = e.db.list_assets(job_id=job.id)
    assert [a.kind for a in assets] == ["bgm", "bgm"]
    for asset in assets:
        files = bgm_files(e, asset)
        expected = {"raw", "loop_wav", "loop_ogg"} if HAVE_FFMPEG else {"raw", "loop_wav"}
        assert set(files) == expected and all(f.is_file() for f in files.values())
        assert files["raw"].name == "raw.flac" and files["loop_wav"].name == "loop.wav"
        meta = asset.meta
        assert (meta["raw_s"], meta["requested_s"], meta["bpm"], meta["vocal"]) == (30.0, 30.0, 100, False)
        assert meta["trimmed_s"] == pytest.approx(26.0, abs=0.06)  # the fake song ends 4 s early
        bar = 2.4 * meta["sample_rate"]
        wav = sf.info(str(files["loop_wav"]))
        assert abs(wav.frames - meta["loop"]["bars"] * bar) <= 1
        assert meta["loop"]["bars"] == 10  # whole bars in 26 s minus the 30 ms crossfade
        assert meta["loop"]["seam_ratio"] <= 1
        assert meta["length_s"] == pytest.approx(wav.frames / wav.samplerate, abs=1e-3)
        assert meta["models"]["unet"] == "acestep_v1.5_turbo.safetensors"
        assert meta["workflow"] == "ace_music" and meta["comfy_prompt_id"] in e.fake.prompts
        if HAVE_FFMPEG:
            assert sf.info(str(files["loop_ogg"])).format == "OGG"
    assert len(e.db.get_job(job.id).timings["candidates"]) == 2


async def test_bgm_without_loop(env):
    e = await env()
    job = bgm_job(e, seconds=30, count=1, seed=1, loop=False)
    await run_bgm_job(e.ctx, job)
    [asset] = e.db.list_assets(job_id=job.id)
    assert "full_wav" in asset.files and "loop" not in asset.meta
    assert e.fake.graphs[0]["94"]["inputs"]["lyrics"] == "[Instrumental]"
    assert sf.info(str(bgm_files(e, asset)["full_wav"])).duration == pytest.approx(26.0, abs=0.06)


async def test_bgm_too_few_bars_keeps_the_whole_song(env):
    e = await env(audio_seconds=12)  # 8 s of music at 100 BPM: 3 bars
    job = bgm_job(e, seconds=30, count=1, seed=1)
    await run_bgm_job(e.ctx, job)
    [asset] = e.db.list_assets(job_id=job.id)
    assert "full_wav" in asset.files and "loop_wav" not in asset.files
    assert "whole bars" in asset.meta["loop_error"]


async def test_bgm_without_ffmpeg_keeps_the_wav(env, tmp_path):
    e = await env(ffmpeg=str(tmp_path / "no-ffmpeg.exe"))
    job = bgm_job(e, seconds=30, count=1, seed=1)
    await run_bgm_job(e.ctx, job)
    [asset] = e.db.list_assets(job_id=job.id)
    assert set(asset.files) == {"raw", "loop_wav"}
    assert "ffmpeg not found" in asset.meta["ogg_error"]


async def test_bgm_vocal_song(env):
    e = await env()
    with pytest.raises(ValueError, match="needs lyrics"):
        await run_bgm_job(e.ctx, bgm_job(e, "yue2", vocal=True, lyrics="  ", seconds=30, count=1, seed=1))
    lyrics = "[Verse]\n창가에 스친 빗소리"
    job = bgm_job(e, "yue2", vocal=True, lyrics=lyrics, seconds=40, count=1, seed=3, loop=False)
    await run_bgm_job(e.ctx, job)
    graph = e.fake.graphs[-1]
    assert graph["25"]["inputs"]["style"] == "cozy village theme, flute, 100 BPM"
    assert graph["25"]["inputs"]["lyrics"] == lyrics and graph["25"]["inputs"]["max_duration"] == 40.0
    [asset] = e.db.list_assets(job_id=job.id)
    assert (asset.meta["workflow"], asset.meta["vocal"], asset.meta["lyrics"]) == ("yue2_song", True, lyrics)
    assert "full_wav" in asset.files


# --- animations (tests/fake_spritegen.py stands in for sprite-gen and codex) --------------------------------------

SHADOW = (40, 40, 70)


@pytest.fixture
def spritegen_log(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "spritegen-calls.jsonl"
    monkeypatch.setenv("FAKE_SPRITEGEN_LOG", str(path))
    for var in ("FAKE_SPRITEGEN_FAIL", "FAKE_SPRITEGEN_SLOW", "FAKE_SPRITEGEN_HEIGHTS"):
        monkeypatch.delenv(var, raising=False)
    return path


def spritegen_calls(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def animation_project(e, cloud: bool = True) -> None:
    keeper = np.zeros((32, 32, 4), np.uint8)
    keeper[3:29, 7:25] = (60, 70, 90, 255)  # stands on row 28, like the LAST LIGHT keeper
    reference = store_reference(e.settings, "demo", Image.fromarray(keeper, "RGBA"))
    e.db.update_project(
        "demo",
        pixel_art=True,
        logical_width=32,
        logical_height=32,
        max_colors=12,
        reference_image=reference,
        animation_cloud=cloud,
    )


def sprite_asset(e, kind: str = "sprite", description: str = "a creeping shadow creature"):
    """A finished 32x32 sprite candidate: a 17x26 creature with an outline and two eyes, feet on row 28."""
    job = e.db.create_job(e.project.id, "image", "qwen", {"kind": kind, "description": description, "count": 1})
    asset_id = new_id()
    directory = asset_dir(e.settings, "demo", asset_id)
    creature = np.zeros((32, 32, 4), np.uint8)
    creature[3:29, 8:25] = (10, 10, 20, 255)
    creature[4:28, 9:24] = (*SHADOW, 255)
    creature[11, 12] = creature[11, 20] = (250, 230, 150, 255)
    Image.fromarray(creature, "RGBA").save(directory / "processed.png")
    files = {"processed": to_rel(e.settings, directory / "processed.png")}
    meta = {"description": description}
    return e.db.create_asset(job.id, e.project.id, kind, files=files, meta=meta, seed=1, asset_id=asset_id)


def animation_job(e, asset, **params):
    return e.db.create_job(e.project.id, "animation", "codex", {"asset_id": asset.id, "count": 1, **params})


async def test_animation(env, spritegen_log, tmp_path):
    e = await env()
    animation_project(e)
    base = sprite_asset(e)
    job = animation_job(e, base)
    await run_animation_job(e.ctx, job)

    [asset] = e.db.list_assets(job_id=job.id)
    assert (asset.kind, asset.status, asset.seed) == ("animation", "candidate", None)
    paths = {role: from_rel(e.settings, rel) for role, rel in asset.files.items()}
    assert set(paths) == {"row", "json", "preview", "gif", "base"}
    assert all(p.is_file() for p in paths.values())
    assert Image.open(paths["row"]).size == (320, 32)
    assert Image.open(paths["base"]).size == (32, 32)
    assert json.loads(paths["json"].read_text(encoding="utf-8"))["tags"][1] == {
        "name": "walk",
        "from": 4,
        "to": 9,
        "duration": 0.1,
    }
    frames = [np.asarray(Image.open(from_rel(e.settings, rel))) for rel in asset.meta["animation"]["files"]]
    assert len(frames) == 10
    for frame in frames:
        assert frame.shape == (32, 32, 4)
        assert set(np.unique(frame[..., 3])) <= {0, 255}
        ys, _ = np.nonzero(frame[..., 3])
        assert ys.max() == 28  # the project's feet row (from the reference)
        assert ys.max() - ys.min() + 1 == 26  # the base sprite's height, though the fake drew rows 34 and 38 tall

    meta = asset.meta
    assert (meta["description"], meta["base_asset"]) == ("a creeping shadow creature", base.id)
    assert meta["animation"]["frames"] == 10 and meta["animation"]["cell"] == [32, 32]
    assert meta["animation"]["max_colors"] == 12  # the gallery shows "colors used / max"
    assert meta["fit"]["size_ok"] is True and meta["fit"]["ground_row"] == 28
    assert meta["fit"]["rows"]["walk"]["native_height"] == 38
    assert meta["fit"]["colors_used"] <= 3  # the base sprite's colors
    assert meta["cloud"]["provider"] == "codex"
    assert meta["spritegen"]["engine_revision"] == "fake"
    assert any("physical cap" in w for w in meta["spritegen"]["warnings"]) is False  # the native run has room
    assert set(meta["timings"]) == {"prepare", "generate", "extract", "postprocess"}
    assert e.db.get_job(job.id).timings == {"candidates": [meta["timings"]]}

    calls = spritegen_calls(spritegen_log)
    assert [c["tool"] for c in calls] == ["prepare", "gen-set", "prepare", "extract", "compose-atlas", "inspect"]
    gen_prepare, genset, native_prepare = calls[0], calls[1], calls[2]
    assert gen_prepare["args"][gen_prepare["args"].index("--cell-width") + 1] == "32"
    assert native_prepare["args"][native_prepare["args"].index("--cell-width") + 1] == "64"
    assert genset["args"][genset["args"].index("--provider") + 1] == "codex"
    assert genset["path"].startswith(str(tmp_path / "codex-app"))  # the configured codex comes first on PATH
    description = gen_prepare["args"][gen_prepare["args"].index("--description") + 1]
    assert description == "a creeping shadow creature"
    sent = Image.open(gen_prepare["args"][gen_prepare["args"].index("--base-image") + 1])
    assert sent.size == (1024, 1024)  # the base sprite, enlarged 32x


async def test_animation_needs_the_cloud_setting(env, spritegen_log):
    e = await env()
    animation_project(e, cloud=False)
    job = animation_job(e, sprite_asset(e))
    with pytest.raises(ValueError, match="animation is not allowed for this project: demo has animation_cloud off"):
        await run_animation_job(e.ctx, job)
    assert spritegen_calls(spritegen_log) == []  # nothing ran, nothing was sent
    assert e.db.list_assets(job_id=job.id) == []


async def test_animation_of_something_else(env, spritegen_log):
    e = await env()
    animation_project(e)
    with pytest.raises(ValueError, match="is not a sprite of project demo"):
        await run_animation_job(e.ctx, animation_job(e, sprite_asset(e, kind="icon")))
    e.db.update_project("demo", pixel_art=False)
    with pytest.raises(ValueError, match="demo is not pixel art"):
        await run_animation_job(e.ctx, animation_job(e, sprite_asset(e)))
    assert spritegen_calls(spritegen_log) == []


async def test_animation_spritegen_failure(env, spritegen_log, monkeypatch):
    e = await env()
    animation_project(e)
    monkeypatch.setenv("FAKE_SPRITEGEN_FAIL", "gen-set")
    job = animation_job(e, sprite_asset(e))
    with pytest.raises(SpriteGenError, match="codex: not logged in"):
        await run_animation_job(e.ctx, job)
    assert e.db.list_assets(job_id=job.id) == []
    assert [c["tool"] for c in spritegen_calls(spritegen_log)] == ["prepare", "gen-set"]


async def test_animation_two_candidates(env, spritegen_log):
    e = await env()
    animation_project(e)
    job = animation_job(e, sprite_asset(e), count=2)
    await run_animation_job(e.ctx, job)
    assets = e.db.list_assets(job_id=job.id)
    assert len(assets) == 2 and assets[0].files["row"] != assets[1].files["row"]
    assert [c["tool"] for c in spritegen_calls(spritegen_log)].count("gen-set") == 2
