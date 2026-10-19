#!/usr/bin/env python3
"""Render README.md and the SVG figures in assets/ from profile.toml.

    python scripts/build.py            # build in the repo this script lives in
    python scripts/build.py --root D   # build somewhere else (used by the tests)

Standard library only. Output is deterministic: the same profile.toml and
data/notebook.json always produce byte-identical files, so the weekly
workflow only commits when something actually changed.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import tomllib
from dataclasses import dataclass
from html import escape
from pathlib import Path

MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', 'DejaVu Sans Mono', monospace"
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"

# GitHub Primer colours, so the figures sit natively in either theme.
THEMES = {
    "dark": {
        "bg": "#0d1117", "panel": "#161b22", "border": "#30363d", "faint": "#21262d",
        "text": "#e6edf3", "muted": "#8b949e", "accent": "#d2a8ff", "accent2": "#79c0ff",
        "green": "#7ee787", "string": "#a5d6ff", "on_accent": "#0d1117", "raw_opacity": ".45",
    },
    "light": {
        "bg": "#ffffff", "panel": "#f6f8fa", "border": "#d0d7de", "faint": "#eaeef2",
        "text": "#1f2328", "muted": "#656d76", "accent": "#8250df", "accent2": "#0969da",
        "green": "#1a7f37", "string": "#0a3069", "on_accent": "#ffffff", "raw_opacity": ".3",
    },
}

REDUCED_MOTION = "@media (prefers-reduced-motion: reduce) { * { animation: none !important; } }"


def svg_open(width: int, height: int, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">\n'
        f"<title>{escape(title)}</title>\n"
    )


def pct(t: float, total: float) -> str:
    return f"{max(0.0, min(100.0, 100 * t / total)):.2f}%"


# ── Hero: the profile introduces itself by decoding, token by token ─────────

@dataclass
class Token:
    text: str               # includes a leading space when one precedes it
    alternatives: list[str]  # runner-up candidates; empty for ordinary tokens

    @property
    def sampled(self) -> bool:
        return bool(self.alternatives)


def tokenize(answer: str) -> list[Token]:
    """Split the hero answer into word/punctuation tokens; {a|b|c} is sampled."""
    tokens = []
    for m in re.finditer(r"(\s*)(\{[^}]*\}|[\w'’\-]+|[^\w\s])", answer):
        lead, body = m.groups()
        space = " " if lead else ""
        if body.startswith("{"):
            chosen, *alternatives = body[1:-1].split("|")
            tokens.append(Token(space + chosen, alternatives))
        else:
            tokens.append(Token(space + body, []))
    return tokens


def candidate_probs(seed: str, n: int) -> list[float]:
    rng = random.Random(seed)
    probs = [rng.uniform(0.48, 0.79)]
    for _ in range(n - 1):
        probs.append((1 - sum(probs)) * rng.uniform(0.45, 0.7))
    return [round(p, 2) for p in probs]


def render_hero(profile: dict, theme: dict) -> str:
    handle = profile["identity"]["handle"]
    model_id = profile["identity"]["model_id"]
    hero = profile["hero"]
    tokens = tokenize(hero["answer"])

    W, PAD = 900, 32
    FS, CW = 19, 19 * 0.6              # monospace advance is ~0.6em
    max_chars = int((W - 2 * PAD) // CW)
    PFS, PCW = 15, 15 * 0.6
    SFS, SCW = 12, 12 * 0.6
    TOP, LH = 128, 34

    # Wrap tokens into lines and give each one a column.
    placed, line, col = [], 0, 0
    for tok in tokens:
        text = tok.text
        if col and col + len(text) > max_chars:
            line, col = line + 1, 0
        if col == 0:
            text = text.lstrip()
        placed.append((tok, text, line, col))
        col += len(text)
    n_lines = line + 1
    last_baseline = TOP + (n_lines - 1) * LH
    POP_ROW, POP_PAD = 19, 6
    H = last_baseline + 12 + 3 * POP_ROW + 2 * POP_PAD + 16

    # Timeline (seconds).
    prompt = f'generate("{hero["prompt"]}")'
    t = 0.35
    prompt_times = []
    for _ in ">>> " + prompt:
        prompt_times.append(t)
        t += 0.045
    think_from, think_to = t + 0.25, t + 1.25
    t = think_to + 0.05
    token_times = []
    for tok, *_ in placed:
        t += 0.75 if tok.sampled else 0.09
        token_times.append(t)
    done = t + 0.4
    T = done + 5.5
    fade_from, fade_to = T - 0.8, T - 0.3

    css, body, k = [], [], 0

    # Every element loops on the same period T with its own keyframes.
    def animate(frames: str) -> str:
        nonlocal k
        k += 1
        css.append(f"@keyframes k{k}{{{frames}}} .k{k}{{animation:k{k} {T:.2f}s linear infinite}}")
        return f"k{k}"

    def hold(a: float) -> str:
        """Appear at `a`, stay until the whole loop fades out."""
        return animate(f"0%,{pct(a, T)}{{opacity:0}} {pct(a + 0.06, T)},{pct(fade_from, T)}{{opacity:1}} "
                       f"{pct(fade_to, T)},100%{{opacity:0}}")

    def window(a: float, until: float) -> str:
        """Visible only between `a` and `until`."""
        return animate(f"0%,{pct(a, T)}{{opacity:0}} {pct(a + 0.08, T)},{pct(until, T)}{{opacity:1}} "
                       f"{pct(until + 0.12, T)},100%{{opacity:0}}")

    def flash(a: float) -> str:
        """A short highlight that fades within half a second."""
        return animate(f"0%,{pct(a, T)}{{opacity:0}} {pct(a + 0.05, T)}{{opacity:.45}} "
                       f"{pct(a + 0.55, T)},100%{{opacity:0}}")

    c = theme
    body.append(f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" fill="{c["bg"]}" stroke="{c["border"]}"/>')
    body.append(f'<path d="M0.5 40 V12.5 a12 12 0 0 1 12 -12 H{W - 12.5} a12 12 0 0 1 12 12 V40 Z" fill="{c["panel"]}"/>')
    body.append(f'<line x1="0.5" y1="40.5" x2="{W - 0.5}" y2="40.5" stroke="{c["border"]}"/>')
    for i, dot in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        body.append(f'<circle cx="{22 + 18 * i}" cy="20.5" r="6" fill="{dot}"/>')
    body.append(f'<text x="{W / 2}" y="25" text-anchor="middle" font-family="{MONO}" font-size="12" '
                f'fill="{c["muted"]}">{escape(handle)} — inference</text>')
    body.append(f'<text x="{W - 18}" y="25" text-anchor="end" font-family="{MONO}" font-size="12" '
                f'fill="{c["muted"]}">{escape(model_id)} · T=0.7</text>')

    # Prompt, typed one character at a time.
    colours = [c["green"]] * 4 + [c["text"]] * len("generate(")
    colours += [c["string"]] * (len(hero["prompt"]) + 2) + [c["text"]]
    for i, (ch, a, fill) in enumerate(zip(">>> " + prompt, prompt_times, colours)):
        if ch == " ":
            continue
        body.append(f'<text class="{hold(a)}" x="{PAD + i * PCW:.1f}" y="78" font-family="{MONO}" '
                    f'font-size="{PFS}" fill="{fill}" textLength="{PCW:.1f}" '
                    f'lengthAdjust="spacingAndGlyphs">{escape(ch)}</text>')

    body.append(f'<text class="{window(think_from, think_to)}" style="opacity:0" x="{PAD}" y="{TOP}" '
                f'font-family="{MONO}" font-size="15" font-style="italic" fill="{c["muted"]}">'
                f'∴ thinking…</text>')

    # Answer tokens: a brief highlight marks each token boundary as it streams.
    popovers = []
    for (tok, text, ln, col), a in zip(placed, token_times):
        lead = len(text) - len(text.lstrip())
        x = PAD + (col + lead) * CW
        y = TOP + ln * LH
        word = text.strip()
        width = len(word) * CW
        body.append(f'<rect class="{flash(a)}" style="opacity:0" x="{x - 2:.1f}" y="{y - FS + 2}" '
                    f'width="{width + 4:.1f}" height="{FS + 6}" rx="4" fill="{c["accent2"]}"/>')
        fill = c["accent"] if tok.sampled else c["text"]
        weight = ' font-weight="600"' if tok.sampled else ""
        body.append(f'<text class="{hold(a)}" x="{x:.1f}" y="{y}" font-family="{MONO}" font-size="{FS}" '
                    f'fill="{fill}"{weight} textLength="{width:.1f}" lengthAdjust="spacingAndGlyphs">'
                    f"{escape(word)}</text>")
        if tok.sampled:
            popovers.append((tok, word, x, y, a))

    # Top-k popovers: the candidates the "model" chose between at each sampled token.
    for tok, word, x, y, a in popovers:
        options = [word] + tok.alternatives
        probs = candidate_probs(f"{handle}:{word}", len(options))
        name_w = max(len(o) for o in options) * SCW
        box_w = 10 + 14 + name_w + 10 + 64 + 8 + 4 * SCW + 10
        box_h = len(options) * POP_ROW + 2 * POP_PAD
        bx = min(max(x - 6, PAD - 6), W - PAD - box_w)
        by = y + 12
        rows = [f'<rect x="{bx:.1f}" y="{by}" width="{box_w:.1f}" height="{box_h}" rx="7" '
                f'fill="{c["panel"]}" stroke="{c["border"]}"/>']
        for i, (opt, p) in enumerate(zip(options, probs)):
            ry = by + POP_PAD + i * POP_ROW + 14
            chosen = i == 0
            colour = c["accent"] if chosen else c["muted"]
            if chosen:
                rows.append(f'<text x="{bx + 10:.1f}" y="{ry}" font-family="{MONO}" font-size="{SFS}" '
                            f'fill="{colour}">▸</text>')
            rows.append(f'<text x="{bx + 24:.1f}" y="{ry}" font-family="{MONO}" font-size="{SFS}" '
                        f'fill="{colour}">{escape(opt)}</text>')
            bar_x = bx + 24 + name_w + 10
            rows.append(f'<rect x="{bar_x:.1f}" y="{ry - 9}" width="64" height="8" rx="2" fill="{c["faint"]}"/>')
            rows.append(f'<rect x="{bar_x:.1f}" y="{ry - 9}" width="{64 * p:.1f}" height="8" rx="2" '
                        f'fill="{colour}"/>')
            rows.append(f'<text x="{bar_x + 72:.1f}" y="{ry}" font-family="{MONO}" font-size="{SFS}" '
                        f'fill="{colour}">{p:.2f}</text>')
        body.append(f'<g class="{window(a - 0.7, a + 0.35)}" style="opacity:0">' + "".join(rows) + "</g>")

    # Cursor and run statistics once decoding finishes.
    _, last_text, last_ln, last_col = placed[-1]
    cx = PAD + (last_col + len(last_text)) * CW + 3
    cy = TOP + last_ln * LH
    css.append("@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}} .blink{animation:blink 1s steps(1) infinite}")
    body.append(f'<g class="{hold(done)}" style="opacity:0"><rect class="blink" x="{cx:.1f}" y="{cy - FS + 3}" '
                f'width="{CW * 0.6:.1f}" height="{FS}" fill="{c["accent"]}"/></g>')
    stats = (f'<tspan fill="{c["muted"]}">▸ {len(tokens)} tokens · temperature 0.7 · top-p 0.95 · '
             f'stop_reason: </tspan><tspan fill="{c["green"]}">end_turn</tspan>')
    body.append(f'<text class="{hold(done + 0.15)}" style="opacity:0" x="{PAD}" y="{last_baseline + 46}" '
                f'font-family="{MONO}" font-size="12.5">{stats}</text>')

    return (svg_open(W, H, f"{profile['identity']['name']}: {re.sub(r'[{}]|[|][^}]*', '', hero['answer'])}")
            + "<style>" + "\n".join(css) + "\n" + REDUCED_MOTION + "</style>\n"
            + "\n".join(body) + "\n</svg>\n")


# ── Attention map: domains attend over methods, computed from project tags ──

def attention_matrix(profile: dict) -> tuple[list[str], list[tuple[str, str]], list[list[float]], list[int]]:
    cfg = profile["attention"]
    domains, keys, tau = cfg["domains"], cfg["keys"], cfg.get("temperature", 1.0)
    key_ids = [kid for kid, _ in keys]
    counts = {d: {kid: 0 for kid in key_ids} for d in domains}
    runs = {d: 0 for d in domains}
    for p in profile["projects"]:
        if p["domain"] not in counts:
            raise SystemExit(f"project {p['name']!r}: unknown domain {p['domain']!r}")
        runs[p["domain"]] += 1
        for u in p.get("uses", []):
            if u not in counts[p["domain"]]:
                raise SystemExit(f"project {p['name']!r}: unknown method {u!r} (see [attention].keys)")
            counts[p["domain"]][u] += 1
    matrix = []
    for d in domains:
        exps = [math.exp(counts[d][kid] / tau) for kid in key_ids]
        total = sum(exps)
        matrix.append([e / total for e in exps])
    return domains, keys, matrix, [runs[d] for d in domains]


def render_attention(profile: dict, theme: dict) -> str:
    domains, keys, matrix, runs = attention_matrix(profile)
    c = theme
    W = 900
    GX, PITCH_X, CELL_W = 196, 72, 68
    GY, PITCH_Y, CELL_H = 132, 48, 44
    H = GY + len(domains) * PITCH_Y + 52
    peak = max(max(row) for row in matrix)
    tau = profile["attention"].get("temperature", 1.0)

    css = [
        "@keyframes in{from{opacity:0}to{opacity:1}}",
        ".cell{animation:in .5s ease-out both}",
        "@keyframes scan{" + " ".join(
            f"{100 * i / len(domains):.2f}%{{transform:translateY({i * PITCH_Y}px)}}" for i in range(len(domains))
        ) + "}",
        f".scan{{animation:scan {2.2 * len(domains):.1f}s steps(1,end) 1.4s infinite}}",
        REDUCED_MOTION,
    ]
    body = [
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" fill="{c["bg"]}" stroke="{c["border"]}"/>',
        f'<text x="28" y="34" font-family="{MONO}" font-size="14" fill="{c["text"]}">'
        f'attention(<tspan fill="{c["accent"]}">Q</tspan> = domains, <tspan fill="{c["accent2"]}">K</tspan> = methods)</text>',
        f'<text x="{W - 28}" y="34" text-anchor="end" font-family="{MONO}" font-size="12" fill="{c["muted"]}">'
        f"softmax over project evidence · τ = {tau:g}</text>",
    ]
    for j, (_, label) in enumerate(keys):
        cx = GX + j * PITCH_X + CELL_W / 2
        body.append(f'<text x="{cx:.1f}" y="{GY - 12}" transform="rotate(-32 {cx:.1f} {GY - 12})" '
                    f'font-family="{SANS}" font-size="12" fill="{c["muted"]}">{escape(label)}</text>')

    scan_w = GX + len(keys) * PITCH_X - 20
    body.append(f'<g class="scan"><rect x="20" y="{GY - 3}" width="{scan_w}" height="{CELL_H + 6}" rx="8" '
                f'fill="none" stroke="{c["accent2"]}" stroke-width="1.5" stroke-dasharray="4 3"/></g>')

    for i, (domain, row, n) in enumerate(zip(domains, matrix, runs)):
        y = GY + i * PITCH_Y
        cy = y + CELL_H / 2
        body.append(f'<text x="{GX - 16}" y="{cy - 1:.1f}" text-anchor="end" font-family="{SANS}" '
                    f'font-size="14" font-weight="600" fill="{c["text"]}">{escape(domain)}</text>')
        body.append(f'<text x="{GX - 16}" y="{cy + 15:.1f}" text-anchor="end" font-family="{MONO}" '
                    f'font-size="11" fill="{c["muted"]}">{n} run{"s" if n != 1 else ""}</text>')
        best = max(row)
        for j, w in enumerate(row):
            x = GX + j * PITCH_X
            level = (w / peak) ** 0.75
            label = f"{w:.2f}".lstrip("0")
            ink = c["on_accent"] if level > 0.55 else c["muted"]
            weight = ' font-weight="700"' if math.isclose(w, best) else ""
            body.append(
                f'<g class="cell" style="animation-delay:{0.05 * (i + j):.2f}s">'
                f'<rect x="{x}" y="{y}" width="{CELL_W}" height="{CELL_H}" rx="6" fill="{c["faint"]}"/>'
                f'<rect x="{x}" y="{y}" width="{CELL_W}" height="{CELL_H}" rx="6" fill="{c["accent"]}" '
                f'fill-opacity="{0.04 + 0.96 * level:.3f}"/>'
                f'<text x="{x + CELL_W / 2}" y="{cy + 4:.1f}" text-anchor="middle" font-family="{MONO}" '
                f'font-size="12"{weight} fill="{ink}">{label}</text></g>'
            )

    fy = GY + len(domains) * PITCH_Y + 22
    body.append(f'<text x="28" y="{fy}" font-family="{SANS}" font-size="12" fill="{c["muted"]}">'
                "Each row sums to 1. Bold = where that domain attends most.</text>")
    gx0 = W - 28 - 180
    body.append(f'<text x="{gx0 - 8}" y="{fy}" text-anchor="end" font-family="{MONO}" font-size="11" '
                f'fill="{c["muted"]}">0</text>')
    for s in range(10):
        body.append(f'<rect x="{gx0 + 14 * s}" y="{fy - 10}" width="14" height="12" fill="{c["accent"]}" '
                    f'fill-opacity="{0.04 + 0.96 * (s / 9):.2f}"/>')
    body.append(f'<text x="{gx0 + 148}" y="{fy}" font-family="{MONO}" font-size="11" fill="{c["muted"]}">'
                f"{peak:.2f}</text>")

    return (svg_open(W, H, "Attention map: which methods each domain of my work relies on")
            + "<style>" + "\n".join(css) + "</style>\n" + "\n".join(body) + "\n</svg>\n")


# ── Training run: a career plotted as a loss curve with checkpoints ─────────

def loss_curve(profile: dict, t0: float, t1: float, n: int = 420) -> tuple[list[float], list[float], list[float]]:
    rng = random.Random(f"{profile['identity']['handle']}:loss")
    spikes = [(cp["when"], cp["spike"]) for cp in profile["checkpoints"] if cp.get("spike")]
    ts, raw = [], []
    for i in range(n):
        t = t0 + (t1 - t0) * i / (n - 1)
        value = 0.22 + 1.25 * (1 + 2.2 * (t - t0)) ** -0.75
        for when, amp in spikes:
            start = when - 0.05
            if t >= start:
                value += amp * min(1.0, (t - start) / 0.05) * math.exp(-max(0.0, t - when) / 0.28)
        noise = rng.gauss(0, 0.07) + (rng.random() < 0.04) * rng.uniform(0.05, 0.18)
        ts.append(t)
        raw.append(max(0.05, value * (1 + noise)))
    smooth, ema = [], raw[0]
    for v in raw:
        ema = 0.9 * ema + 0.1 * v
        smooth.append(ema)
    return ts, raw, smooth


def render_training(profile: dict, theme: dict) -> str:
    c = theme
    cps = profile["checkpoints"]
    W = 900
    X0, X1, Y0, Y1 = 64, 868, 64, 250
    T0, T_END = cps[0]["when"] - 0.25, cps[-1]["when"]
    AX0, AX1 = T0, T_END + 0.25
    YMAX = 1.8
    ts, raw, smooth = loss_curve(profile, T0, T_END)

    def sx(t: float) -> float:
        return X0 + (X1 - X0) * (t - AX0) / (AX1 - AX0)

    def sy(v: float) -> float:
        return Y1 - (Y1 - Y0) * min(v, YMAX) / YMAX

    def path(values: list[float]) -> str:
        return "M" + " L".join(f"{sx(t):.1f} {sy(v):.1f}" for t, v in zip(ts, values))

    legend_rows = math.ceil(len(cps) / 2)
    LY = Y1 + 50
    H = LY + legend_rows * 24 + 14
    draw = 3.2

    css = [
        "@keyframes draw{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}",
        f".curve{{stroke-dasharray:1;stroke-dashoffset:1;animation:draw {draw}s ease-in-out .2s forwards}}",
        "@keyframes in{from{opacity:0}to{opacity:1}}",
        ".pop{animation:in .4s ease-out both}",
        "@keyframes pulse{from{transform:scale(1);opacity:.7}to{transform:scale(2.2);opacity:0}}",
        ".pulse{transform-box:fill-box;transform-origin:center;animation:pulse 1.8s ease-out infinite}",
        "@media (prefers-reduced-motion: reduce) { * { animation: none !important; } "
        ".curve { stroke-dashoffset: 0 !important; } }",
    ]
    body = [
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" fill="{c["bg"]}" stroke="{c["border"]}"/>',
        f'<text x="28" y="34" font-family="{MONO}" font-size="14" fill="{c["text"]}">train/loss'
        f'<tspan fill="{c["muted"]}" font-family="{SANS}" font-size="13">  — what I don\'t know yet</tspan></text>',
        f'<line x1="{W - 340}" y1="30" x2="{W - 320}" y2="30" stroke="{c["accent"]}" stroke-width="2.5"/>',
        f'<text x="{W - 314}" y="34" font-family="{MONO}" font-size="11" fill="{c["muted"]}">EMA 0.9</text>',
        f'<line x1="{W - 244}" y1="30" x2="{W - 224}" y2="30" stroke="{c["muted"]}" stroke-width="1" opacity=".6"/>',
        f'<text x="{W - 218}" y="34" font-family="{MONO}" font-size="11" fill="{c["muted"]}">raw</text>',
        f'<text x="{W - 28}" y="34" text-anchor="end" font-family="{MONO}" font-size="11" fill="{c["muted"]}">'
        f'run {escape(profile["identity"]["model_id"])}</text>',
    ]
    for v in (0.5, 1.0, 1.5):
        body.append(f'<line x1="{X0}" y1="{sy(v):.1f}" x2="{X1}" y2="{sy(v):.1f}" stroke="{c["faint"]}"/>')
        body.append(f'<text x="{X0 - 10}" y="{sy(v) + 4:.1f}" text-anchor="end" font-family="{MONO}" '
                    f'font-size="11" fill="{c["muted"]}">{v:.1f}</text>')
    body.append(f'<line x1="{X0}" y1="{Y1}" x2="{X1}" y2="{Y1}" stroke="{c["border"]}"/>')
    for year in range(math.ceil(AX0), math.floor(AX1) + 1):
        body.append(f'<line x1="{sx(year):.1f}" y1="{Y1}" x2="{sx(year):.1f}" y2="{Y1 + 5}" stroke="{c["border"]}"/>')
        body.append(f'<text x="{sx(year):.1f}" y="{Y1 + 19}" text-anchor="middle" font-family="{MONO}" '
                    f'font-size="11" fill="{c["muted"]}">{year}</text>')

    body.append(f'<path class="pop" style="animation-delay:.3s" d="{path(raw)}" fill="none" '
                f'stroke="{c["muted"]}" stroke-width="1" opacity="{c["raw_opacity"]}"/>')
    body.append(f'<path class="curve" pathLength="1" d="{path(smooth)}" fill="none" stroke="{c["accent"]}" '
                f'stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')

    def on_curve(when: float) -> tuple[float, float]:
        i = min(range(len(ts)), key=lambda j: abs(ts[j] - when))
        return sx(ts[i]), sy(smooth[i])

    prev_x = -math.inf
    for n, cp in enumerate(cps, 1):
        x, y = on_curve(cp["when"])
        delay = 0.2 + draw * (x - X0) / (X1 - X0)
        last = n == len(cps)
        parts = []
        if x - prev_x < 22:  # too close to the previous marker: lift it on a stem
            parts.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y - 17:.1f}" stroke="{c["accent2"]}"/>')
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{c["accent2"]}"/>')
            y -= 26
        prev_x = x
        if last:
            parts.append(f'<circle class="pulse" cx="{x:.1f}" cy="{y:.1f}" r="8" fill="none" '
                         f'stroke="{c["green"]}" stroke-width="2"/>')
        ring = c["green"] if last else c["accent2"]
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="{c["bg"]}" stroke="{ring}" stroke-width="1.8"/>')
        parts.append(f'<text x="{x:.1f}" y="{y + 3.5:.1f}" text-anchor="middle" font-family="{MONO}" '
                     f'font-size="10" font-weight="700" fill="{ring}">{n}</text>')
        if cp.get("note"):  # above the flat stretch before the shift, with a leader to the marker
            parts.append(f'<line x1="{x - 12:.1f}" y1="{y - 34:.1f}" x2="{x - 6:.1f}" y2="{y - 10:.1f}" '
                         f'stroke="{c["muted"]}"/>')
            parts.append(f'<text x="{x - 16:.1f}" y="{y - 38:.1f}" text-anchor="end" font-family="{SANS}" '
                         f'font-size="11.5" font-style="italic" fill="{c["muted"]}">{escape(cp["note"])}</text>')
        if last:
            parts.append(f'<text x="{x - 14:.1f}" y="{y + 32:.1f}" text-anchor="end" font-family="{SANS}" '
                         f'font-size="11.5" font-style="italic" fill="{c["green"]}">still training · no early stopping</text>')
        body.append(f'<g class="pop" style="animation-delay:{delay:.2f}s">' + "".join(parts) + "</g>")

    for n, cp in enumerate(cps, 1):
        col, row = divmod(n - 1, legend_rows)
        lx = 34 + col * 430
        ly = LY + row * 24
        ring = c["green"] if n == len(cps) else c["accent2"]
        body.append(f'<circle cx="{lx + 8}" cy="{ly - 4}" r="8" fill="none" stroke="{ring}" stroke-width="1.5"/>')
        body.append(f'<text x="{lx + 8}" y="{ly - 0.5}" text-anchor="middle" font-family="{MONO}" font-size="9.5" '
                    f'font-weight="700" fill="{ring}">{n}</text>')
        body.append(f'<text x="{lx + 24}" y="{ly}" font-family="{MONO}" font-size="11" fill="{c["muted"]}">'
                    f'{escape(cp.get("date") or "")}</text>')
        body.append(f'<text x="{lx + 92}" y="{ly}" font-family="{SANS}" font-size="12.5" fill="{c["text"]}">'
                    f'{escape(cp["label"])}</text>')

    return (svg_open(W, H, "Training run: my path from electronics to machine learning, drawn as a loss curve")
            + "<style>" + "\n".join(css) + "</style>\n" + "\n".join(body) + "\n</svg>\n")


# ── README ──────────────────────────────────────────────────────────────────

def picture(name: str, alt: str) -> str:
    return (
        "<picture>\n"
        f'  <source media="(prefers-color-scheme: dark)" srcset="assets/{name}-dark.svg">\n'
        f'  <img alt="{escape(alt)}" src="assets/{name}-light.svg" width="100%">\n'
        "</picture>"
    )


def badge(label: str, message: str, colour: str, href: str, logo: str = "") -> str:
    def enc(s: str) -> str:
        return s.replace("-", "--").replace("_", "__").replace(" ", "%20")
    logo_q = f"&logo={logo}&logoColor=white" if logo else ""
    src = f"https://img.shields.io/badge/{enc(label)}-{enc(message)}-{colour}?style=flat-square{logo_q}"
    return f'<a href="{href}"><img alt="{escape(label)}: {escape(message)}" src="{src}"></a>'


def repo_url(handle: str, repo: str) -> str:
    return f"https://github.com/{repo}" if "/" in repo else f"https://github.com/{handle}/{repo}"


def run_ids(projects: list[dict]) -> dict[str, str]:
    ordered = sorted(projects, key=lambda p: (p["date"], p["name"]))
    return {p["name"]: f"exp-{i:02d}" for i, p in enumerate(ordered, 1)}


def render_cards(profile: dict) -> str:
    handle = profile["identity"]["handle"]
    labels = dict(profile["attention"]["keys"])
    ids = run_ids(profile["projects"])
    featured = [p for p in profile["projects"] if p.get("featured")]  # cards keep profile.toml order
    cells = []
    for p in featured:
        tags = " · ".join(labels[u] for u in p.get("uses", []))
        cells.append(
            '<td width="50%" valign="top">\n'
            f'<code>{ids[p["name"]]}</code> <b><a href="{repo_url(handle, p["repo"])}">{escape(p["name"])}</a></b>'
            f' <sub>· {escape(p["domain"])}</sub><br>\n'
            f'<i>{escape(p["question"])}</i><br>\n'
            f'<sub><b>METHOD</b> {escape(p["method"])}</sub><br>\n'
            f'<sub><b>RESULT</b> {escape(p["result"])}</sub><br>\n'
            f"<sub><code>{escape(tags)}</code></sub>\n"
            "</td>"
        )
    rows = ["<tr>\n" + "\n".join(cells[i:i + 2]) + "\n</tr>" for i in range(0, len(cells), 2)]
    others = sorted((p for p in profile["projects"] if not p.get("featured")), key=lambda p: p["date"], reverse=True)
    more = "\n".join(
        f'- `{ids[p["name"]]}` [{p["name"]}]({repo_url(handle, p["repo"])}): {p["summary"]}' for p in others
    )
    return (
        "<table>\n" + "\n".join(rows) + "\n</table>\n\n"
        f"<details>\n<summary><b>{len(others)} more runs</b> (data engineering, statistics, scrapers)</summary>\n\n"
        f"{more}\n\n</details>"
    )


def render_notebook(entries: list[dict], handle: str) -> str:
    if not entries:
        return "_No entries yet. The agent writes one each Monday after a week with public activity._"
    out = []
    for e in entries[:4]:
        repos = " ".join(f"[`{escape(r)}`]({repo_url(handle, r)})" for r in e.get("repos", []))
        meta = " · ".join(x for x in (repos, "✓ grounded", f"written by {escape(e['writer'])}") if x)
        out.append(f"**{e['week']}** · {escape(e['headline'])}  \n{escape(e['body'])}  \n<sub>{meta}</sub>")
    return "\n\n".join(out)


NOTEBOOK_DIAGRAM = """```mermaid
flowchart LR
    A[Public GitHub activity<br/>past 7 days] --> B[Claude<br/>structured JSON entry]
    B --> C{Grounding check<br/>repos and numbers}
    C -- pass --> E[README]
    C -- fail --> D[Repair round<br/>violations fed back]
    D --> B
    D -. fails again .-> F[Deterministic summary]
    F --> E
```"""


def render_readme(profile: dict, notebook: list[dict]) -> str:
    ident, links = profile["identity"], profile["links"]
    handle = ident["handle"]
    by_kind = {p["kind"]: p for p in reversed(profile["publications"])}

    badges = " ".join([
        badge("LinkedIn", "math-191231", "0A66C2", links["linkedin"]),
        badge("Email", "say hi", "EA4335", f"mailto:{links['email']}", "gmail"),
        badge("IEEE", "UCMMT 2021", "00629B", by_kind["Paper"]["url"], "ieee"),
        badge("Patent", "202241031906", "6e7781", by_kind["Patent"]["url"]),
        badge("README", "maintained by an LLM agent", "8250df", "#7-lab-notebook", "anthropic"),
    ])

    rows = profile["card"]["rows"]
    card = [f"| **{rows[0][0]}** | {rows[0][1]} |", "|:--|:--|"]
    card += [f"| **{k}** | {v} |" for k, v in rows[1:]]

    biases = ["| Prior | In practice | Evidence |", "|:--|:--|:--|"]
    biases += [f"| **{b['prior']}** | {b['practice']} | [`{b['evidence']}`]({repo_url(handle, b['evidence'])}) |"
               for b in profile["biases"]]

    pubs = []
    for p in profile["publications"]:
        title = f"[{p['title']}]({p['url']})" if p.get("url") else f"*{p['title']}*"
        doi = f" · DOI [{p['doi']}](https://doi.org/{p['doi']})" if p.get("doi") else ""
        note = f"  \n  <sub>{p['note']}</sub>" if p.get("note") else ""
        pubs.append(f"- **{p['kind']}** · {title}  \n  {p['authors']} · {p['venue']}{doi}{note}")
    if talks := profile.get("talks"):
        pubs.append(f"\n**Presentations** <sub>{talks['authors']}</sub>\n")
        pubs += [f"- **{date}** · *{title}* · {venue}" for date, title, venue in talks["items"]]
    bibtex = "\n\n".join(p["bibtex"].strip() for p in profile["publications"] if p.get("bibtex"))
    if bibtex:
        pubs.append(f"\n<details>\n<summary><b>BibTeX</b></summary>\n\n```bibtex\n{bibtex}\n```\n\n</details>")

    abstract = " ".join(profile["abstract"]["text"].split())

    return f"""<!-- Generated by scripts/build.py from profile.toml. Edit those, not this file. -->

{picture("hero", f"A language model decodes an introduction to {ident['name']}, token by token.")}

<p align="center">
{badges}
</p>

> **Abstract.** {abstract}

## 1. Model card

{chr(10).join(card)}

## 2. What I attend to

{picture("attention", "Attention heatmap: rows are the domains I work in, columns the methods I use, cells a softmax over my projects.")}

<sub>Each cell is a row-wise softmax over how many of my projects in that domain use that method, computed by
<code>scripts/build.py</code> from the tags in <code>profile.toml</code>. The dashed box is the query being processed.</sub>

## 3. Experiments

{render_cards(profile)}

## 4. Inductive biases

The priors I bring to every AI system, each with the repo where it's applied.

{chr(10).join(biases)}

## 5. Training run

{picture("training", "My path drawn as a training-loss curve, with checkpoints from an IEEE paper and a patent to LLM systems.")}

<sub>Loss spikes at each distribution shift (a new field) and recovers faster every time. The curve is illustrative;
the checkpoints are real.</sub>

## 6. Research, publications & talks

{chr(10).join(pubs)}

## 7. Lab notebook

Every Monday a GitHub Action reads my public activity and has Claude write this entry. It is only published if every
repository and number in it can be traced back to that activity.

{render_notebook(notebook, handle)}

<details>
<summary><b>How the agent works</b></summary>

{NOTEBOOK_DIAGRAM}

- **Grounded by construction.** The model only sees the week's activity as JSON, and returns `headline`, `body` and
  `repos` through structured output.
- **Checked, not trusted.** [`scripts/lab_notebook.py`](scripts/lab_notebook.py) rejects any repo that wasn't touched
  that week, any number not in the data, and any link. Violations are fed back for one repair round.
- **Fails closed.** If the repair also fails, or there's no API key, a deterministic summary is published instead. A week
  with no activity gets no entry.
- **Tested.** [`tests/`](tests) runs on every build.

</details>

---

<sub>Figures are SVGs generated by <a href="scripts/build.py"><code>scripts/build.py</code></a> from
<a href="profile.toml"><code>profile.toml</code></a>: no third-party stats services. Refreshed weekly by
<a href=".github/workflows/refresh.yml">GitHub Actions</a>.</sub>
"""


def build(root: Path) -> list[Path]:
    profile = tomllib.loads((root / "profile.toml").read_text(encoding="utf-8"))
    notebook_path = root / "data" / "notebook.json"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8")) if notebook_path.exists() else []

    assets = root / "assets"
    assets.mkdir(exist_ok=True)
    written = []
    for name, render in (("hero", render_hero), ("attention", render_attention), ("training", render_training)):
        for theme_name, theme in THEMES.items():
            path = assets / f"{name}-{theme_name}.svg"
            path.write_text(render(profile, theme), encoding="utf-8")
            written.append(path)
    readme = root / "README.md"
    readme.write_text(render_readme(profile, notebook), encoding="utf-8")
    written.append(readme)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    for path in build(args.root):
        print(f"wrote {path.relative_to(args.root)}")


if __name__ == "__main__":
    main()
