"""Static analysis qualification using only self-authored, temporary fixtures."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import warnings
import zipfile

from traceanchor.analysis import analyze_path, json_shape


class AnalysisTests(unittest.TestCase):
    def test_python_functions_calls_imports_locations_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = root / "fixture.py"
            sentinel = root / "executed"
            sample.write_text(
                "import os as operating\nfrom pathlib import Path\n"
                "class C:\n    async def work(self, x, *, flag=False):\n"
                "        return operating.path.join(x, 'tail')\n"
                "Path(" + repr(str(sentinel)) + ").write_text('executed')\n", encoding="utf-8")
            result = analyze_path(sample)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["target_kind"], "development-component")
            functions = [f for f in result["facts"] if f["kind"] == "python-function"]
            self.assertEqual(functions[0]["qualified_name"], "C.work")
            self.assertEqual(functions[0]["line"], 4)
            self.assertEqual(functions[0]["end_line"], 5)
            self.assertTrue(functions[0]["asynchronous"])
            self.assertEqual(functions[0]["keyword_only"], ["flag"])
            self.assertTrue(any(f.get("callee") == "operating.path.join" for f in result["facts"]))
            self.assertEqual(len([f for f in result["facts"] if f["kind"] == "python-import"]), 2)
            self.assertFalse(sentinel.exists())
            self.assertNotIn("sha256", result)
            json.dumps(result)

    def test_python_bad_syntax_and_truncated_source_remain_unknown_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.py"
            path.write_text("def invalid(\n", encoding="utf-8")
            self.assertEqual(analyze_path(path)["status"], "unknown")
            path.write_text("def valid():\n    return 42\n", encoding="utf-8")
            result = analyze_path(path, max_bytes=8)
            self.assertEqual(result["status"], "partial")
            self.assertTrue(result["coverage"]["truncated"])
            self.assertFalse(any(f["kind"] == "python-function" for f in result["facts"]))
            self.assertEqual(result["coverage"]["bytes_read"], 8)

    def test_javascript_hints_are_explicitly_inferred(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.mjs"
            path.write_text("import thing from './thing.js';\nconst x = require('lib');\n"
                            "fetch('/api/items');\n// 'https://example.invalid/hint'\n", encoding="utf-8")
            result = analyze_path(path)
            imports = [f for f in result["facts"] if f["kind"] == "javascript-import-hint"]
            self.assertEqual({f["module"] for f in imports}, {"./thing.js", "lib"})
            hints = [f for f in result["facts"] if f["kind"] == "endpoint-hint"]
            self.assertEqual({f["endpoint"] for f in hints}, {"/api/items", "https://example.invalid/hint"})
            self.assertTrue(all(f["evidence"] == "textual/inferred" for f in imports + hints))
            self.assertEqual(result["target_kind"], "javascript/web")

    def test_extension_manifest_and_generic_json_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps({"manifest_version": 3, "name": "Fixture", "version": "1.0",
                                        "permissions": ["storage"], "background": {"service_worker": "worker.js"}}), encoding="utf-8")
            result = analyze_path(path)
            self.assertEqual(result["target_kind"], "extension")
            manifest = next(f for f in result["facts"] if f["kind"] == "extension-manifest")
            self.assertEqual(manifest["fields"]["permissions"], ["storage"])
            data = Path(directory) / "data.json"
            data.write_text('{"users":[{"id":1,"enabled":false}],"empty":null}', encoding="utf-8")
            result = analyze_path(data)
            shape = next(f["shape"] for f in result["facts"] if f["kind"] == "json-structure")
            self.assertEqual(shape["properties"]["empty"], {"type": "null"})
            self.assertEqual(shape["properties"]["users"]["items"][0]["properties"]["enabled"], {"type": "boolean"})
            self.assertNotEqual(json_shape(True), json_shape(1))

    def test_bad_json_nonfinite_and_invalid_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            for payload in (b'{"x":', b'{"x":NaN}', b'\xff\xfe\x00'):
                path.write_bytes(payload)
                result = analyze_path(path)
                self.assertEqual(result["status"], "unknown")
                self.assertTrue(result["unknowns"])

    def test_apk_inventory_complete_hash_and_plain_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.apk"
            dex = b"synthetic dex inventory, not executable"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("AndroidManifest.xml", '<manifest package="test.fixture"/>')
                archive.writestr("classes.dex", dex)
            result = analyze_path(path)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["target_kind"], "apk")
            record = next(f for f in result["facts"] if f.get("name") == "classes.dex")
            self.assertEqual(record["sha256"], hashlib.sha256(dex).hexdigest())
            self.assertEqual(record["hash_status"], "complete")
            self.assertTrue(any(f.get("package") == "test.fixture" for f in result["facts"]))
            self.assertEqual(set(Path(directory).iterdir()), {path})

    def test_binary_axml_explicitly_unsupported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "binary.apk"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00binary-axml")
            result = analyze_path(path)
            self.assertEqual(result["status"], "partial")
            self.assertTrue(any("AXML" in item["reason"] for item in result["unknowns"]))

    def test_zip_unsafe_paths_symlink_and_duplicate_never_extracted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../escape.txt", b"outside")
                archive.writestr("C:\\absolute.txt", b"outside")
                link = zipfile.ZipInfo("link")
                link.create_system = 3
                link.external_attr = 0o120777 << 16
                archive.writestr(link, b"../outside")
            result = analyze_path(path)
            entries = [f for f in result["facts"] if f["kind"] == "zip-entry"]
            self.assertEqual(result["status"], "partial")
            self.assertEqual(len(entries), 3)
            self.assertIn("unsafe-path", entries[0]["issues"])
            self.assertIn("unsafe-path", entries[1]["issues"])
            self.assertIn("symlink-entry", entries[2]["issues"])
            self.assertTrue(all(f["sha256"] is None for f in entries))
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_zip_entry_budget_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "many.zip"
            with zipfile.ZipFile(path, "w") as archive:
                for i in range(4):
                    archive.writestr(str(i), b"x")
            result = analyze_path(path, max_entries=2)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["coverage"]["entries_omitted"], 4)
            self.assertEqual(result["coverage"]["expanded_bytes_read"], 0)
            self.assertTrue(result["coverage"]["truncated"])

    def test_zip_expansion_budget_and_compression_bomb(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bomb.zip"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("huge.txt", b"0" * 2_000_000)
            result = analyze_path(path, max_bytes=20_000)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["coverage"]["expanded_bytes_read"], 0)
            record = next(f for f in result["facts"] if f["kind"] == "zip-entry")
            self.assertIn("expanded-byte-budget", record["issues"])
            self.assertIn("compression-ratio-limit", record["issues"])
            self.assertIsNone(record["sha256"])

    def test_bad_and_prefix_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.apk"
            path.write_bytes(b"PK\x03\x04broken")
            self.assertEqual(analyze_path(path)["status"], "unknown")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("AndroidManifest.xml", b"<manifest/>")
            result = analyze_path(path, max_bytes=12)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["coverage"]["expanded_bytes_read"], 0)

    def test_pe_elf_macho_bounded_header_identification(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.bin"
            pe = bytearray(88)
            pe[:2] = b"MZ"
            struct.pack_into("<I", pe, 0x3C, 64)
            pe[64:68] = b"PE\x00\x00"
            struct.pack_into("<HHIIIHH", pe, 68, 0x8664, 3, 0, 0, 0, 0, 2)
            elf = bytearray(64)
            elf[:7] = b"\x7fELF\x02\x01\x01"
            struct.pack_into("<HHI", elf, 16, 2, 62, 1)
            struct.pack_into("<H", elf, 52, 64)
            macho = b"\xcf\xfa\xed\xfe" + struct.pack("<7I", 0x1000007, 3, 2, 0, 0, 0, 0)
            for payload, expected in ((pe, "PE"), (elf, "ELF"), (macho, "Mach-O")):
                path.write_bytes(payload)
                result = analyze_path(path)
                header = next(f for f in result["facts"] if f["kind"] == "native-header")
                self.assertEqual(header["format"], expected)
                self.assertTrue(header["complete"])
                self.assertEqual(result["target_kind"], "desktop/native")
                path.write_bytes(payload[:4])
                self.assertEqual(analyze_path(path)["status"], "partial")
            pe[0x3C:0x40] = b"\xff\xff\xff\x7f"
            path.write_bytes(pe)
            self.assertEqual(analyze_path(path)["status"], "partial")

    def test_missing_special_and_invalid_budget_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing"
            self.assertEqual(analyze_path(path)["status"], "unknown")
            self.assertEqual(analyze_path(None)["status"], "unknown")
            for budgets in ({"max_bytes": 0}, {"max_entries": -1}, {"max_bytes": True}):
                self.assertEqual(analyze_path(path, **budgets)["status"], "unknown")

    def test_directory_budget_and_link_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tree"
            source.mkdir()
            for i in range(4):
                (source / (str(i) + ".json")).write_text("{}", encoding="utf-8")
            result = analyze_path(source, max_entries=2)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["coverage"]["entries_examined"], 2)
            self.assertTrue(result["coverage"]["truncated"])

    def test_symlink_target_and_ancestor_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tree"
            source.mkdir()
            (source / "0.json").write_text("{}", encoding="utf-8")
            link = root / "alias"
            try:
                link.symlink_to(source, target_is_directory=True)
            except OSError as exc:
                self.skipTest("Symlink creation privilege unavailable: " + str(exc))
            self.assertEqual(analyze_path(link)["status"], "unknown")
            self.assertEqual(analyze_path(link / "0.json")["status"], "unknown")

    def test_zip_duplicate_names_have_explicit_issues(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.zip"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("same", b"one")
                    archive.writestr("same", b"two")
            result = analyze_path(path)
            entries = [f for f in result["facts"] if f["kind"] == "zip-entry"]
            self.assertEqual(result["status"], "partial")
            self.assertEqual(entries[0]["hash_status"], "complete")
            self.assertIn("duplicate-name", entries[1]["issues"])
            self.assertIsNone(entries[1]["sha256"])

    def test_directory_kind_is_not_last_file_kind(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "worker.js").write_text("import './util.js';", encoding="utf-8")
            (root / "data.json").write_text("{}", encoding="utf-8")
            self.assertEqual(analyze_path(root)["target_kind"], "development-component")
            (root / "manifest.json").write_text('{"manifest_version":3,"name":"test","version":"1"}', encoding="utf-8")
            self.assertEqual(analyze_path(root)["target_kind"], "extension")

    def test_zip_forged_eocd_count_cannot_bypass_real_entry_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forged.zip"
            with zipfile.ZipFile(path, "w") as archive:
                for i in range(4):
                    archive.writestr(str(i), b"x")
            data = bytearray(path.read_bytes())
            eocd = data.rfind(b"PK\x05\x06")
            struct.pack_into("<HH", data, eocd + 8, 1, 1)
            path.write_bytes(data)
            result = analyze_path(path, max_entries=2)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["coverage"]["expanded_bytes_read"], 0)
            self.assertTrue(any("Actual ZIP" in item["reason"] for item in result["unknowns"]))
            self.assertEqual(analyze_path(path, max_entries=5)["status"], "unknown")

    def test_corrupt_crc_does_not_refund_expansion_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corrupt.zip"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("first", b"a" * 400)
                archive.writestr("second", b"b" * 400)
            data = bytearray(path.read_bytes())
            central = data.find(b"PK\x01\x02")
            data[central + 16] ^= 1
            path.write_bytes(data)
            result = analyze_path(path, max_bytes=600)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["coverage"]["expanded_bytes_reserved"], 400)
            entries = [f for f in result["facts"] if f["kind"] == "zip-entry"]
            self.assertTrue(any("member-read-failed" in issue for issue in entries[0]["issues"]))
            self.assertIn("expanded-byte-budget", entries[1]["issues"])
            self.assertTrue(all(f["sha256"] is None for f in entries))

    def test_ast_fact_count_is_bounded_separately_from_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "many.py"
            path.write_text("call()\n" * 100, encoding="utf-8")
            result = analyze_path(path, max_entries=1)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(len(result["facts"]), result["coverage"]["max_facts"])
            self.assertGreater(result["coverage"]["facts_omitted"], 0)

    def test_http_text_facts_are_not_network_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.http"
            path.write_text("GET http://example.invalid/items\nPOST /api/test\n", encoding="utf-8")
            result = analyze_path(path)
            self.assertEqual(result["target_kind"], "protocol")
            self.assertEqual([f["method"] for f in result["facts"] if f["kind"] == "http-request-hint"], ["GET", "POST"])


if __name__ == "__main__":
    unittest.main()
