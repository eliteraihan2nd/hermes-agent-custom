"""Structured cron response metadata must survive the owner receipt/RPC boundary."""

import asyncio
from contextlib import nullcontext
from typing import Any, cast

from cron import jobs, scheduler
from gateway import run, session_cron
from gateway.config import Platform
from gateway.session_contract import SessionRef
from gateway.session_local_recovery import local_adapter_map
from hermes_state_runtime import claim_session_input, settle_session_input
from tests.cron.test_cron_recovery import _owner


class _Outcome(tuple):
    semantic_response: str
    diagnostic_footer: str
    turn_exit_reason: str

    def __new__(cls, values, *, semantic_response, diagnostic_footer, turn_exit_reason):
        result = super().__new__(cls, values)
        result.semantic_response = semantic_response
        result.diagnostic_footer = diagnostic_footer
        result.turn_exit_reason = turn_exit_reason
        return result


def test_owner_receipt_round_trips_structured_metadata_and_exit_reason(tmp_path, monkeypatch):
    """The gateway persists the same structured evidence that the firing scheduler consumes."""
    monkeypatch.setattr(run, "_profile_runtime_scope", lambda _home: nullcontext())
    footer = "\n\n⚠️ File-mutation verifier: 1 failed edit — `/tmp/project/draft`"

    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="report", schedule="every 1h", deliver="local")
        authority, db = _owner(tmp_path, monkeypatch)
        try:
            async def probe():
                params = {"job_id": job["id"], "request_id": "structured-fire", "extra_prompt": None}
                receipt = cast(dict[str, Any], await session_cron.operation(authority, "submit", params))
                ref = SessionRef(str(tmp_path), cast(str, receipt["session_id"]))
                row = cast(dict[str, Any], claim_session_input(db, epoch=authority.epoch, session_id=ref.session_id))
                policy = local_adapter_map(authority)[Platform.LOCAL].policies[ref.session_id]
                outcome = _Outcome(
                    (True, "diagnostic output", "", None), semantic_response="",
                    diagnostic_footer=footer, turn_exit_reason="empty_response_exhausted",
                )
                monkeypatch.setattr(scheduler, "run_job", lambda *_args, **_kwargs: outcome)
                result = await session_cron.execute(authority, ref, row, policy)
                assert result == ""
                settle_session_input(
                    db, epoch=authority.epoch, admission_id=row["admission_id"],
                    generation=row["generation"], outcome="completed",
                    result=authority.pending_results[row["admission_id"]],
                )
                return await session_cron.operation(
                    authority, "status", {"session_id": ref.session_id,
                                            "admission_id": row["admission_id"]})

            state = asyncio.run(probe())
        finally:
            db.close()

    expected_metadata = {
        "version": 1,
        "semantic_response": "",
        "diagnostic_footer": footer,
    }
    assert state["result"] == [True, "diagnostic output", "", None]
    assert state["response_metadata"] == expected_metadata
    assert state["turn_exit_reason"] == "empty_response_exhausted"
    assert state["diagnostic_footer"] == footer


def test_canonical_rpc_returns_four_values_with_metadata_preserved(tmp_path, monkeypatch):
    from cron import scheduler_authority
    from hermes_cli import gateway_client

    footer = "\n\n⚠️ File-mutation verifier: failed edit — `/tmp/project/draft`"
    rendered = "(empty)" + footer
    metadata = {"version": 1, "semantic_response": "(empty)", "diagnostic_footer": footer}
    state = {
        "status": "terminal",
        "result": [True, "diagnostic output", rendered, None],
        "response_metadata": metadata,
        "turn_exit_reason": "text_response",
        "diagnostic_footer": footer,
        "job_flags": {},
        "progress_at": None,
    }

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def rpc(self, method, **_kwargs):
            if method == "cron.submit":
                return {"session_id": "session", "admission_id": "admission"}
            if method == "cron.status":
                return state
            raise AssertionError(f"unexpected RPC: {method}")

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(gateway_client, "connect_gateway", lambda: _Client())
    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="report", schedule="every 1h", deliver="local")
        result = scheduler_authority.run_canonical_job(job, execution_id="rpc-fire")

    assert len(result) == 4
    assert getattr(result, "semantic_response", None) == "(empty)"
    assert getattr(result, "diagnostic_footer", None) == footer
    assert getattr(result, "turn_exit_reason", None) == "text_response"


def test_canonical_missing_metadata_fails_closed_but_keeps_independent_footer(tmp_path, monkeypatch):
    from cron import scheduler_authority
    from hermes_cli import gateway_client

    footer = "\n\n⚠️ File-mutation verifier: failed edit — `/tmp/project/draft`"
    state = {
        "status": "terminal",
        "result": [True, "diagnostic output", "", None],
        "turn_exit_reason": "empty_response_exhausted",
        "diagnostic_footer": footer,
        "job_flags": {},
        "progress_at": None,
    }

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def rpc(self, method, **_kwargs):
            if method == "cron.submit":
                return {"session_id": "session", "admission_id": "admission"}
            if method == "cron.status":
                return state
            raise AssertionError(f"unexpected RPC: {method}")

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(gateway_client, "connect_gateway", lambda: _Client())
    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="report", schedule="every 1h", deliver="local")
        result = scheduler_authority.run_canonical_job(job, execution_id="rpc-missing-metadata")

    assert len(result) == 4
    assert getattr(result, "semantic_response", "not-structured") is None
    assert footer in getattr(result, "diagnostic_footer", "")
    assert getattr(result, "turn_exit_reason", None) == "empty_response_exhausted"
