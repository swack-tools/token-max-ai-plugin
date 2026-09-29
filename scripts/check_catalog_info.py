#!/usr/bin/env python3
"""Validate curated catalog metadata against the pinned schema and this checkout."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath

from bs4 import BeautifulSoup
from jsonschema import Draft202012Validator
from markdown_it import MarkdownIt

SCHEMA_SHA256 = "d115d44f2d32c653f97c08e889587a04353c871db55821d11e126d2e14707e13"
SCHEMA_MARKETPLACE_COMMIT = "437c642bdac19d744dbb26b79bc2e673bebf0691"
SCHEMA_PATH = Path(".github/schemas/upstream-info.schema.json")


def _native(root: Path, plugin_id: str) -> tuple[set[str], set[str]]:
    package = root / "plugins" / plugin_id
    capabilities: set[str] = set()
    hook_targets: set[str] = set()
    if not package.is_dir():
        return capabilities, hook_targets
    for skill in package.rglob("SKILL.md"):
        text = skill.read_text(encoding="utf-8")
        match = re.search(r"(?ms)^---\s*\n(.*?)\n---", text)
        name = re.search(r"(?m)^name:\s*['\"]?([^'\"\n]+)", match.group(1)) if match else None
        if name:
            capabilities.add(f"skill:{name.group(1).strip()}")
    for command in package.rglob("commands/*.md"):
        capabilities.add(f"command:{command.stem}")
    for manifest in package.rglob("*.json"):
        if manifest.name.lower() not in {"hooks.json", "mcp.json", ".mcp.json"}:
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rel = manifest.relative_to(root).as_posix()
        hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
        if isinstance(hooks, dict):
            for event, groups in hooks.items():
                for i, group in enumerate(groups if isinstance(groups, list) else []):
                    for j, _ in enumerate(group.get("hooks", []) if isinstance(group, dict) else []):
                        hook_targets.add(f"{rel}#/hooks/{event}/{i}/hooks/{j}")
        servers = data.get("mcpServers", data if manifest.name.lower() == ".mcp.json" else {}) if isinstance(data, dict) else {}
        if isinstance(servers, dict):
            capabilities.update(f"mcp_server:{name}" for name in servers)
    rust_sources = list(package.rglob("*.rs"))
    if not rust_sources and (root / "src").is_dir():
        rust_sources = list((root / "src").rglob("*.rs"))
    for source in rust_sources:
        text = source.read_text(encoding="utf-8", errors="replace")
        capabilities.update(f"mcp_tool:{name}" for name in re.findall(r'\btool\(\s*"([a-zA-Z0-9_-]+)"', text))
    return capabilities, hook_targets


def _heading_matches(text: str, path: list[str]) -> int:
    tokens = MarkdownIt("commonmark").enable("table").parse(text)
    stack: list[tuple[int, str]] = []
    matches = 0
    for i, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        level = int(token.tag[1:])
        inline = tokens[i + 1].content.strip() if i + 1 < len(tokens) else ""
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, inline))
        if path and [part.casefold() for _, part in stack[-len(path):]] == [part.casefold() for part in path]:
            matches += 1
    return matches


def _source_entries(data):
    found = []
    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("path"), str):
                found.append(value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(data)
    return found


def validate(root: Path, data: dict | None = None) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    schema_file = root / SCHEMA_PATH
    try:
        schema_bytes = schema_file.read_bytes()
        schema = json.loads(schema_bytes)
        if hashlib.sha256(schema_bytes).hexdigest() != SCHEMA_SHA256:
            errors.append(f"pinned schema digest mismatch for marketplace revision {SCHEMA_MARKETPLACE_COMMIT}")
        if data is None:
            data = json.loads((root / "catalog-info.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return errors + ["catalog metadata or pinned schema is missing or invalid JSON"]
    for issue in Draft202012Validator(schema).iter_errors(data):
        errors.append("schema violation at " + "/".join(map(str, issue.absolute_path)))
    if not isinstance(data, dict) or not isinstance(data.get("pluginId"), str):
        return errors
    capabilities, hook_targets = _native(root, data["pluginId"])
    resolved_sources: set[int] = set()
    for source in _source_entries(data):
        rel = source["path"]
        posix = PurePosixPath(rel)
        if posix.is_absolute() or ".." in posix.parts or "\\" in rel:
            errors.append(f"unsafe source path: {rel}")
            continue
        path = (root / Path(*posix.parts)).resolve()
        if root not in path.parents or not path.is_file():
            if source.get("required", True):
                errors.append(f"source path missing or outside repository: {rel}")
            continue
        required = source.get("required", True)
        resolved = True
        if source.get("format") == "markdown" and source.get("mode") == "section" and not source.get("heading_path"):
            resolved = False
            if required:
                errors.append(f"Markdown section is missing its heading selector: {rel}")
        if source.get("format") == "html" and source.get("mode") == "section" and not source.get("selector"):
            resolved = False
            if required:
                errors.append(f"HTML section is missing its CSS selector: {rel}")
        if source.get("format") == "markdown" and source.get("heading_path"):
            try:
                matches = _heading_matches(path.read_text(encoding="utf-8"), source["heading_path"])
                if matches != 1:
                    resolved = False
                    if required:
                        errors.append(f"Markdown heading selector must match exactly once: {rel}")
            except (OSError, UnicodeError):
                resolved = False
                if required:
                    errors.append(f"cannot resolve Markdown source: {rel}")
        if source.get("format") == "html" and source.get("selector"):
            try:
                if len(BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser").select(source["selector"])) != 1:
                    resolved = False
                    if required:
                        errors.append(f"HTML selector must match exactly once: {rel}")
            except Exception:
                resolved = False
                if required:
                    errors.append(f"HTML selector invalid: {rel}")
        if resolved:
            resolved_sources.add(id(source))
    for example in data.get("examples", []):
        for ref in example.get("capability_refs", []):
            if ref not in capabilities:
                errors.append(f"example references unknown native capability: {ref}")
    cited = {ref for example in data.get("examples", []) for ref in example.get("capability_refs", [])}
    for cap in capabilities:
        if cap.startswith("hook:"):
            continue
        if cap not in cited:
            errors.append(f"native capability missing from examples: {cap}")
    for server in data.get("mcpServers", {}):
        if f"mcp_server:{server}" not in capabilities:
            errors.append(f"metadata declares unknown MCP server: {server}")
    hooks = data.get("hooks", {})
    declared = set()
    if isinstance(hooks, list):
        for item in hooks:
            declared.add(f"{item.get('target', {}).get('path', '')}#{item.get('target', {}).get('pointer', item.get('target', {}).get('jsonPointer', ''))}")
    elif isinstance(hooks, dict):
        for item in hooks.values():
            if isinstance(item, list):
                for note in item:
                    target = note.get("target", {})
                    declared.add(f"{target.get('path', '')}#{target.get('pointer', target.get('jsonPointer', ''))}")
    for _target in declared - hook_targets:
        errors.append("metadata declares unknown native hook target")
    for _target in hook_targets - declared:
        errors.append("native hook is missing a catalog note")
    for platform in data.get("platforms", {}).values():
        sources = platform.get("sources", [])
        if platform.get("status") in {"documented", "unsupported"} and not any(
            id(source) in resolved_sources for source in sources
        ):
            errors.append("documented platform claim requires at least one resolved source")
    return errors


def main() -> int:
    errors = validate(Path(__file__).resolve().parents[1])
    if errors:
        for error in errors:
            print(f"catalog-info: {error}", file=sys.stderr)
        return 1
    print("catalog-info.json is valid against the pinned marketplace schema and repository sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
