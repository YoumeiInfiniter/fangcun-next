"""Unit tests for clean release package building."""

import tempfile
import unittest
from pathlib import Path
import zipfile

from scripts.release_builder import build_package, check_private_isolation, iter_package_files


class ReleaseBuilderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name) / "dist" / "test.zip"

    def tearDown(self):
        self._tmp.cleanup()

    def test_build_package_excludes_legacy_and_private_dirs(self):
        zip_path = build_package(self.out)
        self.assertTrue(zip_path.exists())
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        joined = "\n".join(names)
        self.assertIn("fangcun-next-0.3.2/SKILL.md", joined)
        self.assertIn("fangcun-next-0.3.2/scripts/project_cli.py", joined)
        self.assertIn("fangcun-next-0.3.2/references/schemas/project-config.schema.json", joined)
        for excluded in ("tests/", "skills/", "docs/", "tools/", "hooks/", "memory/", "projects/"):
            self.assertNotIn(excluded, joined)
        manifest = self.out.parent / "release_manifest.json"
        self.assertTrue(manifest.exists())
        data = __import__("json").loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], "0.3.2")

    def test_check_private_isolation_flags_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.py").write_text("print('hello')", encoding="utf-8")
            (root / "leak.py").write_text("api_key = 'sk-1234567890abcdefghijklmnop'", encoding="utf-8")
            files = iter_package_files(root)
            problems = check_private_isolation(files)
            self.assertEqual(len(problems), 1)
            self.assertIn("leak.py", problems[0])

    def test_package_excludes_egg_info_directories(self):
        zip_path = build_package(self.out)
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        self.assertFalse(any(".egg-info" in name for name in names))

    def test_build_package_raises_on_secret(self):
        import scripts.release_builder as rb

        original_root = rb.skill_root
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            (fake_root / "SKILL.md").write_text("# skill", encoding="utf-8")
            (fake_root / "scripts").mkdir()
            (fake_root / "scripts" / "x.py").write_text("token='feishu.cn/base/AbCdEf123'", encoding="utf-8")
            rb.skill_root = lambda: fake_root
            try:
                with self.assertRaises(RuntimeError):
                    build_package(Path(tmp) / "out.zip")
            finally:
                rb.skill_root = original_root


if __name__ == "__main__":
    unittest.main()
