"""Synthetic project host transactions; no installed host is started or edited."""
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from traceanchor import hosts
from traceanchor.core import TraceError


class HostsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="traceanchor-host-test-")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.python = str(Path(sys.executable).absolute())
        self.workspace = str(self.project / "workspace")

    def install(self, host, apply=False, python=None):
        return hosts.install_host(self.project, host, python or self.python, self.workspace, apply=apply)

    def config(self, host):
        return self.project / hosts.TARGETS[host]

    def receipt(self, host):
        return self.project / ".traceanchor-hosts" / (host + ".json")

    def write(self, host, content):
        path = self.config(host)
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes(content)

    def test_preview_never_writes_even_management_directory(self):
        for host in hosts.TARGETS:
            result = self.install(host)
            self.assertFalse(result["applied"])
            self.assertEqual(result["action"], "install")
            self.assertEqual(list(self.project.iterdir()), [])
            self.assertEqual(hosts.uninstall_host(self.project, host)["action"], "absent")

    def test_fresh_install_uninstall_removes_only_owned_file(self):
        for host in hosts.TARGETS:
            self.assertTrue(self.install(host, True)["applied"])
            self.assertTrue(self.config(host).is_file())
            self.assertEqual(self.install(host, True)["action"], "unchanged")
            self.assertFalse(hosts.uninstall_host(self.project, host)["applied"])
            self.assertTrue(self.config(host).exists())
            self.assertTrue(hosts.uninstall_host(self.project, host, True)["applied"])
            self.assertFalse(self.config(host).exists())
            self.assertFalse(self.receipt(host).exists())

    def test_existing_top_level_and_unrelated_entries_preserved(self):
        cases = {"claude": b'{"other":{"value":7},"mcpServers":{"foreign":{"command":"tool","args":[]}}}\n',
                 "codex": b'# keep comment\nmodel = "user-choice"\n[mcp_servers.foreign]\ncommand = "tool"\nargs = []\n'}
        for host, original in cases.items():
            self.write(host, original)
            self.install(host, True)
            data = self.config(host).read_bytes()
            value = json.loads(data) if host == "claude" else tomllib.loads(data.decode())
            self.assertIn("foreign", value["mcpServers" if host == "claude" else "mcp_servers"])
            if host == "claude":
                self.assertEqual(value["other"], {"value": 7})
                self.assertEqual(value["mcpServers"]["traceanchor"]["type"], "stdio")
            else:
                self.assertEqual(value["model"], "user-choice")
                self.assertTrue(data.startswith(original))
            hosts.uninstall_host(self.project, host, True)
            self.assertEqual(self.config(host).read_bytes(), original)

    def test_reinstall_updates_owned_entry_preserves_original_backup(self):
        for host in hosts.TARGETS:
            original = b'{"user":1}\n' if host == "claude" else b'model = "choice"\n'
            self.write(host, original)
            self.install(host, True)
            replacement = str(self.project / "python-new.exe")
            self.assertEqual(self.install(host, True, python=replacement)["action"], "reinstall")
            self.assertIn(replacement.replace("\\", "\\\\"), self.config(host).read_text())
            hosts.uninstall_host(self.project, host, True)
            self.assertEqual(self.config(host).read_bytes(), original)

    def test_user_modified_config_blocks_uninstall_and_reinstall(self):
        for host in hosts.TARGETS:
            self.install(host, True)
            path = self.config(host)
            changed = path.read_bytes() + b" \n"
            path.write_bytes(changed)
            for operation in (lambda: hosts.uninstall_host(self.project, host, True), lambda: self.install(host, True)):
                with self.assertRaises(TraceError) as error:
                    operation()
                self.assertEqual(error.exception.code, "host.conflict")
                self.assertEqual(path.read_bytes(), changed)

    def test_external_same_name_and_lost_receipt_preserved(self):
        for host in hosts.TARGETS:
            self.install(host, True)
            original = self.config(host).read_bytes()
            self.receipt(host).unlink()
            for operation in (lambda: self.install(host), lambda: hosts.uninstall_host(self.project, host, True)):
                with self.assertRaises(TraceError):
                    operation()
                self.assertEqual(self.config(host).read_bytes(), original)

    def test_bad_config_duplicate_keys_and_oversized(self):
        for host, original in [("claude", b'{bad'), ("claude", b'{"x":1,"x":2}'),
                               ("claude", b'{"mcpServers":[]}'), ("codex", b'[broken'),
                               ("codex", b'mcp_servers = 1'), ("codex", b'x' * (hosts.MAX_CONFIG_BYTES + 1))]:
            self.write(host, original)
            with self.assertRaises(TraceError):
                self.install(host, True)
            self.assertEqual(self.config(host).read_bytes(), original)
            self.assertFalse(self.receipt(host).exists())

    def test_corrupt_or_prepared_receipt_and_backup_digest(self):
        self.install("claude", True)
        receipt = self.receipt("claude")
        original = receipt.read_bytes()
        for content in (b"{}", b"garbage", original.replace(b'"installed"', b'"prepared"'),
                        original.replace(b'"before_sha256": null', b'"before_sha256": "bad"')):
            receipt.write_bytes(content)
            with self.assertRaises(TraceError):
                hosts.uninstall_host(self.project, "claude", True)
            self.assertTrue(self.config("claude").exists())
        receipt.write_bytes(original)
        self.assertTrue(hosts.uninstall_host(self.project, "claude", True)["applied"])

    def test_install_failure_rolls_back_both_files(self):
        original = b'{"user":true}\n'
        self.write("claude", original)
        atomic = hosts._atomic
        count = 0
        def fail_once(path, data, project):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError("synthetic receipt commit failure")
            return atomic(path, data, project)
        with patch.object(hosts, "_atomic", side_effect=fail_once):
            with self.assertRaises(OSError):
                self.install("claude", True)
        self.assertEqual(self.config("claude").read_bytes(), original)
        self.assertFalse(self.receipt("claude").exists())
        self.install("claude", True)
        self.assertEqual(self.install("claude", True)["action"], "unchanged")

    def test_uninstall_failure_restores_installed_config(self):
        self.install("claude", True)
        original = self.config("claude").read_bytes()
        replace = hosts._replace_checked
        def fail_receipt(path, expected, replacement, project):
            if path == self.receipt("claude"):
                raise OSError("synthetic uninstall failure")
            return replace(path, expected, replacement, project)
        with patch.object(hosts, "_replace_checked", side_effect=fail_receipt):
            with self.assertRaises(OSError):
                hosts.uninstall_host(self.project, "claude", True)
        self.assertEqual(self.config("claude").read_bytes(), original)
        self.assertEqual(self.install("claude")["action"], "unchanged")

    def test_detect_intervening_write_and_preserve_user_edit(self):
        self.write("claude", b"{}\n")
        replace = hosts._replace_checked
        def mutate_before_config(path, expected, replacement, project):
            if path == self.config("claude"):
                path.write_bytes(b'{"user_changed":true}\n')
            return replace(path, expected, replacement, project)
        with patch.object(hosts, "_replace_checked", side_effect=mutate_before_config):
            with self.assertRaises(TraceError):
                self.install("claude", True)
        self.assertEqual(self.config("claude").read_bytes(), b'{"user_changed":true}\n')
        self.assertEqual(json.loads(self.receipt("claude").read_bytes())["phase"], "prepared")

    def test_reinstall_failure_restores_previous_install(self):
        self.install("claude", True)
        before_config, before_receipt = self.config("claude").read_bytes(), self.receipt("claude").read_bytes()
        atomic = hosts._atomic
        count = 0
        def fail(path, data, project):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError("synthetic reinstall failure")
            return atomic(path, data, project)
        with patch.object(hosts, "_atomic", side_effect=fail):
            with self.assertRaises(OSError):
                self.install("claude", True, str(self.project / "new-python"))
        self.assertEqual(self.config("claude").read_bytes(), before_config)
        self.assertEqual(self.receipt("claude").read_bytes(), before_receipt)

    def test_symlink_and_hardlink_rejected(self):
        target = self.project / "target"
        target.write_bytes(b"{}")
        try:
            self.config("claude").symlink_to(target)
        except OSError:
            pass  # Windows may not grant symlink privilege; hardlink test still runs.
        else:
            with self.assertRaises(TraceError):
                self.install("claude", True)
            self.config("claude").unlink()
        os.link(target, self.config("claude"))
        with self.assertRaises(TraceError):
            self.install("claude", True)
        self.assertEqual(target.read_bytes(), b"{}")

    def test_lock_excludes_another_product_writer(self):
        with hosts._lock(self.project):
            with self.assertRaises(TraceError) as error:
                self.install("claude", True)
            self.assertEqual(error.exception.code, "host.busy")
        self.assertFalse(self.config("claude").exists())

    def test_explicit_arguments_and_toml_quoted_windows_paths(self):
        for value in ("yes", 1, None):
            with self.assertRaises(TraceError):
                hosts.install_host(self.project, "claude", self.python, self.workspace, value)
        for host in hosts.TARGETS:
            with self.assertRaises(TraceError):
                hosts.install_host(self.project, host, "python", self.workspace)
        with self.assertRaises(TraceError):
            self.install("other")
        command = str(self.project / 'path with spaces' / 'py"thon.exe')
        self.install("codex", True, command)
        self.assertEqual(tomllib.loads(self.config("codex").read_text())["mcp_servers"]["traceanchor"]["command"], command)


class ProvenanceTests(unittest.TestCase):
    """Packaged static traceability checks; no research snapshots or network needed."""
    def setUp(self):
        self.product = Path(__file__).resolve().parents[1]
        self.provenance = self.product / "docs" / "provenance"
        self.baselines = json.loads((self.provenance / "baselines.json").read_text(encoding="utf-8"))
        self.mapping = json.loads((self.provenance / "mechanisms.json").read_text(encoding="utf-8"))

    def test_fixed_baselines_and_separate_version_roles(self):
        import re
        sources = self.baselines["sources"]
        self.assertEqual({s["id"] for s in sources}, {"reverse", "rea", "craft", "seep"})
        for source in sources:
            self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", source["research_baseline"]))
            self.assertEqual(source["review_baselines"], [])
            self.assertIn(source["research_baseline"], source["product_influence_baselines"])
            self.assertTrue(source["url"].startswith("https://github.com/"))
            self.assertTrue(source["license_layers"])
            report, _ = source["report"].split("#")
            self.assertTrue((self.provenance / report).is_file())
        self.assertIn("review_baselines", self.baselines["baseline_policy"])
        self.assertIn("automatically", self.baselines["baseline_policy"])

    def test_bidirectional_source_and_local_maps_and_fixed_blob_anchors(self):
        baselines = {s["id"]: s for s in self.baselines["sources"]}
        mechanisms = self.mapping["mechanisms"]
        self.assertEqual(len({m["id"] for m in mechanisms}), len(mechanisms))
        expected_sources = {key: [] for key in baselines}
        expected_local = {}
        for mechanism in mechanisms:
            for field in ("id", "title", "adoption", "local", "contract", "rationale", "differences", "tests", "limitations", "maintenance", "falsification"):
                self.assertTrue(mechanism.get(field), (mechanism["id"], field))
            if mechanism["adoption"] == "original":
                self.assertEqual(mechanism["sources"], [])
            else:
                self.assertEqual(mechanism["adoption"], "independent-implementation")
                self.assertTrue(mechanism["sources"])
            for source_id in sorted({a["source"] for a in mechanism["sources"]}):
                expected_sources[source_id].append(mechanism["id"])
            for anchor in mechanism["sources"]:
                source = baselines[anchor["source"]]
                start, end = anchor["lines"]
                self.assertGreaterEqual(start, 1)
                self.assertGreaterEqual(end, start)
                expected = source["url"] + "/blob/" + source["research_baseline"] + "/" + anchor["path"] + f"#L{start}-L{end}"
                self.assertEqual(anchor["url"], expected)
                self.assertTrue(anchor["symbol"])
            for local in mechanism["local"]:
                expected_local.setdefault(local["module"], []).append(mechanism["id"])
                self.assertTrue((self.product / local["module"]).is_file(), local)
                self.assertTrue(local["symbol"])
            for test in mechanism["tests"]:
                self.assertTrue((self.product / test["path"]).is_file(), test)
                self.assertTrue(test["symbol"])
                self.assertTrue(test["level"])
        self.assertEqual(self.mapping["source_to_mechanisms"], expected_sources)
        self.assertEqual(self.mapping["local_to_mechanisms"], expected_local)

    def test_decisions_prompt_and_archive_recovery_are_self_contained(self):
        decisions = (self.provenance / "decisions.md").read_text(encoding="utf-8")
        for mechanism in self.mapping["mechanisms"]:
            self.assertIn(mechanism["id"], decisions)
        prompt = (self.product / "UPSTREAM-REVIEW-PROMPT.md").read_text(encoding="utf-8")
        for source in self.baselines["sources"]:
            self.assertIn(source["url"], prompt)
            self.assertIn(source["research_baseline"], prompt)
        for text in ("默认静态", "工作树", "保留用户改动", "research_baseline", "review_baselines", "product_influence_baselines",
                     "新增", "删除", "弃用", "许可", "release notes", "采用/试验/观察/不采用", "L1", "L2/L3", "租约", "完整性", "单独明确授权"):
            self.assertIn(text, prompt)
        template = (self.provenance / "review-template.md").read_text(encoding="utf-8")
        for text in ("旧 research_baseline", "product_influence_baselines", "实际覆盖", "archive_id", "preview", "恢复", "not-run", "原创新提议"):
            self.assertIn(text, template)
        notices = (self.provenance / "notices.md").read_text(encoding="utf-8")
        self.assertIn("code_reuse", notices)
        self.assertIn("均为空", notices)

    def test_public_host_and_provenance_docs_omit_private_machine_paths(self):
        import re
        paths = list(self.provenance.glob("*")) + [self.product / "docs/hosts.md", self.product / "UPSTREAM-REVIEW-PROMPT.md", self.product / "skills/traceanchor/SKILL.md"]
        pattern = re.compile(r"[A-Za-z]:[\\/](?:Users|Project)[\\/]|/Users/[^/]+/|/home/[^/]+/", re.I)
        for path in paths:
            if path.is_file():
                self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")), path.name)
        host_doc = (self.product / "docs/hosts.md").read_text(encoding="utf-8")
        self.assertIn("static-doc-blocked", host_doc)
        self.assertIn("真实 Codex 工作流端到端未执行", host_doc)
        self.assertIn("真实 Claude 工作流端到端未执行", host_doc)
        self.assertIn("dispatcher 是显式 stub", host_doc)


if __name__ == "__main__":
    unittest.main()
