#!/usr/bin/env python3
"""Validate curated catalog metadata against the pinned schema and this checkout."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

from bs4 import BeautifulSoup
from jsonschema import Draft202012Validator
from markdown_it import MarkdownIt
import yaml

SCHEMA_SHA256 = "d115d44f2d32c653f97c08e889587a04353c871db55821d11e126d2e14707e13"
SCHEMA_MARKETPLACE_COMMIT = "437c642bdac19d744dbb26b79bc2e673bebf0691"
SCHEMA_PATH = Path(".github/schemas/upstream-info.schema.json")
CANONICAL_PLUGIN_ID = "token-max"


def _native(root: Path, plugin_id: str) -> tuple[set[str], set[str], list[str]]:
    package = root / "plugins" / plugin_id
    capabilities: set[str] = set()
    hook_targets: set[str] = set()
    errors: list[str] = []
    if not package.is_dir():
        return capabilities, hook_targets, [f"canonical plugin package is missing: plugins/{plugin_id}"]
    package_manifest = package / "plugin.json"
    try:
        manifest_data = json.loads(package_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"canonical plugin manifest is missing or invalid: plugins/{plugin_id}/plugin.json: {exc}")
    else:
        if not isinstance(manifest_data, dict) or manifest_data.get("name") != plugin_id:
            errors.append(f"catalog pluginId does not match canonical package manifest: {plugin_id}")
    for skill in package.rglob("SKILL.md"):
        text = skill.read_text(encoding="utf-8")
        match = re.search(r"(?ms)^---\s*\n(.*?)\n---", text)
        if match:
            try:
                frontmatter = yaml.safe_load(match.group(1))
            except yaml.YAMLError:
                frontmatter = None
            name = frontmatter.get("name") if isinstance(frontmatter, dict) else None
            if isinstance(name, str) and name.strip():
                capabilities.add(f"skill:{name.strip()}")
            else:
                errors.append(f"skill frontmatter has no valid name: {skill.relative_to(root).as_posix()}")
        else:
            errors.append(f"skill frontmatter is missing or malformed: {skill.relative_to(root).as_posix()}")
    for command in package.rglob("commands/*.md"):
        capabilities.add(f"command:{command.stem}")
    for manifest in package.rglob("*.json"):
        if manifest.name.lower() not in {"hooks.json", "mcp.json", ".mcp.json"}:
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"native manifest is unreadable or invalid JSON: {manifest.relative_to(root).as_posix()}: {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(f"native manifest root must be a JSON object: {manifest.relative_to(root).as_posix()}")
            continue
        rel = manifest.relative_to(root).as_posix()
        hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
        if manifest.name.lower() == "hooks.json" and (not isinstance(data, dict) or "hooks" not in data):
            errors.append(f"native hooks manifest is missing its hooks object: {rel}")
        if isinstance(data, dict) and "hooks" in data and not isinstance(hooks, dict):
            errors.append(f"native hooks manifest has invalid hooks object: {rel}")
        elif isinstance(hooks, dict):
            for event, groups in hooks.items():
                if not isinstance(groups, list):
                    errors.append(f"native hooks manifest event must contain a list: {rel}#/hooks/{event}")
                    continue
                for i, group in enumerate(groups):
                    if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                        errors.append(f"native hooks manifest group must contain a hooks list: {rel}#/hooks/{event}/{i}")
                        continue
                    for j, _ in enumerate(group["hooks"]):
                        hook_targets.add(f"{rel}#/hooks/{event}/{i}/hooks/{j}")
        servers = data.get("mcpServers", data if manifest.name.lower() == ".mcp.json" else {}) if isinstance(data, dict) else {}
        has_servers = isinstance(data, dict) and ("mcpServers" in data or manifest.name.lower() == ".mcp.json")
        if manifest.name.lower() == "mcp.json" and not has_servers:
            errors.append(f"native MCP manifest is missing its mcpServers object: {rel}")
        if has_servers and not isinstance(servers, dict):
            errors.append(f"native MCP manifest has invalid mcpServers object: {rel}")
        elif isinstance(servers, dict):
            capabilities.update(f"mcp_server:{name}" for name in servers)
    rust_sources = list(package.rglob("*.rs"))
    for source in rust_sources:
        text = source.read_text(encoding="utf-8", errors="replace")
        capabilities.update(f"mcp_tool:{name}" for name in _rust_tool_names(text))
    return capabilities, hook_targets, errors


def _rust_tool_names(text: str) -> set[str]:
    """Read tool registrations from Rust code while ignoring comments and literals."""
    masked = list(text)
    literals: dict[int, str] = {}
    i = 0
    while i < len(text):
        if text.startswith("//", i):
            end = text.find("\n", i)
            end = len(text) if end < 0 else end
            for j in range(i, end):
                masked[j] = " "
            i = end
            continue
        if text.startswith("/*", i):
            start, depth = i, 1
            i += 2
            while i < len(text) and depth:
                if text.startswith("/*", i):
                    depth += 1
                    i += 2
                elif text.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            for j in range(start, i):
                if masked[j] != "\n":
                    masked[j] = " "
            continue
        raw = re.match(r"r(#+)?\"", text[i:])
        if raw:
            hashes = raw.group(1) or ""
            end_marker = f'"{hashes}'
            value_start = i + len(raw.group(0))
            end_at = text.find(end_marker, value_start)
            end = len(text) if end_at < 0 else end_at + len(end_marker)
            if end_at >= 0:
                literals[i] = text[value_start:end_at]
            for j in range(i, end):
                if masked[j] != "\n":
                    masked[j] = " "
            if end_at >= 0:
                masked[i] = "§"
            i = end
            continue
        if text[i] == '"':
            start = i
            i += 1
            value = []
            while i < len(text):
                if text[i] == "\\" and i + 1 < len(text):
                    value.append(text[i + 1])
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    value.append(text[i])
                    i += 1
            literals[start] = "".join(value)
            for j in range(start, i):
                if masked[j] != "\n":
                    masked[j] = " "
            masked[start] = "§"
            continue
        i += 1
    code = "".join(masked)
    names = set()
    for match in re.finditer(r"\btool\s*\(\s*", code):
        quote_at = match.end()
        while quote_at < len(text) and text[quote_at].isspace():
            quote_at += 1
        name = literals.get(quote_at)
        if name and re.fullmatch(r"[a-zA-Z0-9_-]+", name):
            names.add(name)
    return names


def _heading_matches(text: str, path: list[str]) -> int:
    tokens = MarkdownIt("commonmark").enable("table").parse(text)
    stack: list[tuple[int, str]] = []
    matches = 0
    for i, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        level = int(token.tag[1:])
        inline_token = tokens[i + 1] if i + 1 < len(tokens) else None
        inline = _rendered_inline_text(inline_token).strip() if inline_token else ""
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, inline))
        if path and [part.casefold() for _, part in stack[-len(path):]] == [part.casefold() for part in path]:
            matches += 1
    return matches


def _rendered_inline_text(token) -> str:
    if not token or not token.children:
        return token.content if token else ""
    return "".join(
        child.content if child.type in {"text", "code_inline", "html_inline"}
        else _rendered_inline_text(child)
        for child in token.children
    )


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
    if data["pluginId"] != CANONICAL_PLUGIN_ID:
        errors.append(f"pluginId must identify the canonical package: {CANONICAL_PLUGIN_ID}")
        return errors
    capabilities, hook_targets, native_errors = _native(root, data["pluginId"])
    errors.extend(native_errors)
    try:
        tracked = set(subprocess.run(
            ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
        ).stdout.decode("utf-8").split("\0"))
    except (OSError, subprocess.CalledProcessError, UnicodeError):
        tracked = set()
        errors.append("cannot determine tracked repository source files")
    resolved_sources: set[int] = set()
    for source in _source_entries(data):
        rel = source["path"]
        posix = PurePosixPath(rel)
        if posix.is_absolute() or ".." in posix.parts or "\\" in rel:
            errors.append(f"unsafe source path: {rel}")
            continue
        path = (root / Path(*posix.parts)).resolve()
        if root not in path.parents or not path.is_file() or rel not in tracked:
            if source.get("required", True):
                errors.append(f"source path missing, untracked, or outside repository: {rel}")
            continue
        required = source.get("required", True)
        resolved = True
        source_format = source.get("format")
        source_mode = source.get("mode")
        if source_format is not None and source_format not in {"markdown", "html"}:
            resolved = False
            if required:
                errors.append(f"unsupported source format: {rel}")
        if source_mode is not None and source_mode not in {"section", "whole"}:
            resolved = False
            if required:
                errors.append(f"unsupported source mode: {rel}")
        if source_mode == "section" and source_format not in {"markdown", "html"}:
            resolved = False
            if required:
                errors.append(f"section source requires a supported format: {rel}")
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
        platform = example.get("platform")
        if platform not in data.get("platforms", {}):
            errors.append(f"example references undeclared platform: {platform}")
        example_sources = example.get("sources", [])
        singular_source = example.get("source")
        if isinstance(singular_source, dict):
            example_sources = [*example_sources, singular_source]
        if not any(id(source) in resolved_sources for source in example_sources):
            errors.append(f"documented example requires at least one resolved source: {example.get('id', '<unknown>')}")
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
    declared_servers = {f"mcp_server:{server}" for server in data.get("mcpServers", {})}
    for capability in capabilities:
        if capability.startswith("mcp_server:") and capability not in declared_servers:
            errors.append(f"native MCP server missing from catalog metadata: {capability.removeprefix('mcp_server:')}")
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
