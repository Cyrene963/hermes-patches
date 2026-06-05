"""Auto-Store Heuristic for Memory Detection

Detects when user messages contain information worth automatically storing
in long-term memory, without requiring explicit memory() tool calls.

This module provides heuristic detection based on linguistic patterns that
signal the user wants the agent to remember something.
"""

import re
from typing import List, Tuple, Optional


# Core detection patterns
# Format: (pattern, weight, description)
# Weight: 1.0 = strong signal, 0.5 = moderate, 0.3 = weak
# Note: \b doesn't work with Chinese characters, so we use lookahead/lookbehind or omit \b for CJK
DETECTION_PATTERNS: List[Tuple[str, float, str]] = [
    # Explicit storage instructions (strong signals)
    (r'(记住|记下|记一下|记录|保存)', 1.0, "Explicit Chinese: remember/record"),
    (r'\b(remember|don\'t forget)\b', 1.0, "Explicit: remember/don't forget"),
    (r'(记得|别忘了)', 1.0, "Chinese: remember/don't forget"),
    (r'\b(note that|make a note|keep in mind|bear in mind)\b', 1.0, "Explicit: note taking"),
    (r'\b(save this|store this)\b', 1.0, "Explicit: save/store"),
    (r'记下这个', 1.0, "Chinese: save this"),

    # Preference declarations (strong signals)
    (r'(我喜欢|我爱|我偏好)', 0.9, "User preference positive (Chinese)"),
    (r'\b(I like|I love|I prefer)\b', 0.9, "User preference positive (English)"),
    (r'(我不喜欢|我讨厌|我不爱)', 0.9, "User preference negative (Chinese)"),
    (r'\b(I don\'t like|I hate|I dislike)\b', 0.9, "User preference negative (English)"),
    (r'(我倾向于|我习惯)', 0.8, "User habit/tendency (Chinese)"),
    (r'\b(I tend to|I usually|I typically)\b', 0.8, "User habit/tendency (English)"),

    # Corrections (strong signals - user is fixing wrong information)
    (r'(不对|不是|错了)', 0.9, "Correction signal (Chinese)"),
    (r'\b(actually|correction|incorrect)\b', 0.9, "Correction signal (English)"),
    (r'(应该是|其实是|正确的是)', 0.9, "Correction with correct info (Chinese)"),
    (r'\b(it should be|it\'s actually)\b', 0.9, "Correction with correct info (English)"),
    (r'(我说过|我之前说的是)', 0.8, "Clarification of past statement (Chinese)"),
    (r'\b(I said|I meant)\b', 0.8, "Clarification of past statement (English)"),

    # Environmental/biographical information (moderate signals)
    (r'(我的项目|我在做)', 0.7, "Project information (Chinese)"),
    (r'\b(my project|I\'m working on)\b', 0.7, "Project information (English)"),
    (r'(我用的是|我使用)', 0.7, "Tool/technology preference (Chinese)"),
    (r'\b(I use|I\'m using)\b', 0.7, "Tool/technology preference (English)"),
    (r'(我住在|我来自)', 0.8, "Location information (Chinese)"),
    (r'\b(I live in|I\'m from)\b', 0.8, "Location information (English)"),
    (r'我是[一个]?[一-鿿]+', 0.7, "Identity/profession (Chinese)"),
    (r'\b(I am|I work as)\b', 0.7, "Identity/profession (English)"),
    (r'我的[一-鿿]+[在是]', 0.6, "Possessive statements (Chinese: my X is/at)"),
    (r'\bmy\s+\w+\s+is\b', 0.6, "Possessive statements (English: my X is)"),

    # Explicit negations/boundaries (moderate signals)
    (r'(不要|别|不许)', 0.8, "Explicit prohibition (Chinese)"),
    (r'\b(don\'t|never|avoid)\s+\w+', 0.8, "Explicit prohibition (English)"),
    (r'(总是|一定要|必须)', 0.7, "Explicit requirement (Chinese)"),
    (r'\b(always|must)\s+\w+', 0.7, "Explicit requirement (English)"),

    # Contact/identity info (strong signals)
    (r'(我的邮箱|我的电话)', 0.9, "Contact information (Chinese)"),
    (r'\b(my email|my phone)\b', 0.9, "Contact information (English)"),
    (r'(我的名字叫|我叫)', 0.9, "Name introduction (Chinese)"),
    (r'\b(my name is|call me)\b', 0.9, "Name introduction (English)"),

    # Time-sensitive events (moderate signals)
    (r'(我的生日|纪念日)', 0.8, "Important dates (Chinese)"),
    (r'\b(my birthday|anniversary)\b', 0.8, "Important dates (English)"),
    (r'(提醒我|别让我忘了)', 1.0, "Explicit reminder request (Chinese)"),
    (r'\b(remind me)\b', 1.0, "Explicit reminder request (English)"),
]


# Negative patterns (things that look like memory-worthy but aren't)
# These reduce confidence when present
NEGATIVE_PATTERNS: List[Tuple[str, float, str]] = [
    (r'(假设|假如)', -0.5, "Hypothetical scenario (Chinese)"),
    (r'\b(if|suppose|imagine|what if)\b', -0.5, "Hypothetical scenario (English)"),
    (r'(例如|比如|比方说)', -0.5, "Example/illustration (Chinese)"),
    (r'\b(for example|e\.g\.)\b', -0.5, "Example/illustration (English)"),
    (r'(可能|也许|大概)', -0.2, "Uncertainty (Chinese)"),
    (r'\b(maybe|perhaps|might)\b', -0.2, "Uncertainty (English)"),
    (r'(能不能|可以吗)', -0.3, "Question/request (Chinese)"),
    (r'\b(could you|can you|would you)\b', -0.3, "Question/request (English)"),
    (r'^(what|how|why|when|where)', -0.4, "Question at start (English)"),
    (r'^(谁|什么|怎么|为什么|哪里)', -0.4, "Question at start (Chinese)"),
]


# Additional heuristics (contextual signals)
def has_colon_statement(text: str) -> bool:
    """Detect 'X: Y' pattern (often used for specifying attributes)"""
    return bool(re.search(r'\w+[:：]\s*\w+', text))


def has_url_or_path(text: str) -> bool:
    """Detect URLs or file paths (often project/resource references)"""
    return bool(re.search(r'(https?://|/[a-z]+/|~/|[A-Z]:\\)', text))


def has_code_block(text: str) -> bool:
    """Detect code blocks (might contain config/preference info)"""
    return '```' in text or bool(re.search(r'`[^`]+`', text))


def is_short_acknowledgment(text: str) -> bool:
    """Detect short acknowledgments/agreements (not memory-worthy)"""
    text_clean = text.strip().lower()
    short_acks = {'ok', 'okay', 'thanks', 'thank you', '好的', '谢谢', 'yes', 'no',
                  'sure', 'got it', '明白', '了解', 'cool', 'great'}
    # Only check exact matches for common acknowledgments
    # Don't use word count as it fails with CJK (Chinese characters don't split by space)
    return text_clean in short_acks


def detect_auto_store(user_message: str, *, threshold: float = 0.5) -> Tuple[bool, float, List[str]]:
    """Detect if a user message contains information worth auto-storing.

    Args:
        user_message: The user's message text
        threshold: Minimum confidence score to trigger storage (0.0-1.0)

    Returns:
        Tuple of (should_store, confidence_score, matched_patterns)
        - should_store: True if confidence >= threshold
        - confidence_score: Cumulative score from matched patterns
        - matched_patterns: List of human-readable pattern descriptions that matched

    Examples:
        >>> detect_auto_store("记住我喜欢用 PostgreSQL")
        (True, 1.9, ["Explicit Chinese: remember/record", "User preference positive"])

        >>> detect_auto_store("我的项目在 ~/code/hermes-agent")
        (True, 0.7, ["Project information"])

        >>> detect_auto_store("How does this work?")
        (False, -0.4, [])
    """
    if not user_message or not user_message.strip():
        return (False, 0.0, [])

    # Quick exit for short acknowledgments
    if is_short_acknowledgment(user_message):
        return (False, 0.0, [])

    score = 0.0
    matched = []

    # Check positive patterns
    for pattern, weight, description in DETECTION_PATTERNS:
        if re.search(pattern, user_message, re.IGNORECASE):
            score += weight
            matched.append(description)

    # Check negative patterns
    for pattern, weight, description in NEGATIVE_PATTERNS:
        if re.search(pattern, user_message, re.IGNORECASE):
            score += weight  # weight is already negative
            matched.append(f"[NEGATIVE] {description}")

    # Apply contextual heuristics
    if has_colon_statement(user_message):
        score += 0.3
        matched.append("[CONTEXT] Colon statement (X: Y)")

    if has_url_or_path(user_message):
        score += 0.2
        matched.append("[CONTEXT] Contains URL/path")

    if has_code_block(user_message):
        score += 0.2
        matched.append("[CONTEXT] Contains code block")

    # Normalize score to 0-1 range (practical max is ~3.0, min is ~-1.0)
    confidence = max(0.0, min(1.0, score / 3.0 + 0.33))

    return (score >= threshold, confidence, matched)


# Convenience functions for direct bool checks

def should_auto_store(user_message: str, *, threshold: float = 0.5) -> bool:
    """Simple boolean check: should this message be auto-stored?

    Args:
        user_message: The user's message text
        threshold: Minimum confidence score to trigger storage

    Returns:
        True if message should be auto-stored, False otherwise
    """
    should_store, _, _ = detect_auto_store(user_message, threshold=threshold)
    return should_store


def get_store_confidence(user_message: str) -> float:
    """Get confidence score for auto-storage decision.

    Args:
        user_message: The user's message text

    Returns:
        Confidence score (0.0-1.0)
    """
    _, confidence, _ = detect_auto_store(user_message)
    return confidence


# Test cases (for validation)
def _run_tests():
    """Run built-in test cases to validate heuristic behavior."""
    test_cases = [
        # (message, expected_result, description)
        ("记住我喜欢用 PostgreSQL", True, "Chinese explicit + preference"),
        ("Remember I prefer dark mode", True, "English explicit + preference"),
        ("我的项目在 ~/code/hermes-agent", True, "Project location"),
        ("不对，应该是 port 8080", True, "Correction"),
        ("我不喜欢 MySQL", True, "Negative preference"),
        ("我是一个软件工程师", True, "Identity"),
        ("提醒我明天开会", True, "Reminder request"),
        ("How does this work?", False, "Question without memory signal"),
        ("Thanks!", False, "Short acknowledgment"),
        ("假设我喜欢 Redis", False, "Hypothetical scenario"),
        ("Can you help me?", False, "Request question"),
        ("我用的是 Vim 编辑器", True, "Tool preference"),
        ("别忘了我住在北京", True, "Location + explicit"),
        ("For example, I like Python", False, "Example with negative pattern"),
        ("我的邮箱是 user@example.com", True, "Contact info"),
    ]

    passed = 0
    failed = 0

    print("Running auto-store heuristic tests...\n")
    for message, expected, description in test_cases:
        result, confidence, patterns = detect_auto_store(message)
        status = "✓" if result == expected else "✗"

        if result == expected:
            passed += 1
        else:
            failed += 1

        print(f"{status} [{confidence:.2f}] {description}")
        print(f"   Message: \"{message}\"")
        print(f"   Expected: {expected}, Got: {result}")
        if patterns:
            print(f"   Matched: {', '.join(patterns[:3])}")
        print()

    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    # Run tests when executed directly
    import sys
    success = _run_tests()
    sys.exit(0 if success else 1)
