# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""The scheduled run must actually reach the harness job.

The harness credential dies of inactivity unless something redeems it
(#89), so CI runs the harness job on a weekly schedule. That only
works if a scheduled run reaches the job — and the failure mode is
silent: GitHub skips a job whose `if:` evaluates false and reports the
workflow as green, so a guard that quietly excludes `schedule` would
look exactly like a working keep-alive right up until the credential
expires 90 days later.

`github.event.pull_request` is null on a scheduled run, so the
fork-safety condition alone evaluates false. These tests pin that the
event names are listed explicitly, and that the fork-safety half they
sit beside is still there.

Parsing the workflow rather than grepping it means a reshuffle of the
YAML cannot make the assertions vacuously pass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def ci() -> dict[Any, Any]:
    loaded = yaml.safe_load(WORKFLOW.read_text())
    assert isinstance(loaded, dict)
    return loaded


def _triggers(ci: dict[Any, Any]) -> dict[str, Any]:
    # PyYAML resolves an unquoted `on:` key to the boolean True — the
    # Norway problem's cousin. Accept whichever spelling survived.
    triggers = ci["on"] if "on" in ci else ci[True]
    assert isinstance(triggers, dict), "workflow has no trigger block"
    return triggers


def _harness_if(ci: dict[Any, Any]) -> str:
    condition = ci["jobs"]["harness"]["if"]
    assert isinstance(condition, str)
    return condition


def test_workflow_runs_on_a_schedule(ci: dict[Any, Any]) -> None:
    schedule = _triggers(ci)["schedule"]
    assert schedule, "no cron entries"
    for entry in schedule:
        assert entry["cron"].split()[-1] != "*", (
            "cron runs daily or more often; weekly is the documented cadence"
        )


def test_schedule_is_frequent_enough_to_beat_the_inactivity_window(
    ci: dict[Any, Any],
) -> None:
    """Entra expires a refresh token after 90 days of inactivity. A
    weekly cadence leaves an order of magnitude of margin; a monthly
    one would not survive two missed runs."""
    day_of_month_fields = {entry["cron"].split()[2] for entry in _triggers(ci)["schedule"]}
    assert day_of_month_fields == {"*"}, "a day-of-month cron can be a month apart"


def test_workflow_can_be_run_by_hand(ci: dict[Any, Any]) -> None:
    """A freshly installed credential must be verifiable now, not on
    the next scheduled Monday."""
    assert "workflow_dispatch" in _triggers(ci)


def test_harness_job_is_not_skipped_on_scheduled_or_manual_runs(
    ci: dict[Any, Any],
) -> None:
    """The silent-failure guard. `github.event.pull_request` is null on
    these events, so the fork check alone evaluates false and the job
    would never run."""
    condition = _harness_if(ci)
    assert "github.event_name == 'schedule'" in condition
    assert "github.event_name == 'workflow_dispatch'" in condition


def test_harness_job_still_refuses_forked_pull_requests(ci: dict[Any, Any]) -> None:
    """Fork safety is the reason the guard exists at all; widening it
    for the schedule must not have widened it for forks."""
    assert "github.event.pull_request.head.repo.full_name == github.repository" in _harness_if(ci)


def test_nothing_between_the_trigger_and_the_harness_job_excludes_a_scheduled_run(
    ci: dict[Any, Any],
) -> None:
    """`needs:` makes the harness job inherit its dependencies' fate: a
    dependency skipped on `schedule` would skip the harness job too,
    just as invisibly."""
    jobs = ci["jobs"]

    def needs_of(job: str) -> list[str]:
        # `needs:` is a string for a single dependency, a list for many.
        declared = jobs[job].get("needs", [])
        return [declared] if isinstance(declared, str) else list(declared)

    pending = needs_of("harness")
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        assert "if" not in jobs[name], (
            f"job {name!r} is a dependency of harness and carries its own `if:`; "
            "it could skip a scheduled run and take the harness job with it"
        )
        pending.extend(needs_of(name))
    assert seen, "harness job has no dependencies — expected it to need the test job"
