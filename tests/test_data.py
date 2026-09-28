import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rowing_tracker.archive import DataError, archive_digest, load_manifest, read_json, sync, write_json
from rowing_tracker.client import APIError
from rowing_tracker.site import build_site, make_data


NOW = datetime(2026, 9, 25, 1, 0, tzinfo=timezone.utc)
CONFIG = {"goal_meters": 40075000, "rowing_types": ["rower", "dynamic", "slides"],
          "include_rest_distance": True, "publish_comments": False}


def workout(key=1, **changes):
    value = {"id": key, "user_id": 12, "date": "2018-01-01 23:30:00", "timezone": None,
             "distance": 10000, "time": 25200, "type": "rower", "workout_type": "JustRow"}
    value.update(changes)
    return value


class FakeAPI:
    def __init__(self, rows, page_size=1):
        self.rows = copy.deepcopy(rows)
        self.visible = list(self.rows)
        self.page_size = page_size
        self.calls = []
        self.fail = None
        self.mutate_page = None
        self.samples = {}
        self.account_id = 12

    def get(self, path, params=None):
        self.calls.append((path, params))
        if self.fail and self.fail(path, params):
            raise APIError("Simulated service failure", 503)
        if path == "":
            return {"data": {"id": self.account_id, "email": "private@example.invalid"}}
        if path == "/results":
            page = params["page"]
            values = self.visible[(page - 1) * self.page_size:page * self.page_size]
            result = {"data": copy.deepcopy(values), "meta": {"pagination": {
                "total": len(self.visible), "current_page": page, "count": len(values),
                "total_pages": (len(self.visible) + self.page_size - 1) // self.page_size,
                "links": {"next": "http://untrusted.invalid/steal-token"},
            }}}
            if self.mutate_page:
                self.mutate_page(result, page)
            return result
        key = int(path.split("/")[2])
        if path.endswith("/strokes"):
            if key not in self.samples:
                raise APIError("No stroke data", 404)
            return {"data": copy.deepcopy(self.samples[key])}
        for row in self.rows:
            if row["id"] == key:
                return {"data": copy.deepcopy(row)}
        raise APIError("Missing workout", 404)


class DataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.archive = self.root / "archive"

    def tearDown(self):
        self.temp.cleanup()

    def test_full_pagination_and_repeat_are_idempotent(self):
        api = FakeAPI([workout(1), workout(2)])
        report = sync(api, self.archive, now=NOW)
        digest = archive_digest(self.archive)
        manifest = (self.archive / "manifest.json").read_bytes()
        self.assertEqual(report["archived"], 2)
        self.assertEqual(len([c for c in api.calls if c[0] == "/results"]), 2)
        repeat = sync(api, self.archive, now=NOW + timedelta(hours=6))
        self.assertEqual(repeat["mode"], "incremental")
        self.assertEqual(repeat["changed_files"], 0)
        self.assertEqual(archive_digest(self.archive), digest)
        self.assertEqual((self.archive / "manifest.json").read_bytes(), manifest)
        query = [params for path, params in api.calls if path == "/results"][-1]
        self.assertEqual(query["updated_after"], "2026-09-25 00:55:00")
        self.assertNotIn("type", query)

    def test_old_edit_and_machine_change_replace_record(self):
        api = FakeAPI([workout(1), workout(2)])
        sync(api, self.archive, now=NOW)
        api.rows[0]["distance"] = 12000
        api.rows[1]["type"] = "bike"
        api.visible = list(api.rows)
        sync(api, self.archive, now=NOW + timedelta(hours=6))
        index, _, _, _ = make_data(self.archive, CONFIG)
        self.assertEqual(index["activity_count"], 1)
        self.assertEqual(index["total_meters"], 12000)

    def test_failures_do_not_advance_checkpoint_or_change_records(self):
        api = FakeAPI([workout(1), workout(2)])
        sync(api, self.archive, now=NOW)
        before = (self.archive / "manifest.json").read_bytes()
        digest = archive_digest(self.archive)
        api.rows[0]["distance"] = 12000
        api.visible = list(api.rows)
        for failure in (
            lambda path, params: path == "/results" and params["page"] == 2,
            lambda path, params: path == "/results/2",
            lambda path, params: path == "/results/2/strokes",
        ):
            api.fail = failure
            with self.assertRaises(APIError):
                sync(api, self.archive, now=NOW + timedelta(hours=6))
            self.assertEqual((self.archive / "manifest.json").read_bytes(), before)
            self.assertEqual(archive_digest(self.archive), digest)

    def test_inconsistent_pagination_cannot_reconcile_deletions(self):
        api = FakeAPI([workout(1), workout(2)])
        sync(api, self.archive, now=NOW)
        before = load_manifest(self.archive)
        api.mutate_page = lambda response, page: response["meta"]["pagination"].update(total=3 if page == 2 else 2)
        with self.assertRaises(DataError):
            sync(api, self.archive, force_full=True, now=NOW)
        self.assertEqual(load_manifest(self.archive), before)

    def test_duplicate_page_id_is_rejected(self):
        api = FakeAPI([workout(1), workout(1)])
        with self.assertRaises(DataError):
            sync(api, self.archive, now=NOW)
        self.assertFalse((self.archive / "manifest.json").exists())

    def test_unavailable_strokes_are_distinct_from_failure(self):
        api = FakeAPI([workout()])
        sync(api, self.archive, now=NOW)
        self.assertEqual(read_json(self.archive / "workouts/1.json")["stroke_status"], "unavailable")
        self.assertFalse((self.archive / "strokes/1.json").exists())
        api.samples[1] = [{"t": 21, "d": 153, "p": 1250, "hr": 140}]
        sync(api, self.archive, now=NOW + timedelta(hours=6))
        self.assertEqual(read_json(self.archive / "strokes/1.json")["data"][0]["d"], 153)
        self.assertEqual(read_json(self.archive / "workouts/1.json")["stroke_status"], "available")

    def test_work_rest_and_interval_totals_count_once(self):
        record = workout(rest_distance=250, rest_time=1200, workout={"intervals": [
            {"type": "distance", "distance": 5000, "time": 12600},
            {"type": "distance", "distance": 5000, "time": 12600}]})
        sync(FakeAPI([record]), self.archive, now=NOW)
        index, details, _, _ = make_data(self.archive, CONFIG)
        self.assertEqual(index["total_meters"], 10250)
        self.assertEqual(details["1"]["time"], 25200)
        index, _, _, _ = make_data(self.archive, dict(CONFIG, include_rest_distance=False))
        self.assertEqual(index["total_meters"], 10000)

    def test_confirmed_deletion_retires_record_without_losing_raw(self):
        api = FakeAPI([workout(1), workout(2)])
        sync(api, self.archive, now=NOW)
        api.rows = api.rows[:1]
        api.visible = list(api.rows)
        report = sync(api, self.archive, force_full=True, now=NOW + timedelta(days=1))
        self.assertEqual(report["deleted"], 1)
        self.assertEqual(load_manifest(self.archive)["retired_ids"], ["2"])
        self.assertTrue((self.archive / "workouts/2.json").exists())
        index, _, _, _ = make_data(self.archive, CONFIG)
        self.assertEqual(index["activity_count"], 1)

    def test_missing_but_existing_record_aborts_reconciliation(self):
        api = FakeAPI([workout(1), workout(2)])
        sync(api, self.archive, now=NOW)
        api.visible = api.rows[:1]
        with self.assertRaises(DataError):
            sync(api, self.archive, force_full=True, now=NOW)
        self.assertEqual(load_manifest(self.archive)["activity_ids"], ["1", "2"])

    def test_account_mismatch_rejected_even_when_new_account_is_empty(self):
        sync(FakeAPI([workout()]), self.archive, now=NOW)
        api = FakeAPI([])
        api.account_id = 999
        with self.assertRaises(DataError):
            sync(api, self.archive, force_full=True, now=NOW)
        self.assertEqual(load_manifest(self.archive)["user_id"], 12)

    def test_interrupted_commit_blocks_build_and_recovers(self):
        api = FakeAPI([workout()])
        sync(api, self.archive, now=NOW)
        api.rows[0]["distance"] = 12000
        api.visible = list(api.rows)
        with patch("rowing_tracker.archive.copy_if_changed", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                sync(api, self.archive, now=NOW + timedelta(hours=6))
        with self.assertRaises(DataError):
            make_data(self.archive, CONFIG)
        report = sync(api, self.archive, now=NOW + timedelta(hours=7))
        self.assertEqual(report["mode"], "full")
        self.assertFalse((self.archive / "pending.json").exists())
        self.assertEqual(make_data(self.archive, CONFIG)[0]["total_meters"], 12000)

    def test_unprojected_fields_do_not_enter_browser_build(self):
        record = workout(comments="PRIVATE-NOTE", metadata={"serial_number": "PRIVATE-SERIAL"},
                         private_unknown_field="PRIVATE-FIELD", heart_rate={"average": 130})
        api = FakeAPI([record])
        api.samples[1] = [{"t": 10, "d": 100, "p": 1200, "private": "PRIVATE-STROKE"}]
        sync(api, self.archive, now=NOW)
        output = self.root / "site"
        build_site(self.archive, output, CONFIG, ROOT / "web")
        serialized = "".join(path.read_text() for path in output.rglob("*.json"))
        self.assertNotIn("PRIVATE-", serialized)
        self.assertIn("PRIVATE-SERIAL", (self.archive / "workouts/1.json").read_text())
        detail = read_json(output / "data/activities/1.json")
        self.assertEqual(detail["concept2_url"], "https://log.concept2.com/profile/12/log/1")
        self.assertEqual(detail["date"], "2018-01-01 23:30:00")

    def test_failed_build_keeps_previous_public_output(self):
        sync(FakeAPI([workout()]), self.archive, now=NOW)
        output = self.root / "site"
        build_site(self.archive, output, CONFIG, ROOT / "web")
        before = (output / "data/index.json").read_bytes()
        write_json(self.archive / "pending.json", {"started_at": "interrupted"})
        with self.assertRaises(DataError):
            build_site(self.archive, output, CONFIG, ROOT / "web")
        self.assertEqual((output / "data/index.json").read_bytes(), before)

    def test_empty_account_and_missing_metrics(self):
        sync(FakeAPI([]), self.archive, now=NOW)
        index, _, _, _ = make_data(self.archive, CONFIG)
        self.assertEqual(index["total_meters"], 0)
        self.assertEqual(index["activity_count"], 0)
        api = FakeAPI([workout()])
        sync(api, self.archive, now=NOW + timedelta(hours=6))
        _, details, _, _ = make_data(self.archive, CONFIG)
        self.assertNotIn("stroke_rate", details["1"])
        self.assertEqual(details["1"]["heart_rate"], {})

    def test_interrupted_initial_import_still_binds_account(self):
        api = FakeAPI([workout()])
        with patch("rowing_tracker.archive.copy_if_changed", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                sync(api, self.archive, now=NOW)
        self.assertFalse((self.archive / "manifest.json").exists())
        stranger = FakeAPI([])
        stranger.account_id = 999
        with self.assertRaises(DataError):
            sync(stranger, self.archive, now=NOW)
        sync(api, self.archive, now=NOW)
        self.assertEqual(load_manifest(self.archive)["user_id"], 12)

    def test_build_recovers_directory_swap_after_process_interruption(self):
        sync(FakeAPI([workout()]), self.archive, now=NOW)
        output = self.root / "site"
        build_site(self.archive, output, CONFIG, ROOT / "web")
        output.rename(self.root / "site.previous")
        build_site(self.archive, output, CONFIG, ROOT / "web")
        self.assertTrue((output / "index.html").exists())
        self.assertFalse((self.root / "site.previous").exists())

    def test_embedded_batch_preserves_details_without_per_workout_requests(self):
        class EmbeddedAPI(FakeAPI):
            def get(self, path, params=None):
                if path not in ("", "/results"):
                    raise AssertionError("Unexpected per-workout request")
                response = super().get(path, params)
                if path == "/results":
                    for item in response["data"]:
                        item["metadata"] = {"data": {"client_version": "test"}}
                        item["workout"] = {"splits": []}
                        item["stroke_data"] = item["id"] == 1
                        if item["stroke_data"]:
                            item["strokes"] = {"data": [{"t": 12, "d": 140, "p": 1250}]}
                return response
        api = EmbeddedAPI([workout(1), workout(2)])
        sync(api, self.archive, now=NOW)
        self.assertEqual(read_json(self.archive / "strokes/1.json")["data"][0]["d"], 140)
        record = read_json(self.archive / "workouts/1.json")
        self.assertNotIn("strokes", record["result"])
        self.assertIn("metadata", record["result"])
        self.assertEqual(read_json(self.archive / "workouts/2.json")["stroke_status"], "unavailable")
        self.assertFalse((self.archive / "strokes/2.json").exists())

    def test_duplicate_manifest_id_is_rejected_before_counting(self):
        sync(FakeAPI([workout()]), self.archive, now=NOW)
        manifest = read_json(self.archive / "manifest.json")
        manifest["activity_ids"] = ["1", "1"]
        write_json(self.archive / "manifest.json", manifest)
        with self.assertRaises(DataError):
            load_manifest(self.archive)

    def test_malformed_stroke_archive_is_rejected_before_building(self):
        api = FakeAPI([workout()])
        api.samples[1] = [{"t": 10, "d": 100, "p": 1200}]
        sync(api, self.archive, now=NOW)
        write_json(self.archive / "strokes/1.json", {"data": ["not-an-object"]})
        with self.assertRaises(DataError):
            make_data(self.archive, CONFIG)

    def test_full_reconciliation_records_manifest_change(self):
        api = FakeAPI([workout()])
        sync(api, self.archive, now=NOW)
        before = archive_digest(self.archive)
        report = sync(api, self.archive, force_full=True, now=NOW + timedelta(days=1))
        self.assertEqual(report["changed_files"], 1)
        self.assertNotEqual(archive_digest(self.archive), before)


if __name__ == "__main__":
    unittest.main()
