from __future__ import annotations

"""Rim-motor — finner rimord basert på fonetikk.

Provides three rhyme-finding functions:
- finn_perfekte_rim: exact rhyme suffix match
- finn_halvrim: halvrim (near-rhyme) using phoneme equivalence classes
- match_konsonanter: consonant skeleton matching
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from rimordbok.db import (
    _connect, hent_fonetikk, hent_rim_dialekt, hent_varianter,
    hent_rim_for_suffiks, hent_rim_med_ipa, hent_ord_for_halvrim,
    GYLDIGE_DIALEKTER,
)
from rimordbok.phonetics import slaa_opp

# --- IPA vowel perceptual distance ---
# Norwegian vowels grouped by perceptual similarity for rimsti.
# Each vowel gets a 2D coordinate (height, front-back) tuned so that
# pairs that sound alike in Norwegian have small distances.
# Rounding is encoded in the front-back axis: rounded front vowels
# are shifted toward central position (as they sound in Norwegian).
_VOWEL_COORDS = {
    # Coordinates: (height, front-back) following the IPA vowel
    # quadrilateral (vokalfirkanten).  Height: 1.0 = close, 0.0 = open.
    # Front-back: 0.0 = front, 1.0 = back.  Rounding shifts front vowels
    # significantly toward central, matching Norwegian perceptual reality
    # where i/y, e/ø, u/ʉ are clearly distinct vowels.
    #
    # Close front unrounded
    "i": (1.0, 0.0), "iː": (1.0, 0.0),
    # Close front rounded — clearly distinct from i
    "y": (1.0, 0.3), "yː": (1.0, 0.3),
    # Close central rounded — distinct from both y and u
    "ʉ": (1.0, 0.55), "ʉː": (1.0, 0.55),
    # Close back rounded
    "u": (1.0, 0.9), "uː": (1.0, 0.9),
    # Near-close (short vowel allophones)
    "ɪ": (0.8, 0.05),
    "ʏ": (0.8, 0.3),
    "ʊ": (0.8, 0.8),
    # Close-mid
    "e": (0.6, 0.0), "eː": (0.6, 0.0),
    "ø": (0.6, 0.3), "øː": (0.6, 0.3),
    "o": (0.6, 0.9), "oː": (0.6, 0.9),
    # Open-mid
    "ɛ": (0.35, 0.05),
    "œ": (0.35, 0.3),
    "ɔ": (0.35, 0.85),
    # Near-open / open
    "æ": (0.15, 0.1), "æː": (0.15, 0.1),
    "a": (0.0, 0.5),
    "ɑ": (0.0, 0.9), "ɑː": (0.0, 0.9),
    # Schwa (centralized, reduced)
    "ə": (0.5, 0.5),
}


def _vowel_distance(v1: str, v2: str) -> float:
    """Perceptual distance between two Norwegian vowels (0.0-~1.1)."""
    c1 = _VOWEL_COORDS.get(v1.replace("ː", ""), _VOWEL_COORDS.get(v1))
    c2 = _VOWEL_COORDS.get(v2.replace("ː", ""), _VOWEL_COORDS.get(v2))
    if c1 is None or c2 is None:
        return 0.8  # unknown vowels = fairly far
    dh = c1[0] - c2[0]
    db = c1[1] - c2[1]
    return (dh * dh + db * db) ** 0.5


# --- Phoneme equivalence classes for Norwegian near-rhyme ---

# Vowel nucleus equivalence: vowels that sound similar enough for near-rhyme
VOWEL_EQUIV = {
    # Short-long pairs
    "ɑ": "A", "ɑː": "A",
    "ɛ": "E", "eː": "E",
    "ɪ": "I", "iː": "I",
    "ɔ": "O", "oː": "O", "ʊ": "O", "uː": "O_LONG",
    "ʉ": "U", "ʉː": "U",
    "ʏ": "Y", "yː": "Y",
    "æ": "AE", "æː": "AE",
    "œ": "OE", "øː": "OE",
    "ə": "SCHWA",
}

# Consonant equivalence: grouped by manner of articulation + voicing.
# For halvrim, consonants that share how they're produced (plosive, nasal,
# fricative) and voicing sound more alike than consonants at the same
# place but different manner.  E.g. k≈t (both voiceless plosives) is
# closer than k≈g (same place, different voicing) for near-rhyme.
CONS_EQUIV = {
    # Voiceless plosives (p≈t≈k)
    "p": "VPLOS", "t": "VPLOS", "k": "VPLOS",
    "ʈ": "VPLOS",  # retroflex voiceless plosive
    # Voiced plosives (b≈d≈g)
    "b": "SPLOS", "d": "SPLOS", "g": "SPLOS",
    "ɖ": "SPLOS",  # retroflex voiced plosive
    # Nasals (m≈n≈ŋ)
    "m": "NAS", "n": "NAS", "ŋ": "NAS",
    "ɳ": "NAS",  # retroflex nasal
    # Voiceless fricatives (f≈s≈ʃ≈ʂ≈ç≈h)
    "f": "VFRIK", "s": "VFRIK", "ʃ": "VFRIK", "ʂ": "VFRIK",
    "ç": "VFRIK", "h": "VFRIK",
    # Voiced fricatives / approximants (v≈j)
    "v": "SFRIK", "j": "SFRIK",
    "ʋ": "SFRIK",  # labiodental approximant
    # Liquids: laterals and trills (l≈r)
    "l": "LIQ", "ɭ": "LIQ",
    "r": "LIQ",
}

# IPA vowels for segmentation
_IPA_VOWELS = frozenset({
    "ɑ", "ɛ", "ɪ", "ɔ", "ʊ", "ʉ", "ə",
    "æ", "œ", "ø", "ʏ",
    "e", "i", "o", "u", "y", "a",
})


def _is_vowel_phoneme(ph: str) -> bool:
    base = ph.replace("ː", "")
    if "͡" in base:
        base = base.split("͡")[0]
    return base in _IPA_VOWELS


def _parse_suffix_phonemes(suffix: str) -> list[str]:
    """Parse a rimsuffiks string into individual phonemes.

    Suffix format: phonemes joined directly within syllables, '.' between syllables.
    E.g. 'ɑːg', 'æ.ʈə', 'ɑ.stɪ.sk'
    """
    phonemes = []
    for syl in suffix.split("."):
        phonemes.extend(_segment_phonemes(syl))
    return phonemes


def _segment_phonemes(s: str) -> list[str]:
    """Segment a string of IPA characters into phonemes."""
    result = []
    i = 0
    n = len(s)
    while i < n:
        # Check for combining tie bar (diphthong like æ͡ɪ)
        # The tie bar is U+0361, 3 bytes in UTF-8
        if i + 2 < n and s[i + 1] == "͡":
            result.append(s[i:i + 3])
            i += 3
            # Check for length mark after diphthong
            if i < n and s[i] == "ː":
                result[-1] += "ː"
                i += 1
            continue

        ch = s[i]
        phoneme = ch

        # Check for length mark
        if i + 1 < n and s[i + 1] == "ː":
            phoneme += "ː"
            i += 2
        # Check for syllabic mark (combining low line U+0329)
        elif i + 1 < n and s[i + 1] == "\u0329":
            phoneme += "\u0329"
            i += 2
        else:
            i += 1

        result.append(phoneme)
    return result


def _vowel_equiv_class(ph: str) -> str:
    return VOWEL_EQUIV.get(ph, ph)


def _cons_equiv_class(ph: str) -> str:
    return CONS_EQUIV.get(ph, ph)


# --- Halvrim scoring (assonance + consonance) ---


def _weighted_lcs(phonemes_a: list[str], phonemes_b: list[str],
                  exact_weight: float = 1.0,
                  class_weight: float = 0.6) -> float:
    """Weighted LCS: exact phoneme match scores more than equivalence class match.

    Uses DP like standard LCS but tracks weighted scores.
    - Exact match (same phoneme): exact_weight (1.0)
    - Class match (same equivalence class): class_weight (0.6)
    - No match: 0

    Returns total weighted score (not normalized).
    """
    n, m = len(phonemes_a), len(phonemes_b)
    if n == 0 or m == 0:
        return 0.0

    prev = [0.0] * (m + 1)
    for i in range(1, n + 1):
        cur = [0.0] * (m + 1)
        for j in range(1, m + 1):
            pa, pb = phonemes_a[i - 1], phonemes_b[j - 1]
            # Always consider skipping (not matching)
            best = max(prev[j], cur[j - 1])
            # Consider matching (exact or class)
            if pa == pb:
                best = max(best, prev[j - 1] + exact_weight)
            elif _cons_equiv_class(pa) == _cons_equiv_class(pb):
                best = max(best, prev[j - 1] + class_weight)
            cur[j] = best
        prev = cur
    return prev[m]


def _split_vc(suffix: str) -> tuple[list[str], list[str]]:
    """Split a suffix into ordered vowel and consonant lists."""
    phs = _parse_suffix_phonemes(suffix)
    vowels = [ph for ph in phs if _is_vowel_phoneme(ph)]
    consonants = [ph for ph in phs if not _is_vowel_phoneme(ph)]
    return vowels, consonants


def _vowel_sequence_similarity(va: list[str], vb: list[str]) -> float:
    """Score vowel similarity using continuous distance.

    Compares aligned vowels position-by-position. If lengths differ,
    the shorter is padded from the end (so final vowels align first,
    which matters more for rhyme).

    Returns 0.0 (completely different) to 1.0 (identical).
    """
    if not va and not vb:
        return 1.0
    if not va or not vb:
        return 0.0

    n = max(len(va), len(vb))
    total = 0.0

    # Right-align: pad from left
    off_a = n - len(va)
    off_b = n - len(vb)

    for i in range(n):
        ia = i - off_a
        ib = i - off_b
        if ia >= 0 and ib >= 0:
            d = _vowel_distance(va[ia], vb[ib])
            # Quadratic falloff: perceptually distinct vowels drop fast.
            # R=0.4 means vowels at distance ≥0.4 get 0 similarity,
            # while close pairs (short/long allophones, d<0.15) stay >0.85.
            # This matches Norwegian perception where e.g. ʉ and u are
            # completely different vowels (d=0.35 → sim≈0.23).
            total += max(0.0, 1.0 - (d / 0.4) ** 2)
        # else: unmatched position scores 0

    return total / n


def _score_halvrim(target_sfx: str, cand_sfx: str) -> float:
    """Score halvrim (near-rhyme) similarity between two suffixes.

    target_sfx: the search word's suffix (what we're rhyming against).
    cand_sfx: the candidate word's suffix.

    Combines:
    - Vowel similarity (continuous distance, 60% weight)
    - Consonant similarity (recall against target, 40% weight)

    Both must individually exceed a minimum (0.3) to avoid false
    positives where only vowels or only consonants match. This prevents
    words like "klokken" (same vowels but unrelated consonants) from
    appearing as halvrim of "ånder".
    """
    va, ca = _split_vc(target_sfx)
    vb, cb = _split_vc(cand_sfx)

    v_sim = _vowel_sequence_similarity(va, vb)

    # Consonant recall: how well does the candidate cover the target?
    # Normalise by the TARGET's consonant count so that extra candidate
    # consonants don't penalise the score.
    if not ca and not cb:
        c_sim = 1.0
    elif not ca or not cb:
        c_sim = 0.0
    else:
        weighted = _weighted_lcs(ca, cb, exact_weight=1.0, class_weight=0.6)
        c_sim = min(1.0, weighted / len(ca))

    # Require meaningful consonant overlap — just sharing one common
    # consonant (c_sim ≤ 0.5) while vowels match is not enough.
    # This filters out "klokken" (k,n vs n,r → c_sim=0.5) for "ånder".
    if v_sim < 0.3 or c_sim < 0.55:
        return 0.0

    return 0.60 * v_sim + 0.40 * c_sim


def _berik_varianter_med_definisjoner(ord: str, varianter: list[dict]) -> list[dict]:
    """Enrich pronunciation variants with definitions from Bokmålsordboka.

    Matches GraphQL articles (by wordClass) to DB variants (by POS code).
    Each variant gets a 'definisjon' field with the first definition text,
    and an 'ordklasse_tekst' field with the human-readable word class.
    """
    if len(varianter) <= 1:
        return varianter  # No disambiguation needed

    from rimordbok.definitions import hent_alle_definisjoner, _POS_TIL_WORDCLASS

    artikler = hent_alle_definisjoner(ord)
    if not artikler:
        return varianter

    # Build lookup: pos_code → first definition
    pos_til_def: dict[str, tuple[str, str]] = {}  # pos → (definisjon, ordklasse_tekst)
    for art in artikler:
        pos = art.get("pos", "")
        wc = art.get("ordklasse", "")
        defs = art.get("definisjoner", [])
        first_def = defs[0] if defs else None
        if pos and pos not in pos_til_def:
            pos_til_def[pos] = (first_def, wc)

    # Enrich variants
    enriched = []
    for v in varianter:
        v = dict(v)  # Copy
        # Extract base POS (e.g. "VB" from "VB|part")
        raw_pos = v.get("pos", "")
        base_pos = raw_pos.split("|")[0] if raw_pos else ""

        if base_pos in pos_til_def:
            defn, wc_tekst = pos_til_def[base_pos]
            v["definisjon"] = defn
            v["ordklasse_tekst"] = wc_tekst
        else:
            # Fallback: try to find by wordClass mapping
            expected_wc = _POS_TIL_WORDCLASS.get(base_pos, "")
            for art in artikler:
                if art.get("ordklasse") == expected_wc:
                    defs = art.get("definisjoner", [])
                    v["definisjon"] = defs[0] if defs else None
                    v["ordklasse_tekst"] = expected_wc
                    break
            else:
                v["definisjon"] = None
                v["ordklasse_tekst"] = _POS_TIL_WORDCLASS.get(base_pos, base_pos)

        enriched.append(v)

    return enriched


def _get_word_info(
    ord: str,
    db_path: Optional[Path] = None,
    dialekt: str = "øst",
    rimsuffiks: Optional[str] = None,
) -> Optional[dict]:
    """Get word info from DB or G2P fallback.

    If rimsuffiks is given, selects the variant with that suffix (disambiguation).
    """
    info = slaa_opp(ord, db_path=db_path, dialekt=dialekt, rimsuffiks_override=rimsuffiks)
    if info is None:
        return None
    return info


def _same_vowel_weight(sfx_a: str, sfx_b: str) -> bool:
    """Check if two suffixes have the same syllable weight.

    In Norwegian, short vowel + strong consonant (ɪk, ɪt, ɪkt) is a
    heavy syllable, while long vowel + single consonant (ɪːt) is light.
    These don't rhyme well — 'politikk' (ɪk) matches 'blitt' (ɪt) but
    not 'hit' (ɪːt).  The orthographic double consonant (kk, tt) marks
    the preceding vowel as short; the 'kraft' is in the vowel length.
    """
    phs_a = _parse_suffix_phonemes(sfx_a)
    phs_b = _parse_suffix_phonemes(sfx_b)
    first_v_a = next((ph for ph in phs_a if _is_vowel_phoneme(ph)), None)
    first_v_b = next((ph for ph in phs_b if _is_vowel_phoneme(ph)), None)
    if first_v_a is None or first_v_b is None:
        return True  # no vowel → don't filter
    return ("ː" in first_v_a) == ("ː" in first_v_b)


def _normalize_length(suffix: str) -> str:
    """Strip vowel length marks for structural comparison.

    In Norwegian, vowel length (ɪ vs ɪː) doesn't change rhyme identity.
    'slik' (ɪːk) and 'politikk' (ɪk) are effectively perfect rhymes
    and should be structurally excluded from halvrim results.
    """
    return suffix.replace("ː", "")


def _stavelsessuffiks(ipa_ren: str, dybde: int) -> str:
    """Extract N-syllable rhyme suffix from IPA string.

    Takes the last *dybde* syllables and strips leading consonants from
    the first of those syllables (keeps from first vowel onward).

    Examples for "stɑ.tɪ.stɪk":
      dybde=1 → "ɪk"       (last syllable from vowel)
      dybde=2 → "ɪ.stɪk"   (last 2 syllables from vowel)
      dybde=3 → "ɑ.tɪ.stɪk" (last 3 syllables from vowel)
    """
    if not ipa_ren:
        return ""
    syllables = ipa_ren.split(".")
    if dybde >= len(syllables):
        target_syls = syllables
    else:
        target_syls = syllables[-dybde:]

    # Strip onset consonants from first target syllable
    first_syl = target_syls[0]
    segments = _segment_phonemes(first_syl)
    vowel_idx = None
    for i, seg in enumerate(segments):
        if _is_vowel_phoneme(seg):
            vowel_idx = i
            break

    if vowel_idx is not None:
        trimmed_first = "".join(segments[vowel_idx:])
    else:
        trimmed_first = first_syl  # no vowel found, keep as-is

    if len(target_syls) > 1:
        return trimmed_first + "." + ".".join(target_syls[1:])
    return trimmed_first


def _grupper_etter_stavelser(results: list[dict]) -> list[dict]:
    """Group rhyme results by syllable count (legacy, non-depth grouping).

    Returns list of groups: {stavelser: int, ord: [list of result dicts]}.
    Groups are sorted by syllable count ascending.
    """
    grupper: dict[int, list[dict]] = {}
    for r in results:
        syl = r.get("stavelser", 1) or 1
        if syl not in grupper:
            grupper[syl] = []
        grupper[syl].append(r)

    # Sort within each group by frequency descending
    for syl in grupper:
        grupper[syl].sort(key=lambda r: -r.get("frekvens", 0))

    # Return sorted by syllable count
    return [
        {"stavelser": syl, "ord": grupper[syl]}
        for syl in sorted(grupper.keys())
    ]


def finn_perfekte_rim(
    ord: str,
    db_path: Optional[Path] = None,
    maks: int = 200,
    samme_tonelag: bool = False,
    dialekt: str = "øst",
    rimsuffiks: Optional[str] = None,
    ekskluder_propn: bool = True,
    grupper: bool = False,
) -> dict:
    """Find perfect rhymes — words with identical rhyme suffix.

    Args:
        dialekt: Dialect region ('øst', 'nord', 'midt', 'vest', 'sørvest').
        rimsuffiks: If given, use this suffix directly (for disambiguation).
        ekskluder_propn: Exclude proper nouns (PM) from results.
        grupper: If True, group results by syllable count.

    Returns dict with keys:
        ord, rimsuffiks, varianter (if ambiguous), resultater (flat or grouped).
    """
    # Check for homograph variants
    varianter = hent_varianter(ord, db_path=db_path)

    info = _get_word_info(ord, db_path=db_path, dialekt=dialekt, rimsuffiks=rimsuffiks)
    if info is None:
        return {"ord": ord, "rimsuffiks": None, "varianter": [], "resultater": []}

    suffix = rimsuffiks or info.get("rimsuffiks")
    if not suffix:
        from scripts.build_rhyme_index import compute_rhyme_suffix
        fonemer = info.get("fonemer")
        stress = info.get("stress")
        if fonemer and stress:
            suffix = compute_rhyme_suffix(fonemer, stress)
    if not suffix:
        return {"ord": ord, "rimsuffiks": None, "varianter": varianter, "resultater": []}

    ord_lower = ord.lower()

    # When grouping by depth, we need IPA data for multi-syllable matching
    if grupper and ekskluder_propn:
        results = hent_rim_med_ipa(
            suffiks=suffix,
            ord_lower=ord_lower,
            db_path=db_path,
            maks=maks,
            ekskluder_propn=True,
            samme_tonelag=samme_tonelag,
            tonelag_val=info.get("tonelag"),
        )
        for r in results:
            r["score"] = 1.0
    elif ekskluder_propn:
        results = hent_rim_for_suffiks(
            suffiks=suffix,
            ord_lower=ord_lower,
            db_path=db_path,
            maks=maks,
            samme_tonelag=samme_tonelag,
            tonelag_val=info.get("tonelag"),
            ekskluder_propn=True,
        )
        for r in results:
            r["score"] = 1.0
    else:
        fetch_limit = maks * 10
        results = hent_rim_dialekt(
            suffix=suffix,
            dialekt=dialekt,
            ord_lower=ord_lower,
            db_path=db_path,
            maks=fetch_limit,
            samme_tonelag=samme_tonelag,
            tonelag_val=info.get("tonelag"),
        )
        for r in results:
            r["score"] = 1.0
        results.sort(key=lambda r: -r.get("frekvens", 0))
        results = results[:maks]

    # Enrich variants with definitions for disambiguation
    berikede_varianter = (
        _berik_varianter_med_definisjoner(ord, varianter)
        if len(varianter) > 1 else []
    )

    response = {
        "ord": ord,
        "rimsuffiks": suffix,
        "varianter": berikede_varianter,
    }

    if grupper:
        # Filter morphological variants (e.g. "hjertelig" for "hjerte")
        if len(ord_lower) >= 3:
            results = [
                r for r in results
                if not (ord_lower in r.get("ord", "").lower()
                        or r.get("ord", "").lower() in ord_lower)
            ]
        response["resultater"] = _grupper_etter_stavelser(results)
    else:
        # Flat mode: also filter morphological variants
        if len(ord_lower) >= 3:
            results = [
                r for r in results
                if not (ord_lower in r.get("ord", "").lower()
                        or r.get("ord", "").lower() in ord_lower)
            ]
        response["resultater"] = results

    return response


def finn_rim_alle_dialekter(
    ord: str,
    db_path: Optional[Path] = None,
    maks: int = 20,
) -> dict:
    """Find rhymes across all dialects and show which dialects each pair works in.

    Returns dict:
        ord: input word
        dialektsuffikser: {dialekt: rimsuffiks} for the input word
        rimpar: [{ord, dialekter: [list of dialects where this is a perfect rhyme]}]
    """
    # Get suffix for each dialect
    dialect_suffixes = {}
    for d in GYLDIGE_DIALEKTER:
        info = _get_word_info(ord, db_path=db_path, dialekt=d)
        if info and info.get("rimsuffiks"):
            dialect_suffixes[d] = info["rimsuffiks"]

    if not dialect_suffixes:
        return {"ord": ord, "dialektsuffikser": {}, "rimpar": []}

    # Collect rhymes per dialect
    word_dialects = {}  # word -> set of dialects where it rhymes
    ord_lower = ord.lower()

    for d, suffix in dialect_suffixes.items():
        results = hent_rim_dialekt(
            suffix=suffix,
            dialekt=d,
            ord_lower=ord_lower,
            db_path=db_path,
            maks=maks * 5,
        )
        for r in results:
            w = r["ord"]
            if w.lower() == ord_lower:
                continue
            if w not in word_dialects:
                word_dialects[w] = set()
            word_dialects[w].add(d)

    # Build results sorted by number of dialects (most universal first)
    rimpar = []
    for w, dialekter in sorted(
        word_dialects.items(),
        key=lambda x: (-len(x[1]), x[0]),
    ):
        rimpar.append({
            "ord": w,
            "dialekter": sorted(dialekter),
        })

    return {
        "ord": ord,
        "dialektsuffikser": dialect_suffixes,
        "rimpar": rimpar[:maks],
    }


# Cache all distinct suffixes grouped by dot-count for fast halvrim lookup.
# Loaded once on first use, shared across all requests.
_suffix_by_dots: dict[int, list[str]] | None = None


def _get_suffixes_by_dots(db_path: Optional[Path] = None) -> dict[int, list[str]]:
    global _suffix_by_dots
    if _suffix_by_dots is None:
        conn = _connect(db_path)
        cur = conn.execute("SELECT DISTINCT rimsuffiks FROM ord")
        _suffix_by_dots = {}
        for row in cur:
            s = row[0]
            n = s.count(".")
            if n not in _suffix_by_dots:
                _suffix_by_dots[n] = []
            _suffix_by_dots[n].append(s)
    return _suffix_by_dots


@lru_cache(maxsize=2048)
def _finn_kandidat_suffikser_cached(
    source_suffix: str,
    terskel: float = 0.5,
    maks_suffikser: int = 300,
) -> tuple[tuple[str, float], ...]:
    """Cached version — returns tuple of tuples for hashability."""
    by_dots = _get_suffixes_by_dots()
    n_dots = source_suffix.count(".")
    same_dot = by_dots.get(n_dots, [])

    source_norm = _normalize_length(source_suffix)
    candidates = []
    for cand in same_dot:
        if _normalize_length(cand) == source_norm:
            continue
        score = _score_halvrim(source_suffix, cand)
        if score >= terskel:
            candidates.append((cand, score))

    candidates.sort(key=lambda x: -x[1])
    return tuple(candidates[:maks_suffikser])


def _finn_kandidat_suffikser(
    source_suffix: str,
    db_path: Optional[Path] = None,
    terskel: float = 0.5,
    maks_suffikser: int = 300,
) -> list[tuple[str, float]]:
    """Find rimsuffikser that are halvrim candidates.

    Scans all distinct suffixes with the same dot-count (syllable structure)
    and scores them using _score_halvrim. Results are cached.
    """
    return list(_finn_kandidat_suffikser_cached(source_suffix, terskel, maks_suffikser))


def finn_halvrim(
    ord: str,
    db_path: Optional[Path] = None,
    maks: int = 200,
    terskel: float = 0.5,
    dialekt: str = "øst",
    rimsuffiks: Optional[str] = None,
    grupper: bool = False,
    ekskluder_propn: bool = True,
) -> dict:
    """Find halvrim (near-rhymes) with depth-based grouping.

    Two channels:
    - Assonance: same vowels, different consonants (mor→sol)
    - Consonance: same consonants, different vowels (søvn→jevn)

    Structural exclusion of perfect rhymes: at each depth N, if a word's
    N-syllable suffix matches the search word's exactly, it's a perfect
    rhyme and is excluded.  This guarantees no overlap with finn_perfekte_rim.

    Args:
        rimsuffiks: If given, use this suffix directly (for disambiguation).
        grupper: If True, group results by rhyme depth.
        ekskluder_propn: Exclude proper nouns.

    Returns dict with keys:
        ord, rimsuffiks, varianter, resultater (flat or depth-grouped).
    """
    # --- Resolve word info and variants ---
    varianter = hent_varianter(ord, db_path=db_path)

    info = _get_word_info(ord, db_path=db_path, dialekt=dialekt, rimsuffiks=rimsuffiks)
    if info is None:
        return {"ord": ord, "rimsuffiks": None, "varianter": [], "resultater": []}

    suffix = rimsuffiks or info.get("rimsuffiks")
    if not suffix:
        from scripts.build_rhyme_index import compute_rhyme_suffix
        fonemer = info.get("fonemer")
        stress = info.get("stress")
        if fonemer and stress:
            suffix = compute_rhyme_suffix(fonemer, stress)
    if not suffix:
        return {"ord": ord, "rimsuffiks": None, "varianter": varianter, "resultater": []}

    sokeord_ipa = info.get("ipa_ren", "")
    maks_dybde = len(sokeord_ipa.split(".")) if sokeord_ipa else 1
    ord_lower = ord.lower()

    # Enrich variants for disambiguation
    berikede_varianter = (
        _berik_varianter_med_definisjoner(ord, varianter)
        if len(varianter) > 1 else []
    )

    # --- Step 1: Pre-compute depth suffixes for the search word ---
    dybde_suffikser = {}
    if sokeord_ipa:
        for d in range(1, maks_dybde + 1):
            dybde_suffikser[d] = _stavelsessuffiks(sokeord_ipa, d)

    # --- Step 2: Per-depth candidate suffix search ---
    # At each depth D, find candidate rimsuffikser matching the D-syllable
    # suffix (which has D-1 dots).
    dybde_kandidater: dict[int, list[tuple[str, float]]] = {}
    for d in range(1, maks_dybde + 1):
        target_suffix = dybde_suffikser.get(d, suffix)
        kandidater_d = _finn_kandidat_suffikser(
            target_suffix, db_path=db_path, terskel=terskel,
        )
        dybde_kandidater[d] = kandidater_d

    # --- Step 3: Per-depth fetch, score, and group ---
    grupper_dict: dict[int, list[dict]] = {}

    for d in range(1, maks_dybde + 1):
        target_suffix = dybde_suffikser.get(d, suffix)

        # Raise threshold at deeper depths: more syllables compared
        # means more chance of spurious partial matches.
        # For multi-syllable search words, skip depth 1 entirely —
        # matching only the last syllable gives too many false positives
        # (e.g. "ånder" with suffix "ər" matches "det", "en", "med").
        if d == 1 and maks_dybde >= 2:
            continue
        depth_terskel = terskel + 0.05 * (d - 1)

        # Build suffix list for DB fetch.
        # For depth D, use depth-D candidates (D-1 dot rimsuffikser).
        # For D > 1, also include depth-1 candidates (0-dot rimsuffikser)
        # so that multi-syllable words with short rimsuffikser are found
        # (e.g. trilobitt has rimsuffiks "ɪt" but 3 syllables).
        sfx_set = {s for s, _ in dybde_kandidater[d]}
        sfx_set.add(target_suffix)
        alle_sfx = list(sfx_set)

        if not alle_sfx:
            continue

        # Fetch words at this syllable depth
        fetch_limit = max(maks * 5, len(alle_sfx) * 15)
        if d < maks_dybde:
            ord_ved_dybde = hent_ord_for_halvrim(
                suffikser=alle_sfx, ord_lower=ord_lower,
                db_path=db_path, maks=fetch_limit,
                ekskluder_propn=ekskluder_propn, stavelser_eq=d,
            )
        else:
            # Last group: all words with >= maks_dybde syllables
            ord_ved_dybde = hent_ord_for_halvrim(
                suffikser=alle_sfx, ord_lower=ord_lower,
                db_path=db_path, maks=fetch_limit,
                ekskluder_propn=ekskluder_propn, stavelser_gte=d,
            )

        for w in ord_ved_dybde:
            word_ipa = w.get("ipa_ren", "")
            if not word_ipa:
                continue

            # Exclude morphological variants containing the search word
            if len(ord_lower) >= 3 and (ord_lower in w["ord"] or w["ord"] in ord_lower):
                continue

            word_suffix = _stavelsessuffiks(word_ipa, d)

            # Structural exclusion: suffix match = perfect rhyme.
            # Normalize vowel length (ɪːk ≈ ɪk) since length doesn't
            # change rhyme identity in Norwegian.
            if _normalize_length(word_suffix) == _normalize_length(target_suffix):
                continue

            # Syllable weight filter: short vowel (heavy syllable, e.g.
            # ɪk in 'politikk') doesn't match long vowel (light syllable,
            # e.g. ɪːt in 'hit').  Orthographic double consonant (kk, tt)
            # = short vowel in IPA; they must have matching weight.
            if not _same_vowel_weight(target_suffix, word_suffix):
                continue

            suffix_score = _score_halvrim(target_suffix, word_suffix)
            if suffix_score < depth_terskel:
                continue

            score = suffix_score

            w_copy = dict(w)
            w_copy["score"] = round(score, 3)
            w_copy.pop("ipa_ren", None)

            if d not in grupper_dict:
                grupper_dict[d] = []
            grupper_dict[d].append(w_copy)

    # Sort within each group by score then frequency
    for d in grupper_dict:
        grupper_dict[d].sort(
            key=lambda r: (-r["score"], -r.get("frekvens", 0))
        )
        grupper_dict[d] = grupper_dict[d][:maks]

    if grupper:
        # Always group by actual word syllable count for display.
        # Depth-based grouping is used internally for scoring, but
        # the final output should show "1 stavelse", "2 stavelser" etc.
        flat_all = []
        for d in sorted(grupper_dict.keys()):
            flat_all.extend(grupper_dict[d])
        flat_all.sort(key=lambda r: (-r["score"], -r.get("frekvens", 0)))
        result_groups = _grupper_etter_stavelser(flat_all[:maks])
    else:
        # Flat mode: merge all groups
        flat = []
        for d in sorted(grupper_dict.keys()):
            flat.extend(grupper_dict[d])
        flat.sort(key=lambda r: (-r["score"], -r.get("frekvens", 0)))
        result_groups = flat[:maks]

    return {
        "ord": ord,
        "rimsuffiks": suffix,
        "varianter": berikede_varianter,
        "resultater": result_groups,
    }


def match_konsonanter(
    ord: str,
    db_path: Optional[Path] = None,
    maks: int = 100,
) -> list[dict]:
    """Find words with the same consonant skeleton (vowels stripped).

    Useful for finding alliterative or consonance-based matches.
    Returns list of dicts: ord, rimsuffiks, tonelag, stavelser.
    """
    info = _get_word_info(ord, db_path=db_path)
    if info is None:
        return []

    ipa = info.get("ipa_ren")
    if not ipa:
        return []

    # Extract consonant skeleton from ipa_ren
    source_phs = _segment_phonemes(ipa.replace(".", ""))
    source_cons = "".join(ph for ph in source_phs if not _is_vowel_phoneme(ph))

    if not source_cons:
        return []

    # We need to scan the DB — use rimsuffiks as a starting filter
    # to avoid full table scan. Get words with same syllable count.
    source_syl = info.get("stavelser", 1)

    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT LOWER(ord) as ord, rimsuffiks, tonelag, stavelser, fonemer "
            "FROM ord WHERE stavelser = ? AND LOWER(ord) != ? "
            "GROUP BY LOWER(ord) LIMIT 10000",
            (source_syl, ord.lower()),
        )

        results = []
        for r in cur:
            d = dict(r)
            cand_phs = _segment_phonemes(d["fonemer"].replace(".", ""))
            cand_cons = "".join(ph for ph in cand_phs if not _is_vowel_phoneme(ph))
            if cand_cons == source_cons:
                del d["fonemer"]
                results.append(d)

        results.sort(key=lambda r: r["ord"])
        return results[:maks]
    finally:
        pass


def finn_rimsti(
    ord: str,
    db_path: Optional[Path] = None,
    min_familiestr: int = 3,
    maks_steg: int = 8,
    ord_per_steg: int = 5,
    min_frekvens: float = 1.0,
    dialekt: str = "øst",
) -> dict:
    """Build a rhyme path — suffix drifts via consonant equivalence.

    Each step is a rhyme family. The bridge between steps changes one
    consonant to an equivalent (l→r, t→p→k, m→n→ŋ) or extends/reduces
    the suffix structure (uːl → uː.lə → uː.rə). This creates gradual
    drift through sound-space.

    Example for "sol":
      Step 1: sol, stol, alkohol, domstol    /uːl/
      Step 2: for, stor, tror, fjor          /uːr/   (l→r, both LIQ)
      Step 3: store, gjorde, tore, bordet    /uː.rə/ (extend r→.rə)
      Step 4: skole, stole, vinmonopolet     /uː.lə/ (swap r→l)
    """
    empty = {"ord": ord, "rimsuffiks": None, "steg": [], "antall_steg": 0}

    info = _get_word_info(ord, db_path=db_path, dialekt=dialekt)
    if info is None:
        return empty

    suffix = info.get("rimsuffiks")
    if not suffix:
        return empty

    used_words: set[str] = {ord.lower()}
    used_suffixes: set[str] = set()
    all_steg: list[dict] = []
    cur_suffix = suffix

    for step_i in range(maks_steg):
        # Fill step with helrim words
        step_words = []
        if step_i == 0:
            step_words.append(ord.lower())

        rim = hent_rim_for_suffiks(
            suffiks=cur_suffix, ord_lower="|",
            db_path=db_path, maks=500, ekskluder_propn=True,
        )
        rim.sort(key=lambda r: -(r.get("frekvens", 0) or 0))
        for r in rim:
            w = r["ord"]
            if w in used_words or len(w) > 12:
                continue
            step_words.append(w)
            used_words.add(w)
            if len(step_words) >= ord_per_steg:
                break

        if not step_words:
            break

        all_steg.append({
            "rimsuffiks": cur_suffix,
            "ord": step_words,
            "aktiv": step_i == 0,
        })
        used_suffixes.add(cur_suffix)

        if len(all_steg) >= maks_steg:
            break

        # Bridge: find neighbor suffix via consonant drift
        neighbors = _suffix_neighbors(cur_suffix)
        neighbors = [(n, t) for n, t in neighbors if n not in used_suffixes]
        if not neighbors:
            break

        # Pick neighbor with most common words available
        best_sfx = None
        best_count = 0
        for n, _t in neighbors:
            words = hent_rim_for_suffiks(n, "|", db_path=db_path, maks=10, ekskluder_propn=True)
            count = sum(1 for w in words if w["ord"] not in used_words)
            if count > best_count:
                best_count = count
                best_sfx = n

        if not best_sfx or best_count == 0:
            break

        cur_suffix = best_sfx

    return {
        "ord": ord,
        "rimsuffiks": suffix,
        "steg": all_steg,
        "antall_steg": len(all_steg),
    }


# --- Suffix neighbor finding for rimsti ---

_all_suffixes_cache = None


def _get_all_suffixes(db_path: Optional[Path] = None) -> set:
    global _all_suffixes_cache
    if _all_suffixes_cache is None:
        conn = _connect(db_path)
        _all_suffixes_cache = set()
        for row in conn.execute("SELECT rimsuffiks FROM rimsti_indeks WHERE familiestr >= 3"):
            _all_suffixes_cache.add(row[0])
    return _all_suffixes_cache


def _suffix_neighbors(suffix: str) -> list[tuple[str, str]]:
    """Find suffixes reachable by one consonant mutation.

    Three mutation types:
    1. Swap: replace one consonant with equiv class member (l→r)
    2. Extend: move last consonant into schwa syllable (uːl → uː.lə)
    3. Reduce: collapse trailing schwa syllable (uː.rə → uːr)

    Returns list of (neighbor_suffix, change_description).
    """
    phonemes = _parse_suffix_phonemes(suffix)
    all_sfx = _get_all_suffixes()
    neighbors = []
    seen = set()

    # Type 1: Swap one consonant for equiv class member
    for i, ph in enumerate(phonemes):
        if _is_vowel_phoneme(ph):
            continue
        my_class = _cons_equiv_class(ph)
        for other_cons, other_class in CONS_EQUIV.items():
            if other_class == my_class and other_cons != ph:
                new_phonemes = list(phonemes)
                new_phonemes[i] = other_cons
                new_suffix = _rebuild_suffix(suffix, phonemes, new_phonemes)
                if new_suffix in all_sfx and new_suffix != suffix and new_suffix not in seen:
                    neighbors.append((new_suffix, f"swap {ph}→{other_cons}"))
                    seen.add(new_suffix)

    # Type 2: Extend — move last consonant into schwa syllable
    last_cons = [ph for ph in phonemes if not _is_vowel_phoneme(ph)]
    if last_cons:
        last_c = last_cons[-1]
        if suffix.endswith(last_c):
            base = suffix[:-len(last_c)]
            extended = base + "." + last_c + "ə"
            if extended in all_sfx and extended not in seen:
                neighbors.append((extended, f"extend {last_c}→.{last_c}ə"))
                seen.add(extended)
        # Also try plain schwa addition
        extended2 = suffix + ".ə"
        if extended2 in all_sfx and extended2 not in seen:
            neighbors.append((extended2, "extend +.ə"))
            seen.add(extended2)

    # Type 3: Reduce — collapse trailing schwa syllable
    if "." in suffix:
        parts = suffix.rsplit(".", 1)
        tail_phonemes = _parse_suffix_phonemes(parts[1])
        tail_cons = [p for p in tail_phonemes if not _is_vowel_phoneme(p)]
        if tail_cons:
            reduced = parts[0] + tail_cons[0]
            if reduced in all_sfx and reduced not in seen:
                neighbors.append((reduced, f"reduce .{parts[1]}→{tail_cons[0]}"))
                seen.add(reduced)
        reduced_bare = parts[0]
        if reduced_bare in all_sfx and reduced_bare not in seen:
            neighbors.append((reduced_bare, f"reduce .{parts[1]}"))
            seen.add(reduced_bare)

    return neighbors


def _rebuild_suffix(original: str, old_phonemes: list, new_phonemes: list) -> str:
    """Rebuild suffix string preserving dot positions."""
    result = []
    ph_idx = 0
    for syl_i, syl in enumerate(original.split(".")):
        if syl_i > 0:
            result.append(".")
        syl_phonemes = _segment_phonemes(syl)
        for _sp in syl_phonemes:
            if ph_idx < len(new_phonemes):
                result.append(new_phonemes[ph_idx])
            ph_idx += 1
    return "".join(result)
