"""Behaviour contract for the reasoning-tag gate in ``agent.turn_response_intake._relay_thinking``.

Fork drift protection for patch c5d664a1a5 (cherry-pick of 9ab1e7e85f) on
eliteraihan2nd/hermes-agent-custom: ``reasoning.available`` must fire only for
in-band reasoning-tagged content. Test-file rubric convention follows upstream
NousResearch/hermes-agent Contributing.md (contract test plus a red-prove on the
unfixed base). Upstream itself is READ-ONLY for us — this test guards fork drift.

Invariants pinned here:
- INVARIANT A (the fix): untagged final-answer content must NOT emit the
  ``reasoning.available`` callback (red on base bf0203a794: the pre-patch
  ``elif _think_text:`` relays any non-empty content, echoing the answer into
  the thinking card — WebUI live path has no echo guard).
- INVARIANT B (no collateral): reasoning-tagged content still emits
  ``reasoning.available`` (intended upstream behaviour, cc2b56b26a / a51e6cf1),
  for every tag spelling the gate accepts.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

# Stub optional heavy imports so the module imports cleanly in isolation
# (same stub set as sibling reasoning tests).
sys.modules.setdefault("fire", types.SimpleNamespace(Fire=lambda *a, **k: None))
sys.modules.setdefault("firecrawl", types.SimpleNamespace(Firecrawl=object))
sys.modules.setdefault("fal_client", types.SimpleNamespace())

from agent.turn_response_intake import _relay_thinking

_THINK_TAG = "think"
_SCRATCHPAD_TAG = "REASONING_SCRATCHPAD"


class _CaptureAgent:
    """Minimal stand-in for the agent surface ``_relay_thinking`` touches."""

    def __init__(self, delegate_depth: int = 0):
        self._delegate_depth = delegate_depth
        self.events: list[tuple] = []

    def tool_progress_callback(self, event: str, *rest: object) -> None:
        self.events.append((event,) + tuple(rest))


def _reasoning_available_calls(agent: _CaptureAgent) -> list[tuple]:
    return [ev for ev in agent.events if ev[0] == "reasoning.available"]


def _tagged_content(tag: str) -> str:
    return "<" + tag + ">weighing the options here</" + tag + ">\nFinal answer text."


def test_reasoning_available_gated_off_for_untagged_content():
    """INVARIANT A: content with no reasoning tag must not emit reasoning.available."""
    agent = _CaptureAgent()
    _relay_thinking(agent, "Deploy finished. All services healthy, nothing more to do.")
    assert _reasoning_available_calls(agent) == []


def test_reasoning_available_still_fires_for_tagged_content():
    """INVARIANT B: reasoning-tagged content still emits reasoning.available."""
    for tag in (_THINK_TAG, _SCRATCHPAD_TAG, "reasoning"):
        agent = _CaptureAgent()
        _relay_thinking(agent, _tagged_content(tag))
        assert _reasoning_available_calls(agent), "no reasoning.available event for tag <" + tag + ">"
