"""A cron turn that produced no answer must never be booked ``ok``.

Regression for the 2026-10-29 meta-maintenance run (job ``c6b8bfb4e363``): the turn ended with no
answer, ``agent.turn_empty_response`` returned the literal sentinel ``(empty)``, the turn-end
file-mutation verifier footer was appended on top of it, and the run was booked ``ok`` and delivered
as a success report — ``cron/deliveries.db`` recorded ``length(content)=0`` with ``status=delivered``.

``(empty)`` is non-blank, so the blank-only predicate in ``fail_empty_response`` never fired. A body
that is only the verifier footer is the same class of no-output: the footer is appended *after* the
response is normalised, so it can make an empty turn look like content.
"""

import os
from pathlib import Path

import pytest

from agent.turn_explainers import TurnExplainersMixin
from cron.scheduler import _RunDelivery
from cron.scheduler_bookkeeping import EMPTY_RESPONSE_ERROR, fail_empty_response

def _scratch_footer():
    root = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    return (
        "\n\n⚠️ File-mutation verifier: 1 file edit(s) FAILED\n"
        f"  • {root / 'cache' / 'scratch' / 'fact_probe.py'} — not modified "
        "(outside HERMES_WRITE_SAFE_ROOT)"
    )
# Same footer naming a path the operator actually cares about.
REAL_FOOTER = (
    "\n\n⚠️ File-mutation verifier: 1 file edit(s) FAILED\n"
    "  • /home/raihanno/apps/notes/2026-10-29-meta-maint.md — Could not find old_string"
)


def _run(final_response, *, semantic_response=None, diagnostic_footer=None):
    d = _RunDelivery(job={"id": "job1"}, success=True, error=None)
    if semantic_response is None and diagnostic_footer is None:
        fail_empty_response(d, final_response)
    else:
        fail_empty_response(
            d, final_response, semantic_response=semantic_response,
            diagnostic_footer=diagnostic_footer)
    return d


@pytest.mark.parametrize("body", ["", "   \n\t ", None])
def test_blank_answer_is_a_failure(body):
    d = _run(body)
    assert d.success is False
    assert d.error == EMPTY_RESPONSE_ERROR


def test_empty_sentinel_is_a_failure():
    d = _run("(empty)")
    assert d.success is False
    assert d.error == EMPTY_RESPONSE_ERROR


def test_empty_sentinel_with_scratch_only_footer_is_a_failure():
    """The exact delivered body from the 2026-10-29 run."""
    footer = _scratch_footer()
    d = _run(
        "(empty)" + footer, semantic_response="(empty)", diagnostic_footer=footer)
    assert d.success is False
    assert d.error == EMPTY_RESPONSE_ERROR + footer


def test_empty_sentinel_with_real_path_footer_is_failure_and_preserves_diagnostic():
    d = _run(
        "(empty)" + REAL_FOOTER, semantic_response="(empty)",
        diagnostic_footer=REAL_FOOTER)
    assert d.success is False
    assert d.error == EMPTY_RESPONSE_ERROR + REAL_FOOTER


@pytest.mark.parametrize(
    "footer",
    [
        "\n\n⚠️ File-mutation verifier: malformed footer with no entries",
        "\n\n⚠️ File-mutation verifier: 1 failure\n  • ambiguous — malformed path text",
        "\n\nverifier metadata with an unknown format",
    ],
)
def test_empty_sentinel_with_malformed_or_ambiguous_footer_fails_closed(footer):
    d = _run(
        "(empty)" + footer, semantic_response="(empty)", diagnostic_footer=footer)
    assert d.success is False
    assert d.error == EMPTY_RESPONSE_ERROR + footer


def test_project_tmp_path_is_diagnostic_not_answer():
    footer = REAL_FOOTER.replace("/home/raihanno/apps/notes", "/home/user/project/tmp")
    d = _run(
        "(empty)" + footer, semantic_response="(empty)", diagnostic_footer=footer)
    assert d.success is False
    assert d.error == EMPTY_RESPONSE_ERROR + footer


def test_mixed_scratch_and_real_paths_preserve_evidence():
    footer = _scratch_footer() + REAL_FOOTER
    d = _run(
        "(empty)" + footer, semantic_response="(empty)", diagnostic_footer=footer)
    assert d.success is False
    assert d.error == EMPTY_RESPONSE_ERROR + footer


def test_scratch_only_footer_alone_is_a_failure():
    footer = _scratch_footer().strip()
    d = _run(footer, semantic_response="", diagnostic_footer=footer)
    assert d.success is False
    assert d.error == EMPTY_RESPONSE_ERROR + footer


def test_a_real_answer_plus_a_scratch_footer_stays_a_success():
    answer = "Consolidated MEMORY.md: 7 entries merged, 2 stale removed."
    footer = _scratch_footer()
    d = _run(answer + footer, semantic_response=answer, diagnostic_footer=footer)
    assert d.success is True
    assert d.error is None


def test_a_real_answer_plus_an_unreachable_real_path_stays_a_success():
    """A write that failed against a real path is evidence, not no-output."""
    answer = "Patched two skills."
    d = _run(
        answer + REAL_FOOTER, semantic_response=answer, diagnostic_footer=REAL_FOOTER)
    assert d.success is True
    assert d.error is None


def test_exhausted_empty_failure_is_classified_before_compose_and_never_delivered(monkeypatch):
    from cron import scheduler

    observed = {}

    monkeypatch.setattr(scheduler, "self_removal_delivery_allowed", lambda _job_id: False)
    monkeypatch.setattr(scheduler, "save_job_output", lambda *_args: None)
    monkeypatch.setattr(scheduler, "_is_interrupted", lambda *_args: False)

    def compose(_job, *, success, error, **_kwargs):
        observed.update(success=success, error=error)
        return "A generated failure notice", False, False, False, None

    monkeypatch.setattr(scheduler, "_compose_run_delivery", compose)
    delivery = _RunDelivery(job={"id": "job1"}, success=True, error=None)
    scheduler._save_compose_deliver(
        delivery, scheduler._FireOwnership(job={"id": "job1"}), "", "", adapters=None, loop=None,
        verbose=False, execution_token=None, semantic_response="", diagnostic_footer="",
        structured_metadata=True, turn_exit_reason="empty_response_exhausted")

    assert observed == {"success": False, "error": EMPTY_RESPONSE_ERROR}
    assert delivery.should_deliver is False


def test_non_exhausted_empty_failure_notice_remains_deliverable(monkeypatch):
    from cron import scheduler

    observed = {}
    monkeypatch.setattr(scheduler, "self_removal_delivery_allowed", lambda _job_id: False)
    monkeypatch.setattr(scheduler, "save_job_output", lambda *_args: None)
    monkeypatch.setattr(scheduler, "_is_interrupted", lambda *_args: False)

    def compose(_job, *, success, error, **_kwargs):
        observed.update(success=success, error=error)
        return "A generated failure notice", False, False, False, None

    monkeypatch.setattr(scheduler, "_compose_run_delivery", compose)
    delivery = _RunDelivery(job={"id": "job1"}, success=True, error=None)
    scheduler._save_compose_deliver(
        delivery, scheduler._FireOwnership(job={"id": "job1"}), "(empty)", "",
        adapters=None, loop=None, verbose=False, execution_token=None,
        semantic_response="(empty)", diagnostic_footer="", structured_metadata=True,
        turn_exit_reason="text_response")

    assert observed == {"success": False, "error": EMPTY_RESPONSE_ERROR}
    assert delivery.should_deliver is True


def test_empty_sentinel_with_real_footer_is_failure_during_compose_and_preserves_evidence(monkeypatch):
    from cron import scheduler
    from cron.scheduler import _agent_job_outcome

    ordinary_path = "/home/user/project/notes.md"
    delimiter_path = "/home/user/project/draft folder/notes — final`copy.md"
    formatted_footer = TurnExplainersMixin._format_file_mutation_failure_footer({
        ordinary_path: {"tool": "patch", "error_preview": "Could not find old_string"},
        delimiter_path: {"tool": "write_file", "error_preview": "Permission denied"},
    })
    diagnostic_footer = "\n\n" + formatted_footer
    assert f"`{ordinary_path}`" in formatted_footer
    assert delimiter_path in formatted_footer
    final_response = "(empty)" + diagnostic_footer
    result = {
        "final_response": final_response,
        "semantic_response": "(empty)", "file_mutation_footer": diagnostic_footer,
        "turn_exit_reason": "text_response",
    }
    outcome = _agent_job_outcome(result, "", final_response)
    success, output, final_response, error = outcome
    assert (success, error) == (True, None)
    assert outcome.semantic_response == "(empty)"
    assert outcome.diagnostic_footer == diagnostic_footer

    observed = {}

    monkeypatch.setattr(scheduler, "self_removal_delivery_allowed", lambda _job_id: False)
    monkeypatch.setattr(scheduler, "save_job_output", lambda *_args: None)
    monkeypatch.setattr(scheduler, "_is_interrupted", lambda *_args: False)

    def compose(_job, *, success, error, **_kwargs):
        observed.update(success=success, error=error)
        return f"Failure: {error}", False, False, False, None

    monkeypatch.setattr(scheduler, "_compose_run_delivery", compose)
    delivery = _RunDelivery(job={"id": "job1"}, success=True, error=None)
    scheduler._save_compose_deliver(
        delivery, scheduler._FireOwnership(job={"id": "job1"}), final_response, output,
        adapters=None, loop=None, verbose=False, execution_token=None,
        semantic_response=outcome.semantic_response,
        diagnostic_footer=outcome.diagnostic_footer, structured_metadata=True)

    assert observed == {
        "success": False, "error": EMPTY_RESPONSE_ERROR + diagnostic_footer,
    }
    assert delivery.should_deliver is True


@pytest.mark.parametrize(
    "corrupt_metadata",
    [
        pytest.param(lambda result: result.pop("semantic_response"), id="missing-semantic"),
        pytest.param(lambda result: result.update(semantic_response=None), id="null-semantic"),
        pytest.param(lambda result: result.update(semantic_response={"bad": "metadata"}), id="nonstring-semantic"),
        pytest.param(lambda result: result.pop("file_mutation_footer"), id="missing-footer"),
        pytest.param(lambda result: result.update(file_mutation_footer=None), id="null-footer"),
        pytest.param(lambda result: result.update(file_mutation_footer={"bad": "metadata"}), id="nonstring-footer"),
        pytest.param(lambda result: result.update(semantic_response="Claimed success"), id="contradictory-semantic"),
        pytest.param(lambda result: result.update(file_mutation_footer="different footer"), id="contradictory-footer"),
        pytest.param(lambda result: result.update(final_response="different rendered response"), id="contradictory-rendered"),
        pytest.param(lambda result: result.update(final_response="(empty)", semantic_response=None), id="empty-rendered-with-separate-footer"),
    ],
)
def test_malformed_structured_metadata_fails_closed_through_scheduler(monkeypatch, corrupt_metadata):
    from cron import scheduler
    from cron.scheduler import _agent_job_outcome

    path = "/home/user/project/notes — release draft.md"
    formatted_footer = TurnExplainersMixin._format_file_mutation_failure_footer({
        path: {"tool": "patch", "error_preview": "Could not find old_string"},
    })
    diagnostic_suffix = "\n\n" + formatted_footer
    rendered = "(empty)" + diagnostic_suffix
    result = {
        "final_response": rendered,
        "semantic_response": "(empty)",
        "file_mutation_footer": diagnostic_suffix,
        "turn_exit_reason": "text_response",
    }
    corrupt_metadata(result)
    outcome = _agent_job_outcome(result, "", result["final_response"])

    assert outcome.semantic_response == ""
    assert isinstance(outcome.diagnostic_footer, str)
    assert path in outcome.diagnostic_footer

    observed = {}
    monkeypatch.setattr(scheduler, "self_removal_delivery_allowed", lambda _job_id: False)
    monkeypatch.setattr(scheduler, "save_job_output", lambda *_args: None)
    monkeypatch.setattr(scheduler, "_is_interrupted", lambda *_args: False)

    def compose(_job, *, success, error, **_kwargs):
        observed.update(success=success, error=error)
        return f"Failure: {error}", False, False, False, None

    monkeypatch.setattr(scheduler, "_compose_run_delivery", compose)
    delivery = _RunDelivery(job={"id": "job1"}, success=True, error=None)
    delivery_response = result["final_response"]
    scheduler._save_compose_deliver(
        delivery, scheduler._FireOwnership(job={"id": "job1"}), delivery_response, "",
        adapters=None, loop=None, verbose=False, execution_token=None,
        semantic_response=outcome.semantic_response,
        diagnostic_footer=outcome.diagnostic_footer, structured_metadata=True)

    assert observed["success"] is False
    assert delivery_response in observed["error"]
    assert path in observed["error"]
    assert delivery.should_deliver is True


def test_invalid_structured_metadata_cannot_book_a_real_answer_success():
    from cron.scheduler import _RunDelivery

    for rendered, semantic, footer in (
        ("A useful answer", "A useful answer", None),
        ("A useful answer\n\nreal diagnostic", "A useful answer", "different diagnostic"),
    ):
        delivery = _RunDelivery(job={"id": "job1"}, success=True, error=None)
        fail_empty_response(
            delivery, rendered, semantic_response=semantic, diagnostic_footer=footer)
        assert delivery.success is False
        assert rendered in delivery.error
        if isinstance(footer, str):
            assert footer in delivery.error


def test_an_already_failed_run_is_left_alone():
    """The predicate only upgrades a would-be ``ok``; it never overwrites a real error."""
    d = _RunDelivery(job={"id": "job1"}, success=False, error="provider 429 after 3 retries")
    fail_empty_response(d, "(empty)")
    assert d.success is False
    assert d.error == "provider 429 after 3 retries"
