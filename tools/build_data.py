#!/usr/bin/env python3
"""
build_data.py — Generate the JSON content + static assets for the
Ganapati Sambhavam reading website from the markdown source in the
sibling ../ganapati-sambavam repo.

USAGE
-----
  python3 tools/build_data.py

Reads:
  ../ganapati-sambavam/markdown/telugu/...
  ../ganapati-sambavam/markdown/english/...
  ../ganapati-sambavam/images/*.png
  ../ganapati-sambavam/publishing/fonts_cache/*.ttf
  ../ganapati-sambavam/markdown/fonts_cache/*.ttf
  Google Drive folder AUDIO_GDRIVE_FOLDER_ID (verse-recitation audio,
  gs_<sarga>_<verse>.wav or gs_<sarga>_<verse>.mp3 — both formats are
  synced and playable) — requires GOOGLE_API_KEY in the environment;
  silently skipped without it, so a local run without the key still
  works, just with no play buttons.

Writes (into this site folder):
  data/meta.json            — book + sarga + topic metadata (both languages)
  data/te/sarga-0.json      — Telugu front matter
  data/te/sarga-N.json      — Telugu sarga N topics (N = 1..10)
  data/en/sarga-0.json      — English front matter
  data/en/sarga-N.json      — English sarga N topics (N = 1..10)
  images/*.png, *.jpeg      — copied illustrations
  fonts/*.ttf               — copied fonts
  audio/gs_*.wav, gs_*.mp3  — synced verse-recitation audio (if available)

Re-run any time the source markdown changes; this script does not
modify anything in ../ganapati-sambavam.
"""

import json
import re
import shutil
import yaml
from html import escape as esc
from pathlib import Path

SITE_DIR   = Path(__file__).resolve().parent.parent          # ganapati-sambhavam-site/
SRC_REPO   = SITE_DIR.parent / "ganapati-sambavam"            # ganapati-sambavam/
TE_BASE    = SRC_REPO / "markdown" / "telugu"
EN_BASE    = SRC_REPO / "markdown" / "english"
YAML_PATH  = TE_BASE / "meta_data" / "chapter_topics.yaml"
IMG_SRC    = SRC_REPO / "images"

DATA_DIR   = SITE_DIR / "data"
IMG_DEST   = SITE_DIR / "images"
FONTS_DEST = SITE_DIR / "fonts"
AUDIO_DEST = SITE_DIR / "audio"

# Verse-recitation audio (Vagdhenu-generated), shared by both languages
# since it's a Sanskrit chant — independent of the Telugu/English gloss.
# Files are named gs_<sarga>_<verse-number-within-sarga>, as either .wav
# or .mp3 (both are synced and both play fine via the browser's <audio>
# element); the Drive folder must be shared "Anyone with the link:
# Viewer", same as the images folder
# ganapati-sambavam/publishing/make_pdf_book.py reads.
AUDIO_GDRIVE_FOLDER_ID = "1fSkt3tUU7Pb6g3kmGl6gN2cxbAqm0bP5"
AUDIO_EXTENSIONS = (".wav", ".mp3")

# English theme summaries — one-sentence "what happens in this sarga"
# blurbs (mirrors publishing/make_pdf_book_english.py). Distinct from
# name_translation in chapter_topics.yaml, which is the sarga's actual
# title translated (e.g. "Introduction to the Himalayas") rather than a
# summary of its contents; no per-sarga source exists for these longer
# blurbs, so they stay a hardcoded dict here.
SARGA_THEMES_EN = {
    1:  "The Himalayas, Kashmir, and Nepal — a geographical panorama.",
    2:  "The wedding of Shiva and Parvati.",
    3:  "Parvati creates Ganesha from clay using yogic power.",
    4:  "The debate between Shiva and the boy, and the beheading.",
    5:  "The elephant-head transplant and Ganesha's childhood.",
    6:  "The confrontation with Parashurama and the loss of one tusk.",
    7:  "Ganesha serves as scribe of the Mahabharata for Vyasa.",
    8:  "The divine modaka, and the circumambulation of his parents.",
    9:  "Ganesha's form as a metaphor for democratic governance.",
    10: "The poet's autobiography and his other works.",
}

DEVANAGARI_RE = re.compile(r'[ऀ-ॿ]')
BR_RE = re.compile(r'<br\s*/?>\n?', re.IGNORECASE)


# ── Shared inline helpers ──────────────────────────────────────────

def inline_te(text):
    """Telugu: convert **bold** markdown, clean stray backslash escapes."""
    text = re.sub(r'\\([=\-!.,:()\[\]/])', r'\1', text)
    parts = re.split(r'(\*\*[^*\n]+\*\*)', text)
    out = []
    for p in parts:
        if p.startswith('**') and p.endswith('**') and len(p) > 4:
            out.append(f'<strong>{esc(p[2:-2])}</strong>')
        else:
            out.append(esc(p))
    return ''.join(out)


def inline_en(text):
    """English: convert **bold** and *italic* markdown."""
    parts = re.split(r'(\*\*[^*\n]+\*\*|\*[^*\n]+\*)', text)
    out = []
    for p in parts:
        if p.startswith('**') and p.endswith('**') and len(p) > 4:
            out.append(f'<strong>{esc(p[2:-2])}</strong>')
        elif p.startswith('*') and p.endswith('*') and len(p) > 2:
            out.append(f'<em>{esc(p[1:-1])}</em>')
        else:
            out.append(esc(p))
    return ''.join(out)


def image_ref(sarga_dir, md_relpath):
    """Resolve a markdown image path against the source repo and, if it
    exists, return the site-relative "images/<filename>" path."""
    src = (sarga_dir / md_relpath).resolve()
    if src.exists():
        return f"images/{src.name}"
    return None


# Matches a double-danda verse-end marker followed by the verse number:
# ASCII "|| 12 ||" (Telugu source, English IAST lines) or the real
# Devanagari double-danda character "॥ 12 ॥" (English Devanagari lines).
VERSE_NUM_RE = re.compile(r'(?:॥|\|\|)\s*(\d+)')


def extract_verse_number(raw_lines):
    """Pull the shloka number out of a verse block's own raw text lines
    (whichever pada carries the trailing "|| N ||"/"॥ N ॥" marker)."""
    nums = []
    for line in raw_lines:
        nums.extend(VERSE_NUM_RE.findall(line))
    return nums[-1] if nums else None


def verse_block_html(sarga_num, raw_lines, inner_html, available_audio):
    """Wrap a shloka's rendered pada HTML in its .verse-block div, adding
    a play button + data-audio attribute when: this is a numbered main-sarga
    verse (sarga_num given, i.e. not front matter), a verse number could be
    extracted, and a matching audio file actually exists — so a verse with
    no recorded audio yet renders with no button at all. Matches
    gs_<sarga>_<verse> (underscore, as specified) or gs_<sarga>.<verse>
    (dot — seen in real sample files already dropped in
    ganapati-sambavam/audio/), in either .wav or .mp3 — both play fine via
    the browser's <audio> element, and different verses have arrived in
    different formats, so all four combinations are checked."""
    attr, button = '', ''
    if sarga_num is not None:
        vnum = extract_verse_number(raw_lines)
        if vnum is not None:
            for sep in ('_', '.'):
                for ext in AUDIO_EXTENSIONS:
                    fname = f'gs_{sarga_num}{sep}{vnum}{ext}'
                    if fname in available_audio:
                        attr = f' data-audio="audio/{fname}"'
                        button = ('<button type="button" class="play-btn" '
                                   'aria-label="Play recitation">▶</button>')
                        break
                if attr:
                    break
    return f'<div class="verse-block"{attr}>{button}{inner_html}</div>'


def sync_audio_from_gdrive(force=False):
    """Download verse-recitation audio (.wav or .mp3) into audio/,
    incrementally — unlike make_pdf_book.py's image sync (which skips
    entirely once any local file exists), this always lists the Drive
    folder and fetches only files not already present, so newly recorded
    verses get picked up on the next build without wiping
    already-committed audio. Audio is an optional enhancement: with no
    GOOGLE_API_KEY (e.g. a local run with nothing exported) this just
    keeps whatever is already in audio/ and every other verse renders
    with no play button, rather than failing the build."""
    import os
    AUDIO_DEST.mkdir(parents=True, exist_ok=True)
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        existing = [f for f in AUDIO_DEST.glob("*") if f.suffix.lower() in AUDIO_EXTENSIONS]
        print(f"  GOOGLE_API_KEY not set — using {len(existing)} already-cached audio file(s), no sync")
        return
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError:
        print("  google-api-python-client not installed — skipping audio sync")
        return
    import io
    service = build("drive", "v3", developerKey=api_key)
    print(f"  Listing Drive folder {AUDIO_GDRIVE_FOLDER_ID}…", flush=True)
    files, page_token = [], None
    while True:
        resp = service.files().list(
            q=f"'{AUDIO_GDRIVE_FOLDER_ID}' in parents and trashed=false",
            fields="nextPageToken, files(id, name)",
            pageSize=1000,
            pageToken=page_token,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    audio_files = [f for f in files if f["name"].lower().endswith(AUDIO_EXTENSIONS)]
    to_fetch = [f for f in audio_files if force or not (AUDIO_DEST / f["name"]).exists()]
    print(f"  Found {len(audio_files)} audio file(s) in Drive, {len(to_fetch)} new", flush=True)
    for f in to_fetch:
        dest = AUDIO_DEST / f["name"]
        req = service.files().get_media(fileId=f["id"])
        buf = io.FileIO(dest, mode="wb")
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        print(f"    {f['name']}", flush=True)
    print(f"  Downloaded {len(to_fetch)} new audio file(s).")


# ══════════════════════════════════════════════════════════════════
#  TELUGU PARSER  (mirrors ganapati-sambavam/publishing/make_pdf_book.py,
#  minus PDF/page concerns; పదచ్ఛేదము is kept, not skipped, since the
#  website has no page-budget reason to hide it)
# ══════════════════════════════════════════════════════════════════

TE_SECTION_MAP = {
    "**పదచ్ఛేదము**":     ("padachedam", "పదచ్ఛేదము"),
    "**అన్వయము**":       ("anvaya",     "అన్వయము"),
    "**ప్రతిపదార్థము**":  ("pratipa",    "ప్రతిపదార్థము"),
    "**భావము**":          ("bhava",      "భావము"),
}


def te_mark_verse_lines(lines):
    """Index of lines belonging to a shloka block: a contiguous run of
    fully-bold lines immediately followed (after blank lines) by a
    standalone '**పదచ్ఛేదము**' line."""
    n = len(lines)
    verse_idx = set()
    i = 0
    while i < n:
        s = lines[i].strip()
        if s.startswith('**') and s.endswith('**') and len(s) > 4:
            j = i
            block = []
            while j < n and lines[j].strip() != '':
                block.append(j)
                j += 1
            k = j
            while k < n and lines[k].strip() == '':
                k += 1
            if k < n and lines[k].strip() == '**పదచ్ఛేదము**':
                verse_idx.update(block)
                i = j
                continue
        i += 1
    return verse_idx


def te_parse_sarga0_file(path):
    """Returns (sec_id, title, html) for one Telugu sarga-0 markdown file."""
    sarga0_dir = path.parent
    text = path.read_text(encoding='utf-8')
    text = text.replace('** **', '**\n**')
    text = BR_RE.sub('\n', text)
    lines = text.split('\n')
    buf, sec_id, title = [], path.stem, path.stem
    fallback_label = None
    state, in_vb, skipping, img_count = 'body', False, False, 0

    def close_vb():
        nonlocal in_vb
        if in_vb:
            buf.append('</div>')
            in_vb = False

    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith('### '):
            close_vb(); buf.append(f'<h3 class="s0-h3">{inline_te(s[4:])}</h3>')
            if fallback_label is None:
                fallback_label = re.sub(r'\*\*([^*]+)\*\*', r'\1', s[4:]).strip()
            continue
        if s.startswith('## '):
            close_vb(); buf.append(f'<h2 class="s0-h2">{inline_te(s[3:])}</h2>')
            if fallback_label is None:
                fallback_label = re.sub(r'\*\*([^*]+)\*\*', r'\1', s[3:]).strip()
            continue
        if s.startswith('# '):
            close_vb()
            raw_title = re.sub(r'\*\*([^*]+)\*\*', r'\1', s[2:])
            title = raw_title.strip()
            buf.append(f'<h1 id="{sec_id}" class="s0-title">{inline_te(s[2:])}</h1>')
            state, skipping = 'body', False
            continue
        if s.startswith('!['):
            close_vb()
            m = re.match(r'!\[([^\]]*)\]\(([^)]+)\)', s)
            if m:
                ref = image_ref(sarga0_dir, m.group(2))
                if ref:
                    img_count += 1
                    buf.append(f'<div class="s0-img"><img src="{ref}" alt="{esc(m.group(1))}" loading="lazy">'
                               f'<p class="img-caption">{esc(m.group(1))}</p></div>')
            continue
        if s in TE_SECTION_MAP:
            close_vb()
            _, label = TE_SECTION_MAP[s]
            skipping, state = False, 'section'
            buf.append(f'<div class="sec-hdr">{esc(label)}</div>')
            continue
        if skipping:
            continue
        if s.startswith('*') and s.endswith('*') and not s.startswith('**') and len(s) > 2:
            close_vb(); buf.append(f'<p class="s0-caption">{esc(s[1:-1])}</p>'); continue
        if s.startswith('- ') or s.startswith('* '):
            close_vb(); buf.append(f'<div class="s0-bullet">{inline_te(s[2:])}</div>'); continue
        if s.startswith('**') and s.endswith('**') and len(s) > 4:
            inner_txt = s[2:-2]
            if '|' in inner_txt:
                if not in_vb:
                    buf.append('<div class="verse-block">'); in_vb = True
                buf.append(f'<div class="verse">{inline_te(s)}</div>')
                state = 'verse'
            else:
                close_vb(); buf.append(f'<p class="s0-bold">{inline_te(s)}</p>')
                if fallback_label is None:
                    fallback_label = inner_txt.strip()
            continue
        close_vb()
        buf.append(f'<p class="{"body-text" if state == "section" else "s0-body"}">{inline_te(s)}</p>')

    close_vb()

    if title == path.stem and img_count > 1 and len(buf) > 1:
        head, rest = buf[0], buf[1:]
        cells, i = [], 0
        while i < len(rest) - 1:
            cells.append(f'<div class="family-cell">{rest[i]}{rest[i + 1]}</div>')
            i += 2
        if i < len(rest):
            cells.append(f'<div class="family-cell">{rest[i]}</div>')
        return sec_id, title, head + ''.join(cells), fallback_label

    return sec_id, title, ''.join(buf), fallback_label


def te_parse_topic(path, sarga_dir, topic_id, sarga_num, available_audio):
    text = path.read_text(encoding='utf-8')
    text = text.replace('** **', '**\n**')
    text = BR_RE.sub('\n', text)
    lines = text.split('\n')
    verse_idx = te_mark_verse_lines(lines)
    buf, title = [], path.stem
    skipping, state, in_vb = False, 'header', False
    image_src = image_alt = None
    verse_raw, verse_html = [], []

    def close_vb():
        nonlocal in_vb
        if in_vb:
            buf.append(verse_block_html(sarga_num, verse_raw, ''.join(verse_html), available_audio))
            verse_raw.clear()
            verse_html.clear()
            in_vb = False

    for idx, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        if s.startswith('# '):
            close_vb()
            title = re.sub(r'\*\*([^*]+)\*\*', r'\1', s[2:]).strip()
            buf.append(f'<h2 class="topic-title">{esc(title)}</h2>')
            state, skipping = 'header', False
            continue
        if s.startswith('!['):
            m = re.match(r'!\[([^\]]*)\]\(([^)]+)\)', s)
            if m:
                ref = image_ref(sarga_dir, m.group(2))
                if ref:
                    if image_src is None:
                        image_src, image_alt = ref, m.group(1)
                    buf.append(f'<div class="img-pg"><img src="{ref}" alt="{esc(m.group(1))}" loading="lazy">'
                               f'<p class="img-caption">{esc(m.group(1))}</p></div>')
            continue
        if s in TE_SECTION_MAP:
            close_vb()
            _, label = TE_SECTION_MAP[s]
            skipping, state = False, label
            buf.append(f'<div class="sec-hdr">{esc(label)}</div>')
            continue
        if skipping:
            continue
        if s.startswith('* '):
            buf.append(f'<div class="pratipa-item">{inline_te(s[2:])}</div>')
            continue
        if idx in verse_idx:
            if not in_vb:
                if state == 'భావము':
                    buf.append('<div class="bhava-spacer"></div>')
                in_vb = True
            verse_raw.append(s)
            verse_html.append(f'<div class="verse">{inline_te(s)}</div>')
            state = 'verse'
            continue
        if s.startswith('**') and s.endswith('**') and len(s) > 4:
            close_vb()
            buf.append(f'<div class="trans-label">{esc(s[2:-2])}</div>')
            continue
        buf.append(f'<p class="{"topic-desc" if state == "header" else "body-text"}">{inline_te(s)}</p>')

    close_vb()
    return {'topic_id': topic_id, 'title': title, 'image': image_src, 'html': ''.join(buf)}


# ══════════════════════════════════════════════════════════════════
#  ENGLISH PARSER  (mirrors make_pdf_book_english.py; Padacchedam kept)
# ══════════════════════════════════════════════════════════════════

EN_SECTION_MAP = {
    "पदच्छेदम् (Padacchedam):": ("padachedam", "Word Division", True),
    "अन्वयः (Anvaya):":         ("anvaya",     "Prose order of words", True),
    "Meaning of Terms:":        ("terms",      "Meaning of Terms", False),
    "Meaning:":                 ("bhava",      "Meaning", False),
}


def en_flush_shloka(buf, deva_lines, iast_lines, sarga_num, available_audio):
    if not deva_lines and not iast_lines:
        return
    pieces = []
    if deva_lines:
        pieces.append(f'<div class="verse verse-deva">{"<br/>".join(inline_en(l) for l in deva_lines)}</div>')
    if iast_lines:
        pieces.append(f'<div class="verse-iast">{"<br/>".join(inline_en(l) for l in iast_lines)}</div>')
    buf.append(verse_block_html(sarga_num, deva_lines + iast_lines, ''.join(pieces), available_audio))


def en_parse_topic(path, sarga_dir, topic_id, sarga_num, available_audio):
    text = path.read_text(encoding='utf-8')
    lines = text.split('\n')
    buf, title = [], path.stem
    image_src = image_alt = None
    state, seen_h1 = 'header', [False]
    deva_lines, iast_lines = [], []

    def flush_shloka():
        en_flush_shloka(buf, deva_lines, iast_lines, sarga_num, available_audio)
        deva_lines.clear(); iast_lines.clear()

    for raw in lines:
        s = raw.strip()
        if s.startswith('# '):
            if state == 'shloka':
                flush_shloka()
            heading = re.sub(r'\*\*([^*]+)\*\*', r'\1', s[2:]).strip()
            if not seen_h1[0]:
                title = heading
                buf.append(f'<h2 class="topic-title">{esc(title)}</h2>')
                seen_h1[0] = True
            else:
                buf.append(f'<p class="topic-desc">{inline_en(heading)}</p>')
            state = 'header'
            continue
        if s.startswith('!['):
            if state == 'shloka':
                flush_shloka()
            m = re.match(r'!\[([^\]]*)\]\(([^)]+)\)', s)
            if m:
                ref = image_ref(sarga_dir, m.group(2))
                if ref:
                    if image_src is None:
                        image_src, image_alt = ref, m.group(1)
                    buf.append(f'<div class="img-pg"><img src="{ref}" alt="{esc(m.group(1))}" loading="lazy">'
                               f'<p class="img-caption">{esc(m.group(1))}</p></div>')
            continue
        if s.startswith('### '):
            if state == 'shloka':
                flush_shloka()
            label = s[4:].strip()
            if label == 'Shloka:':
                state = 'shloka'; continue
            if label in EN_SECTION_MAP:
                key, hdr_label, is_deva = EN_SECTION_MAP[label]
                state = key
                buf.append(f'<div class="sec-hdr{" sec-hdr-deva" if is_deva else ""}">{esc(hdr_label)}</div>')
                if key == 'bhava':
                    buf.append('<div class="bhava-spacer"></div>')
                continue
            state = 'trans'
            buf.append(f'<p class="topic-desc">{inline_en(label)}</p>')
            continue
        if not s:
            continue
        if state == 'shloka':
            line = s[:-5].rstrip() if s.endswith('<br/>') else s
            (iast_lines if not DEVANAGARI_RE.search(s) else deva_lines).append(line)
            continue
        if state == 'trans':
            continue
        if state == 'terms' and s.startswith('* '):
            buf.append(f'<div class="pratipa-item">{inline_en(s[2:])}</div>')
            continue
        cls = 'topic-desc' if state == 'header' else 'body-text'
        buf.append(f'<p class="{cls}">{inline_en(s)}</p>')

    if state == 'shloka':
        flush_shloka()

    return {'topic_id': topic_id, 'title': title, 'image': image_src, 'html': ''.join(buf)}


EN_S0_LABELS = {'Anvaya:': 'sec-hdr sec-hdr-deva', 'Word Meanings:': 's0-sec-hdr', 'Meaning:': 's0-sec-hdr'}


def en_parse_sarga0_file(path):
    s0_dir = path.parent
    text = path.read_text(encoding='utf-8')
    lines = text.split('\n')
    buf, sec_id, title = [], path.stem, path.stem
    fallback_label = None
    in_vb, verse_start, img_count = False, None, 0

    def close_vb():
        nonlocal in_vb, verse_start
        if in_vb:
            merged = ''.join(buf[verse_start:]) + '</div>'
            del buf[verse_start:]
            buf.append(merged)
            in_vb = False; verse_start = None

    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if s == '---':
            close_vb(); buf.append('<hr class="s0-hr">'); continue
        if s.startswith('### '):
            close_vb(); buf.append(f'<h3 class="s0-h3">{inline_en(s[4:])}</h3>')
            if fallback_label is None:
                fallback_label = re.sub(r'\*\*([^*]+)\*\*', r'\1', s[4:]).strip()
            continue
        if s.startswith('## '):
            close_vb(); buf.append(f'<h2 class="s0-h2">{inline_en(s[3:])}</h2>')
            if fallback_label is None:
                fallback_label = re.sub(r'\*\*([^*]+)\*\*', r'\1', s[3:]).strip()
            continue
        if s.startswith('# '):
            close_vb()
            title = re.sub(r'\*\*([^*]+)\*\*', r'\1', s[2:]).strip()
            buf.append(f'<h1 id="{sec_id}" class="s0-title">{inline_en(s[2:])}</h1>')
            continue
        if s.startswith('!['):
            close_vb()
            m = re.match(r'!\[([^\]]*)\]\(([^)]+)\)', s)
            if m:
                ref = image_ref(s0_dir, m.group(2))
                if ref:
                    img_count += 1
                    buf.append(f'<div class="s0-img"><img src="{ref}" alt="{esc(m.group(1))}" loading="lazy">'
                               f'<p class="img-caption">{esc(m.group(1))}</p></div>')
            continue
        matched = next((l for l in EN_S0_LABELS if s.startswith(f'**{l}**')), None)
        if matched:
            close_vb()
            buf.append(f'<div class="{EN_S0_LABELS[matched]}">{esc(matched[:-1])}</div>')
            rest = s[len(f'**{matched}**'):].strip()
            if rest:
                buf.append(f'<p class="body-text">{inline_en(rest)}</p>')
            continue
        if s.startswith('* '):
            close_vb(); buf.append(f'<div class="pratipa-item">{inline_en(s[2:])}</div>'); continue
        if s.startswith('- '):
            close_vb(); buf.append(f'<div class="s0-bullet">{inline_en(s[2:])}</div>'); continue
        if s.startswith('—'):
            close_vb(); buf.append(f'<p class="s0-attribution">{esc(s)}</p>'); continue
        if s.startswith('**') and s.endswith('**') and len(s) > 4:
            inner_txt = s[2:-2]
            if DEVANAGARI_RE.search(inner_txt):
                if not in_vb:
                    verse_start = len(buf)
                    buf.append('<div class="s0-verse-block">'); in_vb = True
                buf.append(f'<div class="s0-verse">{esc(inner_txt)}</div>')
            else:
                close_vb(); buf.append(f'<p class="s0-bold">{inline_en(s)}</p>')
                if fallback_label is None:
                    fallback_label = inner_txt.strip()
            continue
        if s.startswith('*') and s.endswith('*') and not s.startswith('**') and len(s) > 2:
            if not in_vb:
                verse_start = len(buf)
                buf.append('<div class="s0-verse-block">'); in_vb = True
            buf.append(f'<div class="s0-verse-iast">{esc(s[1:-1])}</div>')
            continue
        close_vb()
        buf.append(f'<p class="s0-body">{inline_en(s)}</p>')

    close_vb()

    if title == path.stem and img_count > 1 and len(buf) > 1:
        head, rest = buf[0], buf[1:]
        cells, i = [], 0
        while i < len(rest) - 1:
            cells.append(f'<div class="family-cell">{rest[i]}{rest[i + 1]}</div>')
            i += 2
        if i < len(rest):
            cells.append(f'<div class="family-cell">{rest[i]}</div>')
        return sec_id, title, head + ''.join(cells), fallback_label

    return sec_id, title, ''.join(buf), fallback_label


# ══════════════════════════════════════════════════════════════════
#  Build
# ══════════════════════════════════════════════════════════════════

def build_meta(yaml_data):
    sargas = []
    for s in yaml_data['sargas']:
        n = s['number']
        sargas.append({
            'number': n,
            'name_te': s['name'],
            'title_te': s.get('title', s['name']),
            'description_te': s.get('description', ''),
            'name_en': s.get('name_translation', s['name_transliteration']),
            'name_transliteration_en': s['name_transliteration'],
            'description_en': SARGA_THEMES_EN.get(n, ''),
            'shloka_range': s['shloka_range'],
            'topics': [
                {
                    'number': t['number'],
                    'id': f"s{n}-t{t['number']:02d}",
                    'name_te': t['name'],
                    'description_te': t.get('description', ''),
                    'shloka_range': t['shloka_range'],
                }
                for t in s['topics']
            ],
        })
    return {
        'book': {
            'title_te': yaml_data['book']['title'],
            'title_en': yaml_data['book']['title_transliteration'],
        },
        'sargas': sargas,
    }


def build_front_matter(lang):
    parse_fn = te_parse_sarga0_file if lang == 'te' else en_parse_sarga0_file
    base = TE_BASE if lang == 'te' else EN_BASE
    s0_dir = base / 'sarga-0'
    entries = []
    for sf in sorted(s0_dir.glob('*.md')):
        sec_id, title, html, fallback_label = parse_fn(sf)
        has_title = title != sf.stem
        # Some front-matter files use a "##"/bold lead-in instead of a "#"
        # H1 (translator bio, family-photo pages); fall back to that text
        # — extracted from the file's own content — rather than deriving an
        # English label from the filename, which would put English words in
        # the Telugu sidebar.
        label = title if has_title else (fallback_label or sec_id.replace('_', ' '))
        entries.append({
            'id': sec_id,
            'title': label,
            'nav': has_title,
            'html': html,
        })
    out = DATA_DIR / lang / 'sarga-0.json'
    out.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"  wrote {out.relative_to(SITE_DIR)}  ({len(entries)} pages)")


def build_sarga(n, lang, topic_numbers, available_audio):
    """topic_numbers: the authoritative list of topic numbers for this sarga
    (taken from the Telugu source, which is complete) so English gaps show
    as an explicit placeholder rather than silently vanishing from the nav."""
    base = TE_BASE if lang == 'te' else EN_BASE
    sarga_dir = base / f'sarga-{n}'
    parse_fn = te_parse_topic if lang == 'te' else en_parse_topic
    topics = []
    for num in topic_numbers:
        tid = f"s{n}-t{num:02d}"
        tf = sarga_dir / f'topic_{num:02d}.md'
        if tf.exists():
            parsed = parse_fn(tf, sarga_dir, tid, n, available_audio)
            topics.append({'id': tid, 'number': num, 'title': parsed['title'],
                            'image': parsed['image'], 'html': parsed['html'], 'pending': False})
        else:
            note = ("ఈ విభాగం ఇంకా అందుబాటులో లేదు." if lang == 'te' else
                    "This section is not yet available in English — translation is pending.")
            topics.append({
                'id': tid, 'number': num, 'title': f"Topic {num}", 'image': None,
                'pending': True,
                'html': f'<h2 class="topic-title">Topic {num}</h2><p class="body-text"><em>{esc(note)}</em></p>',
            })
    out = DATA_DIR / lang / f'sarga-{n}.json'
    out.write_text(json.dumps(topics, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"  wrote {out.relative_to(SITE_DIR)}  ({len(topics)} topics)")


def copy_assets():
    IMG_DEST.mkdir(parents=True, exist_ok=True)
    FONTS_DEST.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in IMG_SRC.glob('*'):
        if f.is_file() and f.suffix.lower() in ('.png', '.jpg', '.jpeg'):
            shutil.copy2(f, IMG_DEST / f.name)
            n += 1
    print(f"  copied {n} images -> {IMG_DEST.relative_to(SITE_DIR)}")

    font_sources = [
        SRC_REPO / 'publishing' / 'fonts_cache' / 'Gidugu.ttf',
        SRC_REPO / 'publishing' / 'fonts_cache' / 'Ponnala.ttf',
        SRC_REPO / 'publishing' / 'fonts_cache' / 'TiroTelugu.ttf',
        SRC_REPO / 'publishing' / 'fonts_cache' / 'NotoSerifDevanagari-Regular.ttf',
        SRC_REPO / 'publishing' / 'fonts_cache' / 'NotoSerifDevanagari-Bold.ttf',
        SRC_REPO / 'publishing' / 'fonts_cache' / 'NotoSerif-Regular.ttf',
        SRC_REPO / 'publishing' / 'fonts_cache' / 'NotoSerif-Bold.ttf',
        SRC_REPO / 'publishing' / 'fonts_cache' / 'NotoSerif-Italic.ttf',
    ]
    m = 0
    for f in font_sources:
        if f.exists():
            shutil.copy2(f, FONTS_DEST / f.name)
            m += 1
    print(f"  copied {m} fonts  -> {FONTS_DEST.relative_to(SITE_DIR)}")


def main():
    if not SRC_REPO.exists():
        raise SystemExit(f"Source repo not found at {SRC_REPO} — expected as a sibling folder.")

    (DATA_DIR / 'te').mkdir(parents=True, exist_ok=True)
    (DATA_DIR / 'en').mkdir(parents=True, exist_ok=True)

    print("Reading sarga metadata…")
    with open(YAML_PATH, encoding='utf-8') as f:
        yaml_data = yaml.safe_load(f)
    meta = build_meta(yaml_data)
    (DATA_DIR / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"  wrote {(DATA_DIR / 'meta.json').relative_to(SITE_DIR)}")

    print("Copying images and fonts…")
    copy_assets()

    print("Syncing verse-recitation audio…")
    sync_audio_from_gdrive()
    available_audio = ({f.name for f in AUDIO_DEST.glob('*') if f.suffix.lower() in AUDIO_EXTENSIONS}
                        if AUDIO_DEST.exists() else set())
    print(f"  {len(available_audio)} audio file(s) available for linking")

    print("Building Telugu front matter…")
    build_front_matter('te')
    print("Building English front matter…")
    build_front_matter('en')

    for sarga in meta['sargas']:
        n = sarga['number']
        topic_numbers = [t['number'] for t in sarga['topics']]
        print(f"Building sarga-{n} (te)…")
        build_sarga(n, 'te', topic_numbers, available_audio)
        print(f"Building sarga-{n} (en)…")
        build_sarga(n, 'en', topic_numbers, available_audio)

    print("Done.")


if __name__ == '__main__':
    main()
