#!/usr/bin/env python3
"""Run from any directory; Python 3.9+, no third-party dependencies."""

import argparse
import getpass
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rowing_tracker.archive import DataError, archive_lock, read_json, sync
from rowing_tracker.client import APIError, Concept2
from rowing_tracker.site import build_site, make_data


def setup_token():
    if not sys.stdin.isatty():
        raise DataError("Run setup-token in an interactive terminal so the token stays hidden.")
    token = getpass.getpass("Paste your Concept2 personal API token (hidden): ").strip()
    if not token or any(c.isspace() for c in token):
        raise DataError("The token is empty or contains whitespace.")
    folder = ROOT / ".secrets"
    folder.mkdir(mode=0o700, exist_ok=True)
    os.chmod(str(folder), 0o700)
    path = folder / "concept2-token"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(token + "\n")
    os.chmod(str(path), 0o600)
    print("Token saved locally in the ignored .secrets directory. It has not been printed or tested.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup-token", help="Securely save a local token without echoing it")
    for name, description in (("sync", "Read Concept2 results into the archive"),
                              ("refresh", "Read new/edited workouts and rebuild the local website")):
        import_parser = commands.add_parser(name, help=description)
        import_parser.add_argument("--full", action="store_true", help="Reconcile the complete activity list")
        import_parser.add_argument("--archive", type=Path, default=ROOT / "data" / "archive")
        if name == "refresh":
            import_parser.add_argument("--config", type=Path, default=ROOT / "config.json")
            import_parser.add_argument("--output", type=Path, default=ROOT / "dist")
    for name in ("build", "audit"):
        sub = commands.add_parser(name)
        sub.add_argument("--archive", type=Path, default=ROOT / "data" / "archive")
        sub.add_argument("--config", type=Path, default=ROOT / "config.json")
        if name == "build":
            sub.add_argument("--output", type=Path, default=ROOT / "dist")
        else:
            sub.add_argument("--expected-meters", type=int)
            sub.add_argument("--expected-activities", type=int)
    args = parser.parse_args()
    try:
        if args.command == "setup-token":
            setup_token()
        elif args.command in ("sync", "refresh"):
            token = os.environ.get("CONCEPT2_TOKEN", "").strip()
            saved = ROOT / ".secrets" / "concept2-token"
            if not token and saved.exists():
                token = saved.read_text().strip()
            if not token:
                raise DataError("No token configured. Run: python3 scripts/tracker.py setup-token")
            client = Concept2(token)
            try:
                report = sync(client, args.archive, args.full, progress=print)
            finally:
                client.close()
            print(json.dumps(report, indent=2))
            if args.command == "refresh":
                # An import failure must never continue into a website build.
                built = build_site(args.archive, args.output, read_json(args.config), ROOT / "web")
                print("Built public files in " + str(args.output.resolve()))
                print(json.dumps(built, indent=2))
        elif args.command == "build":
            report = build_site(args.archive, args.output, read_json(args.config), ROOT / "web")
            print("Built public files in " + str(args.output.resolve()))
            print(json.dumps(report, indent=2))
        elif args.command == "audit":
            with archive_lock(args.archive):
                _, _, _, report = make_data(args.archive, read_json(args.config))
            print(json.dumps(report, indent=2))
            if args.expected_meters is not None and report["goal_meters_completed"] != args.expected_meters:
                raise DataError("Distance differs from the expected logbook total.")
            if args.expected_activities is not None and report["rowing_activities"] != args.expected_activities:
                raise DataError("Activity count differs from the expected logbook count.")
        return 0
    except (DataError, APIError, ValueError, KeyError, OSError) as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
