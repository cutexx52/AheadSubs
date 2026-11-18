from contextlib import redirect_stderr
import io
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.ci import docs_only


class DocumentationCITests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = Path(directory.name)
        self.git("init", "--initial-branch=main")
        self.write("aheadsubs/service.py", "service")
        self.write("README.md", "docs")
        self.commit()

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-c", "user.name=CI test", "-c", "user.email=ci@example.test", *args],
            cwd=self.repo,
            stderr=subprocess.STDOUT,
        )

    def write(self, relative_path, content):
        path = self.repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "--no-gpg-sign", "--allow-empty", "-m", "Test snapshot")

    def test_only_pr_changes_count_against_updated_base(self):
        self.git("switch", "-c", "docs")
        self.write("README.md", "updated docs")
        self.write("docs/images/流程图.png", "fixture")
        self.write("docs/images/manifest.json", "{}")
        self.commit()

        self.git("switch", "main")
        self.write("aheadsubs/service.py", "already on main")
        self.commit()
        self.git("merge", "--no-ff", "--no-edit", "--no-gpg-sign", "docs")

        self.assertTrue(docs_only(self.repo))

    def test_mixed_change_runs_full_ci(self):
        self.write("README.md", "updated docs")
        self.write(".github/workflows/ci.yml", "updated workflow")
        self.commit()

        self.assertFalse(docs_only(self.repo))

    def test_moving_runtime_file_to_docs_runs_full_ci(self):
        (self.repo / "docs").mkdir()
        self.git("mv", "aheadsubs/service.py", "docs/service.md")
        self.commit()

        self.assertFalse(docs_only(self.repo))

    def test_unknown_documentation_directory_file_runs_full_ci(self):
        self.write("docs/dependency-licenses.json", "{}")
        self.commit()

        self.assertFalse(docs_only(self.repo))

    def test_empty_diff_runs_full_ci(self):
        self.commit()

        self.assertFalse(docs_only(self.repo))

    def test_unavailable_base_runs_full_ci(self):
        with redirect_stderr(io.StringIO()) as errors:
            self.assertFalse(docs_only(self.repo))
        self.assertIn("Running full CI", errors.getvalue())
