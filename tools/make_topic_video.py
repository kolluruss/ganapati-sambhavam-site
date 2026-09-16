#!/usr/bin/env python3
"""
make_topic_video.py — Render one recitation video per topic from the
English markdown source + the site's synced verse audio, in the style
of https://www.youtube.com/watch?v=fJt8dgAWw38&list=PLDiYyVdyo2Sc
(a shloka-by-shloka chant video), with these differences:

  - one video per topic (not per sarga)
  - English markdown is the source (Devanagari + IAST already sit
    side by side there)
  - the topic's illustration is shown alone for 3s before any audio
    starts
  - both Devanagari and IAST captions are shown together while each
    verse's audio plays
  - a 0.5s gap (image only, no captions) between verses

REQUIRES PYTHON 3.8+ (needs Pillow built with raqm — see
tools/add_meters.py for why; check with
`python3.9 -c "from PIL import features; print(features.check('raqm'))"`)
and `ffmpeg`/`ffprobe` on PATH.

USAGE
-----
  python3.9 tools/make_topic_video.py <sarga> <topic>
  python3.9 tools/make_topic_video.py 1 1

Reads:
  ../ganapati-sambavam/markdown/english/sarga-<n>/topic_<t>.md
  ../ganapati-sambavam/markdown/telugu/meta_data/chapter_topics.yaml
    (for this topic's starting verse number — same positional-
    numbering approach as export_shlokas.py)
  ../ganapati-sambavam/images/<topic image>
  audio/sarga-<n>-shloka-<v>.mp3 (or legacy gs_* naming)

Writes:
  videos/sarga-<n>/topic-<t>.mov (H.264 + AAC, editable in QuickTime)

A verse with no synced audio yet is skipped (logged), not guessed at
or padded with silence — the video just moves on to the next verse
that has one.
"""

import re
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

SITE_DIR = Path(__file__).resolve().parent.parent
SRC_REPO = SITE_DIR.parent / "ganapati-sambavam"
EN_BASE = SRC_REPO / "markdown" / "english"
YAML_PATH = SRC_REPO / "markdown" / "telugu" / "meta_data" / "chapter_topics.yaml"
IMG_SRC = SRC_REPO / "images"
AUDIO_DIR = SITE_DIR / "audio"
VIDEOS_DIR = SITE_DIR / "videos"
FONTS_DIR = SRC_REPO / "publishing" / "fonts_cache"

DEVANAGARI_RE = re.compile(r'[ऄ-हऽ-ॡ०-९]')
BR_RE = re.compile(r'<br\s*/?>[ \t]*\n?', re.IGNORECASE)

# ── Video timing / layout ───────────────────────────────────────────
W, H = 1920, 1080
FPS = 30
INTRO_SECONDS = 3.0
GAP_SECONDS = 0.5
BG_COLOR = (12, 10, 8)
DEVA_COLOR = (255, 244, 224)
IAST_COLOR = (200, 186, 160)
IMG_MAX_W, IMG_MAX_H = 1700, 620
IMG_TOP = 60
DEVA_FONT_SIZE = 46
IAST_FONT_SIZE = 32
LINE_GAP = 14
CAPTION_MAX_WIDTH = 1740

DEVA_FONT_PATH = FONTS_DIR / "NotoSerifDevanagari-Regular.ttf"
IAST_FONT_PATH = FONTS_DIR / "NotoSerif-Italic.ttf"


def load_topic_start(sarga_num, topic_num):
    with open(YAML_PATH, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    for s in data['sargas']:
        if s['number'] != sarga_num:
            continue
        for t in s['topics']:
            if t['number'] == topic_num:
                return t['shloka_range']['start'], t['shloka_range']['end']
    raise SystemExit(f"sarga {sarga_num} topic {topic_num} not found in {YAML_PATH}")


def parse_topic(path):
    """Returns (image_relpath, [(deva_lines, iast_lines), ...]) — one
    entry per '### Shloka:' block, in order. Devanagari lines are
    detected by script; the first non-devanagari, non-blank line
    after them starts the IAST block, which runs until the blank line
    before the next '### ' heading."""
    text = BR_RE.sub('\n', path.read_text(encoding='utf-8'))
    lines = text.split('\n')
    image_relpath = None
    blocks = []
    in_shloka = False
    deva_lines, iast_lines = [], []

    def flush():
        if deva_lines or iast_lines:
            blocks.append((list(deva_lines), list(iast_lines)))

    for raw in lines:
        s = raw.strip()
        if image_relpath is None:
            m = re.match(r'!\[[^\]]*\]\(([^)]+)\)', s)
            if m:
                image_relpath = m.group(1)
        if s.startswith('### '):
            if in_shloka:
                flush()
                deva_lines, iast_lines = [], []
            in_shloka = (s[4:].strip() == 'Shloka:')
            continue
        if not s:
            continue
        if in_shloka:
            if DEVANAGARI_RE.search(s):
                deva_lines.append(s)
            else:
                iast_lines.append(s)
    if in_shloka:
        flush()
    return image_relpath, blocks


def audio_path_for(sarga_num, vnum):
    """Mirrors build_data.py's audio_filename_candidates (zero-padded
    current naming first, then legacy gs_* forms)."""
    for sarga_str in (f'{sarga_num:02d}', str(sarga_num)):
        for vnum_str in (f'{vnum:03d}', str(vnum)):
            for ext in ('.mp3', '.wav'):
                p = AUDIO_DIR / f'sarga-{sarga_str}-shloka-{vnum_str}{ext}'
                if p.exists():
                    return p
    for sep in ('_', '.'):
        for ext in ('.wav', '.mp3'):
            p = AUDIO_DIR / f'gs_{sarga_num}{sep}{vnum}{ext}'
            if p.exists():
                return p
    return None


def ffprobe_duration(path):
    out = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def wrap_text(draw, text, font, max_width):
    words = text.split(' ')
    lines, cur = [], ''
    for w in words:
        trial = (cur + ' ' + w).strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_background(topic_image):
    """Full-bleed blurred/darkened cover of the topic image, with the
    sharp image inset centered near the top — same backdrop reused for
    every frame in this video."""
    canvas = Image.new('RGB', (W, H), BG_COLOR)
    if topic_image is None:
        return canvas
    img = Image.open(topic_image).convert('RGB')

    # Cover-fit blurred backdrop.
    scale = max(W / img.width, H / img.height)
    bw, bh = int(img.width * scale) + 2, int(img.height * scale) + 2
    backdrop = img.resize((bw, bh), Image.LANCZOS)
    backdrop = backdrop.crop(((bw - W) // 2, (bh - H) // 2, (bw - W) // 2 + W, (bh - H) // 2 + H))
    backdrop = backdrop.filter(ImageFilter.GaussianBlur(40))
    backdrop = ImageEnhance.Brightness(backdrop).enhance(0.32)
    canvas.paste(backdrop, (0, 0))

    # Sharp contain-fit inset.
    scale = min(IMG_MAX_W / img.width, IMG_MAX_H / img.height)
    fw, fh = int(img.width * scale), int(img.height * scale)
    fg = img.resize((fw, fh), Image.LANCZOS)
    canvas.paste(fg, ((W - fw) // 2, IMG_TOP))
    return canvas


def wrap_padas(draw, padas, font, max_width):
    """Each pada (line of the verse, as printed in the source) gets its
    own caption line — only wrapped further if that one pada alone is
    too wide, so the classical per-pada line breaks are preserved
    instead of re-flowing text across pada boundaries."""
    out = []
    for pada in padas:
        out.extend(wrap_text(draw, pada, font, max_width))
    return out


def render_caption_frame(background, deva_padas, iast_padas, out_path):
    frame = background.copy()
    draw = ImageDraw.Draw(frame)
    deva_font = ImageFont.truetype(str(DEVA_FONT_PATH), DEVA_FONT_SIZE)
    iast_font = ImageFont.truetype(str(IAST_FONT_PATH), IAST_FONT_SIZE)

    deva_lines = wrap_padas(draw, deva_padas, deva_font, CAPTION_MAX_WIDTH)
    iast_lines = wrap_padas(draw, iast_padas, iast_font, CAPTION_MAX_WIDTH)

    deva_line_h = DEVA_FONT_SIZE + 16
    iast_line_h = IAST_FONT_SIZE + 10
    block_h = len(deva_lines) * deva_line_h + LINE_GAP + len(iast_lines) * iast_line_h
    y = IMG_TOP + IMG_MAX_H + 40
    max_y = H - 30
    if y + block_h > max_y:
        y = max_y - block_h

    for line in deva_lines:
        w = draw.textlength(line, font=deva_font)
        draw.text(((W - w) / 2, y), line, font=deva_font, fill=DEVA_COLOR, language='sa')
        y += deva_line_h
    y += LINE_GAP
    for line in iast_lines:
        w = draw.textlength(line, font=iast_font)
        draw.text(((W - w) / 2, y), line, font=iast_font, fill=IAST_COLOR)
        y += iast_line_h

    frame.save(out_path)


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def make_silent_clip(image_path, seconds, out_path):
    run([
        'ffmpeg', '-y', '-loop', '1', '-i', str(image_path),
        '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
        '-t', f'{seconds}', '-r', str(FPS),
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-ar', '48000', '-ac', '2',
        '-shortest', str(out_path),
    ])


def make_verse_clip(image_path, audio_path, out_path):
    run([
        'ffmpeg', '-y', '-loop', '1', '-i', str(image_path),
        '-i', str(audio_path),
        '-r', str(FPS),
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-ar', '48000', '-ac', '2',
        '-shortest', str(out_path),
    ])


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: python3.9 tools/make_topic_video.py <sarga> <topic>")
    sarga_num, topic_num = int(sys.argv[1]), int(sys.argv[2])

    start, end = load_topic_start(sarga_num, topic_num)
    expected = end - start + 1
    topic_path = EN_BASE / f'sarga-{sarga_num}' / f'topic_{topic_num:02d}.md'
    if not topic_path.exists():
        sys.exit(f"not found: {topic_path}")

    image_relpath, blocks = parse_topic(topic_path)
    if len(blocks) != expected:
        print(f"WARNING: {topic_path.name} has {len(blocks)} '### Shloka:' block(s), "
              f"expected {expected} (shlokas {start}-{end}) — numbering below may be off "
              f"for topics with known structural quirks (see export_shlokas.py).")

    topic_image = None
    if image_relpath:
        candidate = (topic_path.parent / image_relpath).resolve()
        if candidate.exists():
            topic_image = candidate
        else:
            print(f"WARNING: topic image not found: {candidate}")

    verses = []
    skipped = []
    for i, (deva_lines, iast_lines) in enumerate(blocks):
        vnum = start + i
        audio = audio_path_for(sarga_num, vnum)
        if audio is None:
            skipped.append(vnum)
            continue
        verses.append((vnum, deva_lines, iast_lines, audio))

    print(f"{topic_path.name}: {len(verses)} verse(s) with audio, "
          f"{len(skipped)} skipped (no audio yet): {skipped}")
    if not verses:
        sys.exit("No verses with audio — nothing to render.")

    work = Path(tempfile.mkdtemp(prefix=f'topic_video_s{sarga_num}t{topic_num}_'))
    try:
        background = make_background(topic_image)
        plain_frame = work / 'plain.png'
        background.save(plain_frame)

        clips = []
        intro_clip = work / 'clip_intro.mov'
        make_silent_clip(plain_frame, INTRO_SECONDS, intro_clip)
        clips.append(intro_clip)

        for idx, (vnum, deva_padas, iast_padas, audio) in enumerate(verses):
            frame_path = work / f'frame_{vnum:03d}.png'
            render_caption_frame(background, deva_padas, iast_padas, frame_path)
            clip_path = work / f'clip_{vnum:03d}.mov'
            make_verse_clip(frame_path, audio, clip_path)
            clips.append(clip_path)

            if idx != len(verses) - 1:
                gap_clip = work / f'gap_{vnum:03d}.mov'
                make_silent_clip(plain_frame, GAP_SECONDS, gap_clip)
                clips.append(gap_clip)

        list_file = work / 'concat.txt'
        list_file.write_text(''.join(f"file '{c}'\n" for c in clips), encoding='utf-8')

        out_dir = VIDEOS_DIR / f'sarga-{sarga_num}'
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f'topic-{topic_num:02d}.mov'
        run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(list_file),
             '-c', 'copy', str(out_path)])
        print(f"Wrote {out_path.relative_to(SITE_DIR)}")
        dur = ffprobe_duration(out_path)
        print(f"Duration: {dur:.1f}s ({len(verses)} verse(s), {len(skipped)} skipped)")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
