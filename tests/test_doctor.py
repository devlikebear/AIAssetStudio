import json

import pytest

from aiassetstudio import doctor
from aiassetstudio.cli import main
from aiassetstudio.config import Settings

KEYS = {"id", "status", "detail", "fix"}
GOOD_GPU = ("NVIDIA GeForce RTX 4090 Laptop GPU", "621.01", 16376)


@pytest.fixture
def healthy(monkeypatch):
    monkeypatch.setattr(doctor, "nvidia_gpu", lambda: GOOD_GPU)
    monkeypatch.setattr(doctor, "ram_gb", lambda: 31.7)
    monkeypatch.setattr(doctor, "program", lambda name: f"C:/bin/{name}.exe")
    monkeypatch.setattr(doctor, "comfy_version", lambda url: "0.37.0")
    monkeypatch.setattr(doctor, "backend_up", lambda url: True)
    monkeypatch.setattr(doctor, "port_taken", lambda host, port: port in (8765, 8188))


def by_id(checks: list[dict]) -> dict[str, dict]:
    return {c["id"]: c for c in checks}


def settings(tmp_path, **changes) -> Settings:
    font = tmp_path / "font.ttf"
    font.write_bytes(b"x")
    return Settings(data_dir=tmp_path / "data", comfy_dir=tmp_path / "ComfyUI", book_font=str(font), **changes)


def test_a_healthy_pc_passes(healthy, tmp_path):
    checks = doctor.run_checks(settings(tmp_path))
    assert doctor.failed(checks) == []
    assert all(set(c) == KEYS for c in checks)
    assert {"os", "gpu", "vram", "ram", "disk", "uv", "ffmpeg", "comfyui", "backend", "font"} <= by_id(checks).keys()
    assert {"port_8765", "port_8188", "port_8766"} <= by_id(checks).keys()
    assert by_id(checks)["vram"]["status"] == "ok"
    assert by_id(checks)["ram"]["status"] == "ok"


def test_no_nvidia_gpu_is_fatal(healthy, monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "nvidia_gpu", lambda: None)
    checks = by_id(doctor.run_checks(settings(tmp_path)))
    assert checks["gpu"]["status"] == "fail"
    assert checks["gpu"]["fix"]


def test_less_than_the_tested_memory_is_a_warning(healthy, monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "nvidia_gpu", lambda: ("small", "1", 8192))
    monkeypatch.setattr(doctor, "ram_gb", lambda: 15.9)
    checks = by_id(doctor.run_checks(settings(tmp_path)))
    assert (checks["vram"]["status"], checks["ram"]["status"]) == ("warn", "warn")


@pytest.mark.parametrize("name", ["uv", "ffmpeg"])
def test_a_missing_program_is_fatal_and_says_how_to_get_it(healthy, monkeypatch, tmp_path, name):
    monkeypatch.setattr(doctor, "program", lambda n: None if n == name else "x")
    check = by_id(doctor.run_checks(settings(tmp_path)))[name]
    assert check["status"] == "fail"
    assert check["fix"]


def test_comfyui_on_another_version_is_a_warning(healthy, monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "comfy_version", lambda url: "0.40.0")
    check = by_id(doctor.run_checks(settings(tmp_path)))["comfyui"]
    assert check["status"] == "warn"
    assert "0.37.0" in check["detail"]


def test_comfyui_down_but_installed_is_fine(healthy, monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "comfy_version", lambda url: None)
    config = settings(tmp_path)
    assert by_id(doctor.run_checks(config))["comfyui"]["status"] == "warn"
    config.comfy_dir.mkdir()
    (config.comfy_dir / "main.py").write_text("")
    assert by_id(doctor.run_checks(config))["comfyui"]["status"] == "ok"


def test_a_port_another_program_holds_is_a_warning(healthy, monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "backend_up", lambda url: False)
    checks = by_id(doctor.run_checks(settings(tmp_path)))
    assert checks["port_8765"]["status"] == "warn"
    assert checks["port_8766"]["status"] == "ok"


def test_a_missing_font_is_a_warning(healthy, tmp_path):
    config = Settings(data_dir=tmp_path / "data", comfy_dir=tmp_path / "c", book_font=str(tmp_path / "none.ttf"))
    check = by_id(doctor.run_checks(config))["font"]
    assert check["status"] == "warn"
    assert "AIAS_BOOK_FONT" in check["fix"]


def test_little_free_disk_is_a_warning(healthy, monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "free_disk_gb", lambda path: 1.0)
    assert by_id(doctor.run_checks(settings(tmp_path)))["disk"]["status"] == "warn"


def run_cli(monkeypatch, tmp_path, *args) -> int:
    monkeypatch.setenv("AIAS_DATA_DIR", str(tmp_path / "data"))
    with pytest.raises(SystemExit) as e:
        main(["doctor", *args])
    return e.value.code


def test_doctor_json_has_fixed_keys(healthy, monkeypatch, tmp_path, capsys):
    assert run_cli(monkeypatch, tmp_path, "--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert all(set(c) == KEYS for c in report["checks"])


def test_doctor_is_the_same_twice_and_exits_1_on_a_failure(healthy, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor, "nvidia_gpu", lambda: None)
    assert run_cli(monkeypatch, tmp_path, "--json") == 1
    first = capsys.readouterr().out
    assert run_cli(monkeypatch, tmp_path, "--json") == 1
    assert capsys.readouterr().out == first
    assert not (tmp_path / "data").exists()


def test_doctor_prints_a_line_per_check(healthy, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor, "nvidia_gpu", lambda: None)
    run_cli(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert "fail  gpu" in out
    assert "ok    uv" in out
