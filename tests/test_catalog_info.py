import json
import tempfile
import unittest
from pathlib import Path

import scripts.check_catalog_info as checker

ROOT = Path(__file__).resolve().parents[1]


class CatalogInfoTests(unittest.TestCase):
    def test_repository_catalog_is_valid(self):
        self.assertEqual([], checker.validate(ROOT))

    def test_unknown_top_level_field_is_rejected(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        data["manualCount"] = 3
        self.assertTrue(any("schema" in error for error in checker.validate(ROOT, data)))

    def test_missing_selector_is_rejected(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        target = None
        def find_selector(value):
            nonlocal target
            if isinstance(value, dict):
                if value.get("format") == "html" and "selector" in value:
                    target = (value, "html")
                    return
                if value.get("format") == "markdown" and "heading_path" in value:
                    target = (value, "markdown")
                    return
                for child in value.values():
                    find_selector(child)
                    if target:
                        return
            elif isinstance(value, list):
                for child in value:
                    find_selector(child)
                    if target:
                        return
        find_selector(data)
        self.assertIsNotNone(target, "catalog must exercise a document selector")
        source, format_name = target
        source.pop("selector" if format_name == "html" else "heading_path")
        self.assertTrue(any("selector" in error or "heading" in error for error in checker.validate(ROOT, data)))

    def test_duplicate_markdown_heading_path_is_ambiguous(self):
        self.assertEqual(2, checker._heading_matches("# Parent\n\n## Same\n\n## Same\n", ["Same"]))

    def test_markdown_heading_selector_uses_rendered_text(self):
        self.assertEqual(1, checker._heading_matches("## **Install**\n\n## [Use](guide.md)\n", ["Install"]))
        self.assertEqual(1, checker._heading_matches("## **Install**\n\n## [Use](guide.md)\n", ["Use"]))

    def test_stale_selector_is_rejected(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        target = None
        def find_selector(value):
            nonlocal target
            if isinstance(value, dict):
                if value.get("format") == "html" and "selector" in value:
                    target = (value, "html")
                    return
                if value.get("format") == "markdown" and "heading_path" in value:
                    target = (value, "markdown")
                    return
                for child in value.values():
                    find_selector(child)
                    if target:
                        return
            elif isinstance(value, list):
                for child in value:
                    find_selector(child)
                    if target:
                        return
        find_selector(data)
        source, format_name = target
        if format_name == "html":
            source["selector"] = "#catalog-section-that-does-not-exist"
        else:
            source["heading_path"] = ["Catalog section that does not exist"]
        self.assertTrue(any("selector" in error or "heading" in error for error in checker.validate(ROOT, data)))

    def test_invented_capability_is_rejected(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        data["examples"][0]["capability_refs"] = ["mcp_tool:invented_tool"]
        self.assertTrue(any("capability" in error for error in checker.validate(ROOT, data)))

    def test_invented_mcp_server_is_rejected(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        data["mcpServers"]["invented-server"] = {}
        self.assertTrue(any("MCP server" in error for error in checker.validate(ROOT, data)))

    def test_optional_missing_source_is_not_platform_evidence(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        key = next(iter(data["platforms"]))
        data["platforms"][key]["sources"] = [{"path": "missing-source.md", "required": False}]
        self.assertTrue(any("resolved source" in error for error in checker.validate(ROOT, data)))

    def test_optional_unresolved_selector_is_not_platform_evidence(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        key = next(iter(data["platforms"]))
        target = None
        def find_html(value):
            nonlocal target
            if isinstance(value, dict):
                if value.get("format") == "html" and "selector" in value:
                    target = value
                    return
                for child in value.values():
                    find_html(child)
                    if target:
                        return
            elif isinstance(value, list):
                for child in value:
                    find_html(child)
                    if target:
                        return
        find_html(data)
        self.assertIsNotNone(target)
        evidence = dict(target)
        evidence["selector"] = "#missing-platform-evidence"
        evidence["required"] = False
        data["platforms"][key]["sources"] = [evidence]
        self.assertTrue(any("resolved source" in error for error in checker.validate(ROOT, data)))

    def test_example_requires_resolved_source(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        data["examples"][0]["sources"] = [{"path": "missing.md", "required": False}]
        self.assertTrue(any("documented example requires" in error for error in checker.validate(ROOT, data)))

    def test_example_accepts_schema_singular_source(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        example = data["examples"][0]
        example["source"] = example["sources"].pop()
        self.assertFalse(any("documented example requires" in error for error in checker.validate(ROOT, data)))

    def test_example_platform_must_be_declared(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        data["examples"][0]["platform"] = "codez"
        self.assertTrue(any("undeclared platform" in error for error in checker.validate(ROOT, data)))

    def test_unknown_source_format_is_rejected(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        data["examples"][0]["sources"][0]["format"] = "markdwon"
        self.assertTrue(any("unsupported source format" in error for error in checker.validate(ROOT, data)))

    def test_mcp_tools_are_scanned_from_the_canonical_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "plugins" / "example" / "mcp.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text('{"mcpServers": {"package-server": {"entrypoint": "src/server.rs"}}}')
            package_source = root / "plugins" / "example" / "src" / "server.rs"
            package_source.parent.mkdir(parents=True)
            package_source.write_text('tool("package_tool", "Package tool", "Evidence-backed package tool");')
            root_source = root / "src" / "server.rs"
            root_source.parent.mkdir(parents=True)
            root_source.write_text('tool("compatibility_copy", "Compatibility copy", "Must not count");')
            capabilities, _, _ = checker._native(root, "example")
            self.assertIn("mcp_server:package-server", capabilities)
            self.assertIn("mcp_tool:package_tool", capabilities)
            self.assertNotIn("mcp_tool:compatibility_copy", capabilities)

    def test_noncanonical_plugin_id_is_rejected(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        data["pluginId"] = "other"
        self.assertTrue(any("canonical package" in error for error in checker.validate(ROOT, data)))

    def test_yaml_comments_do_not_change_skill_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "plugins" / "example" / "skills" / "token-audit" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: token-audit # YAML comment\ndescription: example\n---\n")
            capabilities, _, _ = checker._native(root, "example")
            self.assertIn("skill:token-audit", capabilities)
            self.assertNotIn("skill:token-audit # YAML comment", capabilities)

    def test_invalid_skill_frontmatter_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "plugins" / "example" / "skills" / "token-audit" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: [unterminated\n---\n")
            _, _, errors = checker._native(root, "example")
            self.assertTrue(any("valid name" in error for error in errors))

    def test_nested_reference_skill_is_not_inventoried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "plugins" / "example"
            skill_dir = package / "skills" / "sample"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("---\nname: sample\n---\n")
            nested = skill_dir / "references" / "example"
            nested.mkdir(parents=True)
            (nested / "SKILL.md").write_text("---\nname: not-discoverable\n---\n")
            capabilities, _, _ = checker._native(root, "example")
            self.assertIn("skill:sample", capabilities)
            self.assertNotIn("skill:not-discoverable", capabilities)

    def test_default_and_custom_skill_paths_are_both_inventoried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "plugins" / "example"
            package.mkdir(parents=True)
            (package / "plugin.json").write_text('{"name": "example", "skills": "additional-skills"}')
            for folder, name in (("skills/default", "default-skill"), ("additional-skills/custom", "custom-skill")):
                skill = package / folder / "SKILL.md"
                skill.parent.mkdir(parents=True)
                skill.write_text(f"---\nname: {name}\n---\n")
            capabilities, _, _ = checker._native(root, "example")
            self.assertIn("skill:default-skill", capabilities)
            self.assertIn("skill:custom-skill", capabilities)

    def test_command_inventory_ignores_nested_documentation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "plugins" / "example"
            command_root = package / "commands"
            command_root.mkdir(parents=True)
            (command_root / "actual.md").write_text("# Actual command")
            nested = package / "skills" / "sample" / "references" / "commands"
            nested.mkdir(parents=True)
            (nested / "fixture.md").write_text("# Not a command")
            capabilities, _, _ = checker._native(root, "example")
            self.assertIn("command:actual", capabilities)
            self.assertNotIn("command:fixture", capabilities)

    def test_invalid_native_manifest_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "plugins" / "example"
            package.mkdir(parents=True)
            (package / "mcp.json").write_text("{")
            _, _, errors = checker._native(root, "example")
            self.assertTrue(any("invalid JSON" in error for error in errors))

    def test_structurally_invalid_native_manifest_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "plugins" / "example"
            package.mkdir(parents=True)
            (package / "mcp.json").write_text('{"mcpServers": []}')
            _, _, errors = checker._native(root, "example")
            self.assertTrue(any("invalid mcpServers object" in error for error in errors))

    def test_mcp_servers_are_inventoried_from_the_canonical_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "plugins" / "example"
            package.mkdir(parents=True)
            (package / "mcp.json").write_text('{"mcpServers": {"example-server": {"entrypoint": "src/server.py"}}}')
            capabilities, _, _ = checker._native(root, "example")
            self.assertIn("mcp_server:example-server", capabilities)

    def test_non_rust_mcp_tools_are_inventoried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "plugins" / "example"
            source = package / "src"
            source.mkdir(parents=True)
            (package / "plugin.json").write_text('{"name": "example", "mcpServers": {"inline-server": {"entrypoint": "src/server.py"}}}')
            (source / "server.py").write_text('@server.tool()\ndef python_tool():\n    pass\n')
            (source / "server.ts").write_text('server.tool("typescript-tool", {});')
            (package / "mcp.json").write_text('{"mcpServers": {"typescript-server": {"entrypoint": "src/server.ts"}}}')
            capabilities, _, _ = checker._native(root, "example")
            self.assertIn("mcp_server:inline-server", capabilities)
            self.assertIn("mcp_tool:python_tool", capabilities)
            self.assertIn("mcp_tool:typescript-tool", capabilities)

    def test_javascript_inventory_handles_template_literals(self):
        source = 'server.tool(`live-tool`, {}); const docs = `server.tool("fake-tool", {})`;'
        self.assertEqual({"live-tool"}, checker._js_tool_names(source))

    def test_mcp_tool_inventory_ignores_unregistered_code_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "plugins" / "example"
            source = package / "src"
            source.mkdir(parents=True)
            (package / "mcp.json").write_text('{"mcpServers": {"example-server": {"entrypoint": "src/server.py"}}}')
            (source / "server.py").write_text('@server.tool()\ndef actual_tool():\n    pass\n')
            (source / "skill-helper.py").write_text('@server.tool()\ndef unrelated_tool():\n    pass\n')
            capabilities, _, _ = checker._native(root, "example")
            self.assertIn("mcp_tool:actual_tool", capabilities)
            self.assertNotIn("mcp_tool:unrelated_tool", capabilities)

    def test_nested_mcp_manifest_is_not_treated_as_registered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "plugins" / "example"
            (package / "plugin.json").parent.mkdir(parents=True)
            (package / "plugin.json").write_text('{"name": "example"}')
            nested = package / "references"
            nested.mkdir()
            (nested / "mcp.json").write_text('{"mcpServers": {"fixture-only": {}}}')
            capabilities, _, _ = checker._native(root, "example")
            self.assertNotIn("mcp_server:fixture-only", capabilities)

    def test_non_null_changelog_requires_resolved_source(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        data["changelog"] = {}
        self.assertTrue(any("changelog must be null" in error for error in checker.validate(ROOT, data)))

    def test_rust_inventory_ignores_comments_and_string_examples(self):
        source = '''
// tool("commented", "not registered")
const DOC: &str = "tool(\\\"documented\\\", \\\"not registered\\\")";
tool("live-tool", "Registered tool");
'''
        self.assertEqual({"live-tool"}, checker._rust_tool_names(source))

    def test_rust_inventory_accepts_raw_string_tool_names(self):
        self.assertEqual({"my-tool"}, checker._rust_tool_names('tool(r#"my-tool"#, "Raw string tool");'))

    def test_rust_inventory_skips_character_literals(self):
        source = r'''let quote = '\"'; tool("live", "ok");'''
        self.assertEqual({"live"}, checker._rust_tool_names(source))

    def test_untracked_source_is_not_accepted_as_evidence(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        key = next(iter(data["platforms"]))
        data["platforms"][key]["sources"] = [{"path": ".git/config", "required": True}]
        self.assertTrue(any("untracked" in error for error in checker.validate(ROOT, data)))

    def test_invented_hook_target_is_rejected(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        data["hooks"] = [{"target": {"path": "plugins/missing/hooks.json", "pointer": "/hooks/Unknown/0/hooks/0"}}]
        self.assertTrue(any("hook target" in error for error in checker.validate(ROOT, data)))

    def test_path_escape_is_rejected(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        data["examples"][0]["sources"][0]["path"] = "../outside.md"
        self.assertTrue(any("path" in error for error in checker.validate(ROOT, data)))

    def test_documented_platform_requires_sources(self):
        data = json.loads((ROOT / "catalog-info.json").read_text())
        key = next(iter(data["platforms"]))
        data["platforms"][key]["sources"] = []
        self.assertTrue(any("source" in error for error in checker.validate(ROOT, data)))


if __name__ == "__main__":
    unittest.main()
