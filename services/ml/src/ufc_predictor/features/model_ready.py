"""Hard schema gate between source-shaped rows and pre-fight feature views."""

from __future__ import annotations

from collections.abc import Iterable

_EXACT_FORBIDDEN_SOURCE_COLUMNS = frozenset(
    {
        "R_ev",
        "B_ev",
        "Winner",
        "finish",
        "finish_details",
        "finish_round",
        "finish_round_time",
        "total_fight_time_secs",
    }
)


def forbidden_source_columns(columns: Iterable[str]) -> tuple[str, ...]:
    """Return source fields that must never become direct pre-fight features.

    This gate applies to source-provided names only. Project-owned historical
    fields use lowercase ``red_``, ``blue_``, and ``difference_`` prefixes and
    are produced from strictly prior facts by :mod:`historical`.
    """

    return tuple(
        sorted(
            column
            for column in columns
            if column in _EXACT_FORBIDDEN_SOURCE_COLUMNS
            or column.endswith("_dif")
            or column.startswith(("R_", "B_"))
        )
    )


def assert_pre_fight_feature_schema(columns: Iterable[str]) -> None:
    """Reject direct source leakage before a model-ready view is exposed."""

    forbidden = forbidden_source_columns(columns)
    if forbidden:
        raise ValueError(
            "model-ready/pre-fight view contains forbidden source fields: " + ", ".join(forbidden)
        )
