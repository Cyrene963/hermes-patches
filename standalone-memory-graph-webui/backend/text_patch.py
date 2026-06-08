"""
Text normalization and fuzzy patch matching for memory content updates.

When the LLM reads memory content and re-emits it as old_string, subtle
character-level differences creep in (curly vs straight quotes, dash
variants, trailing whitespace, consecutive space collapse).  These helpers
let update_memory fall back to a normalized comparison when the exact match
fails, while keeping a position map so the replacement targets the correct
range in the original content.
"""

import re
import unicodedata
from typing import List, Optional, Tuple

NORM_CHAR_MAP = str.maketrans(
    {
        "\u201c": '"',
        "\u201d": '"',
        "\u00ab": '"',
        "\u00bb": '"',
        "\uff02": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u00b4": "'",
        "\uff07": "'",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\uff0d": "-",
    }
)


def normalize_with_positions(
    text: str,
    *,
    preserve_first_line_indent: bool = True,
) -> Tuple[str, List[int]]:
    """
    Normalize *text* for matching and build a position map.

    Returns ``(normalized, pos_map)`` where ``pos_map[i]`` is the index in
    the **NFC-normalized** input that produced the *i*-th character of the
    normalized output.

    Steps applied in order:

    1. Unicode NFC (compose decomposed sequences)
    2. Quote / dash variant → ASCII equivalent  (1-to-1, no position shift)
    3. Trailing ``[ \\t]`` per line stripped
    4. Consecutive spaces collapsed to one (leading indentation protected)

    When *preserve_first_line_indent* is ``False``, the very first line's
    leading whitespace is treated as ordinary inline spacing (collapsed),
    because the caller is normalizing a snippet (``old_string``) whose first
    line may start mid-line rather than at a true line beginning.  Lines 2+
    always preserve their leading indentation regardless of this flag.
    """
    text = unicodedata.normalize("NFC", text)
    substituted = text.translate(NORM_CHAR_MAP)

    out: List[str] = []
    pos_map: List[int] = []
    lines = substituted.split("\n")
    offset = 0

    for line_idx, original_line in enumerate(lines):
        if line_idx > 0:
            out.append("\n")
            pos_map.append(offset - 1)

        # Handle Windows CRLF: remove \r from the line we process,
        # but keep it in the original length calculation for offset.
        line = original_line
        if line.endswith("\r"):
            line = line[:-1]

        content_end = len(line.rstrip(" \t"))

        # Protect leading indentation from space-collapsing — except on the
        # first line when preserve_first_line_indent is False (snippet mode).
        protect_indent = (line_idx > 0) or preserve_first_line_indent
        leading_ws = 0
        if protect_indent:
            for ci in range(content_end):
                if line[ci] in (" ", "\t"):
                    leading_ws += 1
                else:
                    break

        prev_space = False
        for ci in range(content_end):
            ch = line[ci]

            if ci < leading_ws:
                out.append(ch)
                pos_map.append(offset + ci)
                continue

            if ch == " ":
                if prev_space:
                    continue
                prev_space = True
            else:
                prev_space = False

            out.append(ch)
            pos_map.append(offset + ci)

        offset += len(original_line) + 1

    return "".join(out), pos_map


def find_valid_matches(
    norm_content: str,
    candidate: str,
    *,
    indent_collapsed: bool,
) -> List[int]:
    """
    Find all positions where *candidate* occurs in *norm_content*, rejecting
    hits that would **slide into the middle of another line's indentation**.

    This guard exists because a space/tab at the start of *candidate* could
    coincidentally align with part of a deeper indentation block in the
    content, producing a match that silently corrupts whitespace structure.

    The guard only fires when the hit falls inside a pure-indentation prefix
    (every character between the line start and the hit position is a space or
    tab).  If ANY non-whitespace character precedes the hit on the same line,
    the space is ordinary inline content and the hit is always accepted.

    *indent_collapsed*: whether the candidate's first line had its leading
    whitespace collapsed (i.e. ``preserve_first_line_indent=False`` was used
    during normalization).  This affects how strictly we reject indent-region
    hits:

    - ``False`` (indent preserved): the candidate's leading whitespace was
      kept verbatim, so a hit inside an indentation region is only invalid if
      it doesn't start at the line's very beginning (shorter indent sliding
      into deeper indent).
    - ``True`` (indent collapsed): the candidate's leading whitespace was
      already folded, so ANY hit that falls inside an indentation region is
      suspect — we can't trust the whitespace count to anchor it.

    Returns a list of valid match positions (indices into *norm_content*).
    """
    first_line = candidate.split("\n", 1)[0]
    could_slide_into_indent = (
        bool(first_line) and first_line[0] in (" ", "\t")
    )

    hits: List[int] = []
    start = 0
    while True:
        pos = norm_content.find(candidate, start)
        if pos == -1:
            break

        valid = True
        if could_slide_into_indent:
            line_start = norm_content.rfind("\n", 0, pos)
            line_start = line_start + 1 if line_start != -1 else 0
            prefix = norm_content[line_start:pos]
            hit_is_in_indent_region = (
                prefix == "" or all(c in (" ", "\t") for c in prefix)
            )

            if hit_is_in_indent_region:
                if indent_collapsed:
                    if prefix != "":
                        valid = False
                else:
                    if pos != line_start:
                        valid = False

        if valid:
            hits.append(pos)
        start = pos + 1

    return hits


def try_normalized_patch(
    content: str, old_string: str, new_string: str
) -> Optional[str]:
    """
    Attempt to locate *old_string* inside *content* via normalized comparison.

    Returns the patched content when **exactly one** valid normalized match
    exists, or ``None`` when no match is found or the match is ambiguous.
    """
    content = unicodedata.normalize("NFC", content)
    norm_content, pos_map = normalize_with_positions(content)

    if not pos_map:
        return None

    all_results: List[Tuple[int, str]] = []
    for preserve in (True, False):
        candidate = normalize_with_positions(
            old_string, preserve_first_line_indent=preserve
        )[0]
        if not candidate:
            continue
        valid_hits = find_valid_matches(
            norm_content, candidate, indent_collapsed=(not preserve)
        )
        for hit in valid_hits:
            if not any(h == hit and len(c) == len(candidate) for h, c in all_results):
                all_results.append((hit, candidate))

    if len(all_results) != 1:
        return None

    idx, norm_old = all_results[0]

    orig_start = pos_map[idx]
    match_end = idx + len(norm_old)
    if match_end < len(pos_map):
        orig_end = pos_map[match_end]
    else:
        orig_end = pos_map[-1] + 1

    if (orig_start < len(content) and content[orig_start] == '\n'
            and orig_start > 0 and content[orig_start - 1] == '\r'):
        orig_start -= 1

    if (orig_end < len(content) and content[orig_end] == '\n'
            and orig_end > 0 and content[orig_end - 1] == '\r'):
        orig_end -= 1

    if '\n' in new_string:
        clean = new_string.replace('\r\n', '\n').replace('\r', '\n')
        if '\r\n' in content:
            new_string = clean.replace('\n', '\r\n')
        else:
            new_string = clean

    return content[:orig_start] + new_string + content[orig_end:]


UNESCAPED_NEWLINE_RE = re.compile(r"(?<!\\)\\n")


def normalize_literal_newlines(text: str) -> str:
    """Convert literal ``\\n`` sequences to real newlines.

    Only touches unescaped ``\\n`` (i.e. skips ``\\\\n``).
    This is intentionally a dumb converter with no heuristic — the caller
    is responsible for deciding *when* to apply it.
    """
    return UNESCAPED_NEWLINE_RE.sub("\n", text)


def format_normalization_preview(text: str, limit: int = 160) -> str:
    """Render text in a single-line preview for system notices."""
    preview = repr(text)[1:-1]
    if len(preview) > limit:
        preview = preview[: limit - 3] + "..."
    return preview
