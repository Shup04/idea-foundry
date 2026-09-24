"""Optional large-revision compression preserves bounded, immutable history."""

import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from foundry.storage import COMPRESSION_THRESHOLD, Store, encoded
from foundry.validation import Invalid, digest, read_json


class StorageCompressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state"
        self.large = {"value": "Synthetic personal evidence. " * 45000}
        self.assertGreater(len(encoded(self.large).encode()), COMPRESSION_THRESHOLD)

    def store(self, *, compress=True, max_bytes=2_000_000):
        # These fixtures exercise the storage envelope; evidence validators are
        # covered separately and are still called by Store for every revision.
        return Store(self.path, validator=lambda state: None, max_bytes=max_bytes, compress=compress)

    def revision(self):
        pointer = read_json(self.path / "current.json")
        suffix = ".json.gz" if pointer.get("compression") == "gzip" else ".json"
        return pointer, self.path / "history" / (pointer["revision"] + suffix)

    def test_default_remains_plain_even_for_large_revisions(self):
        store = Store(self.path, validator=lambda state: None)
        store.initialize(self.large)
        pointer, path = self.revision()
        self.assertNotIn("compression", pointer)
        self.assertEqual(path.suffix, ".json")
        self.assertEqual(store.load(), self.large)

    def test_old_plain_history_and_new_compressed_revisions_round_trip_without_rewrite(self):
        plain = self.store(compress=False)
        plain.initialize({"value": "Original small statement"})
        old_pointer, old_path = self.revision()
        old_bytes = old_path.read_bytes()
        compressed = self.store()
        self.assertEqual(compressed.load(), {"value": "Original small statement"})
        compressed.update(lambda state: state.update(self.large), "Synthetic large revision")
        pointer, path = self.revision()
        self.assertEqual(pointer["compression"], "gzip")
        raw = gzip.decompress(path.read_bytes()).decode("utf-8")
        record = json.loads(raw)
        self.assertEqual(record["previous"], old_pointer["revision"])
        self.assertEqual(pointer["sha256"], digest(raw))
        self.assertEqual(plain.load(), self.large, "Read format comes from the pointer, independent of write preference")
        self.assertEqual(path.read_bytes()[4:8], b"\x00\x00\x00\x00", "gzip timestamp must not vary")
        self.assertLess(path.stat().st_size, len(raw.encode()) // 10)
        compressed_bytes = path.read_bytes()
        compressed.update(lambda state: state.update(value="Small again"), "Synthetic small revision")
        latest, latest_path = self.revision()
        self.assertNotIn("compression", latest)
        self.assertEqual(read_json(latest_path)["previous"], pointer["revision"])
        self.assertEqual(path.read_bytes(), compressed_bytes)
        self.assertEqual(old_path.read_bytes(), old_bytes)
        self.assertEqual(compressed.load(), {"value": "Small again"})

    def test_compressed_revision_loads_in_a_fresh_process(self):
        self.store().initialize(self.large)
        result = subprocess.run([sys.executable, "-B", "-c",
            "from pathlib import Path; import json, sys; from foundry.storage import Store; "
            "state=Store(Path(sys.argv[1]), validator=lambda value: None).load(); "
            "print(json.dumps({'characters': len(state['value'])}))", str(self.path)],
            capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), {"characters": len(self.large["value"])})

    def test_corrupt_compression_and_changed_payload_are_rejected(self):
        store = self.store()
        store.initialize(self.large)
        _, path = self.revision()
        original = path.read_bytes()
        for broken in (original[:-8], original[:-1] + bytes([original[-1] ^ 255]), b"not gzip"):
            with self.subTest(size=len(broken)):
                path.write_bytes(broken)
                with self.assertRaisesRegex(Invalid, "invalid compressed state revision"):
                    store.load()
        record = json.loads(gzip.decompress(original))
        record["state"]["value"] = "Changed payload with valid gzip checksum"
        path.write_bytes(gzip.compress(encoded(record).encode(), compresslevel=3, mtime=0))
        with self.assertRaisesRegex(Invalid, "state revision hash mismatch"):
            store.load()

    def test_decompression_limit_precedes_json_parsing(self):
        self.store().initialize(self.large)
        reader = self.store(max_bytes=1000)
        with patch("foundry.storage._pairs", side_effect=AssertionError("oversized payload was parsed")):
            with self.assertRaisesRegex(Invalid, "after decompression"):
                reader.load()

    def test_duplicate_keys_and_nonfinite_json_retain_the_existing_guards(self):
        self.store().initialize(self.large)
        _, path = self.revision()
        for raw, expected in ((b'{"state":{"value":1,"value":2}}', "duplicate JSON key"),
                              (b'{"state":{"value":NaN}}', "non-finite JSON")):
            with self.subTest(expected=expected):
                path.write_bytes(gzip.compress(raw, compresslevel=3, mtime=0))
                with self.assertRaisesRegex(Invalid, expected):
                    self.store().load()

    def test_interruption_before_pointer_preserves_the_previous_revision(self):
        store = self.store()
        original = {"value": "Keep this statement"}
        store.initialize(original)
        pointer_before = (self.path / "current.json").read_bytes()
        _, original_path = self.revision()
        original_bytes = original_path.read_bytes()
        with patch("foundry.storage.atomic_text", side_effect=OSError("Synthetic pointer interruption")):
            with self.assertRaisesRegex(OSError, "Synthetic pointer interruption"):
                store.update(lambda state: state.update(self.large), "Interrupted large revision")
        self.assertEqual((self.path / "current.json").read_bytes(), pointer_before)
        self.assertEqual(original_path.read_bytes(), original_bytes)
        self.assertEqual(store.load(), original)
        self.assertEqual(len(list((self.path / "history").glob("*.json.gz"))), 1)

    def test_compression_never_bypasses_the_uncompressed_write_budget_or_format_check(self):
        store = self.store(max_bytes=1000)
        store.initialize({"value": "Small"})
        previous = (self.path / "current.json").read_bytes()
        with self.assertRaisesRegex(Invalid, "state budget exceeded"):
            store.update(lambda state: state.update(self.large), "Oversized synthetic state")
        self.assertEqual((self.path / "current.json").read_bytes(), previous)
        pointer, _ = self.revision()
        pointer["compression"] = "unrecognized"
        (self.path / "current.json").write_text(encoded(pointer))
        with self.assertRaisesRegex(Invalid, "unsupported state compression"):
            store.load()


if __name__ == "__main__":
    unittest.main()
