#!/usr/bin/env python3
"""Pack and safely cache the complete external skill library (stdlib only)."""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, stat, tempfile, zipfile
from pathlib import Path

SCHEMA = "1.0.0"
EXCLUDE = {".git", "node_modules", "__pycache__"}
BAD_NAMES = {".env", ".env.local", ".env.production", "credentials", "credentials.json", "secrets", "secrets.json"}

def bundle_info(router_root: Path) -> dict | None:
    p = router_root / "assets" / "library-manifest.json"
    try: return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): return None

def _archive(router_root: Path) -> Path:
    return router_root / "assets" / "skills-library.zip"

def cache_directory(router_root: Path) -> Path | None:
    root = os.environ.get("AIO_SKILL_CACHE_DIR")
    if not root:
        root = os.environ.get("LOCALAPPDATA") + "\\aio-skill" if os.name == "nt" and os.environ.get("LOCALAPPDATA") else None
    if not root: root = (Path(os.environ["XDG_CACHE_HOME"]) / "aio-skill" if os.environ.get("XDG_CACHE_HOME") else Path.home() / ".cache" / "aio-skill")
    info = bundle_info(router_root)
    digest = info.get("sha256") if isinstance(info, dict) else None
    return Path(root).expanduser() / digest if isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest) else None

def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""): h.update(b)
    return h.hexdigest()

def _safe(name: str) -> None:
    p = Path(name)
    if not name or p.is_absolute() or "\\" in name or ":" in name or ".." in p.parts: raise ValueError(f"unsafe archive path: {name}")

def ensure_library(router_root: Path) -> Path:
    archive = _archive(router_root); info = bundle_info(router_root)
    if not archive.is_file() or not isinstance(info, dict) or info.get("schema_version") != SCHEMA: raise RuntimeError("library bundle or manifest missing")
    if _digest(archive) != info.get("sha256"): raise RuntimeError("library archive hash mismatch")
    target = cache_directory(router_root)
    if target is None: raise RuntimeError("cannot determine cache directory")
    sentinel = target / ".complete"
    if sentinel.is_file() and sentinel.read_text(encoding="ascii", errors="ignore").strip() == info["sha256"]: return target
    parent = target.parent; parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=parent))
    try:
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                _safe(item.filename)
                mode = (item.external_attr >> 16) & 0xffff
                if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or mode == 0): raise ValueError(f"unsafe archive entry: {item.filename}")
                dest = (tmp / item.filename).resolve()
                if tmp.resolve() not in dest.parents and dest != tmp.resolve(): raise ValueError(f"archive traversal: {item.filename}")
                if item.is_dir(): dest.mkdir(parents=True, exist_ok=True); continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(item) as src, dest.open("wb") as out: shutil.copyfileobj(src, out)
                os.chmod(dest, mode & 0o777 or 0o644)
        (tmp / ".complete").write_text(info["sha256"], encoding="ascii")
        try:
            os.rename(tmp, target)
        except OSError:
            if sentinel.is_file() and sentinel.read_text(encoding="ascii", errors="ignore").strip() == info["sha256"]:
                shutil.rmtree(tmp); return target
            raise RuntimeError(f"Incomplete cache exists; remove it before retrying: {target}")
        return target
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True); raise

def pack(source: Path, archive: Path, manifest_path: Path) -> dict:
    source = source.resolve(); files=[]; licenses=[]; skills=0
    if not source.is_dir(): raise ValueError(f"source does not exist: {source}")
    for p in sorted(source.rglob("*"), key=lambda candidate: candidate.relative_to(source).as_posix()):
        rel=p.relative_to(source); parts=set(rel.parts)
        if parts & EXCLUDE or p.suffix == ".pyc": continue
        if any((x.lower() in BAD_NAMES or x.lower().startswith(".env.")) and not x.lower().endswith((".example", ".sample", ".template")) for x in rel.parts): raise ValueError(f"credential-like file found: {rel}")
        if p.is_symlink(): raise ValueError(f"symlink found: {rel}")
        if p.is_dir(): continue
        if not p.is_file(): raise ValueError(f"special file found: {rel}")
        files.append(p)
        if p.name == "SKILL.md": skills += 1
        if "license" in p.name.lower() or p.name.lower() in ("copying", "notice"): licenses.append(rel.as_posix())
    if not skills: raise ValueError(f"No SKILL.md entrypoints found in source: {source}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with tempfile.NamedTemporaryFile(dir=archive.parent, delete=False) as f: temp=Path(f.name)
    try:
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as z:
            for p in files:
                data = p.read_bytes(); size += len(data)
                rel=p.relative_to(source).as_posix(); zi=zipfile.ZipInfo(rel, (1980,1,1,0,0,0)); zi.create_system=3; zi.compress_type=zipfile.ZIP_DEFLATED; zi.external_attr=((stat.S_IFREG | (0o755 if p.stat().st_mode & 0o111 else 0o644)) << 16); z.writestr(zi,data)
        digest=_digest(temp); os.replace(temp, archive)
    finally:
        if temp.exists(): temp.unlink()
    info={"schema_version":SCHEMA,"sha256":digest,"file_count":len(files),"bytes_uncompressed":size,"skill_count":skills,"license_files":licenses}
    manifest_path.parent.mkdir(parents=True, exist_ok=True); manifest_path.write_text(json.dumps(info,indent=2)+"\n",encoding="utf-8"); return info

def main() -> int:
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd",required=True); packer=sub.add_parser("pack"); packer.add_argument("--source",required=True); packer.add_argument("--output",default=None); packer.add_argument("--manifest",default=None); sub.add_parser("unpack")
    a=p.parse_args(); root=Path(__file__).resolve().parents[1]
    try:
        if a.cmd=="pack":
            info=pack(Path(a.source),Path(a.output) if a.output else _archive(root),Path(a.manifest) if a.manifest else root/"assets"/"library-manifest.json"); print(json.dumps(info,indent=2)); return 0
        print(ensure_library(root)); return 0
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        p.error(str(exc))
if __name__ == "__main__": raise SystemExit(main())
