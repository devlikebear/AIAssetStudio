"""Command line: `serve` runs the backend, `setup` prepares and starts Studio, `doctor` and `check` look at this PC,
`pack` installs feature packs through the backend. Nothing here can agree to a license: a person does that in the
gallery.
"""

import argparse
import asyncio
import dataclasses
import json
import logging
import sys
from pathlib import Path

from .config import Settings, is_loopback, load_settings

EXIT_CONSENT_REQUIRED = 3


def _settings(host: str | None, port: int | None, data_dir: str | None) -> Settings:
    overrides = {"host": host, "port": port, "data_dir": Path(data_dir) if data_dir else None}
    return dataclasses.replace(load_settings(), **{k: v for k, v in overrides.items() if v is not None})


def _gallery_url(settings: Settings) -> str:
    return f"http://{settings.host}:{settings.port}/"


def _serve(settings: Settings) -> int:
    import uvicorn

    from .api.app import create_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per ComfyUI /history poll otherwise
    if not is_loopback(settings.host):
        logging.getLogger(__name__).warning(
            "listening on %s: the API has no login, so anyone who can reach this address can read images on this PC "
            "(reference_image) and write files anywhere it can (export). Use 127.0.0.1 unless you trust the network.",
            settings.host,
        )
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")
    return 0


async def _ensure_backend(settings: Settings) -> None:
    """Start the backend if it is not running, the way the MCP server does."""
    from .mcp_bridge.studio_api import StudioApi

    api = StudioApi.from_settings(settings)
    try:
        await api.ensure_backend()
    finally:
        await api.aclose()


def _serve_detached(settings: Settings) -> int:
    from .mcp_bridge.studio_api import BackendError

    try:
        asyncio.run(_ensure_backend(settings))
    except BackendError as e:
        print(e, file=sys.stderr)
        return 1
    print(_gallery_url(settings))
    return 0


def _doctor(as_json: bool) -> int:
    from .doctor import failed, run_checks

    checks = run_checks(load_settings())
    code = 1 if failed(checks) else 0
    if as_json:
        print(json.dumps({"ok": code == 0, "checks": checks}, ensure_ascii=False, indent=2))
        return code
    for check in checks:
        print(f"{check['status']:<5} {check['id']}: {check['detail']}")
        if check["fix"]:
            print(f"      {check['fix']}")
    return code


def _setup(as_json: bool) -> int:
    """Make Studio ready to use. Safe to run again, and it downloads nothing."""
    from .mcp_bridge.studio_api import BackendError
    from .store.db import Database
    from .store.files import db_path

    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(db_path(settings))  # opening it brings the schema up to date
    schema = db.schema_version()
    db.close()
    report = {
        "data_dir": str(settings.data_dir),
        "schema_version": schema,
        "comfy_dir": str(settings.comfy_dir),
        "comfy_found": (settings.comfy_dir / "main.py").is_file(),
        "gallery_url": _gallery_url(settings),
    }
    try:
        asyncio.run(_ensure_backend(settings))
    except BackendError as e:
        report["backend_error"] = str(e)
    report["backend"] = "backend_error" not in report
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"data: {report['data_dir']} (schema {schema})")
        print(f"ComfyUI: {report['comfy_dir'] if report['comfy_found'] else 'not found; set AIAS_COMFY_DIR'}")
        print(f"gallery: {report['gallery_url']}" if report["backend"] else f"backend: {report['backend_error']}")
    return 0 if report["backend"] else 1


def _pack_lines(pack: dict) -> list[str]:
    state = pack["status"] + (f" ({pack['stage']})" if pack["stage"] else "")
    lines = [f"{pack['id']}: {state}"]
    if pack["error"]:
        lines.append(f"  {pack['error']}")
    return lines


async def _pack(args: argparse.Namespace) -> int:
    from .mcp_bridge.studio_api import BackendError, StudioApi

    settings = load_settings()
    api = StudioApi.from_settings(settings, client="cli")
    calls = {
        "status": api.get_pack,
        "install": api.install_pack,
        "cancel": api.cancel_pack,
        "remove": api.remove_pack,
    }
    try:
        await api.ensure_backend()
        result = await api.list_packs() if args.action == "list" else await calls[args.action](args.id)
    except BackendError as e:
        if e.detail.get("code") != "consent_required":
            print(e, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(e.detail, ensure_ascii=False))
        else:
            print(f"{e.detail['message']}\nA person agrees to it in the gallery: {e.detail['gallery_url']}")
        return EXIT_CONSENT_REQUIRED
    finally:
        await api.aclose()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for pack in result if isinstance(result, list) else [result]:
            print("\n".join(_pack_lines(pack)))
    return 0


async def _check() -> int:
    from .comfy import preflight
    from .comfy.client import ComfyClient

    settings = load_settings()
    client = ComfyClient(settings.comfy_url)
    try:
        if await client.is_up():
            version = (await client.system_stats()).get("system", {}).get("comfyui_version", "?")
            print(f"ComfyUI: up ({settings.comfy_url}, version {version})")
            if version != preflight.VERIFIED_COMFYUI:
                print(f"  note: the API graphs were verified on ComfyUI {preflight.VERIFIED_COMFYUI}")
        else:
            print(f"ComfyUI: down ({settings.comfy_url})")
        results = await preflight.check(client)
    finally:
        await client.aclose()

    all_ok = True
    for family, status in results.items():
        if status.ok:
            print(f"{family}: ok")
            continue
        all_ok = False
        print(f"{family}: not ready" + (f" ({status.reason})" if status.reason else ""))
        for node in status.missing_nodes:
            print(f"  missing node:  {node}")
        for model in status.missing_models:
            print(f"  missing model: {model}")
    return 0 if all_ok else 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="aiassetstudio", description="Local game asset studio backend")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the backend (HTTP API + job queue)")
    serve.add_argument("--host", help="bind address (default AIAS_HOST or 127.0.0.1; the API has no login)")
    serve.add_argument("--port", type=int, help="port (default AIAS_PORT or 8765)")
    serve.add_argument("--data-dir", help="data folder (default AIAS_DATA_DIR or <repo>/data)")
    serve.add_argument("--detach", action="store_true", help="run it in the background; if it already runs, leave it")
    sub.add_parser("check", help="check ComfyUI and the nodes/models each model family needs")
    doctor = sub.add_parser("doctor", help="check this PC against what Studio was tested on")
    doctor.add_argument("--json", action="store_true")
    setup = sub.add_parser("setup", help="prepare the data folder and start the backend; downloads nothing")
    setup.add_argument("--json", action="store_true")
    pack = sub.add_parser("pack", help="list, install or remove feature packs through the backend")
    actions = pack.add_subparsers(dest="action", required=True)
    actions.add_parser("list").add_argument("--json", action="store_true")
    for action, about in (
        ("status", "show one pack and its progress"),
        ("install", "start installing and return at once; a person must have agreed in the gallery"),
        ("cancel", "stop an install"),
        ("remove", "delete what the install put down"),
    ):
        command = actions.add_parser(action, help=about)
        command.add_argument("id")
        command.add_argument("--json", action="store_true")
    sub.add_parser("mcp", help="run the MCP server on stdio (started by Claude Code)")
    args = parser.parse_args(argv)

    if args.command == "serve":
        settings = _settings(args.host, args.port, args.data_dir)
        sys.exit(_serve_detached(settings) if args.detach else _serve(settings))
    if args.command == "mcp":
        from .mcp_bridge.server import main as mcp_main

        mcp_main()
        return
    if args.command == "doctor":
        sys.exit(_doctor(args.json))
    if args.command == "setup":
        sys.exit(_setup(args.json))
    if args.command == "pack":
        sys.exit(asyncio.run(_pack(args)))
    sys.exit(asyncio.run(_check()))
