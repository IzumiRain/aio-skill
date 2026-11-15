#!/usr/bin/env python3
"""Shared portable configuration for AIO Skill."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROUTER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path.home() / ".aio-skill" / "library"
DEFAULT_INDEX = ROUTER_ROOT / "references"
DEFAULT_LOCAL_CONFIG = ROUTER_ROOT / "config.local.json"


@dataclass(frozen=True)
class Settings:
    source: Path
    index_dir: Path
    config_path: Path | None
    bundled: bool = False


def _path(value: Any, base: Path) -> Path | None:
    if value is None or not str(value).strip():
        return None
    if not isinstance(value, str):
        raise ValueError("Configured directory paths must be strings.")
    candidate = Path(value.strip()).expanduser()
    return candidate if candidate.is_absolute() else (base / candidate)


def _read_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a JSON object: {path}")
    return data


def settings(*, source: str | None = None, index_dir: str | None = None, config: str | None = None) -> Settings:
    """Resolve CLI > environment > local config > portable defaults."""

    config_path = _path(config, Path.cwd()) if config else None
    if config_path is None:
        env_config = os.environ.get("AIO_SKILL_CONFIG")
        config_path = _path(env_config, Path.cwd()) if env_config else DEFAULT_LOCAL_CONFIG
    if (config or os.environ.get("AIO_SKILL_CONFIG")) and not config_path.is_file():
        raise ValueError(f"Config file does not exist: {config_path}")
    values = _read_config(config_path)

    config_base = config_path.parent if config_path else ROUTER_ROOT
    from bundle_library import cache_directory
    bundled_source = cache_directory(ROUTER_ROOT)
    external_source = _path(source, Path.cwd()) or _path(os.environ.get("AIO_SKILLS_DIR"), Path.cwd()) or _path(values.get("skills_dir"), config_base)
    bundled = external_source is None and bundled_source is not None
    resolved_source = (external_source or bundled_source or DEFAULT_SOURCE).resolve()
    resolved_index = (_path(index_dir, Path.cwd()) or _path(os.environ.get("AIO_SKILL_INDEX_DIR"), Path.cwd()) or _path(values.get("index_dir"), config_base) or DEFAULT_INDEX).resolve()
    return Settings(source=resolved_source, index_dir=resolved_index, config_path=config_path if config_path and config_path.exists() else None, bundled=bundled)


def add_config_arguments(parser: Any) -> None:
    parser.add_argument("--source", help="Source skill library; overrides AIO_SKILLS_DIR and config.")
    parser.add_argument("--index-dir", help="Directory containing catalog.jsonl and library.json.")
    parser.add_argument("--config", help="Optional JSON config file.")


def safe_child(root: Path, relative: str) -> Path:
    """Resolve a catalog path without allowing traversal outside source."""

    root = root.resolve()
    if not relative or "\\" in relative or ":" in relative or relative.startswith("/") or ".." in relative.split("/"):
        raise ValueError(f"Unsafe catalog path: {relative}")
    candidate = (root / relative.replace("/", os.sep)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Catalog path escapes source root: {relative}") from exc
    return candidate
