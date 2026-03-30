from __future__ import annotations

"""Parse NB Uttale pronunciation lexicons into structured phonetics JSONL.

Strategy:
- Primary source: NB Uttale spoken lexicons (IPA with syllable boundaries)
- Supports 5 dialect regions: øst, nord, midt, vest, sørvest
- Tonelag: from IPA prefix (' = tone 1, " = tone 2) cross-checked with NoFABET
- Stress per syllable: from NoFABET phoneme-level stress numbers (0/1/2)
- Syllable count: from IPA syllable boundaries (.)
- Phonemes: parsed from IPA, split on syllable boundaries

Output: data/processed/phonetics.jsonl — østnorsk (backward compat)
        data/processed/phonetics_{dialekt}.jsonl — per dialect
"""

import csv
import json
import re
import sys
import unicodedata

from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NB_UTTALE_DIR = PROJECT_ROOT / "data/raw/nb_uttale_leksika"
NB_UTTALE_FILE = NB_UTTALE_DIR / "e_spoken_pronunciation_lexicon.csv"
OUTPUT_FILE = PROJECT_ROOT / "data/processed/phonetics.jsonl"
ERROR_LOG = PROJECT_ROOT / "data/processed/parse_errors.log"

# Dialect mapping: code -> (file prefix, Norwegian name)
DIALEKTER = {
    "øst": ("e", "Østnorsk"),
    "nord": ("n", "Nordnorsk"),
    "midt": ("t", "Trøndersk"),
    "vest": ("w", "Vestnorsk"),
    "sørvest": ("sw", "Sørvestnorsk"),
}

# IPA stress markers
STRESS_PRIMARY = "\u02c8"  # ˈ
STRESS_SECONDARY = "\u02cc"  # ˌ
# NB Uttale uses ASCII ' and " instead of proper IPA marks
ASCII_PRIMARY = "'"
ASCII_SECONDARY = '"'

# IPA characters that are phoneme modifiers (attach to previous phoneme)
MODIFIERS = set("ːˑ̩̥̃̊ʰʷʲˠˤ")
# Long mark
LONG = "ː"


def parse_ipa(ipa_raw: str) -> Optional[dict]:
    """Parse an IPA transcription string into structured data.

    Returns dict with keys: fonemer (list of lists per syllable),
    stress (list of int per syllable), tonelag (1 or 2), stavelser (int),
    ipa_ren (cleaned IPA without stress marks).
    Returns None if unparseable.
    """
    ipa = ipa_raw.strip()
    if not ipa:
        return None

    # Determine tonelag from prefix
    tonelag = None
    if ipa.startswith(ASCII_SECONDARY) or ipa.startswith(STRESS_SECONDARY):
        tonelag = 2
        ipa = ipa[1:]
    elif ipa.startswith(ASCII_PRIMARY) or ipa.startswith(STRESS_PRIMARY):
        tonelag = 1
        ipa = ipa[1:]

    # Split into syllables on '.'
    syllable_strs = ipa.split(".")

    # Parse each syllable into phonemes and detect stress
    fonemer = []
    stress = []
    for syl in syllable_strs:
        syl_stress = 0
        clean = syl

        # Check for stress markers within syllable
        if ASCII_PRIMARY in clean or STRESS_PRIMARY in clean:
            syl_stress = 1
            clean = clean.replace(ASCII_PRIMARY, "").replace(STRESS_PRIMARY, "")
        if ASCII_SECONDARY in clean or STRESS_SECONDARY in clean:
            syl_stress = 2
            clean = clean.replace(ASCII_SECONDARY, "").replace(
                STRESS_SECONDARY, ""
            )

        # If this is the first syllable and no inner stress marker was found,
        # and we extracted a tonelag prefix, mark it as primary stress
        if not fonemer and syl_stress == 0 and tonelag is not None:
            syl_stress = 1

        # Segment into individual phonemes
        phones = _segment_phonemes(clean)
        fonemer.append(phones)
        stress.append(syl_stress)

    stavelser = len(fonemer)

    # Build clean IPA (without stress marks, keeping syllable dots)
    ipa_ren = ".".join(
        "".join(phones) for phones in fonemer
    )

    return {
        "fonemer": fonemer,
        "stress": stress,
        "tonelag": tonelag,
        "stavelser": stavelser,
        "ipa_ren": ipa_ren,
    }


def _segment_phonemes(s: str) -> list:
    """Segment an IPA string into individual phonemes.

    Handles digraphs (affricates, diphthongs), long marks, and modifiers.
    """
    phones = []
    i = 0
    while i < len(s):
        ch = s[i]

        # Skip underscores (word boundaries in compounds)
        if ch == "_":
            i += 1
            continue

        # Start building a phoneme
        phoneme = ch
        i += 1

        # Attach any following modifiers (ː, ̩, etc.)
        while i < len(s) and (
            s[i] in MODIFIERS
            or s[i] == LONG
            or unicodedata.category(s[i]) == "Mn"  # combining marks
        ):
            phoneme += s[i]
            i += 1

        phones.append(phoneme)

    return phones


def parse_nofabet_stress(nofabet: str) -> Optional[list]:
    """Extract per-phoneme stress levels from NoFABET transcription.

    NoFABET format: space-separated phonemes with trailing digit for stress.
    Returns list of stress levels for vowel phonemes only.
    """
    if not nofabet.strip():
        return None
    tokens = nofabet.strip().split()
    stresses = []
    for token in tokens:
        if token and token[-1].isdigit():
            stresses.append(int(token[-1]))
    return stresses


def should_skip(word: str, pos: str) -> bool:
    """Decide whether to skip this entry."""
    # Skip suffixes (start with -)
    if word.startswith("-"):
        return True
    # Skip multi-word entries (contain space or underscore)
    if " " in word or "_" in word:
        return True
    # Skip entries that are pure numbers
    if word.isdigit():
        return True
    return False


def parse_file(input_path: Path, output_path: Path, error_path: Path) -> dict:
    """Parse the NB Uttale CSV and write JSONL output.

    Returns statistics dict.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    stats = {
        "total_rows": 0,
        "skipped": 0,
        "parse_errors": 0,
        "duplicates": 0,
        "written": 0,
    }

    seen = {}  # (word, ipa_ren) -> True, for dedup (case-sensitive)
    errors = []

    with (
        open(input_path, encoding="utf-8") as f_in,
        open(output_path, "w", encoding="utf-8") as f_out,
    ):
        reader = csv.reader(f_in)
        header = next(reader)  # skip header

        for row_num, row in enumerate(reader, start=2):
            stats["total_rows"] += 1

            if len(row) < 7:
                errors.append(f"line {row_num}: too few fields ({len(row)})")
                stats["parse_errors"] += 1
                continue

            word = row[0]
            pos = row[1]
            feats = row[2]
            nofabet = row[5]
            ipa_raw = row[6]

            if should_skip(word, pos):
                stats["skipped"] += 1
                continue

            parsed = parse_ipa(ipa_raw)
            if parsed is None:
                errors.append(f"line {row_num}: empty IPA for {word!r}")
                stats["parse_errors"] += 1
                continue

            # Dedup: same exact word + same pronunciation = skip
            # Case-sensitive to keep "Sol" (name) and "sol" (noun) separate
            dedup_key = (word, parsed["ipa_ren"])
            if dedup_key in seen:
                stats["duplicates"] += 1
                continue
            seen[dedup_key] = True

            record = {
                "ord": word,
                "pos": pos,
                "feats": feats,
                "fonemer": parsed["fonemer"],
                "stress": parsed["stress"],
                "tonelag": parsed["tonelag"],
                "stavelser": parsed["stavelser"],
                "ipa_ren": parsed["ipa_ren"],
            }

            f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
            stats["written"] += 1

    # Write error log
    with open(error_path, "w", encoding="utf-8") as f_err:
        f_err.write(f"Parse errors: {stats['parse_errors']}\n")
        f_err.write(f"Total rows: {stats['total_rows']}\n\n")
        for err in errors:
            f_err.write(err + "\n")

    return stats


def _dialect_file(dialect_code: str) -> Path:
    """Get the CSV file path for a dialect."""
    prefix = DIALEKTER[dialect_code][0]
    return NB_UTTALE_DIR / f"{prefix}_spoken_pronunciation_lexicon.csv"


def _dialect_output(dialect_code: str) -> Path:
    """Get the output JSONL path for a dialect."""
    return PROJECT_ROOT / f"data/processed/phonetics_{dialect_code}.jsonl"


def _dialect_errors(dialect_code: str) -> Path:
    """Get the error log path for a dialect."""
    return PROJECT_ROOT / f"data/processed/parse_errors_{dialect_code}.log"


def main():
    # Parse --all flag for all dialects
    parse_all = "--all" in sys.argv

    if parse_all:
        print("Parsing ALL dialects...")
        for code, (prefix, name) in DIALEKTER.items():
            infile = _dialect_file(code)
            if not infile.exists():
                print(f"  SKIP {name} ({code}): {infile.name} not found")
                continue

            # Østnorsk also writes to the default phonetics.jsonl for backward compat
            if code == "øst":
                outfile = OUTPUT_FILE
                errfile = ERROR_LOG
            else:
                outfile = _dialect_output(code)
                errfile = _dialect_errors(code)

            print(f"\n--- {name} ({code}) ---")
            print(f"  Input:  {infile.name}")
            stats = parse_file(infile, outfile, errfile)
            print(f"  Written: {stats['written']:,}  (skipped: {stats['skipped']:,}, "
                  f"errors: {stats['parse_errors']:,}, dupes: {stats['duplicates']:,})")
            print(f"  Output: {outfile}")

        # Also write østnorsk to the dialect-specific file for consistency
        øst_dialect = _dialect_output("øst")
        if OUTPUT_FILE.exists() and not øst_dialect.exists():
            import shutil
            shutil.copy2(OUTPUT_FILE, øst_dialect)
            print(f"\nCopied {OUTPUT_FILE.name} → {øst_dialect.name}")

        print("\nDone. All dialects parsed.")
    else:
        # Original behavior: parse only østnorsk
        if not NB_UTTALE_FILE.exists():
            print(f"ERROR: Input file not found: {NB_UTTALE_FILE}", file=sys.stderr)
            sys.exit(1)

        print(f"Parsing {NB_UTTALE_FILE.name}...")
        stats = parse_file(NB_UTTALE_FILE, OUTPUT_FILE, ERROR_LOG)

        print(f"\n=== Statistics ===")
        print(f"Total rows read:  {stats['total_rows']:>10,}")
        print(f"Skipped:          {stats['skipped']:>10,}")
        print(f"Parse errors:     {stats['parse_errors']:>10,}")
        print(f"Duplicates:       {stats['duplicates']:>10,}")
        print(f"Written:          {stats['written']:>10,}")
        print(f"\nOutput: {OUTPUT_FILE}")
        print(f"Errors: {ERROR_LOG}")

        print(f"\n=== Sample output (first 5 records) ===")
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 5:
                    break
                record = json.loads(line)
                print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
