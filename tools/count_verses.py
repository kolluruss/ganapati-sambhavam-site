#!/usr/bin/env python3
"""
count_verses.py — Count shlokas per (sarga, topic) independently in the
Telugu and English markdown, using each format's own verse-block marker
(NOT the shloka_range in chapter_topics.yaml — the point is to check
whether the markdown itself agrees with that metadata, and whether the
two languages agree with each other).

Telugu format: a contiguous run of fully-bold lines immediately followed
(after a blank line) by a standalone "**పదచ్ఛేదము**" marker — the exact
heuristic tools/build_data.py's te_mark_verse_lines uses to render verses.

English format: each "### Shloka:" heading starts one verse block, up to
the next "### " heading — the exact heuristic
tools/export_vagdhenu_shards.py's extract_shloka_blocks uses.

Scope: sargas 1-10 only (front matter/sarga-0 isn't organized into
numbered topics the same way in either language).

USAGE
-----
  python3 tools/count_verses.py

Writes (into this site folder):
  verse_counts/telugu.csv    — sarga,topic,number_verses
  verse_counts/english.csv   — sarga,topic,number_verses
  verse_counts/comparison.csv — sarga,topic,telugu,english,diff
  and prints a per-sarga summary with the topic-level differences.
"""

import csv
import re
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent.parent
SRC_REPO = SITE_DIR.parent / "ganapati-sambavam"
TE_BASE = SRC_REPO / "markdown" / "telugu"
EN_BASE = SRC_REPO / "markdown" / "english"
OUT_DIR = SITE_DIR / "verse_counts"

BR_RE = re.compile(r'<br\s*/?>[ \t]*\n?', re.IGNORECASE)
DEVANAGARI_RE = re.compile(r'[ऄ-हऽ-ॡ०-९]')


def te_norm_marker(s):
    """Tolerate an inner colon before the closing '**' (some source files
    write '**పదచ్ఛేదము:**' instead of the corpus-standard
    '**పదచ్ఛేదము**') — matches build_data.py's te_norm_marker exactly, so
    this count agrees with what the site actually renders."""
    return s[:-3] + '**' if s.endswith(':**') else s


# Matches build_data.py's TE_BOLD_LINE_RE exactly — a shloka pada's
# closing verse-number marker sometimes sits outside the closing '**'
# (danda + digits, e.g. '**...**|| 80 ||') instead of inside it.
TE_BOLD_LINE_RE = re.compile(r'^\*\*.+\*\*[\s|॥0-9౦-౯०-९]*$')


def count_telugu_verses(path):
    text = path.read_text(encoding='utf-8')
    text = text.replace('** **', '**\n**')
    text = BR_RE.sub('\n', text)
    lines = text.split('\n')
    n = len(lines)
    count = 0
    i = 0
    while i < n:
        s = lines[i].strip()
        if len(s) > 4 and TE_BOLD_LINE_RE.match(s):
            j = i
            while j < n and lines[j].strip() != '':
                j += 1
            k = j
            while k < n and lines[k].strip() == '':
                k += 1
            if k < n and te_norm_marker(lines[k].strip()) == '**పదచ్ఛేదము**':
                count += 1
                i = j
                continue
        i += 1
    return count


def count_english_verses(path):
    """A verse block counts only if it has at least one Devanagari line —
    matching export_vagdhenu_shards.py's extract_shloka_blocks exactly,
    so an empty/malformed "### Shloka:" heading doesn't inflate the count."""
    text = BR_RE.sub('\n', path.read_text(encoding='utf-8'))
    count = 0
    in_shloka = False
    has_devanagari = False
    for raw in text.split('\n'):
        s = raw.strip()
        if s.startswith('### '):
            if in_shloka and has_devanagari:
                count += 1
            in_shloka = (s[4:].strip() == 'Shloka:')
            has_devanagari = False
            continue
        if in_shloka and s and DEVANAGARI_RE.search(s):
            has_devanagari = True
    if in_shloka and has_devanagari:
        count += 1
    return count


def topic_numbers_for_sarga(n):
    """Authoritative topic list: whichever topic_NN.md files exist in the
    Telugu source (complete for every sarga), so a topic missing from
    English still gets a row (with 0) rather than vanishing silently."""
    sarga_dir = TE_BASE / f'sarga-{n}'
    nums = sorted(int(m.group(1)) for m in
                  (re.search(r'topic_(\d+)', f.stem) for f in sarga_dir.glob('topic_*.md')) if m)
    return nums


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    te_rows, en_rows, cmp_rows = [], [], []

    for n in range(1, 11):
        for t in topic_numbers_for_sarga(n):
            te_file = TE_BASE / f'sarga-{n}' / f'topic_{t:02d}.md'
            en_file = EN_BASE / f'sarga-{n}' / f'topic_{t:02d}.md'

            te_count = count_telugu_verses(te_file) if te_file.exists() else 0
            en_count = count_english_verses(en_file) if en_file.exists() else 0

            te_rows.append((n, t, te_count))
            en_rows.append((n, t, en_count))
            cmp_rows.append((n, t, te_count, en_count, te_count - en_count))

    with open(OUT_DIR / 'telugu.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['sarga', 'topic', 'number_verses'])
        w.writerows(te_rows)

    with open(OUT_DIR / 'english.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['sarga', 'topic', 'number_verses'])
        w.writerows(en_rows)

    with open(OUT_DIR / 'comparison.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['sarga', 'topic', 'telugu', 'english', 'diff_telugu_minus_english'])
        w.writerows(cmp_rows)

    print(f"Wrote {OUT_DIR / 'telugu.csv'}")
    print(f"Wrote {OUT_DIR / 'english.csv'}")
    print(f"Wrote {OUT_DIR / 'comparison.csv'}")

    print("\n=== Per-sarga totals ===")
    print(f"{'sarga':>5}  {'telugu':>6}  {'english':>7}  {'diff':>5}")
    grand_te = grand_en = 0
    sarga_diffs = []
    for n in range(1, 11):
        te_total = sum(c for (sn, t, c) in te_rows if sn == n)
        en_total = sum(c for (sn, t, c) in en_rows if sn == n)
        grand_te += te_total
        grand_en += en_total
        diff = te_total - en_total
        sarga_diffs.append((n, te_total, en_total, diff))
        print(f"{n:>5}  {te_total:>6}  {en_total:>7}  {diff:>+5}")
    print(f"{'TOTAL':>5}  {grand_te:>6}  {grand_en:>7}  {grand_te - grand_en:>+5}")

    print("\n=== Sargas with a nonzero difference: topic-level breakdown ===")
    for n, te_total, en_total, diff in sarga_diffs:
        if diff == 0:
            continue
        print(f"\nSarga {n}: telugu={te_total}, english={en_total}, diff={diff:+d}")
        for (sn, t, te_c, en_c, d) in cmp_rows:
            if sn == n and d != 0:
                note = ""
                en_file = EN_BASE / f'sarga-{n}' / f'topic_{t:02d}.md'
                if not en_file.exists():
                    note = "  (no English file at all)"
                print(f"    topic {t:02d}: telugu={te_c}, english={en_c}, diff={d:+d}{note}")


if __name__ == '__main__':
    main()
