# గణపతి సంభవం · Ganapati Sambhavam — reading site

A recitation-style reading website for *Ganapati Sambhavam*, in the spirit of
[bhagavatavani.com](https://bhagavatavani.com/): browse the epic sarga by
sarga, topic by topic, in Telugu or English, with the verse, its word
analysis (పదచ్ఛేదము), prose order (అన్వయము), word-by-word meaning
(ప్రతిపదార్థము) and summary (భావము) all on one page.

It's a plain static site (no build tooling, no framework) that reads
pre-generated JSON. Content is generated from the markdown source in the
sibling `../ganapati-sambavam` repo — this folder never edits that repo.

**Verse recitation audio.** Each shloka can carry a play button (▶) that
plays a pre-recorded `.wav` — these come from a Google Drive folder
(`AUDIO_GDRIVE_FOLDER_ID` in `tools/build_data.py`), matched against either
`gs_<sarga>_<verse-number-within-sarga>.wav` or `gs_<sarga>.<verse>.wav`
(e.g. `gs_1_1.wav` / `gs_1.1.wav` — both mean Sarga 1, verse 1). Both
separators are accepted because real sample recordings already dropped in
`../ganapati-sambavam/audio/` use the dot form, while the naming was
originally specified with an underscore — rather than guess which is
authoritative, the build just matches whichever is actually present. The
recordings themselves are generated separately by
[Vāgdhenu](https://github.com/prathoshap/vagdhenu) (a Sanskrit chant
text-to-speech model that needs a CUDA GPU — not something this build runs);
this site only plays back whatever `.wav` files already exist in that Drive
folder. A shloka with no matching file yet simply renders with no button —
nothing breaks, there's no placeholder or broken player. The same audio is
used for both languages (it's the Sanskrit chant, independent of the
Telugu/English gloss); front-matter verses (సర్గ 0) never get a button,
since the naming convention only covers sargas 1–10.

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
- `audio/gs_*.wav` — synced from Google Drive (see above), incrementally:
  only files not already in `audio/` are downloaded, so already-committed
  recordings aren't re-fetched on every rebuild

It requires `pyyaml` (`pip install pyyaml` if you don't already have it from
working in `../ganapati-sambavam/publishing`). Audio sync additionally needs
`google-api-python-client` (and friends: `google-auth`,
`google-auth-oauthlib`, `google-auth-httplib2`) plus a `GOOGLE_API_KEY`
environment variable — the same key `../ganapati-sambavam/publishing` uses
for images. Without that key set, the build just skips syncing and keeps
whatever `.wav` files are already in `audio/` (empty on a first checkout,
so no play buttons appear) — it never fails the build. The Drive folder
must be shared "Anyone with the link: Viewer", same as the images folder.

Topics that don't yet exist in English (see
`../ganapati-sambavam/markdown/english/flagged_for_review.txt`) render as a
placeholder with a note, rather than breaking the build or silently
vanishing from the navigation.

### Automatic redeploy

`ganapati-sambavam/.github/workflows/deploy-site.yml` runs this exact build
on every push to that repo's `main` branch (syncing images and audio with
its own `GOOGLE_API_KEY` secret), commits the result here if anything
changed, and GitHub Pages redeploys automatically from that commit. You
don't need to run `build_data.py` and push by hand unless you're testing
locally.

## How it's put together

```
index.html          — page shell
css/site.css         — all styling (light/dark themes via CSS variables)
js/app.js            — hash-based router, sidebar, content rendering, audio playback
tools/build_data.py  — markdown → JSON build script
data/                — generated content (JSON)
images/, fonts/, audio/ — generated/synced static assets
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
- No karaoke-style word highlighting during playback (bhagavatavani.com's
  signature feature) — that needs word-level timing data this project
  doesn't have; the play button is a plain whole-verse player.
