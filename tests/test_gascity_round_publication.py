"""Updated rounds edit only their known draft after exact text approval."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_gascity_odoo_checks import checks as checks
from tests.test_gascity_odoo_checks import github_adapter as github_adapter
from tests.test_gascity_odoo_checks import job as job
from tests.test_gascity_odoo_checks import pull_request as pull_request
from tests.test_gascity_odoo_checks import run


@pytest.fixture
def publication(request):
    selected = request.getfixturevalue("job")
    adapter, pushes = request.getfixturevalue("github_adapter")
    checker = request.getfixturevalue("checks")
    publisher = request.getfixturevalue("pull_request")
    bundle, _ = run(checker, selected)
    brief = dict(
        problem="A fresh installation fails.",
        acceptance_criteria=["The delivery menu opens contacts."],
        open_questions=[],
    )
    original = publisher.prepare(selected[0], bundle["brief"], bundle, brief)
    adapter.write_text(json.dumps(dict(commit=original["commit"])))
    receipt = publisher.publish(selected[0], original, original["body_sha256"])
    return SimpleNamespace(
        job=selected[0],
        publisher=publisher,
        adapter=adapter,
        pushes=pushes,
        bundle=bundle,
        brief=brief,
        original=original,
        receipt=receipt,
    )


QUESTION = dict(
    id="question-one",
    question="What should the menu be called?",
    assumption="Use Delivery.",
    reason="That is the existing label.",
)


def revised(case, **changes):
    feedback = dict(
        round=1, questions=[QUESTION], answers=[], previous_questions=[], previous_answers=[]
    )
    feedback.update(changes)
    return case.publisher.prepare(
        case.job, case.bundle["brief"], case.bundle, case.brief, feedback=feedback
    )


def test_body_contains_structured_question_assumption_and_reason(publication):
    result = revised(publication)
    assert all(value in result["body"] for key, value in QUESTION.items() if key != "id")
    assert "Round: 1" in result["body"]


def test_body_revisions_keep_prior_reviewed_files_immutable(publication):
    result = revised(publication)
    assert result["body_sha256"] != publication.original["body_sha256"]
    assert result["body_file"] != publication.original["body_file"]
    assert Path(publication.original["body_file"]).read_text() == publication.original["body"]


def test_known_draft_is_updated_once_instead_of_creating_another(publication):
    result = revised(publication)
    updated = publication.publisher.publish(
        publication.job, result, result["body_sha256"], known_pr=publication.receipt["url"]
    )
    repeated = publication.publisher.publish(
        publication.job, result, result["body_sha256"], known_pr=publication.receipt["url"]
    )
    assert updated == repeated and updated["url"] == publication.receipt["url"]
    calls = [
        json.loads(line)
        for line in publication.adapter.with_suffix(".calls").read_text().splitlines()
    ]
    assert len([args for args in calls if args[:2] == ["pr", "create"]]) == 1
    assert len([args for args in calls if args[:2] == ["pr", "edit"]]) == 1


def test_old_text_approval_cannot_approve_a_revised_body(publication):
    result = revised(publication)
    with pytest.raises(publication.publisher.DeliveryError, match="PR_BODY_APPROVAL_REQUIRED"):
        publication.publisher.publish(
            publication.job,
            result,
            publication.original["body_sha256"],
            known_pr=publication.receipt["url"],
        )
    assert len(publication.pushes) == 1


def test_a_missing_known_pr_does_not_create_a_replacement(publication):
    value = json.loads(publication.adapter.read_text())
    value.pop("pr")
    publication.adapter.write_text(json.dumps(value))
    with pytest.raises(publication.publisher.DeliveryError, match="KNOWN_PR_UNAVAILABLE"):
        publication.publisher.publish(
            publication.job,
            publication.original,
            publication.original["body_sha256"],
            known_pr=publication.receipt["url"],
        )
    assert len(publication.pushes) == 1


def test_an_unrelated_known_url_is_refused_even_for_identical_text(publication):
    with pytest.raises(publication.publisher.DeliveryError, match="KNOWN_PR_MISMATCH"):
        publication.publisher.publish(
            publication.job,
            publication.original,
            publication.original["body_sha256"],
            known_pr="https://github.com/fixture/task/pull/99",
        )


def test_next_round_body_explains_the_answer_that_replaced_an_assumption(publication):
    result = revised(
        publication,
        round=2,
        questions=[],
        previous_questions=[QUESTION],
        previous_answers=[
            dict(
                question_id="question-one",
                accepted=False,
                answer="Call the menu Dispatch contacts.",
            )
        ],
    )
    assert "Round: 2" in result["body"]
    assert QUESTION["question"] in result["body"]
    assert "Call the menu Dispatch contacts." in result["body"]
