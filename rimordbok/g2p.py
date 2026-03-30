from __future__ import annotations

"""Rule-based grapheme-to-phoneme for Norwegian Bokmål.

Norwegian has fairly regular orthography. This module implements a rule-based
G2P as a fallback for words not found in the NB Uttale lexicon.

Approach chosen over alternatives:
- Phonetisaurus (g2p-no): requires OpenFst C++ libs, hard to install
- eSpeak-ng: not available on this system, external binary dependency
- epitran: no Norwegian language map included
- Rule-based: zero dependencies, covers ~85-90% of regular Norwegian words

Limitations:
- No tonelag prediction (requires morphological knowledge)
- Stress defaults to first syllable (correct for most native words)
- Loanwords and irregular spellings will have errors
- Vowel length heuristic (long before single consonant, short before cluster)
"""

from typing import Optional

VOWELS_ORTH = set("aeiouyæøå")


def _is_vowel_char(ch: str) -> bool:
    return ch.lower() in VOWELS_ORTH


def _count_following_consonants(word: str, pos: int) -> int:
    """Count consonant characters following position pos."""
    count = 0
    for i in range(pos + 1, len(word)):
        if _is_vowel_char(word[i]):
            break
        count += 1
    return count


def _is_long_vowel_context(word: str, vowel_pos: int) -> bool:
    """Heuristic: vowel is long before 0-1 consonants, short before clusters."""
    remaining = word[vowel_pos + 1:]

    # Short before double consonant
    if len(remaining) >= 2 and remaining[0] == remaining[1] and not _is_vowel_char(remaining[0]):
        return False

    # Count consonants until next vowel or end
    n_cons = _count_following_consonants(word, vowel_pos)

    # Special: nd, ng at end = short vowel (land, sang)
    if n_cons == 2 and remaining[:2] in ("nd", "ng", "nk"):
        return False

    # Special: vowel before rn, rd, rl, rs, rt = long (barn, gård)
    if n_cons == 2 and remaining[:2] in ("rn", "rd", "rl", "rs", "rt"):
        return True

    # Long if followed by 0 or 1 consonant
    if n_cons <= 1:
        return True

    return False


def _is_final_schwa_e(word: str, pos: int) -> bool:
    """Check if 'e' at position pos is an unstressed final schwa.

    Covers: -e, -en, -er, -ene, -ere, -est, -et, -ene, -else, -ert, etc.
    """
    rest = word[pos:]
    if rest in ("e", "en", "er", "et", "ene", "ere", "est", "ert", "else",
                "ene", "erer", "erne", "enes", "eres", "erte"):
        # Only if there's a preceding vowel (not for monosyllables like "de")
        preceding = word[:pos]
        return any(_is_vowel_char(c) for c in preceding)
    return False


def _is_silent_d(word: str, pos: int) -> bool:
    """Check if 'd' is silent. Silent in: -ld, -nd at word end."""
    if pos == len(word) - 1:  # final d
        if pos > 0 and word[pos - 1] in ("l", "n"):
            return True
    return False


def _is_silent_g(word: str, pos: int) -> bool:
    """Check if 'g' is silent in -ig ending."""
    if pos == len(word) - 1 and pos > 0 and word[pos - 1] == "i":
        return True
    # -lig, -ig endings
    rest = word[pos:]
    if rest == "g" and pos >= 1 and word[pos - 1] == "i":
        return True
    return False


def transkriber(word: str) -> list[str]:
    """Convert a Norwegian word to a list of IPA phonemes.

    This is a rule-based approximation. Returns a flat list of IPA phoneme
    strings (no syllable boundaries or stress marks).
    """
    w = word.lower()
    phonemes = []
    i = 0
    n = len(w)

    while i < n:
        # --- Multi-character rules (longest match first) ---

        # 3-char
        if i + 3 <= n:
            tri = w[i:i + 3]
            if tri == "skj":
                phonemes.append("ʃ")
                i += 3
                continue
            # sk before i, y, ei, øy → ʃ (ski, sky, skje already covered by skj)
            if tri[:2] == "sk" and tri[2] in ("i", "y"):
                phonemes.append("ʃ")
                i += 2  # consume sk, leave the vowel
                continue

        # 2-char
        if i + 2 <= n:
            di = w[i:i + 2]

            # Retroflex assimilation (East Norwegian)
            if di == "rd":
                phonemes.append("ɖ")
                i += 2
                continue
            if di == "rl":
                phonemes.append("ɭ")
                i += 2
                continue
            if di == "rn":
                phonemes.append("ɳ")
                i += 2
                continue
            if di == "rs":
                phonemes.append("ʂ")
                i += 2
                continue
            if di == "rt":
                phonemes.append("ʈ")
                i += 2
                continue

            # Palatal onsets
            if di == "sj":
                phonemes.append("ʃ")
                i += 2
                continue
            if di == "kj":
                phonemes.append("ç")
                i += 2
                continue
            if di == "hj":
                phonemes.append("j")
                i += 2
                continue
            if di == "hv":
                phonemes.append("v")
                i += 2
                continue
            if di == "gj":
                phonemes.append("j")
                i += 2
                continue

            # tj: keep as t+j (not ç) — "tjue" = tjʉːə
            if di == "tj":
                phonemes.append("t")
                phonemes.append("j")
                i += 2
                continue

            # Nasal clusters
            if di == "ng":
                # Check it's not n+g at morpheme boundary: hard to detect
                # Default: ng → ŋ
                phonemes.append("ŋ")
                i += 2
                continue
            if di == "nk":
                phonemes.append("ŋ")
                phonemes.append("k")
                i += 2
                continue

            # Diphthongs
            if di == "ei":
                phonemes.append("æ͡ɪ")
                i += 2
                continue
            if di == "øy":
                phonemes.append("œ͡ʏ")
                i += 2
                continue
            if di == "au":
                phonemes.append("æ͡ʉ")
                i += 2
                continue

            # Double consonants → single phoneme
            if di[0] == di[1] and di[0] not in VOWELS_ORTH:
                if di[0] in CONSONANT_MAP:
                    phonemes.append(CONSONANT_MAP[di[0]])
                    i += 2
                    continue

        # --- Single character rules ---
        ch = w[i]

        # Vowels
        if ch in VOWEL_MAP:
            # Special: final unstressed -e → schwa
            if ch == "e" and _is_final_schwa_e(w, i):
                phonemes.append("ə")
                i += 1
                continue

            # Special: e before rt, rd, rn, rl, rs → æ (hjerte, gjerde)
            if ch == "e" and i + 2 <= n and w[i + 1:i + 3] in ("rt", "rd", "rn", "rl", "rs"):
                phonemes.append("æ")
                i += 1
                continue

            # Special: o has complex behavior in Norwegian
            if ch == "o":
                # o before m at end → ɔ (som, gjennom, from)
                if i + 1 < n and w[i + 1:] in ("m", "mm"):
                    phonemes.append("ɔ")
                    i += 1
                    continue
                # short o before retroflex clusters → ʊ (skjorte, fort, ord)
                if i + 2 <= n and w[i + 1:i + 3] in ("rt", "rd", "rn", "rl", "rs"):
                    phonemes.append("ʊ")
                    i += 1
                    continue
                is_long = _is_long_vowel_context(w, i)
                if is_long:
                    phonemes.append("uː")
                else:
                    # Short o: ʊ in unstressed (pro-, for-, o.l.),
                    # but ɔ when stressed (kort, nord)
                    # Heuristic: first syllable short o before cluster = ʊ if
                    # there's another vowel later (unstressed prefix pattern)
                    remaining_has_vowel = any(
                        _is_vowel_char(w[j]) for j in range(i + 1, n)
                    )
                    if remaining_has_vowel and i < n // 2:
                        phonemes.append("ʊ")
                    else:
                        phonemes.append("ɔ")
                i += 1
                continue

            short, long = VOWEL_MAP[ch]
            if _is_long_vowel_context(w, i):
                phonemes.append(long)
            else:
                phonemes.append(short)
            i += 1
            continue

        # Silent d
        if ch == "d" and _is_silent_d(w, i):
            i += 1
            continue

        # Silent g in -ig
        if ch == "g" and _is_silent_g(w, i):
            i += 1
            continue

        # Consonants
        if ch in CONSONANT_MAP:
            phonemes.append(CONSONANT_MAP[ch])
            i += 1
            continue

        # Unknown character — skip
        i += 1

    return phonemes


VOWEL_MAP = {
    # char: (short, long)
    "a": ("ɑ", "ɑː"),
    "e": ("ɛ", "eː"),
    "i": ("ɪ", "iː"),
    "o": ("ɔ", "uː"),
    "u": ("ʉ", "ʉː"),
    "y": ("ʏ", "yː"),
    "æ": ("æ", "æː"),
    "ø": ("œ", "øː"),
    "å": ("ɔ", "oː"),
}

CONSONANT_MAP = {
    "b": "b",
    "c": "k",
    "d": "d",
    "f": "f",
    "g": "g",
    "h": "h",
    "j": "j",
    "k": "k",
    "l": "l",
    "m": "m",
    "n": "n",
    "p": "p",
    "q": "k",
    "r": "r",
    "s": "s",
    "t": "t",
    "v": "v",
    "w": "v",
    "x": "ks",
    "z": "s",
}


def transkriber_ipa(word: str) -> str:
    """Convert a Norwegian word to an IPA string (no stress/tonelag)."""
    return "".join(transkriber(word))


def transkriber_med_stavelser(word: str) -> dict:
    """Convert a word to structured phonetic data matching the lexicon format.

    Returns a dict with keys: fonemer, stress, tonelag, stavelser, ipa_ren, g2p.
    The g2p flag is always True to mark this as machine-generated.
    """
    phonemes = transkriber(word)
    syllables = _syllabify(phonemes)

    # Default stress: first syllable gets primary stress
    stress = [0] * len(syllables)
    if syllables:
        stress[0] = 1

    ipa_ren = ".".join("".join(syl) for syl in syllables)

    return {
        "fonemer": syllables,
        "stress": stress,
        "tonelag": None,  # Rule-based G2P cannot predict tonelag
        "stavelser": len(syllables),
        "ipa_ren": ipa_ren,
        "g2p": True,
    }


# IPA vowels for syllabification
_IPA_VOWELS = set("ɑɛɪɔʊʉəæœøʏeiouya")


def _is_ipa_vowel(phoneme: str) -> bool:
    """Check if an IPA phoneme is a vowel."""
    base = phoneme.replace("ː", "")
    if "͡" in base:
        base = base.split("͡")[0]
    return len(base) == 1 and base in _IPA_VOWELS


def _syllabify(phonemes: list) -> list:
    """Split a flat phoneme list into syllables.

    Uses the maximal onset principle: consonants between vowels are assigned
    to the following syllable where possible.
    """
    if not phonemes:
        return []

    # Find vowel positions
    vowel_positions = [i for i, ph in enumerate(phonemes) if _is_ipa_vowel(ph)]

    if not vowel_positions:
        return [phonemes[:]]

    syllables = []
    prev_end = 0

    for vi in range(1, len(vowel_positions)):
        prev_vpos = vowel_positions[vi - 1]
        curr_vpos = vowel_positions[vi]

        cons_start = prev_vpos + 1
        n_cons = curr_vpos - cons_start

        if n_cons <= 1:
            split_at = cons_start
        else:
            # Keep first consonant with previous syllable, rest with next
            split_at = cons_start + 1

        syllables.append(phonemes[prev_end:split_at])
        prev_end = split_at

    # Last syllable
    syllables.append(phonemes[prev_end:])

    return syllables
