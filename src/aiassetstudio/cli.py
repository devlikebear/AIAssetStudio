"""Command line: `aiassetstudio serve` runs the backend, `aiassetstudio check` checks ComfyUI."""

import argparse
import asyncio
import dataclasses
import logging
import sys
from pathlib import Path

from .config import is_loopback, load_settings

# The API graphs were verified on this ComfyUI version; node names can change on update.
VERIFIED_COMFYUI = "0.37.0"


def _serve(host: str | None, port: int | None, data_dir: str | None) -> int:
    import uvicorn

    from .api.app import create_app

    overrides = {"host": host, "port": port, "data_dir": Path(data_dir) if data_dir else None}
    settings = dataclasses.replace(load_settings(), **{k: v for k, v in overrides.items() if v is not None})
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


async def _check() -> int:
    from .comfy import preflight
    from .comfy.client import ComfyClient

    settings = load_settings()
    client = ComfyClient(settings.comfy_url)
    try:
        if await client.is_up():
            version = (await client.system_stats()).get("system", {}).get("comfyui_version", "?")
            print(f"ComfyUI: up ({settings.comfy_url}, version {version})")
            if version != VERIFIED_COMFYUI:
                print(f"  note: the API graphs were verified on ComfyUI {VERIFIED_COMFYUI}")
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
    sub.add_parser("check", help="check ComfyUI and the nodes/models each model family needs")
    sub.add_parser("mcp", help="run the MCP server on stdio (started by Claude Code)")
    args = parser.parse_args(argv)

    if args.command == "serve":
        sys.exit(_serve(args.host, args.port, args.data_dir))
    if args.command == "mcp":
        from .mcp_bridge.server import main as mcp_main

        mcp_main()
        return
    sys.exit(asyncio.run(_check()))
