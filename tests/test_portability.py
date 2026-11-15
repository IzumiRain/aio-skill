"""Portable router contracts, exercised only through the public CLI.

Run with: python -m unittest discover -s tests -v
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROUTER = Path(__file__).resolve().parents[1] / "aio-skill"


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="router-contract-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "original-library"
        self.index = self.root / "custom-index"
        self.cwd = self.root / "unrelated-working-directory"
        self.cwd.mkdir()
        self.make_library(self.source)

    def make_library(self, root, name="portable-widget"):
        entries = ((name, "Portable widget documentation and resource guide"),
                   ("other-tool", "Database maintenance operations"),
                   ("bundle/nested-tool", "Nested weather observations"))
        for ident, description in entries:
            folder = root / ident
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "SKILL.md").write_text(
                f"---\nname: {Path(ident).name}\ndescription: {description}\n---\n"
                "Read resources/guide.txt when relevant.\n", encoding="utf-8")
        resources = root / name / "resources"
        resources.mkdir()
        (resources / "guide.txt").write_text("Resource survives relocation.\n", encoding="utf-8")

    def cli(self, script, *args, router=ROUTER, env=None, ok=True):
        clean_env = os.environ.copy()
        for key in ("AIO_SKILLS_DIR", "AIO_SKILL_INDEX_DIR", "AIO_SKILL_CONFIG"):
            clean_env.pop(key, None)
        clean_env["PYTHONUTF8"] = "1"
        clean_env.update(env or {})
        result = subprocess.run(
            [sys.executable, str(router / "scripts" / script), *map(str, args)],
            cwd=self.cwd, env=clean_env, text=True, encoding="utf-8",
            capture_output=True, timeout=30)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def build(self, source=None, index=None, **kwargs):
        return self.cli("build_catalog.py", "--source", source or self.source,
                        "--index-dir", index or self.index, **kwargs)

    def query(self, *options, router=ROUTER, env=None):
        result = self.cli("select_skills.py", "search", "portable-widget",
                          *options, "--json", router=router, env=env)
        rows = json.loads(result.stdout)
        self.assertTrue(rows, result.stdout)
        return next(row for row in rows if row["id"] == "portable-widget")

    def test_relocation_resolves_paths_without_rebuild_and_preserves_resources(self):
        self.build()
        catalog = self.index / "catalog.jsonl"
        rows = [json.loads(line) for line in catalog.read_text(encoding="utf-8").splitlines()]
        self.assertEqual({row["relative_path"] for row in rows}, {
            "portable-widget/SKILL.md", "other-tool/SKILL.md", "bundle/nested-tool/SKILL.md"})
        self.assertTrue(all("path" not in row for row in rows))
        for file in self.index.iterdir():
            if file.is_file():
                self.assertNotIn(str(self.source), file.read_text(encoding="utf-8"))
                self.assertNotIn(str(self.source).replace("\\", "\\\\"), file.read_text(encoding="utf-8"))
        relocated = self.root / "relocated space فارسی"
        relocated.mkdir()
        router = relocated / "router"
        source = relocated / "skill library"
        index = relocated / "routing index"
        shutil.copytree(ROUTER, router)
        shutil.move(str(self.source), source)
        shutil.move(str(self.index), index)
        self.assertFalse(self.source.exists())
        before = {p.name: p.read_bytes() for p in index.iterdir() if p.is_file()}
        row = self.query("--source", source, "--index-dir", index, router=router)
        self.assertIs(row["available"], True)
        self.assertEqual(Path(row["path"]), source / "portable-widget" / "SKILL.md")
        self.assertTrue(Path(row["path"]).is_absolute())
        self.assertEqual((Path(row["path"]).parent / "resources" / "guide.txt").read_text(),
                         "Resource survives relocation.\n")
        shown = json.loads(self.cli("select_skills.py", "show", "bundle/nested-tool",
                           "--source", source, "--index-dir", index, "--json", router=router).stdout)
        self.assertEqual(Path(shown["path"]), source / "bundle/nested-tool/SKILL.md")
        self.assertIs(shown["available"], True)
        self.assertEqual(before, {p.name: p.read_bytes() for p in index.iterdir() if p.is_file()})

    def test_config_relative_paths_and_cli_env_precedence(self):
        config_dir = self.root / "configuration"
        config_dir.mkdir()
        config_source = config_dir / "library"
        config_index = config_dir / "index"
        self.make_library(config_source)
        entry = config_source / "portable-widget/SKILL.md"
        entry.write_text(entry.read_text(encoding="utf-8").replace(
            "Portable widget documentation", "Portable widget config-marker documentation"), encoding="utf-8")
        config = config_dir / "router.json"
        config.write_text(json.dumps({"skills_dir": "library", "index_dir": "index"}), encoding="utf-8")
        self.cli("build_catalog.py", "--config", config)
        row = self.query("--config", config)
        self.assertEqual(Path(row["path"]), config_source / "portable-widget/SKILL.md")
        self.assertIn("config-marker", row["description"])
        self.build()
        env = {"AIO_SKILLS_DIR": str(self.source), "AIO_SKILL_INDEX_DIR": str(self.index)}
        row = self.query("--config", config, env=env)
        self.assertEqual(Path(row["path"]), self.source / "portable-widget/SKILL.md")
        self.assertNotIn("config-marker", row["description"])
        row = self.query("--config", config, "--source", config_source,
                         "--index-dir", config_index, env=env)
        self.assertEqual(Path(row["path"]), config_source / "portable-widget/SKILL.md")
        self.assertIn("config-marker", row["description"])

    def test_rebuild_is_deterministic_and_empty_source_preserves_index(self):
        self.build()
        before = {p.name: p.read_bytes() for p in self.index.iterdir() if p.is_file()}
        self.build()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.index.iterdir() if p.is_file()})
        empty = self.root / "empty-library"
        empty.mkdir()
        result = self.build(source=empty, ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.index.iterdir() if p.is_file()})

    def test_doctor_reports_missing_entrypoint_and_rejects_traversal(self):
        self.build()
        def doctor():
            result = self.cli("select_skills.py", "doctor", "--source", self.source,
                              "--index-dir", self.index, "--json", ok=False)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            try:
                return json.dumps(json.loads(result.stdout)).lower()
            except json.JSONDecodeError:
                self.fail("doctor --json did not return JSON: " + result.stdout + result.stderr)
        entry = self.source / "portable-widget/SKILL.md"
        original = entry.read_bytes()
        entry.unlink()
        self.assertIn("missing", doctor())
        row = self.query("--source", self.source, "--index-dir", self.index)
        self.assertIs(row["available"], False)
        entry.write_bytes(original)
        catalog = self.index / "catalog.jsonl"
        rows = [json.loads(line) for line in catalog.read_text(encoding="utf-8").splitlines()]
        rows[0]["relative_path"] = "../outside/SKILL.md"
        catalog.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        self.assertRegex(doctor(), r"traversal|outside|escape|unsafe")


if __name__ == "__main__":
    unittest.main()
