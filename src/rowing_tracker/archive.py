"""Paginated imports with a durable checkpoint and repeatable recovery."""

import hashlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .client import APIError


class DataError(RuntimeError):
    pass


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def read_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path, value):
    path = Path(path)
    data = json_bytes(value)
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))
    return True


def copy_if_changed(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.exists() and source.read_bytes() == destination.read_bytes():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    with source.open("rb") as src, temporary.open("wb") as dest:
        shutil.copyfileobj(src, dest)
        dest.flush()
        os.fsync(dest.fileno())
    os.replace(str(temporary), str(destination))
    return True


def timestamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise DataError("{} must be an integer >= {}.".format(label, minimum))
    return value


def validate_result(value):
    if not isinstance(value, dict):
        raise DataError("Expected an activity object.")
    integer(value.get("id"), "Activity ID", 1)
    integer(value.get("user_id"), "Account ID", 1)
    for key in ("distance", "time"):
        integer(value.get(key), key)
    for key in ("rest_distance", "rest_time"):
        if value.get(key) is not None:
            integer(value[key], key)
    if not isinstance(value.get("type"), str) or not value["type"]:
        raise DataError("Missing activity type.")
    try:
        datetime.fromisoformat(value["date"])
    except (KeyError, ValueError, TypeError):
        raise DataError("Missing or invalid activity date.") from None
    return value


def validate_strokes(value, activity_id):
    if not isinstance(value, dict) or not isinstance(value.get("data"), list):
        raise DataError("Invalid stroke archive for activity " + str(activity_id))
    if any(not isinstance(row, dict) for row in value["data"]):
        raise DataError("Invalid stroke sample for activity " + str(activity_id))
    return value


def validated_ids(value, label):
    if not isinstance(value, list):
        raise DataError(label + " must be a list.")
    if any(not isinstance(key, str) or not key.isdigit() or int(key) < 1 for key in value):
        raise DataError("Invalid activity ID in " + label + ".")
    if len(value) != len(set(value)):
        raise DataError("Duplicate activity ID in " + label + ".")
    return value


def validate_manifest(value):
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise DataError("Unsupported archive version.")
    integer(value.get("user_id"), "Account ID", 1)
    active = validated_ids(value.get("activity_ids"), "active archive IDs")
    retired = validated_ids(value.get("retired_ids"), "retired archive IDs")
    if set(active) & set(retired):
        raise DataError("An activity cannot be both active and retired.")
    for key in ("checkpoint", "last_successful_sync", "last_full_sync"):
        timestamp_value = value.get(key)
        if not isinstance(timestamp_value, str):
            raise DataError("Missing archive timestamp: " + key)
        try:
            parse_timestamp(timestamp_value)
        except (ValueError, TypeError, AttributeError):
            raise DataError("Invalid archive timestamp: " + key) from None
    return value


def validate_saved_record(path, key, user_id):
    saved = read_json(path / "workouts" / (key + ".json"))
    if not isinstance(saved, dict) or saved.get("schema_version") != 1:
        raise DataError("Unsupported workout archive version for " + key)
    raw = validate_result(saved.get("result"))
    if str(raw["id"]) != key or raw["user_id"] != user_id:
        raise DataError("Archived workout identity does not match its manifest: " + key)
    status = saved.get("stroke_status")
    if status not in ("available", "unavailable"):
        raise DataError("Invalid stroke status for activity " + key)
    stroke_path = path / "strokes" / (key + ".json")
    if status == "available":
        if not stroke_path.is_file():
            raise DataError("Archived stroke samples are missing for " + key)
        strokes = validate_strokes(read_json(stroke_path), key)
        if not strokes["data"]:
            raise DataError("Available stroke archive is empty for activity " + key)
    elif stroke_path.exists():
        raise DataError("Unavailable activity has an unexpected stroke file: " + key)
    return saved


def unwrap(response):
    if not isinstance(response, dict) or "data" not in response:
        raise DataError("The API response has no data field.")
    return response["data"]


def list_results(client, updated_after=None, on_result=None, progress=None):
    results = {}
    expected = None
    expected_pages = None
    page = 1
    while True:
        # Embedded telemetry keeps request count low. Use bounded pages so a
        # lifetime of stroke samples never has to fit in one response or RAM.
        query = {"number": 25 if on_result else 250, "page": page}
        if on_result:
            query["include"] = "strokes,metadata"
        if updated_after:
            query["updated_after"] = updated_after
        response = client.get("/results", query)
        records = unwrap(response)
        if not isinstance(records, list):
            raise DataError("Expected a list of activities.")
        pagination = response.get("meta", {}).get("pagination")
        if not isinstance(pagination, dict):
            raise DataError("Missing pagination metadata; refusing an incomplete import.")
        total = integer(pagination.get("total"), "Pagination total")
        pages = integer(pagination.get("total_pages"), "Pagination pages")
        current = integer(pagination.get("current_page"), "Current page", 1)
        count = integer(pagination.get("count"), "Page count")
        if current != page or count != len(records) or (total and not pages):
            raise DataError("Inconsistent pagination metadata.")
        if expected is None:
            expected, expected_pages = total, pages
        elif expected != total or expected_pages != pages:
            raise DataError("The activity list changed during pagination; retry the sync.")
        for record in records:
            validate_result(record)
            key = str(record["id"])
            if key in results:
                raise DataError("Duplicate activity across pages; retry the sync.")
            if on_result:
                on_result(key, record)
                results[key] = {"id": record["id"], "user_id": record["user_id"]}
            else:
                results[key] = record
        if progress:
            progress("Downloaded {} of {} activities (page {} of {})".format(len(results), total, page, max(1, pages)))
        if page >= max(1, pages):
            break
        if not records:
            raise DataError("An intermediate activity page is empty.")
        page += 1
    if len(results) != expected:
        raise DataError("Activity count did not match pagination metadata.")
    return results


@contextmanager
def archive_lock(path):
    # fcntl is available on macOS and the Linux Actions runner. The lock is
    # released by the OS even after a crash; no stale lock removal is needed.
    import fcntl
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    with (path / ".lock").open("a") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DataError("Another process is using this archive.") from None
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def load_manifest(path, allow_pending=False):
    path = Path(path)
    pending = (path / "pending.json").exists()
    if pending and not allow_pending:
        raise DataError("An interrupted sync needs recovery. Run sync before building.")
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = validate_manifest(read_json(manifest_path))
    for key in manifest["activity_ids"]:
        if not (path / "workouts" / (key + ".json")).is_file():
            raise DataError("An archived workout is missing: " + str(key))
        # A pending journal means the previous commit may be half-applied. The
        # next sync performs a full recovery, so validate records only when the
        # archive is in a publishable state.
        if not (pending and allow_pending):
            validate_saved_record(path, key, manifest["user_id"])
    return manifest


def sync(client, archive_path, force_full=False, now=None, progress=None):
    archive = Path(archive_path)
    started = now or datetime.now(timezone.utc)
    with archive_lock(archive):
        previous = load_manifest(archive, allow_pending=True)
        full = force_full or previous is None or (archive / "pending.json").exists()
        if previous and not full:
            last_full = previous.get("last_full_sync")
            full = not last_full or started - parse_timestamp(last_full) >= timedelta(days=30)
        since = None
        if previous and not full:
            since = (parse_timestamp(previous["checkpoint"]) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        if progress:
            progress("Connecting to Concept2 and checking account identity")
        account_id = integer(unwrap(client.get("")).get("id"), "Account ID", 1)
        if previous and previous.get("user_id") not in (None, account_id):
            raise DataError("This token belongs to a different Concept2 account.")
        pending_path = archive / "pending.json"
        if pending_path.exists():
            pending_account = read_json(pending_path).get("user_id")
            if pending_account is None or pending_account != account_id:
                raise DataError("The interrupted import is not bound to this account; inspect its private archive before recovery.")
        # Disk staging keeps thousands of workouts' stroke arrays out of RAM.
        # A failed download changes no active archive records or checkpoint.
        staging = Path(tempfile.mkdtemp(prefix=".download-", dir=str(archive)))
        try:
            def download(key, summary):
                if summary["user_id"] != account_id:
                    raise DataError("These activities belong to a different Concept2 account.")
                # Live Concept2 results include full splits and support embedded
                # metadata/strokes. Fall back to the documented detail endpoint
                # if a server version omits either requested include.
                embedded = "metadata" in summary and "workout" in summary and ("strokes" in summary or summary.get("stroke_data") is False)
                detail = summary if embedded else validate_result(unwrap(client.get("/results/" + key, {"include": "strokes,metadata"})))
                if str(detail["id"]) != key or detail["user_id"] != account_id:
                    raise DataError("Activity details did not match the requested record.")
                try:
                    if "strokes" in detail:
                        strokes = unwrap(detail["strokes"])
                    elif detail.get("stroke_data") is False:
                        strokes = None
                    else:
                        strokes = unwrap(client.get("/results/" + key + "/strokes"))
                    if strokes is not None and (not isinstance(strokes, list) or any(not isinstance(row, dict) for row in strokes)):
                        raise DataError("Invalid stroke data for activity " + key)
                    if not strokes:
                        strokes = None
                    stroke_status = "available" if strokes is not None else "unavailable"
                except APIError as exc:
                    if exc.status != 404:
                        raise
                    strokes, stroke_status = None, "unavailable"
                raw_detail = {field: value for field, value in detail.items() if field != "strokes"}
                record = {"schema_version": 1, "result": raw_detail, "stroke_status": stroke_status}
                write_json(staging / "workouts" / (key + ".json"), record)
                if strokes is not None:
                    write_json(staging / "strokes" / (key + ".json"), {"data": strokes})
            listed = list_results(client, since, on_result=download, progress=progress)
            ids = set(listed) if full else set(previous["activity_ids"]) | set(listed)
            removed = set(previous["activity_ids"]) - ids if previous else set()
            # Pagination is not a documented snapshot. Confirm missing IDs
            # individually before retiring them from the active totals.
            for key in removed:
                try:
                    client.get("/results/" + key)
                except APIError as exc:
                    if exc.status == 404:
                        continue
                    raise
                raise DataError("An activity missing from the list still exists; retry reconciliation.")
            changed = commit_sync(archive, staging, listed, ids, removed, previous, account_id, started, full, now)
        finally:
            shutil.rmtree(staging)
        return {"mode": "full" if full else "incremental", "downloaded": len(listed),
                "changed_files": changed, "deleted": len(removed), "archived": len(ids)}


def commit_sync(archive, staging, listed, ids, removed, previous, account_id, started, full, now):
    # All HTTP requests succeed before any existing record changes. If a
    # disk write is interrupted, pending.json prevents publishing a mixed
    # archive and the next run performs a complete reconciliation.
    write_json(archive / "pending.json", {"started_at": timestamp(started), "user_id": account_id})
    changed = 0
    for key in listed:
        changed += int(copy_if_changed(staging / "workouts" / (key + ".json"), archive / "workouts" / (key + ".json")))
        new_strokes = staging / "strokes" / (key + ".json")
        stroke_file = archive / "strokes" / (key + ".json")
        if new_strokes.exists():
            changed += int(copy_if_changed(new_strokes, stroke_file))
        elif stroke_file.exists():
            stroke_file.unlink()
            changed += 1
    retired = (set(previous.get("retired_ids", [])) if previous else set()) | removed
    if previous is not None and not full and not changed and not removed:
        # A no-op incremental check must not create timestamp-only Git commits.
        # Keeping the older checkpoint is safe: the overlap is queried again,
        # and the monthly full reconciliation remains the backstop.
        manifest = previous
    else:
        manifest = {
            "schema_version": 1, "user_id": account_id,
            "activity_ids": sorted(ids, key=int), "retired_ids": sorted(retired - ids, key=int),
            "checkpoint": timestamp(started),
            "last_successful_sync": timestamp(datetime.now(timezone.utc) if now is None else now),
            "last_full_sync": timestamp(started) if full else previous["last_full_sync"],
        }
    # Retired records remain in the raw archive but leave active totals.
    changed += int(write_json(archive / "manifest.json", manifest))
    (archive / "pending.json").unlink()
    return changed


def archive_digest(archive_path):
    archive = Path(archive_path)
    load_manifest(archive)
    digest = hashlib.sha256()
    for path in sorted(archive.rglob("*.json"), key=lambda item: item.relative_to(archive).as_posix()):
        relative = path.relative_to(archive).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()
