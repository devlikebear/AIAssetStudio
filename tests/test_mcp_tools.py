import io
from pathlib import Path

import httpx
import pytest
from conftest import ANIMATION_SPEC
from mcp.server.mcpserver.utilities.types import Image
from PIL import Image as PILImage

from aiassetstudio.api.app import create_app
from aiassetstudio.mcp_bridge import server, tools
from aiassetstudio.mcp_bridge.studio_api import BackendError, StudioApi


async def _api(settings, fake_comfy):
    app = create_app(settings, comfy_transport=fake_comfy.transport)
    async with app.router.lifespan_context(app):
        client = StudioApi("http://127.0.0.1:8765", transport=httpx.ASGITransport(app=app))
        yield client
        await client.aclose()


@pytest.fixture
async def api(settings, fake_comfy):
    async for client in _api(settings, fake_comfy):
        yield client


@pytest.fixture
async def animation_api(animation_settings, fake_comfy):
    async for client in _api(animation_settings, fake_comfy):
        yield client


async def test_generate_view_pick_export(api, tmp_path):
    export_dir = tmp_path / "game" / "Icons"
    text = await tools.create_project(api, "demo", "Demo", "cute chibi fantasy", str(export_dir))
    assert "export_dir: " + str(export_dir) in text
    assert "demo: Demo" in await tools.list_projects(api)

    queued = await tools.generate_image(api, "demo", "icon", "a steel sword", count=2)
    job_id = queued.split()[2]
    assert f"get_job(job_id='{job_id}'" in queued

    result = await tools.get_job(api, job_id, wait_seconds=10)
    images = [item for item in result if isinstance(item, Image)]
    assert len(images) == 2
    assert all(img.to_image_content().mime_type == "image/png" for img in images)
    assert "-> done" in result[0]
    assert result[-1] == f"Gallery: http://127.0.0.1:8765/#/jobs/{job_id}"
    asset_ids = [item.split()[1] for item in result if isinstance(item, str) and item.startswith("asset ")]
    assert len(asset_ids) == 2

    assert await tools.set_asset_status(api, asset_ids[0], "selected") == f"asset {asset_ids[0]} is now selected"
    assert asset_ids[0] in await tools.list_assets(api, "demo", status="selected")

    first = await tools.export_asset(api, asset_ids[0], name="sword")
    second = await tools.export_asset(api, asset_ids[0], name="sword")
    assert Path(first.splitlines()[1]) == export_dir / "sword.png"
    assert Path(second.splitlines()[1]) == export_dir / "sword_2.png"

    assert "already finished" in await tools.cancel_job(api, job_id)
    status = await tools.studio_status(api)
    assert "image models (Qwen-Image-2.1): ready" in status
    assert "gallery: http://127.0.0.1:8765/" in status
    assert "animation (sprite-gen + codex, cloud): not ready (sprite-gen not found at " in status


async def test_project_spec_and_reference(api, tmp_path):
    reference = tmp_path / "keeper.png"
    PILImage.new("RGBA", (32, 32), (10, 20, 30, 255)).save(reference)
    spec = {"pixel_art": True, "logical_width": 32, "logical_height": 32, "max_colors": 12}
    text = await tools.create_project(api, "px", "Pixel", **spec, reference_image=str(reference))
    assert "pixel art: sprites 32x32, icons 32x32, at most 12 colors" in text
    assert "reference image: projects/px/reference/" in text

    text = await tools.update_project(api, "px", icon_size=16, palette=["#000000", "#FFFFFF"])
    assert "icons 16x16" in text
    assert "palette: #000000 #ffffff" in text
    # False must stay False (False == 0 in Python), while 0, [] and "" clear their fields.
    text = await tools.update_project(api, "px", pixel_art=False, icon_size=0, palette=[], reference_image="")
    assert "pixel art: no" in text
    assert "icon size" not in text and "palette" not in text
    assert "reference image: (none)" in text
    assert "Nothing to change" in await tools.update_project(api, "px")
    with pytest.raises(BackendError, match="needs logical_width"):
        await tools.update_project(api, "px", pixel_art=True, logical_width=0)


async def test_project_animation_cloud(api):
    text = await tools.create_project(api, "px", "Pixel")
    assert "animation: off (update_project animation_cloud=true to allow; it sends sprites to OpenAI)" in text
    text = await tools.update_project(api, "px", animation_cloud=True)
    assert "animation: allowed (sends sprites to OpenAI via codex)" in text
    assert "animation: allowed" in await tools.get_project(api, "px")
    # False must turn it off, not count as "clear" (False == 0 in Python).
    assert "animation: off" in await tools.update_project(api, "px", animation_cloud=False)
    text = await tools.create_project(api, "cloud", "Cloud", animation_cloud=True)
    assert "animation: allowed" in text


async def test_pixel_candidates_say_how_they_were_fitted(api):
    spec = {"pixel_art": True, "logical_width": 32, "logical_height": 32, "max_colors": 12}
    await tools.create_project(api, "px", "Pixel", **spec)
    job_id = (await tools.generate_image(api, "px", "sprite", "a slime", count=1)).split()[2]
    result = await tools.get_job(api, job_id, wait_seconds=10)
    [line] = [item for item in result if isinstance(item, str) and item.startswith("asset ")]
    # FakeComfy draws a plain square: no block grid
    assert line.endswith(", pixel art: stretched to fit (no grid), pixels may differ in size")
    native = {"fit": "native", "scale": 1, "cell_px": [32.0, 32.0], "native_size": [18, 26]}
    assert tools._pixel_note({"pixel": {"fit": native}}) == ", pixel art: the model's own 18x26 pixels at 1x"
    assert tools._pixel_note({}) == ""


async def test_cancel_running(api, fake_comfy):
    await tools.create_project(api, "demo", "Demo")
    fake_comfy.fail_with = "hang"
    job_id = (await tools.generate_image(api, "demo", "sprite", "a slime")).split()[2]
    running = await tools.get_job(api, job_id, wait_seconds=1)
    assert "Still in progress" in running[1]
    assert "-> cancelled" in await tools.cancel_job(api, job_id)


async def test_server_registers_every_tool():
    listed = {t.name: t for t in await server.mcp.list_tools()}
    assert set(listed) == {
        "studio_status",
        "list_projects",
        "get_project",
        "create_project",
        "update_project",
        "generate_image",
        "generate_bgm",
        "generate_animation",
        "get_job",
        "list_assets",
        "set_asset_status",
        "export_asset",
        "cancel_job",
        "create_book",
        "get_book",
        "set_book_pages",
        "set_book_sheets",
        "set_book_terms",
        "set_book_cover",
        "generate_sheet",
        "generate_pages",
        "set_page",
        "check_book_sources",
        "export_book",
        "generate_narration",
        "list_packs",
    }
    reference = listed["update_project"].input_schema["properties"]["reference_image"]
    assert "must be an absolute path; it is copied into the studio" in reference["description"]
    kind = listed["generate_image"].input_schema["properties"]["kind"]
    assert kind["enum"] == ["sprite", "icon"]
    assert listed["get_job"].output_schema is None  # previews come back as image content, not JSON
    assert all(t.description for t in listed.values())


async def test_only_the_person_approves_a_page():
    listed = {t.name: t for t in await server.mcp.list_tools()}
    status = listed["set_page"].input_schema["properties"]["status"]
    assert "approved" not in str(status)


async def test_book_flow(api):
    await tools.create_project(api, "story", "Story", style="Ink wash.")
    created = await tools.create_book(api, "story", "A Book", {"label": "A Work"})
    book_id = created.splitlines()[1].split()[1]
    text = await tools.set_book_pages(
        api,
        book_id,
        [
            {
                "number": 1,
                "text": "Words.",
                "image_prompt": "A scene.",
                "source_refs": [{"node_id": "n1", "content_version": 2, "label": "Chapter 1"}],
            },
            {"number": 2, "text": "More.", "image_prompt": "Another."},
        ],
    )
    assert "rests on Chapter 1" in text
    assert "NO SOURCE RECORDED" in text
    await tools.set_book_terms(api, book_id, [{"term": "abc", "spoken": "a b c"}])

    queued = await tools.generate_pages(api, book_id)
    assert "Queued 2 pages" in queued
    job_ids = queued.split(": ", 1)[1].split(". ")[0].split(", ")
    for job_id in job_ids:
        await tools.get_job(api, job_id, wait_seconds=10)

    view = await tools.get_book(api, book_id)
    assert "0/2 pages approved" in view[0]
    assert "license of the chosen pictures: research_only" in view[0]
    assert f"/#/books/{book_id}" in view[0]
    assert sum(isinstance(item, tools.Image) for item in view) == 2

    pages = (await api.get_book(book_id))["pages"]
    sent_back = await tools.set_page(api, pages[0]["id"], status="redo", note="Darker, please.")
    assert "the person asks: Darker, please." in sent_back

    assert "Every page rests" in await tools.check_book_sources(api, book_id, {"n1": 2})
    assert "was version 2, now 3" in await tools.check_book_sources(api, book_id, {"n1": 3})
    with pytest.raises(BackendError, match="not approved"):
        await tools.export_book(api, book_id)


async def test_bgm_flow(api, tmp_path):
    await tools.create_project(api, "demo", "Demo", export_dir=str(tmp_path / "Music"))
    queued = await tools.generate_bgm(api, "demo", "cozy village theme", bpm=100, seconds=30, count=2, seed=1)
    job_id = queued.split()[2]
    assert "You cannot hear audio" in queued and f"#/jobs/{job_id}" in queued
    result = await tools.get_job(api, job_id, wait_seconds=20)
    assert "-> done" in result[0] and "2 x bgm: cozy village theme" in result[0]
    assert not any(isinstance(item, Image) for item in result)  # songs are text only
    songs = [item for item in result if isinstance(item, str) and item.startswith("asset ")]
    assert len(songs) == 2
    assert "instrumental, seamless loop of 10 bars at 100 BPM" in songs[0]
    assert "loop_wav: http://127.0.0.1:8765/api/assets/" in songs[0]
    assert result[-2].startswith("You cannot hear these.")
    asset_id = songs[0].split()[1]
    assert asset_id in await tools.list_assets(api, "demo", kind="bgm")
    exported = (await tools.export_asset(api, asset_id, name="village")).splitlines()[1:]
    assert {Path(p).name for p in exported} <= {"village.wav", "village.ogg"} and "village.wav" in {
        Path(p).name for p in exported
    }


async def test_bgm_tool_description():
    listed = {t.name: t for t in await server.mcp.list_tools()}
    assert "You cannot hear audio. After generating BGM, ask the user to listen in the gallery and pick one." in (
        " ".join(listed["generate_bgm"].description.split())
    )
    kinds = listed["list_assets"].input_schema["properties"]["kind"]["anyOf"][0]["enum"]
    assert kinds == ["sprite", "icon", "bgm", "animation", "page_image", "narration", "book_export"]


async def test_animation_tool_description():
    listed = {t.name: t for t in await server.mcp.list_tools()}
    text = " ".join(listed["generate_animation"].description.split())
    assert "Sends the sprite (enlarged), a layout guide and a prompt to OpenAI through the Codex CLI" in text
    assert "only projects with animation_cloud on" in text
    assert "animations (generate_animation) are the one exception" in " ".join(server.INSTRUCTIONS.split())


async def test_animation_flow(animation_api, tmp_path):
    await tools.create_project(animation_api, "anim", "Anim", **ANIMATION_SPEC)
    sprite_job = (await tools.generate_image(animation_api, "anim", "sprite", "a creeping shadow", count=1)).split()[2]
    result = await tools.get_job(animation_api, sprite_job, wait_seconds=10)
    sprite_id = next(item.split()[1] for item in result if isinstance(item, str) and item.startswith("asset "))

    with pytest.raises(BackendError, match="does not allow animations: they send its sprites to OpenAI"):
        await tools.generate_animation(animation_api, sprite_id)
    await tools.update_project(animation_api, "anim", animation_cloud=True)
    queued = await tools.generate_animation(animation_api, sprite_id)
    assert "sends the sprite (enlarged), a layout guide and a prompt to OpenAI" in queued
    job_id = queued.split()[2]

    result = await tools.get_job(animation_api, job_id, wait_seconds=30)
    assert "-> done" in result[0] and "1 x animation: a creeping shadow" in result[0]
    [text] = [item for item in result if isinstance(item, str) and item.startswith("asset ")]
    assert "animation, 10 frames of 32x32 (idle 4 at 0.18 s, walk 6 at 0.1 s)" in text
    assert f"of sprite {sprite_id}, made with codex (cloud)" in text
    assert "feet on row 30" in text  # no reference image: the 1-cell margin
    assert "size: idle " in text or "frames differ in size from the base sprite" in text
    [sheet] = [item for item in result if isinstance(item, Image)]
    assert PILImage.open(io.BytesIO(sheet.data)).width > 1000  # 10 frames at 4x
    assert any("export_asset(asset_id, name=...)" in item for item in result if isinstance(item, str))

    animation_id = text.split()[1]
    assert animation_id in await tools.list_assets(animation_api, "anim", kind="animation")
    exported = await tools.export_asset(animation_api, animation_id, str(tmp_path / "Game"), name="shadow_anim")
    assert exported.splitlines()[1:] == [
        str(tmp_path / "Game" / "shadow_anim.png"),
        str(tmp_path / "Game" / "shadow_anim.json"),
        str(tmp_path / "Game" / "shadow_anim"),
    ]


async def test_list_packs_says_who_must_act(api):
    text = await tools.list_packs(api)
    assert "speech-ko" in text
    assert "not_installed" in text
    assert "a person must agree to Apache License 2.0 in the gallery" in text
    assert "/#/packs/speech-ko" in text


async def test_the_server_has_no_tool_to_agree_or_install():
    listed = {t.name for t in await server.mcp.list_tools()}
    assert not {name for name in listed if "accept" in name or "install" in name or "remove" in name}


async def test_narrating_without_the_pack_says_where_to_go(api):
    await api.create_project("demo", "Demo")
    book = await api.create_book("demo", "t", None)
    await api.save_pages(book["id"], [{"number": 1, "text": "글"}])
    with pytest.raises(BackendError, match="/#/packs/speech-ko"):
        await tools.generate_narration(api, book["id"])
