import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tracker_cli", ROOT / "scripts/tracker.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class RefreshTests(unittest.TestCase):
    def test_failed_sync_does_not_build_and_closes_connection(self):
        client = MagicMock()
        with patch.dict("os.environ", {"CONCEPT2_TOKEN": "TEST-TOKEN"}), \
                patch("sys.argv", ["tracker.py", "refresh"]), \
                patch.object(cli, "Concept2", return_value=client), \
                patch.object(cli, "sync", side_effect=cli.APIError("Simulated failure")), \
                patch.object(cli, "build_site") as build, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(), 1)
        build.assert_not_called()
        client.close.assert_called_once_with()

    def test_successful_refresh_builds_from_the_requested_archive(self):
        client = MagicMock()
        calls = []
        def imported(*args, **kwargs):
            calls.append("sync")
            return {"archived": 1}
        def built(*args, **kwargs):
            calls.append("build")
            self.assertEqual(args[0], Path("test-archive"))
            self.assertEqual(args[1], Path("test-site"))
            return {"rowing_activities": 1}
        with patch.dict("os.environ", {"CONCEPT2_TOKEN": "TEST-TOKEN"}), \
                patch("sys.argv", ["tracker.py", "refresh", "--archive", "test-archive", "--output", "test-site"]), \
                patch.object(cli, "Concept2", return_value=client), \
                patch.object(cli, "sync", side_effect=imported), \
                patch.object(cli, "build_site", side_effect=built), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(calls, ["sync", "build"])
        client.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
