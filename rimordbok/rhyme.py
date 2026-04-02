from __future__ import annotations

"""Rim-motor — finner rimord basert på fonetikk.

Provides four rhyme-finding functions:
- finn_perfekte_rim: exact rhyme suffix match
- finn_halvrim: halvrim (near-rhyme) using phoneme equivalence classes
- finn_homofoner: identical phoneme sequence, different spelling
- match_konsonanter: consonant skeleton matching
"""

import sqlite3
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


def _suffix_vowel_distance(sfx_a: str, sfx_b: str) -> float:
    """Average vowel distance between two rhyme suffixes."""
    phs_a = _parse_suffix_phonemes(sfx_a)
    phs_b = _parse_suffix_phonemes(sfx_b)
    vowels_a = [ph for ph in phs_a if _is_vowel_phoneme(ph)]
    vowels_b = [ph for ph in phs_b if _is_vowel_phoneme(ph)]
    if not vowels_a or not vowels_b:
        return 1.0
    # Compare corresponding vowels, pad shorter with last vowel
    total = 0.0
    n = max(len(vowels_a), len(vowels_b))
    for i in range(n):
        va = vowels_a[min(i, len(vowels_a) - 1)]
        vb = vowels_b[min(i, len(vowels_b) - 1)]
        total += _vowel_distance(va, vb)
    return total / n


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


def _consonant_skeleton(suffix: str) -> tuple:
    """Extract the rhythmic skeleton from a rhyme suffix.

    Replaces vowels with "V" (collapsing consecutive vowels/diphthongs)
    and keeps consonants. Preserves syllable structure so that
    monosyllabic and polysyllabic suffixes never match.

    Examples:
        "ʉːs" (hus)    → ("V", "s")
        "ɛs" (press)    → ("V", "s")
        "øː.sə" (løse)  → ("V", "s", "V")
        "ɛŋ.ər" (penger) → ("V", "ŋ", "V", "r")
    """
    phonemes = _parse_suffix_phonemes(suffix)
    result = []
    last_was_vowel = False
    for ph in phonemes:
        if _is_vowel_phoneme(ph):
            if not last_was_vowel:
                result.append("V")
            last_was_vowel = True
        else:
            result.append(ph)
            last_was_vowel = False
    return tuple(result)


def _score_near_rhyme(suffix_a: str, suffix_b: str) -> float:
    """Score the similarity between two rhyme suffixes (legacy, used by rimsti).

    Scoring:
    - Vowel nucleus match (via equivalence class): +0.6 per vowel
    - Coda consonant match (via equivalence class): +0.3 per consonant
    - Normalize by total number of phonemes in the longer suffix.
    """
    phs_a = _parse_suffix_phonemes(suffix_a)
    phs_b = _parse_suffix_phonemes(suffix_b)

    # Separate into vowels and consonants while preserving order
    def split_vc(phs):
        vowels = [ph for ph in phs if _is_vowel_phoneme(ph)]
        consonants = [ph for ph in phs if not _is_vowel_phoneme(ph)]
        return vowels, consonants

    va, ca = split_vc(phs_a)
    vb, cb = split_vc(phs_b)

    score = 0.0
    max_score = 0.0

    # Score vowels
    max_vowels = max(len(va), len(vb))
    for i in range(max_vowels):
        max_score += 0.6
        if i < len(va) and i < len(vb):
            if _vowel_equiv_class(va[i]) == _vowel_equiv_class(vb[i]):
                score += 0.6

    # Score consonants
    max_cons = max(len(ca), len(cb))
    for i in range(max_cons):
        max_score += 0.3
        if i < len(ca) and i < len(cb):
            if _cons_equiv_class(ca[i]) == _cons_equiv_class(cb[i]):
                score += 0.3

    if max_score == 0:
        return 0.0

    return score / max_score


# --- Halvrim scoring (assonance + consonance) ---


def _lcs_length(a: list, b: list) -> int:
    """Longest common subsequence length (DP, O(n*m))."""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 0
    # Optimised 1D DP
    prev = [0] * (m + 1)
    for i in range(1, n + 1):
        cur = [0] * (m + 1)
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = max(prev[j], cur[j - 1])
        prev = cur
    return prev[m]


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


def _consonant_sequence_similarity(ca: list[str], cb: list[str]) -> float:
    """Score consonant similarity using weighted LCS.

    Uses longest common subsequence to handle insertions/deletions.
    Exact phoneme match scores 1.0, equivalence class match (same manner
    of articulation + voicing, e.g. k≈t) scores 0.6.

    Returns 0.0-1.0.
    """
    if not ca and not cb:
        return 1.0
    if not ca or not cb:
        return 0.0

    weighted = _weighted_lcs(ca, cb, exact_weight=1.0, class_weight=0.6)
    denom = max(len(ca), len(cb))
    return weighted / denom if denom > 0 else 0.0


def _score_halvrim(target_sfx: str, cand_sfx: str) -> float:
    """Score halvrim (near-rhyme) similarity between two suffixes.

    target_sfx: the search word's suffix (what we're rhyming against).
    cand_sfx: the candidate word's suffix.

    Combines:
    - Vowel similarity (continuous distance, 75% weight)
    - Consonant similarity (recall against target, 25% weight)

    Vowels dominate because halvrim IS assonance — matching vowels
    is the primary signal.  Consonant recall measures how much of the
    target's consonant structure the candidate covers — extra consonants
    in the candidate are not penalised (plikt covers politikk's [k]
    fully, while hit only class-matches it).
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

    return 0.75 * v_sim + 0.25 * c_sim


def _fullword_consonant_similarity(ipa_a: str, ipa_b: str) -> float:
    """Consonant skeleton similarity across the full word (not just suffix).

    Extracts all consonants from both IPAs in order, then computes
    weighted LCS (exact = 1.0, equivalence class = 0.6).
    Normalises by the TARGET's (ipa_a) consonant count so that extra
    consonants in the candidate don't penalise.

    E.g. politikk [p,l,t,k] vs plikt [p,l,k,t] → high similarity
         politikk [p,l,t,k] vs hit [h,t]        → low similarity
    """
    # Parse full IPA into phonemes (dots separate syllables)
    phs_a = _parse_suffix_phonemes(ipa_a)
    phs_b = _parse_suffix_phonemes(ipa_b)
    ca = [ph for ph in phs_a if not _is_vowel_phoneme(ph)]
    cb = [ph for ph in phs_b if not _is_vowel_phoneme(ph)]
    if not ca and not cb:
        return 1.0
    if not ca or not cb:
        return 0.0
    weighted = _weighted_lcs(ca, cb, exact_weight=1.0, class_weight=0.6)
    recall = weighted / len(ca)       # coverage of target
    precision = weighted / len(cb)    # how much of candidate is relevant
    if recall + precision == 0:
        return 0.0
    return 2.0 * recall * precision / (recall + precision)  # F1


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


def _grupper_etter_dybde(
    sokeord_ipa: str,
    results_med_ipa: list[dict],
    sokeord_lower: str = "",
) -> list[dict]:
    """Group rhyme results by syllable-depth match.

    For a search word with N syllables, creates groups at depths 1..N.
    Each result word is placed in the group matching its own syllable count:
    - A 1-syllable word goes in depth 1 if its suffix matches depth-1 suffix.
    - A 2-syllable word goes in depth 2 if its full suffix matches depth-2 suffix.
    - Words with >= N syllables go in the depth-N group (max depth).

    Returns list of groups: {dybde: int, suffiks: str, ord: [result dicts]}.
    Empty groups are omitted.
    """
    sokeord_syls = sokeord_ipa.split(".")
    maks_dybde = len(sokeord_syls)

    # Pre-compute target suffix for each depth
    dybde_suffikser = {}
    for d in range(1, maks_dybde + 1):
        dybde_suffikser[d] = _stavelsessuffiks(sokeord_ipa, d)

    grupper: dict[int, list[dict]] = {d: [] for d in range(1, maks_dybde + 1)}

    for r in results_med_ipa:
        word_syl = r.get("stavelser", 1) or 1
        word_ipa = r.get("ipa_ren", "")
        if not word_ipa:
            continue

        # Exclude morphological variants containing the search word
        w_lower = r.get("ord", "").lower()
        if sokeord_lower and len(sokeord_lower) >= 3:
            if sokeord_lower in w_lower or w_lower in sokeord_lower:
                continue

        # Determine which depth group this word belongs to
        if word_syl >= maks_dybde:
            d = maks_dybde
        else:
            d = word_syl

        # Compute this word's suffix at the required depth
        word_suffix = _stavelsessuffiks(word_ipa, d)
        target_suffix = dybde_suffikser[d]

        if word_suffix == target_suffix:
            grupper[d].append(r)

    # Sort within each group by frequency descending
    for d in grupper:
        grupper[d].sort(key=lambda r: -r.get("frekvens", 0))

    return [
        {"dybde": d, "suffiks": dybde_suffikser[d], "ord": grupper[d]}
        for d in sorted(grupper.keys())
        if grupper[d]  # skip empty groups
    ]


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
        sokeord_ipa = info.get("ipa_ren", "")
        maks_dybde = len(sokeord_ipa.split(".")) if sokeord_ipa else 1
        if sokeord_ipa and maks_dybde > 1:
            response["resultater"] = _grupper_etter_dybde(
                sokeord_ipa, results, sokeord_lower=ord_lower,
            )
        else:
            # For single-syllable words, depth grouping is meaningless
            # (all results are depth 1). Group by syllable count instead.
            # First apply morphological variant filter
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


def _finn_kandidat_suffikser(
    source_suffix: str,
    db_path: Optional[Path] = None,
    terskel: float = 0.5,
    maks_suffikser: int = 300,
) -> list[tuple[str, float]]:
    """Find rimsuffikser that are halvrim candidates at depth 1.

    Scans all distinct suffixes with the same dot-count (syllable structure)
    and scores them using _score_halvrim. This catches both:
    - Assonance (same vowels, different consonants): mor→sol
    - Consonance (same consonants, different vowels): søvn→jevn

    Returns list of (suffix, score) sorted by score descending.
    The source suffix itself is NOT included (it's a perfect rhyme).
    """
    conn = _connect(db_path)
    n_dots = source_suffix.count(".")

    cur = conn.execute("SELECT DISTINCT rimsuffiks FROM ord")

    source_norm = _normalize_length(source_suffix)
    candidates = []
    for row in cur:
        cand = row[0]
        # Skip exact matches and length-only variants (ɪk ≈ ɪːk)
        if _normalize_length(cand) == source_norm:
            continue
        if cand.count(".") != n_dots:
            continue

        score = _score_halvrim(source_suffix, cand)
        if score >= terskel:
            candidates.append((cand, score))

    candidates.sort(key=lambda x: -x[1])
    return candidates[:maks_suffikser]


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
        depth_terskel = terskel + 0.05 * (d - 1)

        # Build suffix list for DB fetch.
        # For depth D, use depth-D candidates (D-1 dot rimsuffikser).
        # For D > 1, also include depth-1 candidates (0-dot rimsuffikser)
        # so that multi-syllable words with short rimsuffikser are found
        # (e.g. trilobitt has rimsuffiks "ɪt" but 3 syllables).
        sfx_set = {s for s, _ in dybde_kandidater[d]}
        sfx_set.add(target_suffix)
        if d > 1:
            # Add top depth-1 candidates (limited to keep the pool small)
            for s, _ in dybde_kandidater[1][:100]:
                sfx_set.add(s)
            sfx_set.add(suffix)  # exact depth-1 suffix
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
        if maks_dybde == 1:
            # Single-syllable search word: depth grouping is meaningless.
            # Reformat into syllable-count groups instead.
            flat_all = []
            for d in sorted(grupper_dict.keys()):
                flat_all.extend(grupper_dict[d])
            flat_all.sort(key=lambda r: (-r["score"], -r.get("frekvens", 0)))
            result_groups = _grupper_etter_stavelser(flat_all[:maks])
        else:
            result_groups = [
                {
                    "dybde": d,
                    "suffiks": dybde_suffikser.get(d, suffix),
                    "ord": grupper_dict[d],
                }
                for d in sorted(grupper_dict.keys())
                if grupper_dict[d]
            ]
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


def finn_homofoner(
    ord: str,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Find homophones — words with identical phoneme sequence but different spelling.

    Uses prebuilt homofoner table (fast O(1) lookup) with fallback to live query.
    Returns list of dicts: ord, rimsuffiks, tonelag, stavelser, fonemer.
    """
    info = _get_word_info(ord, db_path=db_path)
    if info is None:
        return []

    ipa = info.get("ipa_ren")
    if not ipa:
        return []

    # Try prebuilt homofoner table first (in semantics.db)
    sem_db = Path(__file__).resolve().parent.parent / "data/db/semantics.db"
    if sem_db.exists():
        try:
            sconn = _connect(sem_db)
            cur = sconn.execute(
                "SELECT ord FROM homofoner WHERE ipa = ? AND ord != ?",
                (ipa, ord.lower()),
            )
            hom_words = [r["ord"] for r in cur]
            if hom_words:
                # Enrich with phonetic data from rimindeks
                conn = _connect(db_path)
                try:
                    placeholders = ",".join("?" for _ in hom_words)
                    cur2 = conn.execute(
                        f"SELECT LOWER(ord) as ord, rimsuffiks, tonelag, "
                        f"MAX(stavelser) as stavelser, fonemer "
                        f"FROM ord WHERE LOWER(ord) IN ({placeholders}) "
                        f"GROUP BY LOWER(ord)",
                        hom_words,
                    )
                    return [dict(r) for r in cur2]
                finally:
                    pass
        except Exception:
            pass  # Fall through to live query

    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT LOWER(ord) as ord, rimsuffiks, tonelag, "
            "MAX(stavelser) as stavelser, fonemer "
            "FROM ord WHERE ipa_ren = ? AND LOWER(ord) != ? "
            "GROUP BY LOWER(ord)",
            (ipa, ord.lower()),
        )
        return [dict(r) for r in cur]
    finally:
        pass


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
    """Build a rhyme chain — each word leads to the next through rhyme.

    The chain evolves organically: each word is the anchor for the next.
    The suffix drifts naturally as the chain progresses, creating a
    freestyle training path that escalates step by step.

    Example for "sol":
      Step 1: sol, pol, monopol, parabol
      Step 2: anabol, abstraksjon, busstasjon, telefon
      Step 3: ...

    Each word rhymes with or connects to the previous word.
    Steps are groups where each step's last word bridges to the next.

    Returns dict with steg[] where each steg has ord[] and rimsuffiks.
    """
    empty = {"ord": ord, "rimsuffiks": None, "steg": [], "antall_steg": 0}

    info = _get_word_info(ord, db_path=db_path, dialekt=dialekt)
    if info is None:
        return empty

    suffix = info.get("rimsuffiks")
    if not suffix:
        return empty

    # --- Chain-building algorithm ---
    # Single continuous chain: each word leads to the next through
    # rhyme (perfect or near). The suffix drifts naturally.
    # Steps are created when the suffix CHANGES — that's the boundary.
    #
    # Example: sol → pol → monopol → parabol | anabol → abstraksjon →
    #          busstasjon | telefon → mikrofon → ...
    # The | marks where the suffix shifted, creating a new step.

    used_words: set[str] = {ord.lower()}
    chain: list[tuple[str, str]] = [(ord.lower(), suffix)]  # (word, suffix)
    anchor = ord

    total_words = maks_steg * ord_per_steg
    anchor_info_cur = _get_word_info(anchor, db_path=db_path, dialekt=dialekt)
    anchor_syl_cur = (anchor_info_cur.get("stavelser", 1) or 1) if anchor_info_cur else 1

    for _ in range(total_words):
        # Get ALL candidates: helrim + halvrim
        candidates = _rimsti_candidates(
            anchor, used_words, mode="helrim",
            db_path=db_path, dialekt=dialekt,
        )
        halv_candidates = _rimsti_candidates(
            anchor, used_words, mode="bro",
            db_path=db_path, dialekt=dialekt,
        )
        candidates.extend(halv_candidates)

        # Filter: max ±1 syllable from current anchor
        candidates = [
            c for c in candidates
            if abs((c.get("stavelser", 1) or 1) - anchor_syl_cur) <= 1
        ]

        if not candidates:
            break

        # Prefer staying in the same suffix family (natural flow)
        # but allow drift when it's the best option
        chosen = _rimsti_pick(candidates, anchor, [], prefer_drift=False)
        if chosen is None:
            break

        word = chosen["ord"]
        word_info = _get_word_info(word, db_path=db_path, dialekt=dialekt)
        word_suffix = word_info.get("rimsuffiks", "") if word_info else ""
        anchor_syl_cur = (word_info.get("stavelser", 1) or 1) if word_info else 1

        chain.append((word, word_suffix))
        used_words.add(word)
        anchor = word

    # --- Split chain into fixed-size steps ---
    # Each step has ord_per_steg words. The suffix of the last word
    # represents where the step "landed".
    all_steg: list[dict] = []
    words_only = [w for w, _s in chain]

    for i in range(0, len(words_only), ord_per_steg):
        chunk = words_only[i:i + ord_per_steg]
        if not chunk:
            break
        if len(all_steg) >= maks_steg:
            break
        # Get suffix of last word in chunk
        last_word = chunk[-1]
        last_info = _get_word_info(last_word, db_path=db_path, dialekt=dialekt)
        chunk_suffix = last_info.get("rimsuffiks", "") if last_info else ""
        all_steg.append({
            "rimsuffiks": chunk_suffix,
            "ord": chunk,
            "aktiv": i == 0,
        })

    return {
        "ord": ord,
        "rimsuffiks": suffix,
        "steg": all_steg,
        "antall_steg": len(all_steg),
    }


def _rimsti_candidates(
    anchor: str,
    used_words: set[str],
    mode: str = "helrim",
    db_path: Optional[Path] = None,
    dialekt: str = "øst",
) -> list[dict]:
    """Find candidate next words for the rimsti chain.

    mode="helrim": perfect rhymes (for within-step chaining).
                   No morphological filter — pol → monopol is desired.
    mode="bro":    halvrim, for bridging to new suffix territory.
    """
    candidates = []
    seen = set()
    anchor_lower = anchor.lower()

    if mode == "helrim":
        # Use the DB directly to bypass the morphological filter.
        # In rimsti, words containing the anchor ARE desired (pol → monopol).
        info = _get_word_info(anchor, db_path=db_path, dialekt=dialekt)
        if info and info.get("rimsuffiks"):
            suffix = info["rimsuffiks"]
            from rimordbok.db import hent_rim_for_suffiks
            results = hent_rim_for_suffiks(
                suffiks=suffix,
                ord_lower=anchor_lower,
                db_path=db_path,
                maks=500,
                ekskluder_propn=True,
            )
            for r in results:
                w = r["ord"]
                if w not in used_words and w not in seen:
                    r["score"] = 1.0
                    seen.add(w)
                    candidates.append(r)

    elif mode == "bro":
        halvrim = finn_halvrim(
            anchor, maks=100, terskel=0.6, grupper=False,
            db_path=db_path, dialekt=dialekt, ekskluder_propn=True,
        )
        for r in halvrim.get("resultater", []):
            w = r["ord"]
            if w not in used_words and w not in seen and r.get("score", 0) >= 0.7:
                seen.add(w)
                candidates.append(r)

    return candidates


def _rimsti_pick(
    candidates: list[dict],
    anchor: str,
    step_words: list[str],
    prefer_drift: bool = False,
) -> Optional[dict]:
    """Pick the best next word for the chain.

    Within a step (prefer_drift=False):
    - Prefer common, multi-syllable words that stay in the rhyme family
    - Longer words contain the suffix and add new material (pol → monopol)

    As bridge (prefer_drift=True):
    - Prefer words whose suffix differs from anchor (opens new territory)
    - Still must score well as halvrim
    """
    if not candidates:
        return None

    import math
    anchor_lower = anchor.lower()
    anchor_suffix = None
    anchor_info = _get_word_info(anchor)
    if anchor_info:
        anchor_suffix = anchor_info.get("rimsuffiks", "")

    # Track syllable count of current anchor for rhythm matching
    anchor_syl = None
    anchor_info_full = _get_word_info(anchor)
    if anchor_info_full:
        anchor_syl = anchor_info_full.get("stavelser", 1) or 1

    def score(c: dict) -> float:
        s = 0.0
        freq = c.get("frekvens", 0)
        syl = c.get("stavelser", 1) or 1
        word = c.get("ord", "")
        c_suffix = c.get("rimsuffiks", "")
        rhyme_score = c.get("score", 1.0)

        # Base rhyme quality
        s += rhyme_score * 2.0

        # Frequency: prefer recognizable, common words
        if freq > 0:
            s += min(math.log(freq + 1), 4.0) * 1.2

        # Penalty: very short words (less interesting for freestyle)
        if len(word) <= 2:
            s -= 3.0
        # Penalty: very long compounds (impractical to rap)
        if len(word) > 12:
            s -= 2.0

        # Rhythm: prefer words with similar or escalating syllable count
        # (sol → monopol → parabol all feel rhythmically related)
        if anchor_syl and syl >= anchor_syl:
            s += 0.3  # mild preference for same or more syllables

        if prefer_drift:
            # Bridge mode: reward suffix change (new territory)
            if anchor_suffix and c_suffix and c_suffix != anchor_suffix:
                s += 3.0
            # Prefer multi-syllable bridges (they carry more rhythm)
            if syl >= 3:
                s += 1.0
        else:
            # Within-step: penalize suffix change (stay in family)
            if anchor_suffix and c_suffix and c_suffix != anchor_suffix:
                s -= 2.0

        return s

    ranked = sorted(candidates, key=score, reverse=True)
    return ranked[0] if ranked else None
