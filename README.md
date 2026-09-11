# గణపతి సంభవం · Ganapati Sambhavam — reading site

A recitation-style reading website for *Ganapati Sambhavam*, in the spirit of
[bhagavatavani.com](https://bhagavatavani.com/): browse the epic sarga by
sarga, topic by topic, in Telugu or English, with the verse, its word
analysis (పదచ్ఛేదము), prose order (అన్వయము), word-by-word meaning
(ప్రతిపదార్థము) and summary (భావము) all on one page.

It's a plain static site (no build tooling, no framework) that reads
pre-generated JSON. Content is generated from the markdown source in the
sibling `../ganapati-sambavam` repo — this folder never edits that repo.

**Audio is out of scope for now.** Bhagavata-vani's recitation is generated
by [Vāgdhenu](https://github.com/prathoshap/vagdhenu), a Sanskrit chant
text-to-speech model that requires a CUDA GPU and a multi-GB model
download — it can't run on a laptop. This site is text-only; a `<audio>`
player can be wired in later once recitation files exist for each shloka.

## Running it locally

You need a local web server (the JSON fetches are blocked by the browser's
CORS rules under `file://`). Any of these work:

```bash
# from this folder
python3 -m http.server 8000
# then open http://localhost:8000/
```

or, if you have Node:

```bash
npx serve .
```

## Regenerating the content

Whenever the markdown in `../ganapati-sambavam` changes, rebuild the JSON:

```bash
python3 tools/build_data.py
```

This reads `../ganapati-sambavam/markdown/{telugu,english}/…` and
`markdown/telugu/meta_data/chapter_topics.yaml`, and writes:

- `data/meta.json` — book + sarga + topic metadata (both languages)
- `data/te/sarga-N.json`, `data/en/sarga-N.json` — per-sarga topic content
- `data/te/sarga-0.json`, `data/en/sarga-0.json` — front matter (foreword,
  poet bio, dedication, etc.)
- `images/*`, `fonts/*` — copied from the source repo

It requires `pyyaml` (`pip install pyyaml` if you don't already have it from
working in `../ganapati-sambavam/publishing`).

Topics that don't yet exist in English (see
`../ganapati-sambavam/markdown/english/flagged_for_review.txt`) render as a
placeholder with a note, rather than breaking the build or silently
vanishing from the navigation.

## How it's put together

```
index.html          — page shell
css/site.css         — all styling (light/dark themes via CSS variables)
js/app.js            — hash-based router, sidebar, content rendering
tools/build_data.py  — markdown → JSON build script
data/                — generated content (JSON)
images/, fonts/      — generated static assets
```

There's no client-side markdown parsing — `tools/build_data.py` mirrors the
parsing logic in `../ganapati-sambavam/publishing/make_pdf_book.py` and
`make_pdf_book_english.py` (same section markers, same verse-detection
heuristic) and renders straight to HTML fragments, which `js/app.js` drops
into the page. One deliberate difference from the PDF: **పదచ్ఛేదము /
Padacchedam (word-splitting) is shown**, since the PDF skips it to save
pages but a website has no such constraint.

Routing is a plain hash scheme so a page can be linked/bookmarked directly:

- `#/te/s3/t02` — Sarga 3, Topic 2, Telugu
- `#/en/s3/t02` — same topic, English
- `#/te/front/05_samarpana` — a front-matter page (dedication)

### Known gaps / ideas for later

- No full-text search (would need a small client-side index).
- The "Next/Previous" footer nav shows a generic "Topic N" label for
  English (not the real title) until that sarga's English JSON has been
  loaded once — cosmetic only.
- Two Telugu-only front-matter pages (author bio photo, family photo
  gallery) have no English equivalent; switching to English from one of
  those lands you back on the default page.
- Audio (see above).
