import json
from pathlib import Path

from conftest import make_project, run_animation_job, run_image_job
from PIL import Image


def test_export_to_project_folder(client, tmp_path):
    export_dir = tmp_path / "game" / "Art"  # does not exist yet
    make_project(client, export_dir=str(export_dir))
    [asset] = run_image_job(client)["assets"]

    r = client.post(f"/api/assets/{asset['id']}/export", json={})
    assert r.status_code == 200, r.text
    [path] = r.json()["paths"]
    assert Path(path) == export_dir / f"sprite_demo_{asset['id']}.png"
    assert Path(path).read_bytes() == client.get(asset["files"]["processed"]).content

    exports = client.get(f"/api/assets/{asset['id']}").json()["meta"]["exports"]
    assert [e["path"] for e in exports] == [path]


def test_export_dest_dir_name_and_no_overwrite(client, tmp_path):
    make_project(client)
    [asset] = run_image_job(client)["assets"]
    dest = tmp_path / "elsewhere"
    body = {"dest_dir": str(dest), "name": "Hero Sword!"}

    first = client.post(f"/api/assets/{asset['id']}/export", json=body).json()["paths"]
    second = client.post(f"/api/assets/{asset['id']}/export", json=body).json()["paths"]
    third = client.post(f"/api/assets/{asset['id']}/export", json=body | {"name": "!!!"}).json()["paths"]
    assert [Path(p).name for p in first + second] == ["herosword.png", "herosword_2.png"]
    assert Path(third[0]).name == f"sprite_demo_{asset['id']}.png"  # nothing usable left in the name
    assert len(client.get(f"/api/assets/{asset['id']}").json()["meta"]["exports"]) == 3


def test_export_errors(client):
    make_project(client)
    [asset] = run_image_job(client)["assets"]
    url = f"/api/assets/{asset['id']}/export"
    r = client.post(url, json={})
    assert r.status_code == 400 and "no export directory" in r.json()["detail"]
    assert client.post(url, json={"dest_dir": "relative/dir"}).status_code == 422
    assert client.post("/api/assets/nope/export", json={}).status_code == 404


def test_export_animation_the_games_way(animation_client, tmp_path):
    [asset] = run_animation_job(animation_client)["assets"]
    dest = tmp_path / "Game" / "CampaignArt"
    body = {"dest_dir": str(dest), "name": "shadow_walker"}
    r = animation_client.post(f"/api/assets/{asset['id']}/export", json=body)
    assert r.status_code == 200, r.text
    assert [Path(p) for p in r.json()["paths"]] == [
        dest / "shadow_walker.png",
        dest / "shadow_walker.json",
        dest / "shadow_walker",
    ]
    assert Image.open(dest / "shadow_walker.png").size == (320, 32)
    frames = sorted(p.name for p in (dest / "shadow_walker").iterdir())
    assert frames == [f"{i:03d}.png" for i in range(10)]
    assert all(Image.open(dest / "shadow_walker" / name).size == (32, 32) for name in frames)
    info = json.loads((dest / "shadow_walker.json").read_text(encoding="utf-8"))
    assert (info["name"], info["image"], info["frames"]) == ("shadow_walker", "shadow_walker.png", 10)
    assert [t["name"] for t in info["tags"]] == ["idle", "walk"]
    assert len(list(dest.rglob("*.png"))) + len(list(dest.rglob("*.json"))) == 12  # PNG 11 + JSON 1

    again = animation_client.post(f"/api/assets/{asset['id']}/export", json=body).json()["paths"]
    assert [Path(p).name for p in again] == ["shadow_walker_2.png", "shadow_walker_2.json", "shadow_walker_2"]
    assert json.loads(Path(again[1]).read_text(encoding="utf-8"))["image"] == "shadow_walker_2.png"
    (dest / "only_a_folder").mkdir()  # a taken name is taken whichever of the three it is
    third = animation_client.post(f"/api/assets/{asset['id']}/export", json=body | {"name": "only_a_folder"})
    assert Path(third.json()["paths"][0]).name == "only_a_folder_2.png"
    exports = animation_client.get(f"/api/assets/{asset['id']}").json()["meta"]["exports"]
    assert len(exports) == 9
