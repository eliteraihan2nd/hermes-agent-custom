"""A cron turn that produced no answer must never be booked ``ok``.

Regression for the 2026-10-29 meta-maintenance run (job ``c6b8bfb4e363``): the turn ended with no
answer, ``agent.turn_empty_response`` returned the literal sentinel ``(empty)``, the turn-end
file-mutation verifier footer was appended on top of it, and the run was booked ``ok`` and delivered
as a success report — ``cron/deliveries.db`` recorded ``length(content)=0`` with ``status=delivered``.

``(empty)`` is non-blank, so the blank-only predicate in ``fail_empty_response`` never fired. A body
that is only the verifier footer is the same class of no-output: the footer is appended *after* the
response is normalised, so it can make an empty turn look like content.
"""

import pytest

from cron.scheduler import _RunDelivery
from cron.scheduler_bookkeeping import EMPTY_RESPONSE_ERROR, fail_empty_response

# Shape written by ``agent/turn_finalizer.py::_append_file_mutation_footer`` for a denied scratch write.
SCRATCH_FOOTER = (
    "\n\n⚠️ File-mutation verifier: 1 file edit(s) FAILED\n"
    "  • /home/raihanno/raihanno-hermes-data/cache/scratch/fact_probe.py — not modified "
    "(outside HERMES_WRITE_SAFE_ROOT)"
)
# Same footer naming a path the operator actually cares about.
REAL_FOOTER = (
    "\n\n⚠️ File-mutation verifier: 1 file edit(s) FAILED\n"
    "  • /home/raihanno/apps/notes/2026-10-29-meta-maint.md — Could not find old_string"
)


def _run(final_response):
    d = _RunDelivery(job={"id": "job1"}, success=True, error=None)
    fail_empty_response(d, final_response)
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
    d = _run("(empty)" + SCRATCH_FOOTER)
    assert d.success is False
    assert d.error == EMPTY_RESPONSE_ERROR


def test_scratch_only_footer_alone_is_a_failure():
    d = _run(SCRATCH_FOOTER.strip())
    assert d.success is False
    assert d.error == EMPTY_RESPONSE_ERROR


def test_a_real_answer_plus_a_scratch_footer_stays_a_success():
    d = _run("Consolidated MEMORY.md: 7 entries merged, 2 stale removed." + SCRATCH_FOOTER)
    assert d.success is True
    assert d.error is None


def test_a_real_answer_plus_an_unreachable_real_path_stays_a_success():
    """A write that failed against a *real* path is evidence, not no-output: keep the run green so
    the footer still reaches the operator instead of being replaced by an empty-response alert."""
    d = _run("Patched two skills." + REAL_FOOTER)
    assert d.success is True
    assert d.error is None


def test_an_already_failed_run_is_left_alone():
    """The predicate only upgrades a would-be ``ok``; it never overwrites a real error."""
    d = _RunDelivery(job={"id": "job1"}, success=False, error="provider 429 after 3 retries")
    fail_empty_response(d, "(empty)")
    assert d.success is False
    assert d.error == "provider 429 after 3 retries"
