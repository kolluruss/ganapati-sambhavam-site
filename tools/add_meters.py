#!/usr/bin/env python3
"""
add_meters.py — Identify each shloka's Sanskrit meter (chandas) with the
`chanda` library (https://github.com/hrishikeshrt/chanda) and add a
"meter" attribute to it in shlokas/sarga-N.json, so Vagdhenu (which
needs a meter name per verse — see tools/export_vagdhenu_shards.py's
DEFAULT_METER placeholder) has a real value instead of a guess.

REQUIRES PYTHON 3.8+ (chanda's dependencies don't install on the
project's default python3, which is 3.7). Run explicitly with a newer
interpreter, e.g.:

USAGE
-----
  python3.9 -m pip install chanda indic_transliteration
  python3.9 tools/add_meters.py

Reads/writes shlokas/sarga-1.json ... sarga-10.json in place.

HOW A VERSE COUNTS AS "DETERMINED"
-------------------------------------------------------------------
chanda.Chanda.analyze_text(text, verse=True) returns, per verse, a
ranked list of MeterScore candidates — for well-formed classical
verses this includes both the plain named meter (e.g. "शार्दूलविक्रीडित")
*and* a long tail of "उपजाति (...)" combination names that also
technically satisfy the laghu-guru pattern but only because they're
looser compound meters built from a mix of padas. Filtering on
match_extent == 1.0 alone still lets those combination names through.

The extra signal that separates them: each MeterScore's evidence
list flags whether the matched sub-pattern was in its canonically
valid pāda position for that meter (`pada_position_valid`). For a
real single-name meter this is True for every pāda; for a same-score
"उपजाति" combination it's True for only one pāda position and False
for the rest (it's borrowing that meter's 1st/2nd/3rd/4th-pāda shape
opportunistically, not actually being that meter). So a verse is
"determined" only when some candidate has BOTH match_extent == 1.0
AND every evidence entry's pada_position_valid == True — otherwise
it's left alone, per instructions, rather than guessing.

This does mean many verses come back undetermined (roughly half, in
spot checks) — this corpus takes real metrical liberties (modern
vocabulary, colloquial dialogue, apparent scansion irregularities in
individual pādas), and chanda has no fuzzy/partial credit under this
strict rule. That's intentional: a wrong meter label is worse for
Vagdhenu's audio generation than no label.

METER NAME FORMAT
-------------------------------------------------------------------
chanda returns meter names in Devanagari (e.g. "अनुष्टुभ्"). Stored
"meter" values are the IAST transliteration with diacritics folded
to plain ASCII (śārdūlavikrīḍita -> shardulavikridita, anuṣṭubh ->
anushtubh) to match the plain-ASCII style already used elsewhere in
this project (see export_vagdhenu_shards.py's DEFAULT_METER).
"""

import json
import sys
from pathlib import Path

try:
    import chanda
    from indic_transliteration import sanscript
except ImportError as e:
    sys.exit(f"Missing dependency ({e}). Run with a Python that has chanda "
              f"installed — see this script's USAGE. Current interpreter: {sys.executable}")

SITE_DIR = Path(__file__).resolve().parent.parent
SHLOKAS_DIR = SITE_DIR / "shlokas"

# IAST diacritic -> plain-ASCII digraph, applied after Devanagari->IAST
# transliteration, so "śārdūlavikrīḍita" becomes "shardulavikridita" and
# "anuṣṭubh" becomes "anushtubh" — matching this project's existing
# plain-ASCII meter-name convention (export_vagdhenu_shards.py).
IAST_TO_ASCII = {
    'ā': 'a', 'ī': 'i', 'ū': 'u', 'ṝ': 'ri', 'ḷ': 'l', 'ṛ': 'ri',
    'ṃ': 'm', 'ḥ': '', 'ṅ': 'n', 'ñ': 'n',
    'ṭ': 't', 'ḍ': 'd', 'ṇ': 'n', 'ś': 'sh', 'ṣ': 'sh',
    "'": '', ' ': '',
}


def meter_slug(devanagari_name):
    iast = sanscript.transliterate(devanagari_name, sanscript.DEVANAGARI, sanscript.IAST)
    for k, v in IAST_TO_ASCII.items():
        iast = iast.replace(k, v)
    return iast.strip().lower()


def identify_meter(chandajna, devanagari_text):
    """Returns a plain-ASCII meter name if one candidate cleanly matches
    every pāda in both value (match_extent == 1.0) and canonical pāda
    position (see module docstring) — else None."""
    try:
        result = chandajna.analyze_text(devanagari_text, verse=True)
    except chanda.ChandaError:
        return None
    verses = result.result.verse
    if len(verses) != 1:
        # Should only happen for a malformed/empty entry — never guess.
        return None
    for score in verses[0].scores:
        if score.match_extent == 1.0 and all(
                ev.get('pada_position_valid') for ev in score.evidence):
            return meter_slug(score.name)
    return None


def main():
    chandajna = chanda.Chanda()
    total_verses = total_determined = total_already = 0

    for n in range(1, 11):
        path = SHLOKAS_DIR / f"sarga-{n}.json"
        if not path.exists():
            print(f"sarga-{n}: {path.name} not found — skipped")
            continue
        entries = json.loads(path.read_text(encoding='utf-8'))
        determined = already = 0
        for e in entries:
            total_verses += 1
            if 'meter' in e:
                already += 1
                total_already += 1
                continue
            meter = identify_meter(chandajna, e['devanagari'])
            if meter:
                e['meter'] = meter
                determined += 1
                total_determined += 1
        path.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f"sarga-{n}: {determined} newly determined, {already} already had a meter, "
              f"{len(entries) - determined - already} left undetermined "
              f"(of {len(entries)} verse(s))")

    print(f"\nDone. {total_determined} verse(s) newly annotated, {total_already} already "
          f"annotated, {total_verses - total_determined - total_already} left without a "
          f"meter, out of {total_verses} total.")


if __name__ == '__main__':
    main()
