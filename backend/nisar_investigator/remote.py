"""Read parts of multi-gigabyte NISAR HDF5 granules over HTTPS without downloading them.

The Earthdata data URL redirects through a login hop to a short-lived signed link. Doing that hop on every
range request is slow, so the signed link is resolved once per granule and plain range requests are issued
against it, with an in-memory cache of 4 MiB blocks (the page size NISAR granules are written with).
"""

from __future__ import annotations

import io
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import h5py
import requests

from . import config

_TIMEOUT = (20, 180)


class RemoteAccessError(RuntimeError):
    """Raised when a granule cannot be reached (login missing, link expired, network error)."""


@dataclass
class _SignedLink:
    url: str
    size: int
    expires_at: float


_links: dict[str, _SignedLink] = {}
_links_lock = threading.Lock()


def _resolve(data_url: str, *, force: bool = False) -> _SignedLink:
    """Follow the Earthdata login redirect once and remember the signed link and file size."""
    with _links_lock:
        link = _links.get(data_url)
        if link and not force and link.expires_at - time.time() > 120:
            return link
    session = requests.Session()  # picks up ~/.netrc for the urs.earthdata.nasa.gov hop
    headers = {"Range": "bytes=0-0"}
    token = config.earthdata_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"  # requests drops this header on the cross-host redirect
    try:
        r = session.get(data_url, headers=headers, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise RemoteAccessError(f"could not reach the NISAR archive: {type(exc).__name__}") from None
    if r.status_code in (401, 403):
        raise RemoteAccessError(
            "Earthdata Login was refused. Check ~/.netrc or EARTHDATA_TOKEN, and that the account has "
            "accepted the Alaska Satellite Facility data access terms."
        )
    if r.status_code != 206 or "Content-Range" not in r.headers:
        raise RemoteAccessError(f"unexpected response from the NISAR archive (HTTP {r.status_code})")
    size = int(r.headers["Content-Range"].rsplit("/", 1)[1])
    expires = time.time() + 45 * 60
    query = parse_qs(urlparse(r.url).query)
    if "Expires" in query:  # CloudFront signed URLs carry their expiry as epoch seconds
        try:
            expires = float(query["Expires"][0])
        except ValueError:
            pass
    link = _SignedLink(url=r.url, size=size, expires_at=expires)
    with _links_lock:
        _links[data_url] = link
    return link


class RangeFile(io.RawIOBase):
    """Read-only, seekable file object backed by HTTP range requests and an LRU block cache."""

    def __init__(self, data_url: str):
        super().__init__()
        self.data_url = data_url
        self._link = _resolve(data_url)
        self.size = self._link.size
        self._pos = 0
        self._blocks: OrderedDict[int, bytes] = OrderedDict()
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.trust_env = False  # the signed link needs no credentials
        self.requests_made = 0
        self.bytes_fetched = 0
        self.network_seconds = 0.0

    # -- file protocol -------------------------------------------------------
    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        else:
            self._pos = self.size + offset
        return self._pos

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self._pos
        n = max(0, min(n, self.size - self._pos))
        out = bytearray()
        while n > 0:
            index, offset = divmod(self._pos, config.BLOCK_SIZE)
            piece = self._block(index)[offset : offset + n]
            out += piece
            self._pos += len(piece)
            n -= len(piece)
        return bytes(out)

    def readinto(self, buffer) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)

    # -- blocks --------------------------------------------------------------
    def _fetch(self, index: int) -> bytes:
        start = index * config.BLOCK_SIZE
        end = min(start + config.BLOCK_SIZE, self.size) - 1
        for attempt in range(3):
            t0 = time.time()
            try:
                r = self._session.get(self._link.url, headers={"Range": f"bytes={start}-{end}"}, timeout=_TIMEOUT)
            except requests.RequestException:
                if attempt == 2:
                    raise RemoteAccessError("network error while reading the granule") from None
                time.sleep(0.5 * (attempt + 1))
                continue
            if r.status_code == 206:
                with self._lock:
                    self.requests_made += 1
                    self.bytes_fetched += len(r.content)
                    self.network_seconds += time.time() - t0
                return r.content
            if r.status_code in (401, 403):  # signed link expired: resolve again and retry
                self._link = _resolve(self.data_url, force=True)
                continue
            if attempt == 2:
                raise RemoteAccessError(f"unexpected response while reading the granule (HTTP {r.status_code})")
            time.sleep(0.5 * (attempt + 1))
        raise RemoteAccessError("could not read the granule")

    def _store(self, index: int, data: bytes) -> None:
        with self._lock:
            self._blocks[index] = data
            self._blocks.move_to_end(index)
            while len(self._blocks) > config.MAX_CACHED_BLOCKS:
                self._blocks.popitem(last=False)

    def _block(self, index: int) -> bytes:
        with self._lock:
            data = self._blocks.get(index)
            if data is not None:
                self._blocks.move_to_end(index)
                return data
        data = self._fetch(index)
        self._store(index, data)
        return data

    def prefetch(self, byte_ranges: list[tuple[int, int]], workers: int = 8) -> None:
        """Fetch the blocks covering (offset, length) ranges concurrently, before h5py asks for them.

        h5py holds a global lock while it reads, so its own requests are strictly sequential.
        """
        wanted: list[int] = []
        for offset, length in byte_ranges:
            if length <= 0:
                continue
            first, last = offset // config.BLOCK_SIZE, (offset + length - 1) // config.BLOCK_SIZE
            wanted.extend(range(first, last + 1))
        with self._lock:
            missing = sorted({i for i in wanted if i not in self._blocks})
        missing = missing[: config.MAX_CACHED_BLOCKS]
        if len(missing) < 2:
            return
        with ThreadPoolExecutor(max_workers=min(workers, len(missing))) as pool:
            for index, data in zip(missing, pool.map(self._fetch, missing)):
                self._store(index, data)

    def stats(self) -> dict:
        return {
            "requests": self.requests_made,
            "megabytes": round(self.bytes_fetched / 1e6, 1),
            "fraction_of_file": round(self.bytes_fetched / self.size, 5) if self.size else None,
            "network_seconds": round(self.network_seconds, 2),
        }


class RemoteGranule:
    """Context manager: an open h5py.File over a RangeFile, closed cleanly on exit."""

    def __init__(self, data_url: str):
        self.raw = RangeFile(data_url)
        self.h5 = h5py.File(self.raw, "r")

    def __enter__(self) -> "RemoteGranule":
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.h5.close()
        finally:
            self.raw.close()
