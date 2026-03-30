from __future__ import annotations

"""Build word frequency list from Språkbanken NB 1-gram data.

Source: NB N-gram (sbr-12), 1.175 billion words from Norwegian newspapers.
URL: https://www.nb.no/sbfil/tekst/1gram_nob_f1_freq.zip
License: CC-ZERO

Input:  data/raw/1gram_nob_f1_freq.frk  (space-separated: FREQ WORD)
Output: data/processed/frequencies.jsonl  (JSON lines: {"ord": ..., "frekvens": ...})

Frequencies are normalized to per-million-words.
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_FILE = PROJECT_ROOT / "data/raw/1gram_nob_f1_freq.frk"
OUTPUT_FILE = PROJECT_ROOT / "data/processed/frequencies.jsonl"

# Skip tokens that are not real words
SKIP_PATTERNS = re.compile(
    r"^[<>]"          # XML-like tags (<s>, </s>)
    r"|^[\d.,;:!?\"\'\-–—/\\()@#$%^&*+={}[\]|~`]+$"  # pure punctuation/numbers
    r"|^\d"           # starts with digit
    r"|.*\d.*"        # contains digits (addresses, codes)
    r"|^.{1}$"        # single characters (except Norwegian words like "å", "i")
)

# Single-char words that ARE real Norwegian words
VALID_SINGLE = {"i", "å"}


def should_skip(word: str) -> bool:
    """Check if a token should be skipped."""
    if not word:
        return True
    if len(word) == 1 and word not in VALID_SINGLE:
        return True
    if word.startswith("<") or word.startswith(">"):
        return True
    # Pure punctuation
    if all(not c.isalpha() for c in word):
        return True
    # Contains digits
    if any(c.isdigit() for c in word):
        return True
    return False


def build_frequencies(input_path: Path, output_path: Path) -> dict:
    """Parse frequency file and write normalized frequencies."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    stats = {
        "lines_read": 0,
        "skipped": 0,
        "words_written": 0,
        "total_count": 0,
    }

    # First pass: read all valid words and their raw counts
    word_counts = {}
    total_tokens = 0

    with open(input_path, encoding="latin-1") as f:
        for line in f:
            stats["lines_read"] += 1
            line = line.strip()
            if not line:
                continue

            # Format: FREQ WORD (space-separated, first token is count)
            parts = line.split(" ", 1)
            if len(parts) != 2:
                stats["skipped"] += 1
                continue

            try:
                count = int(parts[0])
            except ValueError:
                stats["skipped"] += 1
                continue

            word = parts[1]

            if should_skip(word):
                stats["skipped"] += 1
                continue

            total_tokens += count

            # Merge case: accumulate both "Hus" and "hus" under "hus",
            # but keep original case if it's the only form
            lower = word.lower()
            word_counts[lower] = word_counts.get(lower, 0) + count

    stats["total_count"] = total_tokens

    # Normalize to frequency per million words
    per_million = total_tokens / 1_000_000

    # Write output sorted by frequency (descending)
    with open(output_path, "w", encoding="utf-8") as out:
        for word, count in sorted(word_counts.items(), key=lambda x: -x[1]):
            freq = count / per_million
            out.write(json.dumps(
                {"ord": word, "frekvens": round(freq, 4)},
                ensure_ascii=False,
            ) + "\n")
            stats["words_written"] += 1

    return stats


def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: Input not found: {INPUT_FILE}", file=sys.stderr)
        print("Download with: curl -L -o data/raw/1gram_nob_f1_freq.zip "
              "https://www.nb.no/sbfil/tekst/1gram_nob_f1_freq.zip")
        sys.exit(1)

    print(f"Building frequencies from {INPUT_FILE.name}...")
    stats = build_frequencies(INPUT_FILE, OUTPUT_FILE)

    print(f"\n=== Statistics ===")
    print(f"Lines read:        {stats['lines_read']:>12,}")
    print(f"Skipped:           {stats['skipped']:>12,}")
    print(f"Words written:     {stats['words_written']:>12,}")
    print(f"Total tokens:      {stats['total_count']:>12,}")
    print(f"\nOutput: {OUTPUT_FILE}")

    # Show top 20
    print(f"\n=== Top 20 words by frequency ===")
    with open(OUTPUT_FILE, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 20:
                break
            r = json.loads(line)
            print(f"  {r['ord']:20} {r['frekvens']:>10.2f} per million")


if __name__ == "__main__":
    main()
