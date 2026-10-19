import json
import math
import shutil
import sys
import tempfile
import tomllib
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402

PROFILE = tomllib.loads((ROOT / "profile.toml").read_text(encoding="utf-8"))


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        shutil.copy(ROOT / "profile.toml", self.tmp / "profile.toml")

    def test_every_figure_is_valid_svg_in_both_themes(self):
        written = build.build(self.tmp)
        svgs = [p for p in written if p.suffix == ".svg"]
        self.assertEqual(len(svgs), 6)
        for path in svgs:
            ET.parse(path)  # raises on malformed XML

    def test_output_is_deterministic(self):
        first = {p.name: p.read_bytes() for p in build.build(self.tmp)}
        second = {p.name: p.read_bytes() for p in build.build(self.tmp)}
        self.assertEqual(first, second)

    def test_readme_has_every_section(self):
        build.build(self.tmp)
        readme = (self.tmp / "README.md").read_text(encoding="utf-8")
        for heading in ("## 1. Model card", "## 2. What I attend to", "## 3. Experiments", "## 4. Inductive biases",
                        "## 5. Training run", "## 6. Publications & patents", "## 7. Lab notebook"):
            self.assertIn(heading, readme)

    def test_notebook_entries_are_rendered_escaped(self):
        (self.tmp / "data").mkdir()
        entry = {"week": "2026-W43", "date": "2026-10-19", "headline": "<script>x</script>", "body": "ok",
                 "repos": ["ClaudeHack"], "writer": "deterministic", "attempts": 0}
        (self.tmp / "data" / "notebook.json").write_text(json.dumps([entry]), encoding="utf-8")
        build.build(self.tmp)
        readme = (self.tmp / "README.md").read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;", readme)
        self.assertNotIn("<script>", readme)


class AttentionTest(unittest.TestCase):
    def test_rows_are_probability_distributions(self):
        _, _, matrix, _ = build.attention_matrix(PROFILE)
        for row in matrix:
            self.assertTrue(math.isclose(sum(row), 1.0))

    def test_unknown_method_tag_is_rejected(self):
        bad = json.loads(json.dumps(PROFILE))
        bad["projects"][0]["uses"].append("telepathy")
        with self.assertRaises(SystemExit):
            build.attention_matrix(bad)


class HeroTest(unittest.TestCase):
    def test_sampled_tokens_carry_their_alternatives(self):
        tokens = build.tokenize("I {build|ship} things.")
        self.assertEqual([t.text for t in tokens], ["I", " build", " things", "."])
        self.assertEqual(tokens[1].alternatives, ["ship"])

    def test_candidate_probabilities_are_ranked_and_sum_below_one(self):
        probs = build.candidate_probs("seed", 3)
        self.assertEqual(probs, sorted(probs, reverse=True))
        self.assertLessEqual(sum(probs), 1.0)


if __name__ == "__main__":
    unittest.main()
