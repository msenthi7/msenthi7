import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import lab_notebook as ln  # noqa: E402

WEEK = json.loads((ROOT / "tests" / "fixtures" / "week.json").read_text(encoding="utf-8"))

GOOD = {
    "headline": "Audit trail and retrieval caching for ClinIQ",
    "body": "ClaudeHack: added an audit trail for prescription checks and cached KB retrieval per patient "
            "(3 commits). Routine practice in neetcode-submissions (12 commits). Starred anthropics/claude-cookbooks.",
    "repos": ["ClaudeHack", "neetcode-submissions", "anthropics/claude-cookbooks"],
}


def week(**changes):
    activity = copy.deepcopy(WEEK)
    activity.update(changes)
    return activity


class CheckTest(unittest.TestCase):
    def test_grounded_entry_passes(self):
        self.assertEqual(ln.check(GOOD, WEEK), [])

    def test_rejects_repo_not_in_activity(self):
        entry = dict(GOOD, repos=GOOD["repos"] + ["TravelGenie"])
        self.assertIn("`TravelGenie` is listed in repos but is not in this week's activity", ln.check(entry, WEEK))

    def test_rejects_untouched_repo_named_in_text(self):
        entry = dict(GOOD, body=GOOD["body"] + " Also revisited Quant_LLM.")
        self.assertIn("mentions `Quant_LLM`, which had no activity this week", ln.check(entry, WEEK))

    def test_handle_is_not_mistaken_for_the_profile_repo(self):
        entry = dict(GOOD, headline="msenthi7 hardened ClinIQ")
        self.assertEqual(ln.check(entry, WEEK), [])

    def test_rejects_invented_number(self):
        entry = dict(GOOD, headline="40 commits shipped to ClaudeHack")
        self.assertIn("the number 40 does not appear in the activity data", ln.check(entry, WEEK))

    def test_rejects_named_repo_missing_from_list(self):
        entry = dict(GOOD, repos=["ClaudeHack", "anthropics/claude-cookbooks"])
        self.assertIn("`neetcode-submissions` is named in the text but missing from repos", ln.check(entry, WEEK))

    def test_rejects_links_and_html(self):
        problems = ln.check(dict(GOOD, body="See https://example.com <b>now</b>"), WEEK)
        self.assertIn("links are not allowed", problems)
        self.assertIn("HTML is not allowed", problems)

    def test_rejects_overlong_fields(self):
        problems = ln.check(dict(GOOD, body="x" * (ln.BODY_MAX + 1)), WEEK)
        self.assertTrue(any(p.startswith("body is") for p in problems))


class DeterministicTest(unittest.TestCase):
    def assertGrounded(self, activity):
        entry = ln.deterministic_entry(activity)
        self.assertEqual(ln.check(entry, activity), [], entry)

    def test_typical_week(self):
        self.assertGrounded(WEEK)

    def test_stars_only(self):
        self.assertGrounded(week(active=[], totals={"commits": 0, "repos": 0, "stars": 1}))

    def test_many_long_repo_names_stay_within_limits(self):
        long = "Medical-Chatbot-using-LLMs-Langchain-Pinecone-Flask-and-AWS"
        active = [dict(WEEK["active"][0], repo=f"{long}-{i}", commit_count=i + 1) for i in range(8)]
        stars = [{"repo": f"someone/{long}-{i}", "description": ""} for i in range(6)]
        self.assertGrounded(week(active=active, starred=stars, known_repos=[a["repo"] for a in active],
                                 totals={"commits": 36, "repos": 8, "stars": 6}))


class WriteEntryTest(unittest.TestCase):
    def test_no_activity_means_no_entry(self):
        quiet = week(active=[], starred=[], totals={"commits": 0, "repos": 0, "stars": 0})
        self.assertIsNone(ln.write_entry(quiet, draft_fn=None))

    def test_without_a_model_uses_the_deterministic_writer(self):
        entry = ln.write_entry(WEEK, draft_fn=None)
        self.assertEqual((entry["writer"], entry["week"]), ("deterministic", "2026-W43"))

    def test_rejected_draft_is_repaired_with_feedback(self):
        calls = []

        def draft_fn(activity, draft, problems):
            calls.append(problems)
            return dict(GOOD, headline="40 commits shipped") if draft is None else GOOD

        entry = ln.write_entry(WEEK, draft_fn)
        self.assertEqual((entry["writer"], entry["attempts"]), (ln.MODEL, 2))
        self.assertIn("the number 40 does not appear in the activity data", calls[1])

    def test_falls_back_when_repair_also_fails(self):
        entry = ln.write_entry(WEEK, lambda activity, draft, problems: dict(GOOD, repos=["TravelGenie"]))
        self.assertEqual((entry["writer"], entry["attempts"]), ("deterministic", 2))

    def test_falls_back_when_model_returns_nothing(self):
        entry = ln.write_entry(WEEK, lambda activity, draft, problems: None)
        self.assertEqual(entry["writer"], "deterministic")

    def test_short_star_names_are_expanded_for_links(self):
        draft = dict(GOOD, body=GOOD["body"].replace("anthropics/claude-cookbooks", "claude-cookbooks"),
                     repos=["ClaudeHack", "neetcode-submissions", "claude-cookbooks"])
        entry = ln.write_entry(WEEK, lambda activity, d, problems: draft)
        self.assertEqual(entry["writer"], ln.MODEL)
        self.assertIn("anthropics/claude-cookbooks", entry["repos"])


class SaveTest(unittest.TestCase):
    def test_rerunning_a_week_replaces_its_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notebook.json"
            first = ln.write_entry(WEEK, draft_fn=None)
            ln.save(first, path)
            ln.save(dict(first, headline="rewritten"), path)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([e["headline"] for e in saved], ["rewritten"])


if __name__ == "__main__":
    unittest.main()
