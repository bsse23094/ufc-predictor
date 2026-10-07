"""Historical division form board from accepted M3 bouts and reviewed division provenance."""

from __future__ import annotations

import functools
import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from ufc_api.data.parquet_catalog import M3_DIR, _fighter_name_map, _load_bouts_df
from ufc_predictor.training.m4_opponent_strength import (
    load_weight_classes_from_m3_provenance,
)

DIVISIONS = (
    ("flyweight", "Flyweight"),
    ("bantamweight", "Bantamweight"),
    ("featherweight", "Featherweight"),
    ("lightweight", "Lightweight"),
    ("welterweight", "Welterweight"),
    ("middleweight", "Middleweight"),
    ("light_heavyweight", "Light Heavyweight"),
    ("heavyweight", "Heavyweight"),
    ("womens_strawweight", "Women's Strawweight"),
    ("womens_flyweight", "Women's Flyweight"),
    ("womens_bantamweight", "Women's Bantamweight"),
)


def _wilson_lower_bound(wins: int, losses: int) -> float:
    count = wins + losses
    if count == 0:
        return 0.0
    rate = wins / count
    z = 1.0
    return (
        rate
        + z * z / (2 * count)
        - z * math.sqrt((rate * (1 - rate) + z * z / (4 * count)) / count)
    ) / (1 + z * z / count)


@functools.lru_cache(maxsize=1)
def division_standouts() -> dict[str, Any]:
    bouts = _load_bouts_df()
    if bouts.is_empty():
        return {"as_of_date": None, "window_start": None, "divisions": []}
    division_by_bout, _ = load_weight_classes_from_m3_provenance(M3_DIR)
    names = _fighter_name_map()
    latest = bouts["fight_date"].max()
    assert isinstance(latest, date)
    start = latest - timedelta(days=3 * 365)
    records: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"wins": 0, "losses": 0, "last_bout_date": start}
    )
    for bout in bouts.iter_rows(named=True):
        bout_date = bout["fight_date"]
        if bout_date < start:
            continue
        division = division_by_bout.get(str(bout["canonical_bout_id"]))
        if division not in dict(DIVISIONS):
            continue
        winner = bout["winner_canonical_fighter_id"]
        loser = bout["loser_canonical_fighter_id"]
        if not winner or not loser:
            continue
        for fighter_id, field in ((winner, "wins"), (loser, "losses")):
            row = records[(division, str(fighter_id))]
            row[field] += 1
            row["last_bout_date"] = max(row["last_bout_date"], bout_date)
    divisions = []
    for code, label in DIVISIONS:
        candidates = []
        for (fighter_division, fighter_id), record in records.items():
            if fighter_division != code or record["wins"] + record["losses"] < 3:
                continue
            score = _wilson_lower_bound(record["wins"], record["losses"])
            candidates.append(
                {
                    "fighter_id": fighter_id,
                    "display_name": names.get(fighter_id, fighter_id),
                    "wins": record["wins"],
                    "losses": record["losses"],
                    "form_score": round(score, 4),
                    "last_bout_date": record["last_bout_date"],
                }
            )
        candidates.sort(
            key=lambda row: (row["form_score"], row["wins"], row["last_bout_date"]),
            reverse=True,
        )
        if candidates:
            divisions.append({"code": code, "label": label, "fighters": candidates[:4]})
    return {"as_of_date": latest, "window_start": start, "divisions": divisions}
