"""Runs sprite-gen's CLI, one stage per call, in its own virtual environment.

sprite-gen is never imported: its CLI and run folder are the contract (its docs/run-contract.md). Every stage but
gen-set prints one JSON object last on stdout; gen-set prints a table and writes reports/gen-set/set.report.json.
Only the keys this app needs are read (ok, errors, warnings; gen-set's failed and items).
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings, find_codex_dir

log = logging.getLogger(__name__)

KILL_WAIT = 10.0  # seconds to wait for a killed stage to exit
TAIL = 1500  # characters of output quoted in an error


class SpriteGenError(RuntimeError):
    """A sprite-gen stage failed. `report` is the JSON it printed (or gen-set's report file), if any."""

    def __init__(self, message: str, report: dict | None = None):
        super().__init__(message)
        self.report = report


def last_json(text: str) -> dict | None:
    """The last JSON object in a stage's stdout: pretty-printed, so it starts on a line of its own with '{'."""
    end = len(text)
    while (start := text.rfind("{", 0, end)) >= 0:
        if start == 0 or text[start - 1] == "\n":
            try:
                value = json.loads(text[start:])
            except ValueError:
                pass
            else:
                return value if isinstance(value, dict) else None
        end = start
    return None


def _tail(*texts: str) -> str:
    text = "\n".join(t.strip() for t in texts if t and t.strip())
    return text[-TAIL:] if text else "no output"


@dataclass
class SpriteGen:
    cmd: list[str]  # the sprite-gen program (tests: [python, fake_spritegen.py])
    codex_dir: Path | None = None  # put first on PATH, so sprite-gen finds this codex CLI (config.find_codex_dir)
    timeout: float = 900  # seconds per stage; the job has its own limit too

    @classmethod
    def from_settings(cls, settings: Settings) -> "SpriteGen":
        program = settings.sprite_gen
        cmd = [sys.executable, program] if program.endswith(".py") else [program]  # a .py (tests' fake): this Python
        return cls(cmd, find_codex_dir(settings), settings.animation_timeout)

    def env(self) -> dict[str, str]:
        # sprite-gen prints Korean and dashes, which the Windows console code page (cp949) cannot encode.
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        if self.codex_dir is not None:
            env["PATH"] = f"{self.codex_dir}{os.pathsep}{env.get('PATH', '')}"
        return env

    def version(self) -> str | None:
        """The installed sprite-gen version, from its virtual environment's package metadata."""
        site = Path(self.cmd[0]).resolve().parents[1] / "Lib" / "site-packages"
        found = sorted(site.glob("sprite_gen-*.dist-info"))
        return found[-1].name.removeprefix("sprite_gen-").removesuffix(".dist-info") if found else None

    async def _exec(self, tool: str, *args: str) -> tuple[int, str, str]:
        # No console window: the backend runs detached, and a console program started from it would open one.
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.cmd,
                tool,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env(),
                creationflags=flags,
            )
        except OSError as e:
            raise SpriteGenError(
                f"cannot run sprite-gen ({self.cmd[0]}): {e}; install it or set AIAS_SPRITE_GEN"
            ) from e
        try:
            out, err = await asyncio.wait_for(proc.communicate(), self.timeout)
        except TimeoutError:
            await _kill(proc)
            raise SpriteGenError(f"sprite-gen {tool} took longer than {self.timeout:g} s") from None
        except BaseException:  # the job was cancelled: never leave sprite-gen (and its codex calls) running
            await _kill(proc)
            raise
        return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    async def run(self, tool: str, *args: str) -> dict:
        """Run a stage that prints a JSON report; the report. SpriteGenError if it fails or prints none."""
        code, out, err = await self._exec(tool, *args)
        report = last_json(out)
        if code != 0 or report is None or report.get("ok") is not True:
            errors = (report or {}).get("errors") or [_tail(out, err)]
            raise SpriteGenError(f"sprite-gen {tool} failed (exit {code}): {'; '.join(map(str, errors))}", report)
        return report

    async def prepare(
        self,
        run_dir: Path,
        base: Path,
        cell: tuple[int, int],
        palette_size: int,
        description: str,
        states: dict[str, dict],
        character_id: str = "sprite",
        safe_margin: int | None = None,
    ) -> dict:
        """A new run folder: pixel art in `cell` (w, h) cells, feet `safe_margin` rows above the bottom (None:
        sprite-gen's default, 9.4% of the cell)."""
        run_dir.mkdir(parents=True, exist_ok=True)
        request = run_dir.with_name(f"{run_dir.name}-request.json")
        request.write_text(json.dumps({"states": states}, ensure_ascii=False), encoding="utf-8")
        margin = ("--safe-margin", str(safe_margin)) if safe_margin is not None else ()
        return await self.run(
            "prepare",
            *("--out-dir", str(run_dir), "--character-id", character_id, "--base-image", str(base)),
            *("--description", description, "--cell-width", str(cell[0]), "--cell-height", str(cell[1]), *margin),
            *("--fit-pixel-unfake", "--fit-palette-size", str(palette_size), "--fit-align-x", "foot-centroid"),
            *("--fit-align-y", "bottom", "--fit-ground-frames", "--request", str(request), "--force"),
        )

    async def gen_set(self, run_dir: Path, concurrency: int = 2) -> dict:
        """Every state row, through the codex CLI (this sends the base image, layout guides and prompts to OpenAI)."""
        report_path = run_dir / "reports" / "gen-set" / "set.report.json"
        report_path.unlink(missing_ok=True)  # only this run's report counts
        code, out, err = await self._exec(
            "gen-set", "--run-dir", str(run_dir), "--provider", "codex", "--concurrency", str(concurrency)
        )
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else None
        if code != 0 or report is None or report.get("failed") or report.get("not_started"):
            errors = [f"{i.get('state')}: {i.get('error')}" for i in (report or {}).get("items", []) if not i.get("ok")]
            errors += [f"not started: {s}" for s in (report or {}).get("not_started", [])]
            raise SpriteGenError(
                f"sprite-gen gen-set failed (exit {code}): {'; '.join(errors) or _tail(out, err)}", report
            )
        return report

    async def extract(self, run_dir: Path) -> dict:
        return await self.run("extract", "--run-dir", str(run_dir))

    async def compose(self, run_dir: Path) -> dict:
        return await self.run("compose-atlas", "--run-dir", str(run_dir))

    async def inspect(self, run_dir: Path) -> dict:
        """sprite-gen's frame-count, identity and motion check. Advisory: a failed check is returned, not raised."""
        code, out, err = await self._exec("inspect", "--run-dir", str(run_dir))
        return last_json(out) or {
            "ok": False,
            "errors": [f"inspect printed no report (exit {code}): {_tail(out, err)}"],
        }


async def _kill(proc: asyncio.subprocess.Process) -> None:
    """Stop a stage and everything it started (gen-set runs codex processes of its own)."""
    if proc.returncode is not None:
        return
    if sys.platform == "win32":
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/T", "/F", "/PID", str(proc.pid),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )  # fmt: skip
        await killer.wait()
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(proc.wait(), KILL_WAIT)
    except TimeoutError:
        log.warning("sprite-gen (pid %d) did not exit within %g s of being killed", proc.pid, KILL_WAIT)
