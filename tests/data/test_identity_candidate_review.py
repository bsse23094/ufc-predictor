from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ufc_predictor.identity.candidates import generate_candidate_pairs
from ufc_predictor.identity.normalize import FighterAliasCandidate, candidate_fighter_aliases
from ufc_predictor.identity.resolver import ReviewedFighterMerge, ReviewedFighterSplit
from ufc_predictor.identity.review import (
    IdentityReviewDecision,
    IdentityReviewDecisionType,
    create_review_queue,
)
from ufc_predictor.identity.scorer import (
    IDENTITY_SCORER_VERSION,
    CandidateRecommendation,
    score_candidate_pair,
)


def _candidates() -> tuple[FighterAliasCandidate, ...]:
    return candidate_fighter_aliases(
        source_identifier="kaggle-ultimate-ufc-dataset",
        rows=(
            {
                "source_record_key": "fight-001",
                "source_raw_sha256": "a" * 64,
                "fighter_one_source_name": "José Aldo",
                "fighter_two_source_name": "Alpha Fighter",
            },
            {
                "source_record_key": "fight-002",
                "source_raw_sha256": "b" * 64,
                "fighter_one_source_name": "Jose Aldo",
                "fighter_two_source_name": "Beta Fighter",
            },
        ),
    )


def test_equal_normalized_aliases_create_one_cross_record_candidate_pair() -> None:
    pairs = generate_candidate_pairs(_candidates())

    assert len(pairs) == 1
    assert pairs[0].normalized_alias == "jose aldo"
    assert {
        pairs[0].first.source_record_key,
        pairs[0].second.source_record_key,
    } == {"fight-001", "fight-002"}
    assert not hasattr(pairs[0], "fighter_id")


def test_same_record_aliases_and_duplicate_occurrences_do_not_become_candidate_pairs() -> None:
    candidates = candidate_fighter_aliases(
        source_identifier="fixture-source",
        rows=(
            {
                "source_record_key": "fight-001",
                "source_raw_sha256": "a" * 64,
                "fighter_one_source_name": "Alpha Fighter",
                "fighter_two_source_name": "Alpha Fighter",
            },
        ),
    )

    assert generate_candidate_pairs((*candidates, candidates[0])) == ()


def test_candidate_scoring_always_requires_human_review_without_an_auto_link_threshold() -> None:
    pair = generate_candidate_pairs(_candidates())[0]

    score = score_candidate_pair(pair)

    assert score.scorer_version == IDENTITY_SCORER_VERSION
    assert score.score == 1.0
    assert score.auto_link_threshold is None
    assert score.recommendation is CandidateRecommendation.REVIEW_REQUIRED
    assert "raw_sha256_provenance_retained" in score.evidence


def test_review_queue_is_stable_and_human_decision_carries_audit_fields() -> None:
    score = score_candidate_pair(generate_candidate_pairs(_candidates())[0])

    queue = create_review_queue((score, score))
    decision = IdentityReviewDecision(
        review_key=queue[0].review_key,
        decision=IdentityReviewDecisionType.PROPOSE_LINK,
        decided_by="data-steward@example.test",
        decided_at=datetime(2026, 7, 17, tzinfo=UTC),
        rationale="Exact normalized alias requires a later source-backed resolver review.",
    )

    assert len(queue) == 1
    assert decision.review_key == queue[0].review_key
    assert not hasattr(decision, "fighter_id")


def test_review_decision_rejects_missing_audit_information() -> None:
    with pytest.raises(ValueError, match="decided_by"):
        IdentityReviewDecision(
            review_key="review-key",
            decision=IdentityReviewDecisionType.DEFER,
            decided_by=" ",
            decided_at=datetime(2026, 7, 17, tzinfo=UTC),
            rationale="Need another source.",
        )


def test_reviewed_canonical_transitions_reject_self_references() -> None:
    fighter_id = uuid4()

    with pytest.raises(ValueError, match="itself"):
        ReviewedFighterMerge(
            decision_id=uuid4(),
            canonical_fighter_id=fighter_id,
            merged_fighter_id=fighter_id,
        )
    with pytest.raises(ValueError, match="itself"):
        ReviewedFighterSplit(
            decision_id=uuid4(),
            canonical_fighter_id=fighter_id,
            restored_fighter_id=fighter_id,
        )
