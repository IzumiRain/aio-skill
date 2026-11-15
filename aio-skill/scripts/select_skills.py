#!/usr/bin/env python3
"""Read-only lexical selector for the AIO skill catalog."""
from __future__ import annotations
import argparse, hashlib, json, math, re, sys
from collections import Counter
from pathlib import Path

from router_config import ROUTER_ROOT, add_config_arguments, safe_child, settings
from bundle_library import ensure_library

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")
ALIASES = {
    "\u0631\u0627\u0633\u062a\u200c\u0686\u06cc\u0646": "rtl right-to-left",
    "\u062f\u0633\u062a\u0631\u0633\u200c\u067e\u0630\u06cc\u0631\u06cc": "accessibility a11y",
    "\u0622\u0632\u0645\u0648\u0646": "test testing",
    "\u062f\u06cc\u067e\u0644\u0648\u06cc": "deploy deployment",
    "\u0648\u0631\u062f": "word docx",
    "\u0627\u06a9\u0633\u0644": "excel spreadsheet xlsx",
    "\u0627\u0645\u0646\u06cc\u062a": "security secure",
    "\u0641\u0631\u0627\u0646\u062a": "frontend front-end",
    "\u062f\u06cc\u062a\u0627\u0628\u06cc\u0633": "database db",
    "\u067e\u0627\u06cc\u06af\u0627\u0647\u200c\u062f\u0627\u062f\u0647": "database db",
    "\u0647\u0648\u0634 \u0645\u0635\u0646\u0648\u0639\u06cc": "ai artificial intelligence",
    "\u062a\u0631\u062c\u0645\u0647": "translation translate",
    "\u0648\u0628": "web website",
    "\u06af\u0632\u0627\u0631\u0634": "report",
    "\u0633\u0627\u062e\u062a": "create build",
    "\u0627\u06cc\u062c\u0627\u062f": "create build",
    "\u062c\u062f\u06cc\u062f": "new",
    "\u0631\u0627\u0647\u0646\u0645\u0627": "guide documentation",
    "\u0628\u0631\u0631\u0633\u06cc": "review audit",
}
def _text(x): return str(x or "")
def tokens(s): return re.findall(r"[^\W_]+(?:\+\+|#)?", normalize(s), flags=re.UNICODE)
def normalize(q): return q.casefold().replace("\u200c", "").replace("\u064a", "\u06cc").replace("\u0643", "\u06a9")
def expand(q):
    q = normalize(q)
    out = q
    for fa, en in ALIASES.items():
        if normalize(fa) in q: out += " " + en
    return out

def load(index_dir: Path):
    catalog = index_dir / "catalog.jsonl"
    metadata = index_dir / "library.json"
    if not catalog.exists(): raise RuntimeError(f"catalog not found: {catalog}")
    rows = []
    with catalog.open(encoding="utf-8-sig") as f:
        for n, line in enumerate(f, 1):
            if not line.strip(): continue
            try: rows.append(json.loads(line))
            except json.JSONDecodeError as e: raise RuntimeError(f"invalid catalog JSON on line {n}: {e}")
    if not metadata.exists(): raise RuntimeError(f"metadata not found: {metadata}")
    try:
        library = json.loads(metadata.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"invalid metadata JSON: {metadata}: {e}") from e
    return rows, library


def shape_errors(rows, library):
    errors = []
    if not isinstance(library, dict):
        return ["library.json must contain a JSON object."]
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        errors.append("catalog.jsonl must contain one JSON object per line.")
    elif any(any(not isinstance(row.get(key), str) for key in ('id', 'name', 'description', 'category', 'relative_path')) or not isinstance(row.get('tags', []), list) or any(not isinstance(tag, str) for tag in row.get('tags', [])) for row in rows):
        errors.append("Catalog entry IDs, names, descriptions, categories and paths must be strings; tags must be a list of strings.")
    if not isinstance(library.get("schema_version"), str):
        errors.append("library.json.schema_version must be a string.")
    if not isinstance(library.get("skills_count"), int):
        errors.append("library.json.skills_count must be an integer.")
    categories = library.get("categories")
    if not isinstance(categories, list) or any(not isinstance(item, dict) for item in categories):
        errors.append("library.json.categories must be a list of objects.")
    elif any(not isinstance(item.get('id'), str) or not isinstance(item.get('count'), int) for item in categories):
        errors.append("Category IDs must be strings and counts must be integers.")
    return errors

def summary(r):
    d = re.sub(r"\s+", " ", _text(r.get("description"))).strip()
    return d[:317] + "..." if len(d) > 320 else d


def resolved_path(row, source: Path):
    relative = row.get("relative_path")
    if not isinstance(relative, str) or not relative:
        return None, False
    try:
        candidate = safe_child(source, relative)
    except ValueError:
        return None, False
    return candidate, candidate.is_file()


def result_row(row, source: Path):
    path, available = resolved_path(row, source)
    return {"id": row.get("id"), "name": row.get("name"), "description": summary(row), "category": row.get("category") or "uncategorized", "risk": row.get("risk") or "", "path": str(path) if path else None, "available": available, "tags": row.get("tags", [])}

def main(argv=None):
    p = argparse.ArgumentParser(prog="select_skills.py", description="Search and inspect the read-only AIO skill catalog.", epilog='Command prefix: python <skill-folder>/scripts/select_skills.py. Examples: search "frontend accessibility" --limit 8; categories; show agent-browser. Reads catalog metadata only; never executes skills or reads their bodies.')
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="search skills by name, ID, description, or tags"); s.add_argument("query"); s.add_argument("--category"); s.add_argument("--limit", type=int, default=8); s.add_argument("--json", action="store_true")
    c = sub.add_parser("categories", help="list catalog categories"); c.add_argument("--json", action="store_true")
    sh = sub.add_parser("show", help="show one skill by exact ID"); sh.add_argument("id"); sh.add_argument("--json", action="store_true")
    doctor = sub.add_parser("doctor", help="validate the index and source paths"); doctor.add_argument("--json", action="store_true")
    for command in (s, c, sh, doctor):
        add_config_arguments(command)
    a = p.parse_args(argv)
    try:
        configured = settings(source=a.source, index_dir=a.index_dir, config=a.config)
        if configured.bundled and a.cmd != 'categories':
            ensure_library(ROUTER_ROOT)
        rows, library = load(configured.index_dir)
    except (RuntimeError, OSError, UnicodeError, ValueError) as e:
        if a.cmd == "doctor":
            print(json.dumps({'ok': False, 'errors': [str(e)]}, ensure_ascii=False, indent=2) if a.json else str(e))
            return 1
        p.error(str(e))
    structural_errors = shape_errors(rows, library)
    if structural_errors and a.cmd == 'doctor':
        print(json.dumps({'ok': False, 'errors': structural_errors}, ensure_ascii=False, indent=2) if a.json else '\n'.join(structural_errors))
        return 1
    if structural_errors and a.cmd != "doctor":
        p.error(" ".join(structural_errors))
    if a.cmd == "doctor":
        errors = list(structural_errors)
        if not isinstance(rows, list):
            rows = []
        rows = [row for row in rows if isinstance(row, dict)]
        if not isinstance(library, dict):
            library = {}
        if library.get('schema_version') != '1.0.0': errors.append('Unsupported catalog schema; rebuild the index.')
        if library.get('skills_count') != len(rows): errors.append('Catalog count differs from metadata; rebuild the index.')
        expected_hash = library.get('catalog_sha256')
        if expected_hash and hashlib.sha256((configured.index_dir / 'catalog.jsonl').read_bytes()).hexdigest() != expected_hash:
            errors.append('Catalog integrity mismatch; rebuild the index.')
        if len({r.get('id') for r in rows}) != len(rows): errors.append('Duplicate catalog IDs.')
        if not configured.source.is_dir(): errors.append(f'Missing source directory: {configured.source}')
        for row in rows:
            path, available = resolved_path(row, configured.source)
            if path is None: errors.append(f'Unsafe catalog path (possible traversal) or missing relative_path: {row.get("id")}')
            elif not available: errors.append(f'Missing skill: {row.get("id")} ({path})')
        report = {'ok': not errors, 'skills_count': len(rows), 'source': str(configured.source), 'index_dir': str(configured.index_dir), 'errors': errors}
        print(json.dumps(report, ensure_ascii=False, indent=2) if a.json else ('OK' if not errors else '\n'.join(errors)))
        return 0 if not errors else 1
    if a.cmd == "categories":
        data = library.get('categories', [])
        print(json.dumps(data, ensure_ascii=False, indent=2) if a.json else "\n".join(f"{x.get('id')}: {x.get('title','')} ({x.get('count',0)})" for x in data)); return 0
    if a.cmd == "show":
        found = next((r for r in rows if r.get("id") == a.id), None)
        if not found: print(f"No skill found for ID: {a.id}", file=sys.stderr); return 1
        result = result_row(found, configured.source)
        print(json.dumps(result, ensure_ascii=False, indent=2) if a.json else f"{result['name']} [{result['category']}]\n{result['description']}\n{result['path']}\nAvailable: {result['available']}"); return 0
    if not 1 <= a.limit <= 30: p.error("--limit must be between 1 and 30")
    valid = {x.get("id") for x in library.get('categories', [])}
    if a.category and a.category not in valid: p.error(f"invalid category: {a.category}")
    q = expand(a.query)
    stopwords = set('a an and are as at be by can do for from help i in is it me of on or please set that the this to up use using want with you'.split())
    qt = set(tokens(q)) - stopwords
    exact = normalize(a.query).strip()
    if not exact: p.error("query must not be empty")
    if not qt: qt = set(tokens(q))
    fields = []
    frequencies = Counter()
    for r in rows:
        names = set(tokens(_text(r.get('id')) + ' ' + _text(r.get('name'))))
        tags = set(tokens(' '.join(map(_text, r.get('tags', [])))))
        desc = set(tokens(_text(r.get('description'))))
        fields.append((names, tags, desc))
        frequencies.update(names | tags | desc)
    weights = {t: math.log(1 + (len(rows) - frequencies[t] + 0.5) / (frequencies[t] + 0.5)) for t in qt}
    scored = []
    for r, (names, tags, desc) in zip(rows, fields):
        cat = _text(r.get("category")) or "uncategorized"
        if a.category and cat != a.category: continue
        ident = normalize(_text(r.get("id")) + " " + _text(r.get("name")))
        matched = qt & (names | tags | desc)
        score = sum(weights[t] * (8 * (t in names) + 2 * (t in tags) + 1.5 * (t in desc)) for t in matched)
        score *= 0.35 + 0.65 * (len(matched) / max(len(qt), 1)) ** 2
        if exact in {normalize(_text(r.get("id"))), normalize(_text(r.get("name")))}: score += 10000
        elif exact in ident: score += 30
        if r.get('entry_type') == 'example' and exact != normalize(_text(r.get('id'))): score *= 0.1
        if score: scored.append((score, r))
    scored.sort(key=lambda x: (-x[0], _text(x[1].get("name"))))
    result = [result_row(r, configured.source) for _, r in scored[:a.limit]]
    if a.json: print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result:
        for x in result: print(f"{x['name']} (ID: {x['id']}) [{x['category']}]\n  {x['description']}\n  {x['path']}\n  Available: {x['available']}\n")
    else: print(f"No skills matched query: {a.query}")
    return 0
if __name__ == "__main__":
    try: raise SystemExit(main())
    except BrokenPipeError: raise SystemExit(0)

