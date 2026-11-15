"""Read parts of multi-gigabyte NISAR HDF5 granules over HTTPS without downloading them.

The Earthdata data URL redirects through a login hop to a short-lived signed link. Doing that hop on every
range request is slow, so the signed link is resolved once per granule and plain range requests are issued
against it, with an in-memory cache of blocks for the HDF5 library's own (metadata) reads.

The login itself is the slowest single step of a first read (measured at 2.8 s). It is done once per
process: the session that logged in keeps its cookies, and later granules resolve in one short hop.
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
from requests.adapters import HTTPAdapter

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
_login = requests.Session()  # picks up ~/.netrc for the urs.earthdata.nasa.gov hop, then keeps the cookies
_login.mount("https://", HTTPAdapter(pool_maxsize=16))
# Every range request of this process goes through one session, so connections to the archive stay open
# from one granule (and one request) to the next instead of being negotiated again each time.
_data = requests.Session()
_data.trust_env = False  # the signed links need no credentials
_data.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=48))


def data_session() -> requests.Session:
    return _data


def _logged_in() -> bool:
    return any("earthdatacloud" in (cookie.domain or "") for cookie in _login.cookies)


def _resolve(data_url: str, *, force: bool = False) -> _SignedLink:
    """Follow the Earthdata login redirect once and remember the signed link and file size."""
    with _links_lock:
        link = _links.get(data_url)
        if link and not force and link.expires_at - time.time() > 120:
            return link
    headers = {"Range": "bytes=0-0"}
    token = config.earthdata_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"  # requests drops this header on the cross-host redirect
    try:
        r = _login.get(data_url, headers=headers, timeout=_TIMEOUT)
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


def resolve_many(data_urls: list[str]) -> dict[str, tuple[str, int, float]]:
    """Signed links for several granules, resolved side by side: {data URL: (link, size, expiry)}.

    Meant for the process that hands granules to reader processes, so that those never log in themselves.
    A granule that cannot be resolved is left out; its reader then meets and reports the error itself.
    The links are credentials: they are passed on, never logged.
    """
    pending = list(dict.fromkeys(data_urls))

    def one(url: str) -> tuple[str, int, float] | None:
        try:
            link = _resolve(url)
        except RemoteAccessError:
            return None
        return link.url, link.size, link.expires_at

    out: dict[str, tuple[str, int, float]] = {}
    if not pending:
        return out
    rest = pending
    if not _logged_in():
        first = one(pending[0])  # the first login sets the cookies the others reuse
        if first:
            out[pending[0]] = first
        rest = pending[1:]
    if rest:
        with ThreadPoolExecutor(max_workers=min(12, len(rest))) as pool:
            out.update({url: link for url, link in zip(rest, pool.map(one, rest)) if link})
    return out


def seed_link(data_url: str, signed: tuple[str, int, float]) -> None:
    """Remember a signed link another process resolved."""
    with _links_lock:
        _links[data_url] = _SignedLink(url=signed[0], size=signed[1], expires_at=signed[2])


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
        self._session = _data
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

    def warm(self, offsets: tuple[int, ...]) -> None:
        """Fetch the blocks holding these byte offsets side by side, before the HDF5 library asks for them
        one after another. For places every granule of a product is known to need."""
        indexes = sorted({offset // config.BLOCK_SIZE for offset in offsets if 0 <= offset < self.size})
        with self._lock:
            missing = [i for i in indexes if i not in self._blocks]
        if not missing:
            return
        with ThreadPoolExecutor(max_workers=len(missing)) as pool:
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

    def __init__(self, data_url: str, warm: tuple[int, ...] = ()):
        self.raw = RangeFile(data_url)
        if warm:
            self.raw.warm(warm)
        self.h5 = h5py.File(self.raw, "r")

    def __enter__(self) -> "RemoteGranule":
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.h5.close()
        finally:
            self.raw.close()
