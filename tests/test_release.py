import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest.mock import patch
import os
import tempfile

spec = importlib.util.spec_from_file_location("release_tools", Path(__file__).resolve().parents[1] / "tools/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 17, tzinfo=timezone.utc)

    def history(self, hours=72, draft=False):
        return [{"draft": draft, "published_at": (self.now - timedelta(hours=hours)).isoformat()}]

    def test_cooldown_boundary_and_no_changes(self):
        self.assertFalse(release.preview_due(self.history(71.99), self.now, ["desktop/App.xaml"])[0])
        self.assertTrue(release.preview_due(self.history(72), self.now, ["desktop/App.xaml"])[0])
        self.assertFalse(release.preview_due(self.history(100), self.now, [])[0])

    def test_docs_tests_and_drafts_do_not_create_releases(self):
        self.assertFalse(release.preview_due([], self.now, ["README.md", "docs/images/hero.png", "tests/test_release.py"])[0])
        self.assertTrue(release.preview_due(self.history(1, draft=True), self.now, ["pyproject.toml"])[0])
        self.assertTrue(release.preview_due([], self.now, ["new-runtime-file"])[0])

    def test_release_asset_completeness_and_limits(self):
        tag = "v0.1.0-preview.abc123"
        assets = [{"name": n, "size": 42, "state": "uploaded"} for n in release.asset_names(tag)]
        release.validate_assets(tag, assets)
        with self.assertRaises(RuntimeError):
            release.validate_assets(tag, assets[:-1])
        assets[0]["size"] = 2**31
        with self.assertRaises(RuntimeError):
            release.validate_assets(tag, assets)
        assets[0]["size"] = 1
        assets[0]["state"] = "starter"
        with self.assertRaises(RuntimeError):
            release.validate_assets(tag, assets)

    @patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_EVENT_NAME": "schedule"})
    @patch.object(release, "output")
    @patch.object(release, "api", return_value={"private": True})
    @patch.object(release, "run", return_value="a" * 40)
    def test_private_repo_stops_before_any_build(self, run, api, output):
        release.plan()
        self.assertEqual(output.call_args.args[0]["build"], "false")
        self.assertEqual(api.call_count, 1)

    @patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_EVENT_NAME": "schedule"})
    def test_first_preview_requires_successful_exact_head_ci(self):
        sha = "a" * 40
        for conclusion in ("failure", "cancelled", "success"):
            with self.subTest(conclusion=conclusion), patch.object(release, "run", side_effect=[sha, "pyproject.toml"]), \
                    patch.object(release, "api", side_effect=[
                        {"private": False, "default_branch": "main"}, {"sha": sha}, [[]],
                        {"workflow_runs": [{"status": "completed", "conclusion": conclusion}]},
                    ]), patch.object(release, "output") as output:
                release.plan()
                result = output.call_args.args[0]
                self.assertEqual(result["build"], str(conclusion == "success").lower())
                if conclusion == "success":
                    self.assertEqual(result["sha"], sha)
                    self.assertTrue(result["tag"].endswith("-preview." + sha[:12]))
                    self.assertEqual(result["publish"], "true")

    @patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_EVENT_NAME": "schedule"})
    def test_preview_rejects_non_default_head(self):
        with patch.object(release, "run", return_value="a" * 40), patch.object(release, "api", side_effect=[
            {"private": False, "default_branch": "main"}, {"sha": "b" * 40},
        ]), self.assertRaises(RuntimeError):
            release.plan()

    @patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_EVENT_NAME": "workflow_dispatch",
                            "RELEASE_MODE": "verify", "RELEASE_VERSION": "0.1.0-check"})
    def test_manual_verification_never_publishes(self):
        with patch.object(release, "run", return_value="a" * 40), \
                patch.object(release, "api", return_value={"private": False}), patch.object(release, "output") as output:
            release.plan()
            self.assertEqual(output.call_args.args[0]["publish"], "false")
            self.assertEqual(output.call_args.args[0]["build"], "true")

    @patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"})
    @patch.object(release, "run")
    @patch.object(release, "api")
    def test_draft_retry_never_overwrites_published_release(self, api, run):
        sha = "a" * 40
        api.return_value = [[{"tag_name": "v0.1.0", "draft": False, "body": f"<!-- aheadsubs-source:{sha} -->"}]]
        with self.assertRaises(RuntimeError):
            release.draft("v0.1.0", sha)
        run.assert_not_called()
        api.return_value[0][0]["draft"] = True
        release.draft("v0.1.0", sha)
        run.assert_not_called()

    @patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"})
    @patch.object(release, "run")
    @patch.object(release, "api")
    def test_publish_rejects_moved_tag(self, api, run):
        sha = "a" * 40
        api.return_value = {"draft": True, "body": f"<!-- aheadsubs-source:{sha} -->",
                            "assets": [{"name": n, "size": 42, "state": "uploaded"} for n in release.asset_names("v0.1.0")]}
        run.return_value = f"{'b' * 40}\trefs/tags/v0.1.0"
        with self.assertRaises(RuntimeError):
            release.publish_release("v0.1.0", sha)
        self.assertEqual(run.call_count, 1)

    @patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"})
    @patch.object(release, "run")
    @patch.object(release, "api")
    def test_bad_checksum_cannot_upload(self, api, run):
        sha = "a" * 40
        tag = "v0.1.0"
        api.return_value = {"draft": True, "body": f"<!-- aheadsubs-source:{sha} -->"}
        with tempfile.TemporaryDirectory() as folder, patch.object(release, "ROOT", Path(folder)):
            dist = Path(folder) / "dist"
            dist.mkdir()
            stem = "aheadsubs-v0.1.0-windows-x64"
            (dist / f"{stem}-setup.exe").write_bytes(b"test")
            (dist / f"{stem}-portable.zip").write_bytes(b"test")
            (dist / f"{stem}-SHA256.txt").write_text(f"{'0'*64}  {stem}-setup.exe\n", encoding="ascii")
            with self.assertRaises(RuntimeError):
                release.upload(tag, sha)
        run.assert_not_called()
