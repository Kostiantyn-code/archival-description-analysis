from contextlib import closing
from io import BytesIO
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import URLError
from zipfile import ZipFile

import map_data as maps
from geography import write_registry_suggestions
from tools import city_register


def registry_zip(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(city_register.SCHEMA)
        db.execute("INSERT INTO metadata VALUES ('schema', '2')")
        db.execute("INSERT INTO places VALUES (1,'Tartu','EE','','','PPL',58,26,0,'','Fixture')")
        db.execute("""INSERT INTO names VALUES
                      (1,'Dorpat','dorpat','de','historical',1,0,0,0,'1224','',NULL,'Fixture')""")
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        archive.write(path, "registry.sqlite")
    return data.getvalue()


def release_asset(name, raw):
    return {"name": name, "size": len(raw), "state": "uploaded",
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "browser_download_url": maps.RELEASE_URL + "test/" + name}


class MapDataTests(unittest.TestCase):
    def test_first_download_caches_both_assets_for_offline_report(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            cache = root / "cache"
            basemap = maps.BASEMAP.read_bytes()
            registry = registry_zip(root / "fixture.sqlite")
            assets = [release_asset(maps.BASEMAP.name, basemap), release_asset(maps.REGISTRY_ASSET, registry)]
            metadata = json.dumps({"assets": assets}).encode()
            replies = {maps.RELEASE_API: metadata,
                       assets[0]["browser_download_url"]: basemap,
                       assets[1]["browser_download_url"]: registry}

            def response(request, timeout):
                url = request.full_url if hasattr(request, "full_url") else request
                return BytesIO(replies[url])

            with patch.object(maps, "urlopen", side_effect=response) as network:
                online = maps.prepare_map_data(True, cache)
                self.assertEqual(network.call_count, 3)
                self.assertEqual(maps.prepare_map_data(True, cache), online)
                self.assertEqual(network.call_count, 3)
            with patch.object(maps, "urlopen", side_effect=AssertionError("Unexpected network request")):
                offline = maps.prepare_map_data(False, cache)
            self.assertEqual(offline, online)
            self.assertEqual(offline.basemap, cache / maps.BASEMAP.name)
            self.assertEqual(offline.registry, cache / "registry.release.sqlite")
            path = root / "matches.csv"
            write_registry_suggestions(path, [{"candidate": "Dorpat", "title": "Letter from Dorpat"}],
                                       offline.registry)
            self.assertIn("Tartu;EE", path.read_text(encoding="utf-8-sig"))

    def test_unreachable_release_and_corrupt_update_keep_working_maps(self):
        with TemporaryDirectory() as folder:
            cache = Path(folder)
            with patch.object(maps, "read_release", side_effect=URLError("offline")):
                self.assertEqual(maps.prepare_map_data(True, cache, notify=lambda _: None).basemap,
                                 maps.BASEMAP)
            (cache / ".last-check").unlink()
            cached = cache / maps.BASEMAP.name
            original = maps.BASEMAP.read_bytes()
            cached.write_bytes(original)
            asset = release_asset(maps.BASEMAP.name, b"expected")
            messages = []
            with (patch.object(maps, "read_release", return_value={"assets": [asset]}),
                  patch.object(maps, "urlopen", return_value=BytesIO(b"mismatch"))):
                self.assertEqual(maps.prepare_map_data(True, cache, notify=messages.append).basemap, cached)
            self.assertEqual(cached.read_bytes(), original)
            self.assertTrue(any("SHA-256" in message for message in messages))
            cached.write_text(json.dumps({
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "geometry": {"type": [], "coordinates": []}}],
            }), encoding="utf-8")
            self.assertEqual(maps.prepare_map_data(False, cache, notify=messages.append).basemap,
                             maps.BASEMAP)

    def test_local_registry_takes_priority(self):
        with TemporaryDirectory() as folder:
            cache = Path(folder)
            local = cache / "registry.sqlite"
            registry_zip(local)
            (cache / "registry.release.sqlite").write_bytes(local.read_bytes())
            self.assertEqual(maps.prepare_map_data(False, cache).registry, local)
