#!/usr/bin/env python3
"""
export_shlokas.py — Export one JSON file per sarga with each verse's
number and its Devanagari text, read off the English markdown (which
carries the Devanagari alongside its IAST transliteration; the Telugu
markdown is in Telugu script, not Devanagari).

USAGE
-----
  python3 tools/export_shlokas.py

Reads:
  ../ganapati-sambavam/markdown/telugu/meta_data/chapter_topics.yaml
  (the authoritative shloka_range per topic — see NUMBERING below)
  ../ganapati-sambavam/markdown/english/sarga-N/topic_NN.md

Writes (into this site folder):
  shlokas/sarga-1.json ... sarga-10.json
  each: [{"number": <int>, "devanagari": "<pada 1>\n<pada 2>\n..."}, ...]

NUMBERING — why this doesn't just read "|| N ||" off each verse
-------------------------------------------------------------------
Same rationale as tools/export_vagdhenu_shards.py: the trailing
"danda + number" marker is inconsistent or missing across large
stretches of the English translation, so it isn't reliably
parseable. Instead each shloka is numbered by its POSITION within
its topic file, using the shloka_range already recorded in
chapter_topics.yaml for that (sarga, topic). Before trusting that,
the block count is checked against the YAML range's size; on a
mismatch the WHOLE topic is skipped with a loud warning rather than
guessing.

CAVEATS
-------------------------------------------------------------------
- A topic file with no English translation yet, or whose "### Shloka:"
  block count doesn't match its YAML shloka_range, is skipped
  entirely (printed as a warning) — its verses are simply absent
  from that sarga's output rather than guessed at.
- Each verse's padas are joined with "\n" in a single "devanagari"
  string, danda marks normalized to proper Devanagari ("।"/"॥"; the
  source mixes in ASCII pipes) and any trailing verse-number/citation
  debris ("N", "॥ N ॥", "॥ S.N ॥", ...) stripped down to a plain
  closing "॥".
"""

import json
import re
import yaml
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent.parent
SRC_REPO = SITE_DIR.parent / "ganapati-sambavam"
EN_BASE = SRC_REPO / "markdown" / "english"
YAML_PATH = SRC_REPO / "markdown" / "telugu" / "meta_data" / "chapter_topics.yaml"

OUT_DIR = SITE_DIR / "shlokas"

DEVANAGARI_RE = re.compile(r'[ऄ-हऽ-ॡ०-९]')
# Some files put multiple padas on one physical markdown line, joined by
# inline "<br/>" rather than real newlines — same handling build_data.py's
# own BR_RE does for the reading site.
BR_RE = re.compile(r'<br\s*/?>[ \t]*\n?', re.IGNORECASE)
DOUBLE_DANDA_RE = re.compile(r'\|\|')
SINGLE_DANDA_RE = re.compile(r'\|')
# Cosmetic only: strip any trailing run of danda-like characters with an
# optional citation (plain number or "sarga.verse") down to a single
# closing danda. A line with no trailing danda at all is left untouched.
TRAILING_CITATION_RE = re.compile(r'[।॥|]+\s*[.0-9०-९]*\s*[।॥|]*\s*$')
# Translator's QA notes like "[possible reading: X -> Y]" occasionally leak
# straight into a verse line rather than staying confined to the
# Meaning-of-Terms section — strip any bracketed note wherever it appears.
EDITORIAL_NOTE_RE = re.compile(r'\[[^\]]*\]')


def normalize_danda(line):
    line = EDITORIAL_NOTE_RE.sub('', line).strip()
    line = DOUBLE_DANDA_RE.sub('॥', line)
    line = SINGLE_DANDA_RE.sub('।', line)
    return line


def clean_trailing_citation(line):
    m = TRAILING_CITATION_RE.search(line)
    if m and any(ch in m.group(0) for ch in '।॥|'):
        return TRAILING_CITATION_RE.sub('॥', line)
    return line


def load_topic_ranges():
    """{(sarga_num, topic_num): (start, end)} from chapter_topics.yaml."""
    with open(YAML_PATH, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    ranges = {}
    for s in data['sargas']:
        for t in s['topics']:
            ranges[(s['number'], t['number'])] = (t['shloka_range']['start'], t['shloka_range']['end'])
    return ranges


def extract_shloka_blocks(path):
    """Parse one English topic .md file's '### Shloka:' blocks, in
    order. Returns a list of pada-line lists (Devanagari only, danda
    normalized, trailing citation debris cleaned) — no verse numbers;
    the caller assigns those positionally."""
    text = BR_RE.sub('\n', path.read_text(encoding='utf-8'))
    lines = text.split('\n')
    blocks = []
    in_shloka = False
    deva_lines = []

    def flush():
        if not deva_lines:
            return
        cleaned = list(deva_lines)
        cleaned[-1] = clean_trailing_citation(cleaned[-1])
        blocks.append(cleaned)

    for raw in lines:
        s = raw.strip()
        if s.startswith('### '):
            if in_shloka:
                flush()
                deva_lines = []
            in_shloka = (s[4:].strip() == 'Shloka:')
            continue
        if not s:
            continue
        if in_shloka:
            if DEVANAGARI_RE.search(s):
                deva_lines.append(normalize_danda(s))
    if in_shloka:
        flush()
    return blocks


def build_sarga_shlokas(n, topic_ranges):
    sarga_dir = EN_BASE / f'sarga-{n}'
    if not sarga_dir.is_dir():
        return None, []

    entries = []
    skipped_topics = []

    sarga_topic_nums = sorted(t for (sn, t) in topic_ranges if sn == n)
    for topic_num in sarga_topic_nums:
        start, end = topic_ranges[(n, topic_num)]
        expected = end - start + 1
        tf = sarga_dir / f'topic_{topic_num:02d}.md'
        if not tf.exists():
            skipped_topics.append((tf.name, f"no English translation yet (shlokas {start}-{end})"))
            continue
        blocks = extract_shloka_blocks(tf)
        if len(blocks) != expected:
            skipped_topics.append((tf.name, f"{len(blocks)} '### Shloka:' block(s) found, "
                                              f"expected {expected} (shlokas {start}-{end})"))
            continue
        for i, padas in enumerate(blocks):
            vnum = start + i
            entries.append({"number": vnum, "devanagari": "\n".join(padas)})

    entries.sort(key=lambda e: e["number"])
    return entries, skipped_topics


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    topic_ranges = load_topic_ranges()
    print(f"Reading English markdown from {EN_BASE}\n")

    total_written = 0
    for n in range(1, 11):
        entries, skipped_topics = build_sarga_shlokas(n, topic_ranges)
        if entries is None:
            print(f"sarga-{n}: no English markdown directory — skipped")
            continue
        for fname, reason in skipped_topics:
            print(f"sarga-{n}: {fname}: {reason}")
        if not entries:
            print(f"sarga-{n}: nothing to export (no source yet)\n")
            continue
        out_path = OUT_DIR / f"sarga-{n}.json"
        out_path.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f"sarga-{n}: wrote {len(entries)} verse(s) -> {out_path.relative_to(SITE_DIR)}\n")
        total_written += len(entries)

    print(f"Done. {total_written} verse(s) exported across "
          f"{len(list(OUT_DIR.glob('sarga-*.json')))} file(s) in {OUT_DIR.relative_to(SITE_DIR)}/")


if __name__ == '__main__':
    main()
