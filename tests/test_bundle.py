"""Boundary tests for the bundled skill-library archive."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1] / "aio-skill"
SCRIPT = ROOT / "scripts" / "bundle_library.py"


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aio-bundle-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def run_cli(self, script, *args, cwd=None, env=None, check=True):
        e = os.environ.copy()
        for key in ("AIO_SKILLS_DIR", "AIO_SKILL_INDEX_DIR", "AIO_SKILL_CONFIG", "AIO_SKILL_CACHE_DIR"):
            e.pop(key, None)
        e["PYTHONUTF8"] = "1"
        e.update(env or {})
        p = subprocess.run([sys.executable, str(script), *map(str, args)], cwd=cwd or self.base,
                           env=e, capture_output=True, text=True, encoding="utf-8", timeout=60)
        if check:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def fixture_source(self):
        src = self.base / "library"
        (src / "alpha" / "resources").mkdir(parents=True)
        (src / "alpha" / "SKILL.md").write_text("---\nname: alpha\n---\n", encoding="utf-8")
        (src / "alpha" / "resources" / "guide.txt").write_text("resource", encoding="utf-8")
        (src / "LICENSE").write_text("MIT", encoding="utf-8")
        return src

    def test_pack_is_deterministic_and_manifest_has_no_absolute_source(self):
        src = self.fixture_source(); out = self.base / "out.zip"; manifest = self.base / "manifest.json"
        first = self.run_cli(SCRIPT, "pack", "--source", src, "--output", out, "--manifest", manifest)
        a = out.read_bytes(); info = json.loads(manifest.read_text())
        self.assertEqual(info["sha256"], hashlib.sha256(a).hexdigest())
        self.assertEqual(info["skill_count"], 1)
        self.assertNotIn(str(src), manifest.read_text())
        self.run_cli(SCRIPT, "pack", "--source", src, "--output", out, "--manifest", manifest)
        self.assertEqual(a, out.read_bytes())

    def test_relocated_bundle_extracts_and_default_selector_works_without_external_source(self):
        relocated = self.base / "relocated bundle"
        shutil.copytree(ROOT / "scripts", relocated / "scripts")
        source = self.fixture_source()
        (relocated / "assets").mkdir()
        self.run_cli(relocated / "scripts" / "bundle_library.py", "pack", "--source", source)
        self.run_cli(relocated / "scripts" / "build_catalog.py", "--source", source,
                     "--index-dir", relocated / "references")
        shutil.rmtree(source)
        cache = self.base / "isolated-cache"
        env = {"AIO_SKILL_CACHE_DIR": str(cache)}
        unpack = self.run_cli(relocated / "scripts" / "bundle_library.py", "unpack", env=env)
        extracted = Path(unpack.stdout.strip())
        self.assertEqual((extracted / "alpha" / "resources" / "guide.txt").read_text(), "resource")
        # The bundled catalog remains usable after relocating the router and with no source env.
        before = (extracted / ".complete").stat().st_mtime_ns
        result = self.run_cli(relocated / "scripts" / "select_skills.py", "search", "alpha", "--json", env=env)
        row = json.loads(result.stdout)[0]
        self.assertIs(row["available"], True)
        self.assertTrue(Path(row["path"]).samefile(extracted / "alpha" / "SKILL.md"))
        self.assertEqual(before, (extracted / ".complete").stat().st_mtime_ns)

    def test_unpack_rejects_zip_slip_entries(self):
        malicious = self.base / "malicious.zip"
        with zipfile.ZipFile(malicious, "w") as z:
            z.writestr("../escape.txt", "bad")
        router = self.base / "router"; shutil.copytree(ROOT, router)
        archive = router / "assets" / "skills-library.zip"; archive.write_bytes(malicious.read_bytes())
        manifest = json.loads((router / "assets" / "library-manifest.json").read_text())
        manifest["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        (router / "assets" / "library-manifest.json").write_text(json.dumps(manifest))
        result = self.run_cli(router / "scripts" / "bundle_library.py", "unpack", check=False,
                             env={"AIO_SKILL_CACHE_DIR": str(self.base / "cache")})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe", (result.stdout + result.stderr).lower())


if __name__ == "__main__":
    unittest.main()
