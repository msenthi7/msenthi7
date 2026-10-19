#!/usr/bin/env python3
"""Write this week's lab-notebook entry for the profile README.

    python scripts/lab_notebook.py --user msenthi7              # GitHub API + Claude
    python scripts/lab_notebook.py --activity week.json         # offline, from saved activity
    python scripts/lab_notebook.py --user msenthi7 --dry-run    # print, don't save

Pipeline: collect the week's public activity → Claude drafts an entry through
structured output → check() rejects any repository or number that can't be
traced to that activity → one repair round with the violations fed back →
deterministic fallback. Without ANTHROPIC_API_KEY the deterministic writer is
used directly, so the notebook keeps working with no API key at all.
"""
from __future__ import annotations

import argparse
import datetime as dt
import functools
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK = ROOT / "data" / "notebook.json"
MODEL = "claude-opus-5-5"
KEEP = 12
HEADLINE_MAX, BODY_MAX = 80, 420

SYSTEM_PROMPT = """\
You write the weekly entry in a research engineer's lab notebook, shown at the bottom of their GitHub \
profile. You receive one week of their public GitHub activity as JSON.

Return a headline (at most 70 characters), a body (at most 380 characters) describing what was worked \
on, and `repos`: every repository you name.

The entry is published automatically and checked by code first. It is rejected if it names a repository \
that isn't in the JSON, writes a number that isn't in the JSON, or contains a link or HTML. So stay \
strictly within the data: name repositories exactly as written, take counts from `totals` and \
`commit_count`, and describe commits by what their messages say rather than guessing at intent. Write \
in a terse, past-tense log style with no first person, emoji or hype. If the week was routine (for \
example, synced practice problems), say so plainly."""

ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "body": {"type": "string"},
        "repos": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "body", "repos"],
    "additionalProperties": False,
}

Draft = dict  # {"headline": str, "body": str, "repos": [str]}
# (activity, previous draft, its problems) -> new draft; None when the model gave nothing usable.
DraftFn = Callable[[dict, Draft | None, list[str] | None], Draft | None]


# ── Collect ─────────────────────────────────────────────────────────────────

def gh(path: str, params: dict | None = None, accept: str = "application/vnd.github+json"):
    url = f"https://api.github.com{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    req = urllib.request.Request(url, headers={
        "Accept": accept, "User-Agent": "profile-lab-notebook", "X-GitHub-Api-Version": "2022-11-28",
    })
    if token := os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def collect_activity(user: str, until: dt.datetime, days: int = 7) -> dict:
    since = until - dt.timedelta(days=days)
    since_iso, until_iso = (t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in (since, until))
    repos = gh(f"/users/{user}/repos", {"sort": "pushed", "per_page": 100, "type": "owner"})
    active = []
    for r in repos:
        if r["name"] == user or not r["pushed_at"] or r["pushed_at"] < since_iso:
            continue
        try:
            commits = gh(f"/repos/{user}/{r['name']}/commits",
                         {"author": user, "since": since_iso, "until": until_iso, "per_page": 100})
        except urllib.error.HTTPError as e:  # 409 = empty repository
            if e.code == 409:
                continue
            raise
        if commits:
            active.append({
                "repo": r["name"],
                "description": r["description"] or "",
                "language": r["language"] or "",
                "commit_count": len(commits),
                "commit_messages": [c["commit"]["message"].splitlines()[0][:120] for c in commits[:15]],
            })
    starred = gh(f"/users/{user}/starred", {"per_page": 30}, accept="application/vnd.github.star+json")
    stars = [{"repo": s["repo"]["full_name"], "description": (s["repo"]["description"] or "")[:160]}
             for s in starred if s["starred_at"] >= since_iso]
    return {
        "user": user,
        "since": since_iso[:10],
        "until": until_iso[:10],
        "known_repos": sorted(r["name"] for r in repos),
        "active": active,
        "starred": stars,
        "totals": {"commits": sum(a["commit_count"] for a in active), "repos": len(active), "stars": len(stars)},
    }


def model_view(activity: dict) -> dict:
    """What the model sees: the week's activity, without the full repo list used for checking."""
    return {k: activity[k] for k in ("user", "since", "until", "active", "starred", "totals")}


# ── Check ───────────────────────────────────────────────────────────────────

def allowed_repos(activity: dict) -> set[str]:
    names = {a["repo"] for a in activity["active"]}
    for s in activity["starred"]:
        names |= {s["repo"], s["repo"].split("/", 1)[1]}
    return names


def mentions(name: str, text: str) -> bool:
    return re.search(rf"(?<![\w/-]){re.escape(name)}(?![\w-])", text) is not None


def check(entry: Draft, activity: dict) -> list[str]:
    """Return every reason this entry can't be published; empty means grounded."""
    headline = str(entry.get("headline", "")).strip()
    body = str(entry.get("body", "")).strip()
    repos = entry.get("repos", [])
    text = f"{headline}\n{body}"
    problems = []
    if not headline or not body:
        problems.append("headline and body must both be non-empty")
    if len(headline) > HEADLINE_MAX:
        problems.append(f"headline is {len(headline)} characters; the limit is {HEADLINE_MAX}")
    if len(body) > BODY_MAX:
        problems.append(f"body is {len(body)} characters; the limit is {BODY_MAX}")

    allowed = allowed_repos(activity)
    for r in repos:
        if r not in allowed:
            problems.append(f"`{r}` is listed in repos but is not in this week's activity")
    for name in activity.get("known_repos", []):
        if name not in allowed and name != activity["user"] and mentions(name, text):
            problems.append(f"mentions `{name}`, which had no activity this week")
    for name in sorted(allowed):
        if mentions(name, text) and name not in repos and not any(r.endswith(f"/{name}") for r in repos):
            problems.append(f"`{name}` is named in the text but missing from repos")

    source_numbers = set(re.findall(r"\d+", json.dumps(model_view(activity))))
    for n in sorted(set(re.findall(r"\d+", text)) - source_numbers):
        problems.append(f"the number {n} does not appear in the activity data")
    if re.search(r"https?://|www\.|\]\(", text):
        problems.append("links are not allowed")
    if re.search(r"[<>]", text):
        problems.append("HTML is not allowed")
    return problems


# ── Write ───────────────────────────────────────────────────────────────────

def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def deterministic_entry(activity: dict) -> Draft:
    """A summary that is grounded by construction: only names and counts from the data."""
    active = sorted(activity["active"], key=lambda a: (-a["commit_count"], a["repo"]))
    stars = activity["starred"]
    totals = activity["totals"]
    if active:
        headline = f"{plural(totals['commits'], 'commit')} across {plural(totals['repos'], 'repo')}"
        body, repos = "Pushed to", []
        for a in active:
            part = f" {a['repo']} ({a['commit_count']}),"
            if len(body) + len(part) > BODY_MAX - 140:
                break
            body += part
            repos.append(a["repo"])
        body = body.rstrip(",") + "."
    else:
        headline = f"Reading week: {plural(totals['stars'], 'repo')} starred"
        body, repos = "", []
    if stars:
        named = []
        for s in stars:
            if len(body) + len(", ".join(named + [s["repo"]])) + 12 > BODY_MAX:
                break
            named.append(s["repo"])
        if named:
            body = f"{body} Starred {', '.join(named)}.".strip()
            repos += named
    return {"headline": headline, "body": body, "repos": repos}


def claude_draft(client, activity: dict, draft: Draft | None = None, problems: list[str] | None = None) -> Draft | None:
    import anthropic

    content = "This week's activity:\n" + json.dumps(model_view(activity), indent=1, ensure_ascii=False)
    if draft is not None:
        content += ("\n\nYour previous draft was rejected by the checker:\n" + json.dumps(draft, ensure_ascii=False)
                    + "\n\nProblems:\n" + "\n".join(f"- {p}" for p in problems or [])
                    + "\n\nWrite a corrected entry.")
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=8000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": ENTRY_SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.RateLimitError as e:
        print(f"warning: rate limited ({e.status_code}); falling back", file=sys.stderr)
        return None
    except anthropic.APIStatusError as e:
        print(f"warning: API error {e.status_code}: {e.message}; falling back", file=sys.stderr)
        return None
    except anthropic.APIConnectionError as e:
        print(f"warning: could not reach the API ({e}); falling back", file=sys.stderr)
        return None
    if response.stop_reason != "end_turn":
        print(f"warning: stop_reason={response.stop_reason}; falling back", file=sys.stderr)
        return None
    text = next((b.text for b in response.content if b.type == "text"), None)
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return None


def write_entry(activity: dict, draft_fn: DraftFn | None) -> dict | None:
    """Draft, check, repair once, fall back. Returns None for a week with no activity."""
    if not activity["active"] and not activity["starred"]:
        return None
    entry, writer, attempts = None, "deterministic", 0
    if draft_fn is not None:
        draft, problems = None, None
        for attempts in (1, 2):
            draft = draft_fn(activity, draft, problems)
            problems = check(draft, activity) if draft else ["no usable response"]
            if not problems:
                entry, writer = draft, MODEL
                break
            print(f"attempt {attempts} rejected:\n  " + "\n  ".join(problems), file=sys.stderr)
    if entry is None:
        entry = deterministic_entry(activity)
        problems = check(entry, activity)
        if problems:  # a bug in deterministic_entry, never in the data
            raise RuntimeError(f"deterministic entry failed its own check: {problems}")
    full_names = {s["repo"].split("/", 1)[1]: s["repo"] for s in activity["starred"]}
    until = dt.date.fromisoformat(activity["until"])
    year, week, _ = until.isocalendar()
    return {
        "week": f"{year}-W{week:02d}",
        "date": activity["until"],
        "headline": entry["headline"].strip(),
        "body": entry["body"].strip(),
        "repos": list(dict.fromkeys(full_names.get(r, r) for r in entry["repos"])),
        "writer": writer,
        "attempts": attempts,
    }


def save(entry: dict, path: Path = NOTEBOOK) -> None:
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries = [entry] + [e for e in entries if e["week"] != entry["week"]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries[:KEEP], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--user", default=os.environ.get("GITHUB_REPOSITORY_OWNER"))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--activity", type=Path, help="read activity JSON instead of calling GitHub")
    parser.add_argument("--dry-run", action="store_true", help="print the entry without saving it")
    args = parser.parse_args()

    if args.activity:
        activity = json.loads(args.activity.read_text(encoding="utf-8"))
    elif args.user:
        activity = collect_activity(args.user, dt.datetime.now(dt.timezone.utc), args.days)
    else:
        parser.error("pass --user or --activity")

    draft_fn = None
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        import anthropic
        draft_fn = functools.partial(claude_draft, anthropic.Anthropic())
    else:
        print("no ANTHROPIC_API_KEY: using the deterministic writer", file=sys.stderr)

    entry = write_entry(activity, draft_fn)
    if entry is None:
        print("no public activity this week: nothing to write")
        return
    print(json.dumps(entry, indent=2, ensure_ascii=False))
    if not args.dry_run:
        save(entry)


if __name__ == "__main__":
    main()
