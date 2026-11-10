"""An abnormal empty turn (``empty_response_exhausted``) is delivered as silence, not as a
'⚠️ Cron ... failed' alert: the finalizer stamps ``failure_reason`` for the UI but keeps
``failed`` False, and the scheduler recognises the model-named explainer text."""

import pytest

from agent.turn_explainers import TurnExplainersMixin
from cron.scheduler import _final_response_from_result


class _AIAgent:
    _format_turn_completion_explanation = staticmethod(TurnExplainersMixin._format_turn_completion_explanation)


def test_empty_response_exhausted_turn_delivers_silence_not_a_failure_alert():
    explainer = TurnExplainersMixin._format_turn_completion_explanation("empty_response_exhausted", model="llama3")
    result = {
        # finalize_turn leaves ``failed`` False for this exit reason (and ``completed`` follows the
        # ordinary rule); only the descriptor code is stamped.
        "final_response": explainer, "failed": False, "completed": True, "model": "llama3",
        "turn_exit_reason": "empty_response_exhausted", "failure_reason": "empty_response",
        "failure_retryable": True, "messages": [], "api_calls": 3,
    }
    assert _final_response_from_result(result, "job1", "Morning brief", _AIAgent) == ""


def test_empty_response_exhausted_with_verifier_footer_stays_silent():
    explainer = TurnExplainersMixin._format_turn_completion_explanation("empty_response_exhausted", model="llama3")
    footer = TurnExplainersMixin._format_file_mutation_failure_footer({
        "/home/user/project/notes — final draft.md": {
            "tool": "patch", "error_preview": "Could not find old_string",
        },
    })
    result = {
        "final_response": explainer + "\n\n" + footer,
        "semantic_response": "",
        "file_mutation_footer": "\n\n" + footer,
        "failed": False, "completed": True, "model": "llama3",
        "turn_exit_reason": "empty_response_exhausted", "failure_reason": "empty_response",
        "failure_retryable": True, "messages": [], "api_calls": 3,
    }
    response = _final_response_from_result(result, "job1", "Morning brief", _AIAgent)
    assert response == ""

    from cron.scheduler import _agent_job_outcome
    outcome = _agent_job_outcome(result, "", response)
    success, _output, final_response, error = outcome
    assert (success, final_response, error) == (True, "", None)
    assert outcome.semantic_response == ""
    assert outcome.diagnostic_footer == "\n\n" + footer
    assert outcome.turn_exit_reason == "empty_response_exhausted"


def test_a_failed_turn_still_raises_so_the_job_is_marked_failed():
    result = {"final_response": "stopped", "failed": True, "completed": False, "error": "boom",
              "turn_exit_reason": "repeated_outer_errors(x)", "messages": [], "api_calls": 3}
    with pytest.raises(RuntimeError):
        _final_response_from_result(result, "job1", "Morning brief", _AIAgent)
