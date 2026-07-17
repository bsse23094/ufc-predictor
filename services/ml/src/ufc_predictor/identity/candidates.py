"""Conservative candidate-pair generation from provenance-carrying aliases."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations

from ufc_predictor.identity.normalize import FighterAliasCandidate, group_candidate_aliases


@dataclass(frozen=True, slots=True)
class FighterAliasCandidatePair:
    """Two observations with an equal comparison key, not an identity match."""

    first: FighterAliasCandidate
    second: FighterAliasCandidate

    def __post_init__(self) -> None:
        if self.first.alias.normalized_value != self.second.alias.normalized_value:
            raise ValueError("candidate pairs must have the same normalized alias")
        if _occurrence_key(self.first) >= _occurrence_key(self.second):
            raise ValueError("candidate pair occurrences must be unique and sorted")
        if (
            self.first.source_identifier == self.second.source_identifier
            and self.first.source_record_key == self.second.source_record_key
        ):
            raise ValueError("candidate pairs must not compare aliases from the same source record")

    @property
    def normalized_alias(self) -> str:
        """Return the shared comparison key, never a canonical display name."""

        return self.first.alias.normalized_value


def generate_candidate_pairs(
    candidates: Iterable[FighterAliasCandidate],
) -> tuple[FighterAliasCandidatePair, ...]:
    """Pair distinct audited occurrences with exact normalized-name agreement.

    The result deliberately includes potential homonyms. A later reviewer must
    decide whether any pair is evidence of one fighter; this function does not
    decide or return a canonical identifier.
    """

    pairs: list[FighterAliasCandidatePair] = []
    for group in group_candidate_aliases(candidates).values():
        unique_occurrences = {_occurrence_key(candidate): candidate for candidate in group}
        ordered = tuple(unique_occurrences[key] for key in sorted(unique_occurrences))
        for first, second in combinations(ordered, 2):
            if (
                first.source_identifier == second.source_identifier
                and first.source_record_key == second.source_record_key
            ):
                continue
            pairs.append(FighterAliasCandidatePair(first=first, second=second))
    return tuple(pairs)


def _occurrence_key(candidate: FighterAliasCandidate) -> tuple[str, str, str, str]:
    return (
        candidate.source_identifier,
        candidate.source_record_key,
        candidate.source_raw_sha256,
        candidate.source_field,
    )
