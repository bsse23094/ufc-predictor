"""Versioned candidate scoring that cannot auto-link fighter identities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ufc_predictor.identity.candidates import FighterAliasCandidatePair

IDENTITY_SCORER_VERSION = "identity-candidate-scorer-v1"


class CandidateRecommendation(StrEnum):
    """The sole permitted outcome until an approved auto-link policy exists."""

    REVIEW_REQUIRED = "review_required"


@dataclass(frozen=True, slots=True)
class CandidateMatchScore:
    """Transparent evidence for a reviewer, not a probability or resolution."""

    candidate_pair: FighterAliasCandidatePair
    scorer_version: str
    score: float
    evidence: tuple[str, ...]
    recommendation: CandidateRecommendation
    auto_link_threshold: None = None

    def __post_init__(self) -> None:
        if not self.scorer_version:
            raise ValueError("scorer_version is required")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be in [0, 1]")
        if self.recommendation is not CandidateRecommendation.REVIEW_REQUIRED:
            raise ValueError("identity candidate scores must require human review")
        if self.auto_link_threshold is not None:
            raise ValueError("an auto-link threshold is not approved")


def score_candidate_pair(pair: FighterAliasCandidatePair) -> CandidateMatchScore:
    """Score exact normalized-alias agreement without inferring identity.

    The score means only that the deterministic comparison key agrees. It is not
    a match probability, has no auto-link threshold, and always enters review.
    """

    return CandidateMatchScore(
        candidate_pair=pair,
        scorer_version=IDENTITY_SCORER_VERSION,
        score=1.0,
        evidence=(
            "exact_normalized_alias",
            "distinct_source_record_keys",
            "raw_sha256_provenance_retained",
        ),
        recommendation=CandidateRecommendation.REVIEW_REQUIRED,
    )
