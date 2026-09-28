"""Create an explicit browser-facing projection without copying the raw archive."""

import json
import os
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

from .archive import DataError, archive_lock, integer, load_manifest, read_json, validate_result, write_json


RESULT_FIELDS = (
    "id", "user_id", "date", "date_utc", "timezone", "type", "workout_type",
    "distance", "time", "rest_distance", "rest_time", "stroke_rate", "stroke_count",
    "drag_factor", "calories_total", "wattminutes_total", "verified", "ranked",
    "source", "weight_class",
)
HR_FIELDS = ("average", "min", "max", "ending", "recovery", "rest")
PART_FIELDS = ("type", "machine", "distance", "time", "rest_time", "rest_distance",
               "stroke_rate", "calories_total", "wattminutes_total")
TARGET_FIELDS = ("stroke_rate", "heart_rate_zone", "pace", "watts", "calories")
STROKE_FIELDS = ("t", "d", "p", "spm", "hr")


def pick(value, fields):
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in fields
            if key in value and (value[key] is None or type(value[key]) in (str, int, float, bool))}


def public_result(raw, publish_comments=False):
    result = pick(raw, RESULT_FIELDS)
    result["heart_rate"] = pick(raw.get("heart_rate"), HR_FIELDS)
    workout = raw.get("workout")
    # Preserve the original shape in the archive, but fail clearly if a live
    # workout schema is not one the display understands.
    if workout is not None and not isinstance(workout, (dict, list)):
        raise DataError("Unexpected workout details structure.")
    if isinstance(workout, list):
        if workout:
            raise DataError("Workout details arrived as a nonempty array; inspect the raw record before publishing.")
        workout = {}
    workout = workout or {}
    details = {"targets": pick(workout.get("targets"), TARGET_FIELDS)}
    for group in ("splits", "intervals"):
        values = workout.get(group, [])
        if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
            raise DataError("Unexpected " + group + " structure.")
        details[group] = []
        for part in values:
            item = pick(part, PART_FIELDS)
            item["heart_rate"] = pick(part.get("heart_rate"), HR_FIELDS)
            item["targets"] = pick(part.get("targets"), TARGET_FIELDS)
            details[group].append(item)
    result["workout"] = details
    if publish_comments and isinstance(raw.get("comments"), str):
        result["comments"] = raw["comments"]
    result["concept2_url"] = "https://log.concept2.com/profile/{}/log/{}".format(raw["user_id"], raw["id"])
    return result


def validate_config(config):
    integer(config.get("goal_meters"), "Goal distance", 1)
    types = config.get("rowing_types")
    if not isinstance(types, list) or not types or any(not isinstance(t, str) for t in types):
        raise DataError("rowing_types must be a nonempty list.")
    for name in ("include_rest_distance", "publish_comments"):
        if type(config.get(name)) is not bool:
            raise DataError(name + " must be true or false.")
    return config


def make_data(archive, config):
    archive = Path(archive)
    manifest = load_manifest(archive)
    if manifest is None:
        raise DataError("No archive exists yet. Set up the token and run sync first.")
    config = validate_config(config)
    records = []
    by_type = defaultdict(lambda: {"activities": 0, "work_meters": 0, "rest_meters": 0})
    details = {}
    strokes = {}
    for key in manifest["activity_ids"]:
        saved = read_json(archive / "workouts" / (key + ".json"))
        raw = validate_result(saved["result"])
        if str(raw["id"]) != key or raw["user_id"] != manifest["user_id"]:
            raise DataError("The archived activity ID or account does not match its manifest.")
        totals = by_type[raw["type"]]
        totals["activities"] += 1
        totals["work_meters"] += raw["distance"]
        totals["rest_meters"] += raw.get("rest_distance") or 0
        if raw["type"] not in config["rowing_types"]:
            continue
        result = public_result(raw, config["publish_comments"])
        result["stroke_status"] = saved.get("stroke_status", "not_fetched")
        result["contribution_meters"] = raw["distance"] + ((raw.get("rest_distance") or 0) if config["include_rest_distance"] else 0)
        details[key] = result
        stroke_file = archive / "strokes" / (key + ".json")
        if result["stroke_status"] == "available":
            if not stroke_file.exists():
                raise DataError("Archived stroke samples are missing for " + key)
            strokes[key] = stroke_file
        records.append({key: result.get(key) for key in (
            "id", "date", "date_utc", "timezone", "distance", "time", "rest_distance",
            "contribution_meters", "type", "workout_type", "stroke_rate", "heart_rate",
        )})
    records.sort(key=lambda row: (row["date"], row["id"]), reverse=True)
    total = sum(row["contribution_meters"] for row in records)
    index = {
        "schema_version": 1, "title": config.get("title", "Rowing around the world"),
        "goal_meters": config["goal_meters"], "total_meters": total,
        "activity_count": len(records), "remaining_meters": max(0, config["goal_meters"] - total),
        "last_successful_sync": manifest["last_successful_sync"],
        "include_rest_distance": config["include_rest_distance"],
        "rowing_types": config["rowing_types"], "activities": records,
    }
    audit = {"archived_activities": len(manifest["activity_ids"]),
             "rowing_activities": len(records), "goal_meters_completed": total,
             "by_type": dict(by_type), "checkpoint": manifest["checkpoint"]}
    return index, details, strokes, audit


def build_site(archive, output, config, web_root):
    archive, output = Path(archive).resolve(), Path(output).resolve()
    if archive == output or archive in output.parents or output in archive.parents:
        raise DataError("The public output and private archive must be separate directories.")
    backup = output.with_name(output.name + ".previous")
    if backup.exists():
        if not (backup / ".rowing-site").is_file():
            raise DataError("An unrecognized backup directory needs inspection: " + str(backup))
        if not output.exists():
            os.replace(str(backup), str(output))
        elif (output / ".rowing-site").is_file():
            shutil.rmtree(backup)
        else:
            raise DataError("Refusing to overwrite an unrecognized output during recovery.")
    if output.exists() and any(output.iterdir()) and not (output / ".rowing-site").exists():
        raise DataError("Refusing to replace a directory not created by this site builder.")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".rowing-build-", dir=str(output.parent)))
    try:
        with archive_lock(archive):
            index, details, strokes, audit = make_data(archive, config)
            for name in ("index.html", "app.js", "style.css"):
                shutil.copy2(str(Path(web_root) / name), str(staging / name))
            write_json(staging / "data" / "index.json", index)
            for key, detail in details.items():
                write_json(staging / "data" / "activities" / (key + ".json"), detail)
            for key, stroke_file in strokes.items():
                # Project one workout at a time; keep the full lifetime archive
                # out of memory even when every activity has stroke telemetry.
                samples = read_json(stroke_file)["data"]
                write_json(staging / "data" / "strokes" / (key + ".json"),
                           {"data": [pick(sample, STROKE_FIELDS) for sample in samples]})
            (staging / ".rowing-site").write_text("Generated static output only.\n")
            (staging / ".nojekyll").touch()
            if backup.exists():
                raise DataError("A previous output backup needs inspection: " + str(backup))
            if output.exists():
                os.replace(str(output), str(backup))
            try:
                os.replace(str(staging), str(output))
            except OSError:
                if backup.exists():
                    os.replace(str(backup), str(output))
                raise
            if backup.exists():
                shutil.rmtree(backup)
        return audit
    finally:
        if staging.exists():
            shutil.rmtree(staging)
