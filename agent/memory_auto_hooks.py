"""Memory Auto-Hooks for Hermes Agent

Integration module that wires auto_store_heuristic into the conversation loop
and enhances system prompts to encourage proactive memory tool usage.

This module provides:
1. Post-turn hook for automatic memory storage detection
2. System prompt enhancements for memory search tools
3. Environment-based configuration (HERMES_AUTO_MEMORY)

Usage:
    # Enable via environment variable
    export HERMES_AUTO_MEMORY=true

    # In conversation_loop.py or agent initialization:
    from agent.memory_auto_hooks import should_enable_auto_memory, install_auto_memory_hooks

    if should_enable_auto_memory():
        install_auto_memory_hooks(agent)
"""

import logging
import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from agent.agent import Agent

logger = logging.getLogger(__name__)


def should_enable_auto_memory() -> bool:
    """Check if auto-memory features should be enabled.

    Reads from HERMES_AUTO_MEMORY environment variable.

    Returns:
        True if auto-memory should be enabled, False otherwise

    Examples:
        export HERMES_AUTO_MEMORY=true    # Enable
        export HERMES_AUTO_MEMORY=1       # Enable
        export HERMES_AUTO_MEMORY=false   # Disable
        export HERMES_AUTO_MEMORY=0       # Disable
        unset HERMES_AUTO_MEMORY          # Disable (default)
    """
    value = os.environ.get("HERMES_AUTO_MEMORY", "").strip().lower()
    return value in ("true", "1", "yes", "on", "enabled")


def get_memory_search_prompt_enhancement() -> str:
    """Generate system prompt enhancement for memory search tools.

    This text is injected into the system prompt to make the LLM more aware
    of when to use memory search tools proactively.

    Returns:
        Enhanced prompt text for memory tools
    """
    return """
## Memory Search Guidelines

When the user's message implies they expect you to recall information:
- **Automatically search memories** before answering
- Don't wait for explicit "search" or "look up" keywords
- Trust your judgment: if it sounds like they expect you to remember, search

Common triggers for memory search:
- "Last time we talked about..."
- "As I mentioned before..."
- "You know I prefer..."
- "Didn't I tell you..."
- "What do I usually..."
- Questions about their past actions, preferences, or statements

Use `memory_tencentdb_memory_search` for:
- User preferences and habits
- Past events and conversations
- Instructions they've given you
- Personal information (projects, tools, locations)

Use `memory_tencentdb_conversation_search` for:
- Exact quotes or specific wording
- When memory_search returns no results but you sense there should be information
- Verifying details from past exchanges
"""


def create_post_turn_hook(agent: "Agent"):
    """Create a post-turn hook for automatic memory storage.

    This hook is called after each conversation turn and checks if the user's
    message contains information worth auto-storing.

    Args:
        agent: The Hermes Agent instance

    Returns:
        Callable post-turn hook function
    """
    from agent.auto_store_heuristic import detect_auto_store

    def auto_store_post_turn(user_message: str, assistant_message: str):
        """Post-turn hook: detect and store memory-worthy information.

        Args:
            user_message: The user's message from this turn
            assistant_message: The assistant's response
        """
        if not user_message:
            return

        # Check if message is worth storing
        should_store, confidence, matched_patterns = detect_auto_store(user_message)

        if should_store:
            logger.info(
                "Auto-memory detected: confidence=%.2f, patterns=%s",
                confidence,
                ", ".join(matched_patterns[:3]) if matched_patterns else "none",
            )

            # Store to memory via memory manager
            if agent._memory_manager:
                try:
                    # Format: action, target, content, metadata
                    # action="append" means append to existing memories
                    # target="auto" means auto-detected storage (not user-initiated)
                    metadata = {
                        "auto_detected": True,
                        "confidence": confidence,
                        "detected_patterns": matched_patterns[:5],  # Top 5 patterns
                        "source": "auto_store_heuristic",
                    }
                    agent._memory_manager.on_memory_write(
                        action="append",
                        target="auto",
                        content=user_message,
                        metadata=metadata,
                    )
                    logger.debug("Auto-memory stored successfully")
                except Exception as e:
                    logger.warning("Auto-memory storage failed (non-fatal): %s", e)
        else:
            logger.debug(
                "Auto-memory skipped: confidence=%.2f (threshold=0.5)",
                confidence,
            )

    return auto_store_post_turn


def install_auto_memory_hooks(agent: "Agent") -> bool:
    """Install auto-memory hooks into the agent.

    This function:
    1. Enhances the system prompt with memory search guidelines
    2. Installs a post-turn hook for automatic memory storage

    Args:
        agent: The Hermes Agent instance

    Returns:
        True if hooks were installed successfully, False otherwise

    Raises:
        AttributeError: If agent doesn't have required attributes
    """
    try:
        # Check if agent has memory manager
        if not hasattr(agent, "_memory_manager") or agent._memory_manager is None:
            logger.warning(
                "Auto-memory hooks not installed: agent has no memory manager"
            )
            return False

        # Enhance system prompt with memory search guidelines
        # Note: This assumes the agent rebuilds system prompt on each turn
        # If not, you may need to manually inject this into the prompt builder
        enhancement = get_memory_search_prompt_enhancement()

        # Store enhancement in agent metadata for prompt builder to pick up
        if not hasattr(agent, "_auto_memory_prompt_enhancement"):
            agent._auto_memory_prompt_enhancement = enhancement
            logger.info("Auto-memory system prompt enhancement registered")

        # Install post-turn hook
        # Note: This assumes a hook mechanism exists in the agent
        # If not, you'll need to manually call this from conversation_loop.py
        post_turn_hook = create_post_turn_hook(agent)

        if hasattr(agent, "_post_turn_hooks"):
            if not isinstance(agent._post_turn_hooks, list):
                agent._post_turn_hooks = []
            agent._post_turn_hooks.append(post_turn_hook)
            logger.info("Auto-memory post-turn hook installed")
        else:
            # Store hook for manual invocation
            agent._auto_memory_post_turn_hook = post_turn_hook
            logger.warning(
                "Agent has no _post_turn_hooks list; hook stored as "
                "_auto_memory_post_turn_hook for manual invocation"
            )

        logger.info("Auto-memory hooks installed successfully")
        return True

    except Exception as e:
        logger.error("Failed to install auto-memory hooks: %s", e)
        return False


def invoke_post_turn_hook_manually(
    agent: "Agent",
    user_message: str,
    assistant_message: str,
) -> None:
    """Manually invoke the post-turn hook if agent doesn't support hook lists.

    Use this from conversation_loop.py if the agent doesn't have a built-in
    post-turn hook mechanism.

    Args:
        agent: The Hermes Agent instance
        user_message: The user's message from this turn
        assistant_message: The assistant's response
    """
    if hasattr(agent, "_auto_memory_post_turn_hook"):
        try:
            agent._auto_memory_post_turn_hook(user_message, assistant_message)
        except Exception as e:
            logger.warning("Auto-memory post-turn hook failed (non-fatal): %s", e)


# Convenience function for integration
def setup_auto_memory(agent: "Agent") -> bool:
    """One-shot setup for auto-memory features.

    Checks environment variable and installs hooks if enabled.

    Args:
        agent: The Hermes Agent instance

    Returns:
        True if auto-memory was enabled and hooks installed, False otherwise

    Example:
        # In agent/__init__.py or conversation_loop.py:
        from agent.memory_auto_hooks import setup_auto_memory

        agent = Agent(...)
        setup_auto_memory(agent)  # Checks env var and installs if enabled
    """
    if not should_enable_auto_memory():
        logger.debug("Auto-memory disabled (HERMES_AUTO_MEMORY not set to true)")
        return False

    logger.info("Auto-memory enabled via HERMES_AUTO_MEMORY environment variable")
    return install_auto_memory_hooks(agent)


# Integration instructions for developers
INTEGRATION_GUIDE = """
=== Auto-Memory Integration Guide ===

This module provides automatic memory detection and storage for Hermes Agent.

## Quick Start

1. Enable via environment variable:
   export HERMES_AUTO_MEMORY=true

2. In your agent initialization code (e.g., agent/__init__.py):

   from agent.memory_auto_hooks import setup_auto_memory

   agent = Agent(...)
   setup_auto_memory(agent)  # Auto-checks env var

3. That's it! The hooks will:
   - Detect memory-worthy messages using linguistic heuristics
   - Automatically store them via memory_manager.on_memory_write()
   - Enhance system prompt to encourage proactive memory search

## Manual Integration (if agent doesn't support hooks)

If your agent doesn't have a _post_turn_hooks mechanism, manually invoke:

   from agent.memory_auto_hooks import (
       should_enable_auto_memory,
       get_memory_search_prompt_enhancement,
       create_post_turn_hook,
   )

   # In system prompt builder:
   if should_enable_auto_memory():
       prompt += get_memory_search_prompt_enhancement()

   # After each turn in conversation_loop.py:
   if should_enable_auto_memory() and hasattr(agent, "_auto_memory_post_turn_hook"):
       agent._auto_memory_post_turn_hook(user_message, assistant_message)

## Configuration

Environment variable: HERMES_AUTO_MEMORY
Valid values: true, 1, yes, on, enabled (case-insensitive)
Default: disabled

## Detection Heuristics

The auto_store_heuristic module detects:
- Explicit instructions: "记住", "remember", "note that"
- Preferences: "我喜欢", "I prefer", "I don't like"
- Corrections: "不对", "actually", "it should be"
- Personal info: "我的项目", "my email", "I live in"
- Reminders: "提醒我", "remind me", "don't forget"

See agent/auto_store_heuristic.py for full pattern list.

## Logging

Set log level to INFO to see auto-memory detections:

   import logging
   logging.getLogger("agent.memory_auto_hooks").setLevel(logging.INFO)

Output example:
   INFO: Auto-memory detected: confidence=0.96, patterns=Explicit Chinese: remember/record, User preference positive (Chinese)
"""


if __name__ == "__main__":
    # Print integration guide when run directly
    print(INTEGRATION_GUIDE)
