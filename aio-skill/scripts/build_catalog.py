#!/usr/bin/env python3
"""Build the small, searchable index used by aio-skill.

The source skills remain in place. This script stores only routing metadata and
relative paths, so refreshing the index never copies their instructions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Iterable

from router_config import ROUTER_ROOT, add_config_arguments, settings
from bundle_library import ensure_library


CATEGORIES: list[tuple[str, str, str]] = [
    ("engineering", "Engineering", "Programming, architecture, backend, APIs, databases, and software engineering."),
    ("frontend-mobile", "Frontend & Mobile", "Web UI, frontend frameworks, CSS, accessibility, iOS, and Android."),
    ("design", "Design", "Visual design, UX, typography, branding, and design systems."),
    ("devops-cloud", "DevOps & Cloud", "Cloud, deployment, CI/CD, containers, infrastructure, observability, and servers."),
    ("security", "Security", "Defensive security, threat modeling, penetration testing, vulnerabilities, privacy, and hardening."),
    ("data-ai", "Data & AI", "Data engineering, analytics, machine learning, LLMs, agents, vectors, and model operations."),
    ("agents-skills", "Agents & Skills", "Agent orchestration, harnesses, memory, skill authoring, and agent workflows."),
    ("automation-integrations", "Automation & Integrations", "Workflow automation, webhooks, MCP, CRM, messaging, and SaaS connectors."),
    ("testing-quality", "Testing & Quality", "Unit, integration, E2E, QA, validation, benchmarking, and test strategy."),
    ("business-operations", "Business & Operations", "Accounting, HR, legal/compliance, procurement, operations, CRM, and vendors."),
    ("finance-trading", "Finance & Trading", "Finance, markets, trading, ledgers, and financial analysis."),
    ("marketing-seo", "Marketing & SEO", "Marketing, growth, advertising, SEO, social channels, and conversion."),
    ("content-media", "Content & Media", "Writing, documents, presentations, video, audio, image, and publishing."),
    ("product-research", "Product & Research", "Product discovery, requirements, strategy, planning, research, and decisions."),
    ("productivity-projects", "Productivity & Projects", "Tasks, calendars, notes, knowledge bases, projects, and personal productivity."),
    ("gaming-3d", "Gaming & 3D", "Game engines, game systems, 3D, rendering, shaders, and interactive scenes."),
    ("science-health", "Science & Health", "Scientific, medical, health, climate, weather, and specialist domains."),
    ("uncategorized", "Uncategorized", "Use when the available metadata is too weak for a safer category."),
]
CATEGORY_IDS = {item[0] for item in CATEGORIES}

# Weighted hints for skills without recognized category metadata. These are
# advisory labels; global search remains available across category boundaries.
SIGNALS: list[tuple[str, tuple[str, ...]]] = [
    ("agents-skills", ("agent", "agents", "skill", "skills", "orchestration", "harness", "codex", "claude code", "openclaw", "prompt engineering", "agentic", "context engineering")),
    ("security", ("security", "cyber", "infosec", "pentest", "penetration", "vulnerability", "threat", "hardening", "exploit", "red team", "blue team", "zero trust", "forensics")),
    ("finance-trading", ("finance", "financial", "trading", "trader", "stock", "market", "ledger", "accounting", "investment", "portfolio", "tax")),
    ("science-health", ("medical", "health", "clinical", "biology", "genome", "protein", "weather", "climate", "scientific", "uniprot", "medicine")),
    ("content-media", ("writing", "writer", "document", "word", "docx", "xlsx", "spreadsheet", "pdf", "presentation", "slide", "video", "audio", "image", "photo", "podcast", "youtube", "content", "publishing")),
    ("marketing-seo", ("marketing", "seo", "advertising", "ads", "growth", "conversion", "social media", "instagram", "twitter", "tiktok", "newsletter", "copywriting")),
    ("business-operations", ("business", "accounting", "hr", "human resources", "legal", "compliance", "procurement", "vendor", "crm", "sales", "operations", "real estate")),
    ("product-research", ("product", "roadmap", "prd", "requirements", "research", "strategy", "discovery", "market research", "decision")),
    ("data-ai", ("machine learning", "deep learning", "llm", "language model", "artificial intelligence", " ai", "data", "analytics", "embedding", "vector", "transformer", "pytorch", "tensorflow", "model")),
    ("testing-quality", ("test", "testing", "qa", "quality", "e2e", "end to end", "validation", "benchmark", "audit", "review")),
    ("devops-cloud", ("devops", "cloud", "aws", "azure", "gcp", "kubernetes", "docker", "terraform", "deployment", "deploy", "ci/cd", "infrastructure", "server", "sre", "observability", "vercel")),
    ("automation-integrations", ("automation", "workflow", "webhook", "integration", "mcp", "api connector", "zapier", "make.com", "twilio", "slack", "notion", "trello")),
    ("design", ("design", "designer", "ux", "ui", "typography", "brand", "branding", "figma", "visual", "wireframe", "accessibility")),
    ("frontend-mobile", ("frontend", "front end", "react", "next.js", "nextjs", "vue", "angular", "svelte", "css", "html", "mobile", "android", "ios", "swift", "swiftui", "flutter", "react native", "accessibility", "a11y", "wcag")),
    ("gaming-3d", ("game", "gaming", "unity", "unreal", "three.js", "threejs", "shader", "rendering", "godot", "phaser", "pixi")),
    ("productivity-projects", ("productivity", "todo", "task", "calendar", "notes", "knowledge base", "project management", "time tracking")),
    ("engineering", ("programming", "software", "architecture", "code", "coding", "refactor", "api", "backend", "database", "sql", "postgresql", "mysql", "python", "javascript", "typescript", "rust", "golang", "kotlin", "java", "csharp", "cpp", "dotnet", "node", "library", "compiler", "git", "debugging", "algorithm")),
]


def clean_scalar(value: str) -> str:
    value = value.strip()
    if value in {"", "|", ">"}:
        return ""
    if value.startswith(("'", '"')) and value.endswith(value[0]) and len(value) >= 2:
        value = value[1:-1]
    return value.replace("\\\"", '"').replace("''", "'").strip()


def parse_list(value: str) -> list[str]:
    value = value.strip()
    if not value:
        return []
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    parts = re.split(r"\s*,\s*|\s*;\s*", value)
    return [clean_scalar(part) for part in parts if clean_scalar(part)]


def frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    match = re.search(r"\n---[ \t]*(?:\r?\n|$)", text[3:])
    return text[3 : 3 + match.start()] if match else ""


def field(fm: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}[ \t]*:[ \t]*(.*)$", fm)
    if not match:
        return ""
    raw = match.group(1).strip()
    following = []
    for line in fm[match.end():].splitlines():
        if line and not line[0].isspace():
            break
        if line.strip():
            following.append(line.strip())
    if raw in {"", "|", ">", "|-", ">-", "|+", ">+"}:
        raw = " ".join(following)
    elif following:
        raw += " " + " ".join(following)
    return re.sub(r"\s+", " ", clean_scalar(raw)).strip()


def explicit_category(fm: str) -> str:
    raw = field(fm, "category")
    if not raw:
        return ""
    lowered = raw.lower()
    aliases = {
        "development": "engineering", "software": "engineering", "backend": "engineering",
        "frontend": "frontend-mobile", "front-end": "frontend-mobile", "mobile": "frontend-mobile",
        "devops": "devops-cloud", "cloud": "devops-cloud", "infrastructure": "devops-cloud",
        "ai": "data-ai", "ml": "data-ai", "machine-learning": "data-ai", "data": "data-ai",
        "agent-orchestration": "agents-skills", "ai-agents": "agents-skills", "agent-behavior": "agents-skills", "agent-tooling": "agents-skills", "meta": "agents-skills",
        "automation": "automation-integrations", "integrations": "automation-integrations",
        "api-integration": "automation-integrations", "browser-automation": "automation-integrations", "mcp": "automation-integrations",
        "testing": "testing-quality", "qa": "testing-quality", "quality": "testing-quality",
        "code-quality": "testing-quality", "document-verification": "content-media",
        "business": "business-operations", "operations": "business-operations",
        "finance": "finance-trading", "trading": "finance-trading",
        "marketing": "marketing-seo", "seo": "marketing-seo",
        "content": "content-media", "media": "content-media",
        "research": "product-research", "product": "product-research",
        "productivity": "productivity-projects", "project-management": "productivity-projects",
        "games": "gaming-3d", "gaming": "gaming-3d", "3d": "gaming-3d",
        "science": "science-health", "health": "science-health",
    }
    if lowered in CATEGORY_IDS:
        return lowered
    return aliases.get(lowered, "")


def inferred_category(name: str, description: str, tags: Iterable[str], explicit: str) -> str:
    if explicit:
        return explicit
    def normalized(value: str) -> str:
        return re.sub(r"[-_/]+", " ", value.casefold())

    fields = [(normalized(name), 8), (normalized(description), 1), (normalized(" ".join(tags)), 3)]
    scores = {}
    for category, terms in SIGNALS:
        score = 0
        for term in terms:
            pattern = rf"(?<!\w){re.escape(normalized(term))}(?!\w)"
            score += sum(weight for text, weight in fields if re.search(pattern, text))
        scores[category] = score
    best = max(scores, key=scores.get)
    return best if scores[best] else "uncategorized"


def token_tags(name: str, description: str, explicit_tags: Iterable[str]) -> list[str]:
    tokens = [item.lower() for item in explicit_tags]
    tokens.extend(re.findall(r"[a-z0-9][a-z0-9+#./-]{2,}", name.lower()))
    # Keep only a small set: description is already indexed separately.
    for token in re.findall(r"[a-z0-9][a-z0-9+#./-]{3,}", description.lower()):
        if token not in tokens and token not in {"this", "that", "with", "when", "from", "using", "use"}:
            tokens.append(token)
    seen: set[str] = set()
    return [token for token in tokens if not (token in seen or seen.add(token))][:18]


def read_record(path: Path, source: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    fm = frontmatter(text)
    relative_dir = path.parent.relative_to(source).as_posix()
    name = field(fm, "name") or path.parent.name
    description = field(fm, "description")
    if not description:
        description = re.sub(r"\s+", " ", text.split("---", 2)[-1][:500]).strip()
    tags = parse_list(field(fm, "tags"))
    category = inferred_category(relative_dir + " " + name, description, tags, explicit_category(fm))
    return {
        "id": relative_dir,
        "name": name,
        "description": description[:1200],
        "category": category,
        "source_category": field(fm, "category"),
        "risk": field(fm, "risk"),
        "source": field(fm, "source"),
        "tags": token_tags(name, description, tags),
        "relative_path": (Path(relative_dir) / "SKILL.md").as_posix(),
        "entry_type": "example" if "assets" in path.relative_to(source).parts else "skill",
    }


def build(source: Path, output_dir: Path) -> tuple[int, Counter[str]]:
    source = source.expanduser().resolve()
    paths = sorted(source.rglob("SKILL.md"))
    # Every SKILL.md is indexed, including nested examples and skill bundles:
    # the user asked for the whole library and a nested entry can be the one
    # that matches a concrete request. Repository metadata is not an entrypoint
    # and is excluded only when it is itself named SKILL.md under .git.
    paths = [path for path in paths if ".git" not in path.relative_to(source).parts]
    if not paths:
        raise ValueError(f"No skill entrypoints found under {source}; existing catalog was preserved.")
    records = [read_record(path, source) for path in paths]
    output_dir.mkdir(parents=True, exist_ok=True)
    records.sort(key=lambda item: (item["name"].lower(), item["id"].lower()))
    counts: Counter[str] = Counter(item["category"] for item in records)
    catalog_path = output_dir / "catalog.jsonl"
    catalog_text = "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records)
    categories = [
        {"id": slug, "title": title, "description": description, "count": counts.get(slug, 0)}
        for slug, title, description in CATEGORIES
    ]
    metadata = {
        "schema_version": "1.0.0",
        "index_kind": "metadata-only",
        "source_layout": "A skill entrypoint is <skill-directory>/SKILL.md; nested directories are valid.",
        "generated_by": "aio-skill/scripts/build_catalog.py",
        "catalog_sha256": hashlib.sha256(catalog_text.encode("utf-8")).hexdigest(),
        "skills_count": len(records),
        "top_level_count": sum("/" not in item["id"] for item in records),
        "nested_count": sum("/" in item["id"] for item in records),
        "catalog": "catalog.jsonl",
        "categories": categories,
    }
    metadata_text = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    # Each individual file is atomically replaced. catalog_sha256 lets doctor
    # detect a mismatched pair if a process stops between the two replacements.
    for destination, content in ((catalog_path, catalog_text), (output_dir / "library.json", metadata_text)):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=output_dir, prefix=f".{destination.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        temporary.replace(destination)
    return len(records), counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the AIO skill routing catalog.")
    add_config_arguments(parser)
    parser.add_argument("--output", help="Deprecated alias for --index-dir.")
    args = parser.parse_args()
    try:
        configured = settings(source=args.source, index_dir=args.output or args.index_dir, config=args.config)
        if configured.bundled:
            ensure_library(ROUTER_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    source, output_dir = configured.source, configured.index_dir
    if not source.is_dir():
        print(f"Source directory does not exist: {source}", file=sys.stderr)
        return 2
    try:
        count, counts = build(source, output_dir)
    except (OSError, ValueError) as exc:
        print(f"Could not build catalog: {exc}", file=sys.stderr)
        return 2
    print(f"Indexed {count} SKILL.md files from {source}")
    print("Categories: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
