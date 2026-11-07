"""Download one file to a `.part` beside its destination, resume it with Range, and keep it only if its sha256 matches."""

import asyncio
import hashlib
from collections.abc import Callable
from pathlib import Path

import httpx

CHUNK = 1 << 20


class DownloadError(RuntimeError):
    pass


class ChecksumError(DownloadError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


async def download(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    size: int,
    sha256: str,
    on_progress: Callable[[int], None] = lambda done: None,
) -> None:
    """Make `dest` the file of `size` bytes and `sha256`. A file already there is kept if it is right. A bad download
    deletes the `.part`: resuming from it could never give the right file."""
    if dest.is_file() and dest.stat().st_size == size and await asyncio.to_thread(file_sha256, dest) == sha256:
        on_progress(size)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(f"{dest.name}.part")
    if part.is_file() and part.stat().st_size > size:
        part.unlink()
    done = part.stat().st_size if part.is_file() else 0
    if done < size:
        done = await _fetch(client, url, part, done, on_progress)
    if done != size:
        raise DownloadError(f"{url} gave {done} bytes, expected {size}")
    if await asyncio.to_thread(file_sha256, part) != sha256:
        part.unlink()
        raise ChecksumError(f"{dest.name} does not match its sha256; the partial file was deleted")
    part.replace(dest)


async def _fetch(client: httpx.AsyncClient, url: str, part: Path, done: int, on_progress: Callable[[int], None]) -> int:
    # identity and aiter_raw: bytes as the file holds them, so they add up to `size` and a resume can continue them.
    headers = {"Accept-Encoding": "identity"} | ({"Range": f"bytes={done}-"} if done else {})
    try:
        async with client.stream("GET", url, headers=headers, follow_redirects=True) as response:
            if response.status_code >= 400:
                raise DownloadError(f"{url} answered HTTP {response.status_code}")
            if response.status_code != 206:  # the server ignored Range and sent the whole file
                done = 0
            with part.open("ab" if done else "wb") as out:
                async for chunk in response.aiter_raw():
                    out.write(chunk)
                    done += len(chunk)
                    on_progress(done)
    except httpx.TransportError as e:
        raise DownloadError(f"the download of {url} stopped after {done} bytes: {e!r}") from e
    return done
