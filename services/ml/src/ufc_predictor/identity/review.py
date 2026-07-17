"""Review-queue contracts for explicit, auditable identity decisions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256

from ufc_predictor.identity.scorer import CandidateMatchScore


class IdentityReviewDecisionType(StrEnum):
    """Human decisions that remain proposals until a resolver applies them."""

    PROPOSE_LINK = "propose_link"
    PROPOSE_MERGE = "propose_merge"
    PROPOSE_SPLIT = "propose_split"
    CONFIRM_DISTINCT = "confirm_distinct"
    DEFER = "defer"


@dataclass(frozen=True, slots=True)
class IdentityReviewQueueItem:
    """An immutable review request with reproducible provenance and evidence."""

    review_key: str
    score: CandidateMatchScore


@dataclass(frozen=True, slots=True)
class IdentityReviewDecision:
    """An explicit reviewer action; it cannot assign or merge canonical IDs."""

    review_key: str
    decision: IdentityReviewDecisionType
    decided_by: str
    decided_at: datetime
    rationale: str

    def __post_init__(self) -> None:
        if not self.review_key:
            raise ValueError("review_key is required")
        if not self.decided_by.strip():
            raise ValueError("decided_by is required")
        if not self.rationale.strip():
            raise ValueError("rationale is required")
        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() is None:
            raise ValueError("decided_at must be timezone-aware")


def create_review_queue(
    scores: list[CandidateMatchScore] | tuple[CandidateMatchScore, ...],
) -> tuple[IdentityReviewQueueItem, ...]:
    """Create stable, deduplicated review items from manual-review scores."""

    items: dict[str, IdentityReviewQueueItem] = {}
    for score in scores:
        review_key = _review_key(score)
        item = IdentityReviewQueueItem(review_key=review_key, score=score)
        existing = items.setdefault(review_key, item)
        if existing != item:
            raise ValueError("conflicting evidence produced the same review key")
    return tuple(items[key] for key in sorted(items))


def _review_key(score: CandidateMatchScore) -> str:
    pair = score.candidate_pair
    payload = {
        "scorer_version": score.scorer_version,
        "first": asdict(pair.first),
        "second": asdict(pair.second),
        "evidence": score.evidence,
    }
    encoded = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return sha256(encoded).hexdigest()
