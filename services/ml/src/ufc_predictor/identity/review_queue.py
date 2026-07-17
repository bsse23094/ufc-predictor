"""Candidate-only identity review queues, including known observed variants."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from ufc_predictor.identity.normalize import normalize_fighter_alias


@dataclass(frozen=True, slots=True)
class IdentityReviewQueueItem:
    source: str
    raw_value: str
    proposed_value: str | None
    affected_count: int
    examples: tuple[str, ...]
    confidence: str
    reason: str
    review_status: str = "pending"


_KNOWN_VARIANTS: tuple[tuple[str, str], ...] = (
    ("JunYong Park", "Junyong Park"),
    ("Jun Yong Park", "Junyong Park"),
    ("Kai Kara France", "Kai Kara-France"),
    ("Aori Qileng", "Aoriqileng"),
    ("Rong Zhu", "Rongzhu"),
    ("Su Mudaerji", "Sumudaerji"),
    ("Peter Yan", "Petr Yan"),
    ("Alekander Volkov", "Alexander Volkov"),
    ("Vincente Luque", "Vicente Luque"),
    ("Caludia Gadelha", "Claudia Gadelha"),
    ("Ode Obsourne", "Ode Osbourne"),
)


def build_identity_review_queue(
    *, source: str, observed_names: Iterable[str]
) -> tuple[IdentityReviewQueueItem, ...]:
    """Emit review suggestions without assigning or merging durable identities."""

    names = tuple(name for name in observed_names if name.strip())
    counts = Counter(names)
    items: list[IdentityReviewQueueItem] = []
    for raw, proposed in _KNOWN_VARIANTS:
        if raw in counts or proposed in counts:
            items.append(
                IdentityReviewQueueItem(
                    source=source,
                    raw_value=raw,
                    proposed_value=proposed,
                    affected_count=counts[raw] + counts[proposed],
                    examples=tuple(name for name in names if name in {raw, proposed})[:3],
                    confidence="review_required",
                    reason="known punctuation, spacing, rename, or spelling candidate",
                )
            )
    for raw, count in sorted(counts.items()):
        normalized = normalize_fighter_alias(raw).normalized_value
        if normalized != raw.casefold().strip():
            items.append(
                IdentityReviewQueueItem(
                    source=source,
                    raw_value=raw,
                    proposed_value=normalized,
                    affected_count=count,
                    examples=(raw,),
                    confidence="review_required",
                    reason="normalization changes punctuation, spacing, Unicode, or case",
                )
            )
    if counts["Bruno Silva"]:
        items.append(
            IdentityReviewQueueItem(
                source=source,
                raw_value="Bruno Silva",
                proposed_value=None,
                affected_count=counts["Bruno Silva"],
                examples=("Flyweight and Middleweight Bruno Silva must remain separate",),
                confidence="review_required",
                reason="known homonym; separate Flyweight and Middleweight identities",
            )
        )
    return tuple(sorted(items, key=lambda item: (item.raw_value, item.proposed_value or "")))
