"""Resolve local map data and optionally refresh it from GitHub Releases."""

from contextlib import closing
from dataclasses import dataclass
import hashlib
import http.client
import json
from pathlib import Path
import re
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import time
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile

from tools.city_register import lookup


ROOT = Path(__file__).resolve().parent
REPOSITORY = "Kostiantyn-code/archival-description-analysis"
RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASE_URL = f"https://github.com/{REPOSITORY}/releases/download/"
BASEMAP = ROOT / "maps" / "europe-basemap.geojson"
CACHE = ROOT / "map-data"
REGISTRY_ASSET = "reiestr-naselenykh-punktiv.zip"
MAX_BASEMAP_SIZE = 16 * 1024**2
MAX_REGISTRY_SIZE = 1024**3
CHECK_INTERVAL = 24 * 60 * 60


@dataclass(frozen=True)
class MapData:
    basemap: Path = BASEMAP
    registry: Path | None = None
    registry_sha256: str | None = None


def read_basemap(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("type") != "FeatureCollection"
            or not isinstance(data.get("features"), list) or not data["features"]):
        raise ValueError("Expected a non-empty GeoJSON FeatureCollection")
    for feature in data["features"]:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError("Invalid GeoJSON feature")
        geometry = feature.get("geometry")
        if (not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon")
                or not isinstance(geometry.get("coordinates"), list)):
            raise ValueError("Expected polygon outlines in the basemap")
    return data


def open_registry(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def validate_registry(path: Path) -> None:
    with closing(open_registry(path)) as db:
        if db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone() != ("2",):
            raise ValueError("Unsupported settlement registry schema")
        lookup(db, "").fetchone()


def read_release() -> dict:
    request = Request(RELEASE_API, headers={"Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=5) as response:
        raw = response.read(1024**2 + 1)
    if len(raw) > 1024**2:
        raise ValueError("GitHub release information is too large")
    release = json.loads(raw)
    if not isinstance(release, dict) or not isinstance(release.get("assets"), list):
        raise ValueError("Invalid GitHub release information")
    return release


def download(asset: dict, destination: Path, maximum: int) -> None:
    size = asset.get("size")
    digest = asset.get("digest")
    url = asset.get("browser_download_url")
    if (not isinstance(size, int) or not 0 < size <= maximum
            or not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            or not isinstance(url, str) or not url.startswith(RELEASE_URL)):
        raise ValueError("Release asset has an invalid URL, size or SHA-256")
    checksum = hashlib.sha256()
    count = 0
    with urlopen(url, timeout=15) as response, destination.open("wb") as stream:
        while chunk := response.read(1024**2):
            count += len(chunk)
            if count > size:
                raise ValueError("Release asset exceeded its declared size")
            checksum.update(chunk)
            stream.write(chunk)
    if count != size or checksum.hexdigest() != digest.removeprefix("sha256:"):
        raise ValueError("Release asset failed SHA-256 verification")


def unpack_registry(archive: Path, destination: Path) -> None:
    with ZipFile(archive) as package:
        info = package.getinfo("registry.sqlite")
        if not 0 < info.file_size <= MAX_REGISTRY_SIZE:
            raise ValueError("Invalid uncompressed registry size")
        with package.open(info) as source, destination.open("wb") as target:
            shutil.copyfileobj(source, target)
    validate_registry(destination)


UPDATE_ERRORS = (OSError, ValueError, KeyError, BadZipFile, sqlite3.Error, http.client.HTTPException)


def refresh_asset(cache: Path, asset: dict, target: Path, *, archive: bool, notify) -> None:
    stamp = target.with_suffix(target.suffix + ".sha256")
    digest = asset.get("digest")
    try:
        if target.is_file() and stamp.read_text(encoding="ascii") == digest:
            (validate_registry if archive else read_basemap)(target)
            return
    except UPDATE_ERRORS:
        pass  # Replace a damaged cache or its metadata from a verified download.
    notify(f"Downloading map data: {asset['name']}")
    with TemporaryDirectory(dir=cache) as directory:
        folder = Path(directory)
        incoming = folder / "download"
        download(asset, incoming, MAX_REGISTRY_SIZE if archive else MAX_BASEMAP_SIZE)
        if archive:
            ready = folder / target.name
            unpack_registry(incoming, ready)
        else:
            read_basemap(incoming)
            ready = incoming
        # The existing cache stays usable until the new file has been verified.
        temporary_stamp = folder / stamp.name
        temporary_stamp.write_text(digest, encoding="ascii")
        ready.replace(target)
        temporary_stamp.replace(stamp)


def refresh(cache: Path, basemap: Path, registry: Path | None, notify) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    marker = cache / ".last-check"
    if marker.exists() and time.time() - marker.stat().st_mtime < CHECK_INTERVAL:
        return
    marker.touch()
    try:
        release = read_release()
    except UPDATE_ERRORS as error:
        notify(f"Map update unavailable: {error}")
        return
    supported = {BASEMAP.name: (basemap, False)}
    if registry is not None:
        supported[REGISTRY_ASSET] = (registry, True)
    for asset in release["assets"]:
        if not isinstance(asset, dict) or asset.get("state") != "uploaded":
            continue
        name = asset.get("name")
        if not isinstance(name, str) or name not in supported:
            continue
        target, archive = supported[name]
        try:
            refresh_asset(cache, asset, target, archive=archive, notify=notify)
        except UPDATE_ERRORS as error:
            notify(f"Map data not updated ({name}): {error}")


def prepare_map_data(auto_update: bool, cache: Path = CACHE, notify=print) -> MapData:
    basemap = cache / BASEMAP.name
    registry = cache / "registry.release.sqlite"
    local = cache / "registry.sqlite"
    local_checksum = registry_checksum(local, notify)
    if auto_update:
        try:
            refresh(cache, basemap, None if local_checksum else registry, notify)
        except OSError as error:
            notify(f"Map cache unavailable: {error}")
    if basemap.is_file():
        try:
            read_basemap(basemap)
        except UPDATE_ERRORS as error:
            notify(f"Using the bundled basemap: {error}")
            basemap = BASEMAP
    else:
        basemap = BASEMAP
    if local_checksum is not None:
        return MapData(basemap, local, local_checksum)
    release_checksum = registry_checksum(registry, notify)
    return MapData(basemap, registry, release_checksum) if release_checksum else MapData(basemap)


def registry_checksum(path: Path, notify) -> str | None:
    if not path.is_file():
        return None
    try:
        validate_registry(path)
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except UPDATE_ERRORS as error:
        notify(f"Skipping unusable settlement registry ({path.name}): {error}")
        return None
