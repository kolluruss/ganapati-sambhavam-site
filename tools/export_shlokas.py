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
- sarga-7/topic_07.md is special-cased (build_sarga7_topic07_verses):
  its embedded Bhagavad Gita quotation collapses 4 verses (80-83)
  into a single "### Shloka:" heading, so the normal 1-heading-per-
  verse assumption doesn't hold. That block is split back into its 4
  verses using their own embedded "<danda> N <danda>" markers (see
  split_multi_verse_block). If this file's structure changes and the
  special case stops matching, it bails and the topic is skipped
  with a warning like any other mismatch, rather than mislabeling.
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


def extract_shloka_blocks(path, clean_last_line=True):
    """Parse one English topic .md file's '### Shloka:' blocks, in
    order. Returns a list of pada-line lists (Devanagari only, danda
    normalized) — no verse numbers; the caller assigns those
    positionally. By default the last line of each block has its
    trailing citation debris cleaned to a plain closing danda; pass
    clean_last_line=False to keep it (needed when a block actually
    holds more than one embedded verse — see split_multi_verse_block)."""
    text = BR_RE.sub('\n', path.read_text(encoding='utf-8'))
    lines = text.split('\n')
    blocks = []
    in_shloka = False
    deva_lines = []

    def flush():
        if not deva_lines:
            return
        cleaned = list(deva_lines)
        if clean_last_line:
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


# Matches a verse-end marker that still carries its citation digits (as
# opposed to a bare mid-verse danda) — used to split a '### Shloka:'
# block that actually holds more than one embedded verse.
VERSE_MARKER_WITH_DIGITS_RE = re.compile(r'[।॥]+\s*[0-9०-९]+\s*[।॥]*')


def split_multi_verse_block(padas):
    """Split a block whose padas actually span multiple verses, each
    ending in its own '<danda> N <danda>' marker, into separate
    per-verse pada-lists. Used only for sarga-7/topic_07's embedded
    Gita quotation, which collapses 4 verses into a single
    '### Shloka:' heading in the English markdown."""
    groups, current = [], []
    for line in padas:
        current.append(line)
        if VERSE_MARKER_WITH_DIGITS_RE.search(line):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def build_sarga7_topic07_verses():
    """Special case: sarga-7/topic_07.md's 12 '### Shloka:' blocks map
    to 15 verses (79-93), not 1:1 — block 2 is a 4-pada-group Gita
    quotation that collapses verses 80-83 into a single heading.
    Bails (returns None) if the file's structure changes so this
    stops matching, rather than silently mislabeling verses."""
    tf = EN_BASE / 'sarga-7' / 'topic_07.md'
    blocks = extract_shloka_blocks(tf, clean_last_line=False)
    if len(blocks) != 12:
        return None

    entries = [{"number": 79, "devanagari": "\n".join(
        blocks[0][:-1] + [clean_trailing_citation(blocks[0][-1])])}]

    gita_subverses = split_multi_verse_block(blocks[1])
    if len(gita_subverses) != 4:
        return None
    for i, sub in enumerate(gita_subverses):
        sub = sub[:-1] + [clean_trailing_citation(sub[-1])]
        entries.append({"number": 80 + i, "devanagari": "\n".join(sub)})

    for i, block in enumerate(blocks[2:12]):
        entries.append({"number": 84 + i, "devanagari": "\n".join(
            block[:-1] + [clean_trailing_citation(block[-1])])})

    return entries


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

        if (n, topic_num) == (7, 7):
            special = build_sarga7_topic07_verses()
            if special is None:
                skipped_topics.append((tf.name, "special-case sarga-7/topic_07 splitter no longer "
                                                  "matches this file's structure — needs review"))
                continue
            entries.extend(special)
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
