"""Source ancestry remains faithful when independent roots share text."""

from copy import deepcopy
import unittest

from foundry.validation import Invalid, digest, source_roots


def source(sid, text, *, origin=None, parents=()):
    return {"id": sid, "kind": "user_supplied_summary", "origin": origin or sid,
            "version": 1, "text": text, "sha256": digest(text), "locator": "Synthetic evidence",
            "parents": list(parents)}


class SourceAncestryTests(unittest.TestCase):
    def test_identical_roots_share_canonical_origin_and_derived_text_does_not_add_one(self):
        sources = {row["id"]: row for row in (
            source("first", "Identical original", origin="z-origin"),
            source("second", "Identical original", origin="a-origin"),
            source("other", "Independent original", origin="other-origin"),
            source("derived", "Identical original", origin="000-derived", parents=("first", "other")),
            source("summary", "A later summary", parents=("derived", "second")),
        )}
        original = deepcopy(sources)
        for order in (("summary", "first", "other", "second"), ("second", "other", "first", "summary")):
            memo = {}
            roots = {sid: source_roots(sid, sources, memo=memo) for sid in order}
            self.assertEqual(roots["first"], {"a-origin"})
            self.assertEqual(roots["second"], {"a-origin"})
            self.assertEqual(roots["other"], {"other-origin"})
            self.assertEqual(roots["summary"], {"a-origin", "other-origin"})
        self.assertEqual(sources, original)

    def test_cached_independent_roots_do_not_hide_missing_or_cyclic_ancestry(self):
        sources = {row["id"]: row for row in (
            source("safe", "Independent original"),
            source("missing-child", "Missing parent", parents=("absent",)),
            source("cycle-a", "Cycle A", parents=("cycle-b",)),
            source("cycle-b", "Cycle B", parents=("cycle-a",)),
        )}
        memo = {}
        self.assertEqual(source_roots("safe", sources, memo=memo), {"safe"})
        with self.assertRaisesRegex(Invalid, "missing source"):
            source_roots("missing-child", sources, memo=memo)
        with self.assertRaisesRegex(Invalid, "cyclic source ancestry"):
            source_roots("cycle-a", sources, memo=memo)


if __name__ == "__main__":
    unittest.main()
