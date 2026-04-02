from __future__ import annotations

"""Rim-motor — finner rimord basert på fonetikk.

Provides four rhyme-finding functions:
- finn_perfekte_rim: exact rhyme suffix match
- finn_nesten_rim: near-rhyme using phoneme equivalence classes
- finn_homofoner: identical phoneme sequence, different spelling
- match_konsonanter: consonant skeleton matching
"""

import sqlite3
from pathlib import Path
from typing import Optional

from rimordbok.db import (
    _connect, hent_fonetikk, hent_rim_dialekt, hent_varianter,
    hent_rim_for_suffiks, GYLDIGE_DIALEKTER,
)
from rimordbok.phonetics import slaa_opp

# --- IPA vowel perceptual distance ---
# Norwegian vowels grouped by perceptual similarity for rimsti.
# Each vowel gets a 2D coordinate (height, front-back) tuned so that
# pairs that sound alike in Norwegian have small distances.
# Rounding is encoded in the front-back axis: rounded front vowels
# are shifted toward central position (as they sound in Norwegian).
_VOWEL_COORDS = {
    # Close front unrounded
    "i": (1.0, 0.0), "iː": (1.0, 0.0),
    # Close front rounded (sounds central-ish in Norwegian)
    "y": (1.0, 0.15), "yː": (1.0, 0.15),
    # Close central rounded
    "ʉ": (1.0, 0.3), "ʉː": (1.0, 0.3),
    # Close back rounded
    "u": (1.0, 0.45), "uː": (1.0, 0.45),
    # Near-close
    "ɪ": (0.8, 0.05),
    "ʏ": (0.8, 0.2),
    "ʊ": (0.8, 0.4),
    # Close-mid
    "e": (0.6, 0.0), "eː": (0.6, 0.0),
    "ø": (0.6, 0.15), "øː": (0.6, 0.15),
    "o": (0.6, 0.5), "oː": (0.6, 0.5),
    # Open-mid
    "ɛ": (0.35, 0.05),
    "œ": (0.35, 0.2),
    "ɔ": (0.35, 0.5),
    # Near-open / open
    "æ": (0.15, 0.1), "æː": (0.15, 0.1),
    "a": (0.0, 0.3),
    "ɑ": (0.0, 0.5), "ɑː": (0.0, 0.5),
    # Schwa
    "ə": (0.5, 0.25),
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

# Consonant equivalence: consonants that are near-rhyme compatible
CONS_EQUIV = {
    # Voiced/voiceless pairs
    "b": "P", "p": "P",
    "d": "T", "t": "T",
    "g": "K", "k": "K",
    "v": "F", "f": "F",
    # Sibilants
    "s": "S", "ʃ": "S", "ʂ": "S", "ç": "S",
    # Retroflexes map to their non-retroflex counterparts
    "ɖ": "T", "ʈ": "T",
    "ɳ": "N", "n": "N",
    "ɭ": "L", "l": "L",
    # Nasals
    "m": "M",
    "ŋ": "NG",
    # Others
    "r": "R",
    "j": "J",
    "h": "H",
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
    """Score the similarity between two rhyme suffixes.

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


def _grupper_etter_stavelser(results: list[dict]) -> list[dict]:
    """Group rhyme results by syllable count, sorted by frequency within each group.

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

    if ekskluder_propn:
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

    response = {
        "ord": ord,
        "rimsuffiks": suffix,
        "varianter": varianter if len(varianter) > 1 else [],
    }

    if grupper:
        response["resultater"] = _grupper_etter_stavelser(results)
    else:
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


def finn_nesten_rim(
    ord: str,
    db_path: Optional[Path] = None,
    maks: int = 100,
    terskel: float = 0.5,
    dialekt: str = "øst",
    rimsuffiks: Optional[str] = None,
    grupper: bool = False,
) -> list[dict]:
    """Find near-rhymes using phoneme equivalence classes.

    Looks at suffixes that share the same vowel equivalence class in the
    stressed nucleus, then scores by consonant similarity.

    Args:
        rimsuffiks: If given, use this suffix directly (for disambiguation).
        grupper: If True, group results by syllable count.

    Returns list of dicts: ord, rimsuffiks, tonelag, stavelser, score.
    Sorted by score descending.
    """
    info = _get_word_info(ord, db_path=db_path, dialekt=dialekt, rimsuffiks=rimsuffiks)
    if info is None:
        return []

    suffix = info.get("rimsuffiks")
    if not suffix:
        from scripts.build_rhyme_index import compute_rhyme_suffix
        fonemer = info.get("fonemer")
        stress = info.get("stress")
        if fonemer and stress:
            suffix = compute_rhyme_suffix(fonemer, stress)
    if not suffix:
        return []

    # Parse the source suffix to find the nucleus vowel class
    source_phs = _parse_suffix_phonemes(suffix)
    source_vowels = [ph for ph in source_phs if _is_vowel_phoneme(ph)]
    if not source_vowels:
        return []

    nucleus_class = _vowel_equiv_class(source_vowels[0])

    # Find candidate suffixes: same number of syllable-dots, similar structure
    # Strategy: query all distinct suffixes, filter by vowel nucleus equivalence
    conn = _connect(db_path)
    try:
        n_dots = suffix.count(".")
        # Get candidate suffixes with same syllable structure
        cur = conn.execute(
            "SELECT DISTINCT rimsuffiks FROM ord"
        )

        candidate_suffixes = []
        for row in cur:
            cand = row[0]
            if cand == suffix:
                continue  # Skip exact match (that's perfect rhyme)
            if cand.count(".") != n_dots:
                continue  # Different syllable count from stressed vowel

            # Check nucleus vowel equivalence
            cand_phs = _parse_suffix_phonemes(cand)
            cand_vowels = [ph for ph in cand_phs if _is_vowel_phoneme(ph)]
            if not cand_vowels:
                continue
            if _vowel_equiv_class(cand_vowels[0]) != nucleus_class:
                continue

            score = _score_near_rhyme(suffix, cand)
            if score >= terskel:
                candidate_suffixes.append((cand, score))

        # Sort by score, take top candidates
        candidate_suffixes.sort(key=lambda x: -x[1])
        top_suffixes = candidate_suffixes[:50]

        # Fetch words for top suffixes
        results = []
        ord_lower = ord.lower()
        for cand_suffix, score in top_suffixes:
            cur2 = conn.execute(
                "SELECT LOWER(ord) as ord, rimsuffiks, tonelag, "
                "MAX(stavelser) as stavelser, MAX(frekvens) as frekvens "
                "FROM ord WHERE rimsuffiks = ? AND LOWER(ord) != ? "
                "GROUP BY LOWER(ord) ORDER BY frekvens DESC LIMIT 20",
                (cand_suffix, ord_lower),
            )
            # Add tonelag bonus
            tonelag_bonus = 0.1 if info.get("tonelag") is not None else 0.0
            for r in cur2:
                d = dict(r)
                final_score = score
                if tonelag_bonus and d["tonelag"] == info["tonelag"]:
                    final_score += tonelag_bonus
                d["score"] = round(final_score, 3)
                results.append(d)

        # Sort by score descending, then alphabetical
        results.sort(key=lambda r: (-r["score"], r["ord"]))
        results = results[:maks]

        if grupper:
            return _grupper_etter_stavelser(results)
        return results
    finally:
        pass


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
    maks_steg: int = 20,
    min_frekvens: float = 1.0,
    dialekt: str = "øst",
) -> dict:
    """Find the rhyme path — rimfamilier sorted by incremental vowel distance.

    Each step is a RHYME FAMILY (group of words sharing a suffix).
    Families are sorted by greedy nearest-neighbor walk through vowel space,
    starting from the input word's family. Each step is one small vowel shift.

    Example for "hus" (/ʉːs/):
      1. hus, brus, rus, sus  (/ʉːs/) — start
      2. lys, nordlys  (/yːs/) — small vowel shift
      3. pris, is, vis  (/ɪːs/) — next step
      ...

    Returns dict with steg[] where each steg has rimsuffiks, ord[] (examples), aktiv.
    """
    empty = {"ord": ord, "rimsuffiks": None, "konsonantskjelett": None, "steg": [], "antall_steg": 0}

    info = _get_word_info(ord, db_path=db_path, dialekt=dialekt)
    if info is None:
        return empty

    suffix = info.get("rimsuffiks")
    if not suffix:
        from scripts.build_rhyme_index import compute_rhyme_suffix
        fonemer = info.get("fonemer")
        stress = info.get("stress")
        if fonemer and stress:
            suffix = compute_rhyme_suffix(fonemer, stress)
    if not suffix:
        return empty

    skeleton = _consonant_skeleton(suffix)
    skeleton_str = ".".join(skeleton) if skeleton else "(tom)"
    syl_count = suffix.count(".")

    conn = _connect(db_path)
    try:
        # Get all candidate suffixes with same skeleton and syllable structure
        try:
            conn.execute("SELECT 1 FROM rimsti_indeks LIMIT 1")
            row = conn.execute(
                "SELECT konsonantskjelett FROM rimsti_indeks WHERE rimsuffiks = ?",
                (suffix,),
            ).fetchone()
            if row:
                skeleton_str = row["konsonantskjelett"]
            cur = conn.execute(
                "SELECT rimsuffiks, familiestr FROM rimsti_indeks "
                "WHERE konsonantskjelett = ? AND familiestr >= ?",
                (skeleton_str, min_familiestr),
            )
        except Exception:
            cur = conn.execute(
                "SELECT DISTINCT rimsuffiks, 0 as familiestr FROM ord"
            )

        # Build family pool: suffix → familiestr (same syllable structure only)
        families = {}
        for r in cur:
            sfx = r["rimsuffiks"]
            if sfx.count(".") == syl_count:
                families[sfx] = r["familiestr"]

        if not families:
            return empty

        # Merge length variants (ɑːs and ɑs are effectively the same family)
        merged = {}
        for sfx, size in families.items():
            key = sfx.replace("ː", "")
            if key not in merged or size > merged[key][1]:
                merged[key] = (sfx, size)
        # Map: canonical suffix → (display suffix, size)

        # --- Greedy nearest-neighbor walk through families ---
        visited_keys = set()
        steg = []
        current_sfx = suffix
        current_key = suffix.replace("ː", "")
        ord_lower = ord.lower()

        for _ in range(maks_steg):
            # Find the display suffix for current key
            display_sfx = current_sfx
            for sfx in families:
                if sfx.replace("ː", "") == current_key:
                    if families[sfx] >= families.get(display_sfx, 0):
                        display_sfx = sfx

            visited_keys.add(current_key)

            # Fetch example words for ALL suffixes in this family (long + short)
            example_suffixes = [s for s in families if s.replace("ː", "") == current_key]
            eks = []
            for esfx in example_suffixes:
                cur2 = conn.execute(
                    "SELECT LOWER(o.ord) as ord, MAX(o.frekvens) as f FROM ord o "
                    "WHERE o.rimsuffiks = ? AND o.frekvens >= 5.0 "
                    "AND length(o.ord) BETWEEN 3 AND 8 "
                    "AND o.ord NOT LIKE '%-%' "
                    "AND o.pos NOT LIKE 'PM%%' "
                    "GROUP BY LOWER(o.ord) ORDER BY f DESC LIMIT 10",
                    (esfx,),
                )
                for row2 in cur2:
                    w = row2["ord"]
                    # Skip compounds of search word
                    if len(w) > len(ord_lower) + 2 and ord_lower in w:
                        continue
                    if w not in eks:
                        eks.append(w)

            # Sort by frequency (already mostly sorted from SQL)
            eks = eks[:5]

            if len(eks) < 2 and current_key != suffix.replace("ː", ""):
                # Skip empty families, but find next neighbor from here
                pass
            else:
                steg.append({
                    "rimsuffiks": display_sfx,
                    "ord": eks,
                    "aktiv": current_key == suffix.replace("ː", ""),
                })

            # Find nearest unvisited family
            best_key = None
            best_dist = float("inf")
            best_sfx = None
            for sfx in families:
                key = sfx.replace("ː", "")
                if key in visited_keys:
                    continue
                d = _suffix_vowel_distance(current_sfx, sfx)
                if d < best_dist:
                    best_dist = d
                    best_key = key
                    best_sfx = sfx

            if best_key is None:
                break
            current_key = best_key
            current_sfx = best_sfx

        return {
            "ord": ord,
            "rimsuffiks": suffix,
            "konsonantskjelett": skeleton_str,
            "steg": steg,
            "antall_steg": len(steg),
        }
    finally:
        pass
