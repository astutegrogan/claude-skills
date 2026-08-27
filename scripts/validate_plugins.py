#!/usr/bin/env python3
"""Validate every plugin in plugins/ has a well-formed plugin.json + skill(s) + README.md,
and that the root marketplace.json lists exactly the plugins that exist on disk.

No dependencies beyond the standard library — this needs to run reliably in CI with no
install step. JSON is stdlib; SKILL.md frontmatter is parsed by hand (just "key: value"
lines between two "---" delimiters, which is all it uses).
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAX_DESCRIPTION_LEN = 1024


def parse_frontmatter(text: str) -> dict[str, str] | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return None  # never found the closing ---


def validate_plugin(plugin_dir: Path) -> list[str]:
    errors: list[str] = []
    name = plugin_dir.name

    if not (plugin_dir / "README.md").exists():
        errors.append(f"{name}: missing README.md")

    manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
    if not manifest_path.exists():
        errors.append(f"{name}: missing .claude-plugin/plugin.json")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{name}/.claude-plugin/plugin.json: invalid JSON ({e})")
            manifest = {}
        if manifest.get("name") != name:
            errors.append(f"{name}/.claude-plugin/plugin.json: 'name' ({manifest.get('name')!r}) does not match directory name ({name!r})")
        if not manifest.get("description"):
            errors.append(f"{name}/.claude-plugin/plugin.json: missing 'description'")
        if not manifest.get("version"):
            errors.append(f"{name}/.claude-plugin/plugin.json: missing 'version'")

    skills_dir = plugin_dir / "skills"
    if not skills_dir.is_dir():
        errors.append(f"{name}: missing skills/ directory")
        return errors

    skill_dirs = sorted(p for p in skills_dir.iterdir() if p.is_dir())
    if not skill_dirs:
        errors.append(f"{name}: skills/ directory has no skills in it")

    for skill_dir in skill_dirs:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            errors.append(f"{name}/skills/{skill_dir.name}: missing SKILL.md")
            continue
        fields = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        if fields is None:
            errors.append(f"{name}/skills/{skill_dir.name}/SKILL.md: no valid YAML frontmatter (--- ... ---) at top of file")
            continue
        if not fields.get("name"):
            errors.append(f"{name}/skills/{skill_dir.name}/SKILL.md: frontmatter missing 'name'")
        elif fields["name"] != skill_dir.name:
            errors.append(f"{name}/skills/{skill_dir.name}/SKILL.md: frontmatter name '{fields['name']}' does not match directory name '{skill_dir.name}'")
        description = fields.get("description")
        if not description:
            errors.append(f"{name}/skills/{skill_dir.name}/SKILL.md: frontmatter missing 'description'")
        elif len(description) > MAX_DESCRIPTION_LEN:
            errors.append(f"{name}/skills/{skill_dir.name}/SKILL.md: description is {len(description)} chars, over the {MAX_DESCRIPTION_LEN}-char cap")

    return errors


def validate_marketplace(plugin_names_on_disk: set[str]) -> list[str]:
    errors: list[str] = []
    marketplace_path = REPO_ROOT / ".claude-plugin" / "marketplace.json"
    if not marketplace_path.exists():
        errors.append("root: missing .claude-plugin/marketplace.json")
        return errors

    try:
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f".claude-plugin/marketplace.json: invalid JSON ({e})")
        return errors

    for required in ("name", "owner", "plugins"):
        if required not in marketplace:
            errors.append(f".claude-plugin/marketplace.json: missing required field '{required}'")

    listed_plugins = marketplace.get("plugins", [])
    listed_names = {p.get("name") for p in listed_plugins}
    for missing in plugin_names_on_disk - listed_names:
        errors.append(f".claude-plugin/marketplace.json: plugin '{missing}' exists in plugins/ but isn't listed")
    for stale in listed_names - plugin_names_on_disk:
        errors.append(f".claude-plugin/marketplace.json: lists plugin '{stale}' but plugins/{stale} doesn't exist")

    # Version is declared in both marketplace.json and each plugin's own plugin.json --
    # nothing else keeps them in sync, so a version bump in one and not the other is a
    # silent drift bug waiting to happen. Cross-check them here.
    for entry in listed_plugins:
        name = entry.get("name")
        if name not in plugin_names_on_disk:
            continue  # already reported above
        marketplace_version = entry.get("version")
        manifest_path = REPO_ROOT / "plugins" / name / ".claude-plugin" / "plugin.json"
        if not manifest_path.exists():
            continue  # already reported by validate_plugin()
        try:
            manifest_version = json.loads(manifest_path.read_text(encoding="utf-8")).get("version")
        except json.JSONDecodeError:
            continue  # already reported by validate_plugin()
        if marketplace_version != manifest_version:
            errors.append(
                f"version mismatch for '{name}': marketplace.json says '{marketplace_version}', "
                f"plugins/{name}/.claude-plugin/plugin.json says '{manifest_version}'"
            )

    return errors


def main() -> int:
    plugins_dir = REPO_ROOT / "plugins"
    plugin_dirs = sorted(p for p in plugins_dir.iterdir() if p.is_dir()) if plugins_dir.is_dir() else []

    if not plugin_dirs:
        print("No plugins found under plugins/.")
        return 0

    all_errors: list[str] = []
    for plugin_dir in plugin_dirs:
        errs = validate_plugin(plugin_dir)
        all_errors.extend(errs)
        print(f"[{'FAIL' if errs else 'ok'}] {plugin_dir.name}")

    all_errors.extend(validate_marketplace({p.name for p in plugin_dirs}))

    if all_errors:
        print("\nErrors:")
        for e in all_errors:
            print(f"  - {e}")
        return 1

    print(f"\nAll {len(plugin_dirs)} plugin(s) and the marketplace manifest are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
