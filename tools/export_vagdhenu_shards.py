#!/usr/bin/env python3
"""
export_vagdhenu_shards.py — Export per-sarga JSON shards of Devanagari
shloka text, in the batch-render input format Vāgdhenu expects
(https://github.com/prathoshap/vagdhenu), so verse-recitation audio can
be generated and dropped into the Drive folder tools/build_data.py
already syncs from (AUDIO_GDRIVE_FOLDER_ID).

Vagdhenu shard schema (one array per file):
  [{"id", "meter", "padas": [devanagari pada strings], "seed",
    "no_sandhi", "out"}, ...]

USAGE
-----
  python3 tools/export_vagdhenu_shards.py

Reads:
  ../ganapati-sambavam/markdown/telugu/meta_data/chapter_topics.yaml
  (the authoritative shloka_range per topic — see NUMBERING below)
  ../ganapati-sambavam/markdown/english/sarga-N/topic_NN.md
  (Devanagari lines only — the IAST transliteration alongside them is
  ignored; Vagdhenu's example input is Devanagari)
  audio/*.wav, audio/*.mp3 (this site's own synced folder) plus, as a
  fallback, the same in ../ganapati-sambavam/audio/ (a local scratch
  folder some verses' test recordings have been dropped into directly)
  — verses already covered by either are EXCLUDED from the export, so
  what you get is
  "what's left to record," not the whole corpus every time.

Writes (into this site folder):
  vagdhenu_shards/sarga-1.json ... sarga-10.json
  (only for sargas that have at least one verse still needing audio;
  a sarga fully covered already is skipped, not written empty)

NUMBERING — why this doesn't just read "|| N ||" off each verse
-------------------------------------------------------------------
The obvious approach — regex out the trailing "danda + number" marker —
was tried first and abandoned: across this corpus that marker appears as
some mix of "॥ N ॥" / "|| N ||" / "।।N।।" (spaced or not, ASCII pipes or
real danda, ASCII or Devanagari digits) in DIFFERENT LINES OF THE SAME
FILE, and in large stretches (much of sarga-5 through sarga-10) the
marker is simply MISSING from the English translation entirely, or
replaced with a "sarga.verse" citation like "॥ ६.७६ ॥" instead of a
plain per-sarga number. None of that is reliably parseable.

Instead, this script numbers each shloka by its POSITION within its
topic file, using the shloka_range already recorded in
chapter_topics.yaml for that (sarga, topic) — e.g. topic 4 of sarga 6
covers shlokas 31-56, so its 1st "### Shloka:" block is verse 31, its
2nd is 32, and so on. Before trusting that, it checks the block count
against the YAML range's size; if they don't match, the WHOLE topic is
skipped with a loud warning rather than guessing (this does happen —
sarga-6/topic_06.md has 32 "### Shloka:" blocks for an 11-verse range,
apparently because dialogue fragments got their own headings during
translation). A skipped topic needs a human to sort out, not a fallback
heuristic that might silently mislabel every verse after the mismatch.

CAVEATS — read before trusting the output
-------------------------------------------------------------------
- "meter" is a REQUIRED field in Vagdhenu's schema, but nothing in this
  project records which classical meter (chandas) each verse uses —
  the source markdown, the YAML metadata, and the research notes are
  all silent on it. This script stamps every verse "anushtubh" (the
  default narrative śloka meter) as a PLACEHOLDER ONLY. It is almost
  certainly wrong for sarga-ending verses, which classical mahakavyas
  (this one explicitly follows Kalidasa's Kumarasambhavam) traditionally
  shift to a different, more ornate meter — Vasantatilaka, Shikharini,
  Sragdhara, etc. Vagdhenu's own text frontend reportedly does
  meter/gaṇa (laghu/guru) detection on its own (src/prep_text.py per
  its README) — check its current docs for whether "meter" is only a
  hint/label rather than load-bearing before trusting this blindly for
  anything but plain narrative śloka verses.
- Verses with no English/Devanagari translation yet (see
  ../ganapati-sambavam/markdown/english/flagged_for_review.txt) are
  skipped, not guessed via Telugu-script transliteration — that's a
  solvable problem (Telugu and Devanagari are both Brahmic scripts with
  a near-1:1 phonemic mapping) but isn't implemented here.
- Each shloka's "padas" are exactly the lines as printed in the source,
  danda marks normalized to proper Devanagari ("।"/"॥"; the source mixes
  in ASCII pipes) and any trailing verse-number/citation debris ("N",
  "॥ N ॥", "॥ S.N ॥", ...) stripped down to a plain closing "॥" — a
  citation was never meant to be vocalized, and this is purely cosmetic
  now that numbering doesn't depend on it.
- "seed" is a fixed 42 for every verse and "no_sandhi" is always true,
  both just copied from Vagdhenu's own one-verse example — neither is
  derived from anything about this text. Adjust freely.
"""

import json
import re
import yaml
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent.parent
SRC_REPO = SITE_DIR.parent / "ganapati-sambavam"
EN_BASE = SRC_REPO / "markdown" / "english"
YAML_PATH = SRC_REPO / "markdown" / "telugu" / "meta_data" / "chapter_topics.yaml"

SITE_AUDIO_DIR = SITE_DIR / "audio"
SCRATCH_AUDIO_DIR = SRC_REPO / "audio"   # local Drive-download staging spot
OUT_DIR = SITE_DIR / "vagdhenu_shards"

DEVANAGARI_RE = re.compile(r'[ऄ-हऽ-ॡ०-९]')
# Some files (e.g. sarga-6/topic_01.md) put multiple padas on one physical
# markdown line, joined by inline "<br/>" rather than real newlines — same
# thing build_data.py's own BR_RE handles for the reading site. Without
# this, those padas end up as one string with literal "<br/>" text stuck
# in the middle instead of being split out.
BR_RE = re.compile(r'<br\s*/?>[ \t]*\n?', re.IGNORECASE)
DOUBLE_DANDA_RE = re.compile(r'\|\|')
SINGLE_DANDA_RE = re.compile(r'\|')
# Cosmetic only (see NUMBERING above): strip any trailing run of danda-like
# characters with an optional citation (plain number or "sarga.verse") down
# to a single closing danda. A line with no trailing danda at all — some
# genuinely have none — is left untouched.
TRAILING_CITATION_RE = re.compile(r'[।॥|]+\s*[.0-9०-९]*\s*[।॥|]*\s*$')
# Translator's QA notes like "[possible reading: X -> Y]" occasionally leak
# straight into a verse line (found once, sarga-6/topic_04.md) rather than
# staying confined to the Meaning-of-Terms section — strip any bracketed
# note wherever it appears, since Sanskrit verse text has no legitimate use
# for square brackets.
EDITORIAL_NOTE_RE = re.compile(r'\[[^\]]*\]')

DEFAULT_METER = "anushtubh"
DEFAULT_SEED = 42


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


def existing_audio_verse_numbers(sarga_num):
    """Verse numbers (within this sarga) that already have a synced
    recording, checking both this site's audio/ and the content repo's
    local scratch audio/ folder. Matches the current naming
    (sarga-<n>-shloka-<v>.mp3 — zero-padded as actually synced from
    Drive, e.g. sarga-01-shloka-046.mp3, but unpadded is accepted too)
    as well as the older gs_<n>_<v> / gs_<n>.<v> forms (both
    separators exist in the wild) in either .wav or .mp3 — see
    build_data.py's audio_filename_candidates, which recognizes the
    same set."""
    patterns = [
        re.compile(rf'^sarga-0*{sarga_num}-shloka-0*(\d+)\.(?:wav|mp3)$', re.IGNORECASE),
        re.compile(rf'^gs_{sarga_num}[._](\d+)\.(?:wav|mp3)$', re.IGNORECASE),
    ]
    found = set()
    for d in (SITE_AUDIO_DIR, SCRATCH_AUDIO_DIR):
        if not d.is_dir():
            continue
        for f in d.glob('*'):
            for pat in patterns:
                m = pat.match(f.name)
                if m:
                    found.add(int(m.group(1)))
                    break
    return found


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


def build_sarga_shard(n, topic_ranges):
    sarga_dir = EN_BASE / f'sarga-{n}'
    if not sarga_dir.is_dir():
        return None, []

    already = existing_audio_verse_numbers(n)
    entries = []
    skipped_have_audio = []
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
            if vnum in already:
                skipped_have_audio.append(vnum)
                continue
            entries.append({
                "id": f"sarga-{n:02d}-shloka-{vnum:03d}",
                "meter": DEFAULT_METER,
                "padas": padas,
                "seed": DEFAULT_SEED,
                "no_sandhi": True,
                "out": f"out/sarga-{n:02d}-shloka-{vnum:03d}.mp3",
            })

    entries.sort(key=lambda e: int(e["id"].rsplit('-', 1)[1]))
    notes = []
    if skipped_have_audio:
        notes.append(f"{len(skipped_have_audio)} verse(s) already have audio, excluded: "
                      f"{sorted(skipped_have_audio)}")
    if skipped_topics:
        notes.append(f"{len(skipped_topics)} topic file(s) skipped entirely (needs manual review):")
        for fname, reason in skipped_topics:
            notes.append(f"    {fname}: {reason}")
    return entries, notes


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    topic_ranges = load_topic_ranges()
    print(f"Reading English markdown from {EN_BASE}")
    print(f"Excluding verses already covered by {SITE_AUDIO_DIR} and {SCRATCH_AUDIO_DIR}\n")

    total_written = 0
    for n in range(1, 11):
        entries, notes = build_sarga_shard(n, topic_ranges)
        if entries is None:
            print(f"sarga-{n}: no English markdown directory — skipped")
            continue
        for note in notes:
            print(f"sarga-{n}: {note}")
        if not entries:
            print(f"sarga-{n}: nothing left to export (fully covered, or no source yet)\n")
            continue
        out_path = OUT_DIR / f"sarga-{n}.json"
        out_path.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f"sarga-{n}: wrote {len(entries)} verse(s) -> {out_path.relative_to(SITE_DIR)}\n")
        total_written += len(entries)

    print(f"Done. {total_written} verse(s) exported across "
          f"{len(list(OUT_DIR.glob('sarga-*.json')))} file(s) in {OUT_DIR.relative_to(SITE_DIR)}/")
    print("\nRemember: \"meter\" is a placeholder (\"anushtubh\") for every verse — see the "
          "module docstring before trusting it for anything but plain narrative śloka verses.")


if __name__ == '__main__':
    main()
