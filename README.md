# aio-skill

One skill entrypoint for **3,025 skill files in 18 categories**, with the complete source library bundled for offline use.

The harness discovers a small router. The router searches local metadata, opens only relevant skills, and leaves the rest out of model context. Source instructions, scripts, references, assets, and existing upstream notices travel together in a compressed archive. No account, API, runtime package installation, or original machine path is needed for routing.

## Install

Download or clone this project. Copy the **entire `aio-skill/` folder** into your harness's skill directory, or configure the harness to use that folder. Keep its `assets/` and `references/` subfolders intact. There is only one discoverable `SKILL.md` in the package.

For Codex, the usual user skill directory is `~/.codex/skills/`. In another harness, use its equivalent skill directory. The folder is portable; it may be placed anywhere the agent can read and run its Python helpers.

Invoke **`$aio-skill`** when you want to select it explicitly. Automatic invocation is enabled in `agents/openai.yaml` for harnesses that support that field.

### Quick check

From the repository root, run these commands with Python 3.9 or newer (use `python3` if that is your system's command):

```text
python aio-skill/scripts/select_skills.py search "React accessibility audit" --limit 5
python aio-skill/scripts/select_skills.py doctor --json
```

The first search extracts `aio-skill/assets/skills-library.zip` to the user's cache outside the skill directory. The cache is identified by the archive's SHA-256. Later searches reuse it. No bundled executable is run during extraction. The initial extraction needs roughly 120 MB of free space and may take longer when antivirus software inspects many small files.

On Windows the default cache is under `%LOCALAPPDATA%/aio-skill/`; on macOS/Linux it is under `$XDG_CACHE_HOME/aio-skill/` or `~/.cache/aio-skill/`. Override it with `AIO_SKILL_CACHE_DIR`.

## Search

```text
python aio-skill/scripts/select_skills.py search "AWS ECS Docker deployment" --limit 5 --json
python aio-skill/scripts/select_skills.py search "accessibility" --category frontend-mobile
python aio-skill/scripts/select_skills.py show "design-it/glassmorphism" --json
python aio-skill/scripts/select_skills.py categories
```

Results include an absolute `path` resolved on the current machine and an `available` flag. The stored catalog uses POSIX relative paths. Search supports English and common Persian keywords. Category labels are approximate; remove a filter if it hides a useful result. A selected source skill may still require its own tools, network access, credentials, or operating-system dependencies.

## Configuration

No configuration is needed for the included library. To use another library, pass `--source` or create a local config based on [config.example.json](aio-skill/config.example.json).

| Setting | Command option | Environment variable |
| --- | --- | --- |
| External source library | `--source` | `AIO_SKILLS_DIR` |
| Catalog directory | `--index-dir` | `AIO_SKILL_INDEX_DIR` |
| JSON config file | `--config` | `AIO_SKILL_CONFIG` |
| Extracted library cache | — | `AIO_SKILL_CACHE_DIR` |

CLI options override environment variables, which override `aio-skill/config.local.json`. Relative config paths resolve from the config file; relative CLI/environment paths resolve from the current working directory. With no source override, the included bundle is used. A router distributed without an archive looks for `~/.aio-skill/library` instead.

## Updating the bundle

Run the packer against your complete source directory, then rebuild the catalog from that exact archived snapshot:

```text
python aio-skill/scripts/bundle_library.py pack --source path/to/skills
python aio-skill/scripts/build_catalog.py
python aio-skill/scripts/select_skills.py doctor --json
```

Clear any source/index overrides when refreshing the bundled catalog. The manifest records the archive SHA-256, file count, expanded size, skill count, and paths of available license/notice files. `catalog.jsonl` and `library.json` are deterministic for an unchanged corpus and contain no generated timestamp or absolute source directory. Each index file is replaced atomically; `doctor` detects a mismatched pair through the catalog hash.

The packer excludes `.git`, `node_modules`, Python caches, and bytecode. It rejects symlinks and credential-like configuration files instead of silently including them. It preserves source file content. It does not rewrite upstream instructions or guarantee that every source skill is compatible with every harness.

## Development

The router and tests use the Python standard library only:

```text
python -m unittest discover -s tests -v
```

GitHub Actions runs the CLI portability contracts on Windows, macOS, and Linux. Tests exercise movement to paths with spaces and Unicode, configuration precedence, resource availability, deterministic generation, invalid catalogs, and safe extraction.

## Source licenses

[LICENSE-ROUTER](LICENSE-ROUTER) applies to the router's original code, tests, and documentation. It does **not** relicense the aggregated skills. Their existing licenses and notices are retained in the archive; the manifest lists available notice files. Some upstream entries do not supply explicit licensing information. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the scope and provenance of this snapshot.
