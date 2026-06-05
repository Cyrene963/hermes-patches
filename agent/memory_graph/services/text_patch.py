"""Text normalization for LLM output drift.

Prevents duplicate content caused by smart quotes, trailing whitespace,
and inconsistent blank lines.
"""

import re
import unicodedata


def normalize_text(text: str) -> str:
    """4-step normalization for LLM output drift.

    1. Unicode NFC normalization
    2. Smart quote substitution (→ straight quotes)
    3. Trailing whitespace strip per line
    4. Collapse multiple blank lines
    """
    text = unicodedata.normalize("NFC", text)
    # Smart quotes → straight
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    # Em/en dash → hyphen (optional, comment out if not desired)
    # text = text.replace("\u2014", "-").replace("\u2013", "-")
    # Trailing whitespace per line
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    # Collapse 3+ blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
