"""Parquet-backed read-only catalog for standalone local operation.

Provides resilient access to the accepted M3 canonical fighters and historical bouts
when PostgreSQL is not running or unconfigured.
"""

from __future__ import annotations

import functools
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

import polars as pl

from ufc_api.data.schemas import DataFreshnessResponse, SourceFreshness
from ufc_api.db.pagination import decode_cursor, encode_cursor
from ufc_api.fighters.schemas import (
    FighterAliasSummary,
    FighterDetail,
    FighterPage,
    FighterSummary,
)
from ufc_api.fights.schemas import (
    FightDetail,
    FighterHistoryPage,
    FightPage,
    FightSummary,
    ParticipantSummary,
    ResultSummary,
)

# Root directory of the repository
_ROOT = Path(__file__).parents[5]
ACCEPTED_M3_GENERATION_ID = "m3-74eeb9b7f49b5adca45e461a"
M3_DIR = _ROOT / "data/processed/m3-v6/.m3-generations" / ACCEPTED_M3_GENERATION_ID
UPCOMING_CSV = _ROOT / "data/upcoming.csv"


@functools.lru_cache(maxsize=1)
def _load_fighters_df() -> pl.DataFrame:
    fighters_path = M3_DIR / "m3_canonical_fighters.parquet"
    if not fighters_path.is_file():
        return pl.DataFrame()
    return pl.read_parquet(fighters_path)


@functools.lru_cache(maxsize=1)
def _load_aliases_df() -> pl.DataFrame:
    aliases_path = M3_DIR / "m3_canonical_fighter_aliases.parquet"
    if not aliases_path.is_file():
        return pl.DataFrame()
    return pl.read_parquet(aliases_path)


@functools.lru_cache(maxsize=1)
def _load_bouts_df() -> pl.DataFrame:
    bouts_path = M3_DIR / "m3_canonical_historical_bouts.parquet"
    if not bouts_path.is_file():
        return pl.DataFrame()
    return pl.read_parquet(bouts_path)


@functools.lru_cache(maxsize=1)
def _load_prefight_history_df() -> pl.DataFrame:
    p = M3_DIR / "m3_prefight_fighter_history.parquet"
    if not p.is_file():
        return pl.DataFrame()
    return pl.read_parquet(p)


@functools.lru_cache(maxsize=1)
def _load_prefight_perf_df() -> pl.DataFrame:
    p = M3_DIR / "m3_prefight_performance_history.parquet"
    if not p.is_file():
        return pl.DataFrame()
    return pl.read_parquet(p)


@functools.lru_cache(maxsize=1)
def _fighter_name_map() -> dict[str, str]:
    """Map canonical_fighter_id to display name."""
    df = _load_fighters_df()
    if df.is_empty():
        return {}
    return dict(
        zip(
            df["canonical_fighter_id"].to_list(),
            df["canonical_display_name"].to_list(),
            strict=False,
        )
    )


@functools.lru_cache(maxsize=1)
def _name_to_fighter_id_map() -> dict[str, str]:
    """Map normalized display name to canonical_fighter_id."""
    df = _load_fighters_df()
    if df.is_empty():
        return {}
    candidates: dict[str, set[str]] = {}
    for fid, name in zip(
        df["canonical_fighter_id"].to_list(), df["canonical_display_name"].to_list(), strict=False
    ):
        candidates.setdefault(name.lower().strip(), set()).add(fid)
    return {name: next(iter(ids)) for name, ids in candidates.items() if len(ids) == 1}


def resolve_canonical_fighter_id(identifier: str) -> str:
    """Return the supplied canonical ID; name-only identity linking is unsafe."""
    return identifier


class ParquetCatalog:
    """Read-only catalog querying immutable Parquet artifacts."""

    @staticmethod
    def get_data_freshness(source: str | None = None) -> DataFreshnessResponse:
        bouts_df = _load_bouts_df()
        fighters_df = _load_fighters_df()
        bouts_count = len(bouts_df)
        fighters_count = len(fighters_df)

        all_sources = [
            SourceFreshness(
                source_id="src-kaggle-ufc-master",
                stable_key="kaggle_raw_csv",
                display_name="Kaggle UFC Historical Bouts CSV",
                source_type="file",
                audit_state="audited",
                dataset_license="CC BY 4.0",
                published_records_count=0,
                quarantined_records_count=0,
                open_quality_issues_count=0,
                status="unknown",
            ),
            SourceFreshness(
                source_id="src-canonical-bouts-parquet",
                stable_key="m3_canonical_bouts",
                display_name="Canonical Bouts Parquet",
                source_type="parquet",
                audit_state="accepted",
                dataset_license="Research-Only / Verified",
                published_records_count=bouts_count,
                quarantined_records_count=0,
                open_quality_issues_count=0,
                status="healthy" if bouts_count else "unavailable",
            ),
            SourceFreshness(
                source_id="src-canonical-fighters-parquet",
                stable_key="m3_canonical_fighters",
                display_name="Fighter Identity & Aliases Registry",
                source_type="parquet",
                audit_state="accepted",
                dataset_license="Research-Only / Deduplicated",
                published_records_count=fighters_count,
                quarantined_records_count=0,
                open_quality_issues_count=0,
                status="healthy" if fighters_count else "unavailable",
            ),
            SourceFreshness(
                source_id="src-upcoming-event-schedule",
                stable_key="upcoming_csv",
                display_name="Local upcoming event schedule",
                source_type="file",
                audit_state="unverified",
                dataset_license=None,
                published_records_count=len(ParquetCatalog.get_upcoming_bouts()),
                quarantined_records_count=0,
                open_quality_issues_count=0,
                status="healthy" if ParquetCatalog.get_upcoming_bouts() else "unavailable",
            ),
            SourceFreshness(
                source_id="src-ufcstats-realtime",
                stable_key="ufcstats_live",
                display_name="UFCStats Realtime",
                source_type="scraper",
                audit_state="quarantined",
                dataset_license="Proprietary (Scraping Prohibited)",
                published_records_count=0,
                quarantined_records_count=0,
                open_quality_issues_count=0,
                status="degraded",
            ),
        ]

        if source:
            filtered = [s for s in all_sources if s.stable_key == source.strip()]
        else:
            filtered = all_sources

        return DataFreshnessResponse(
            sources=filtered,
            accepted_dataset_generation_id=ACCEPTED_M3_GENERATION_ID,
            prediction_cutoff_date="2023-11-11",
            summary_timestamp=datetime.now(UTC),
            limitations=[
                (
                    "Only approved, locally acquired datasets are ingested; "
                    "automated UFCStats scraping is disabled."
                ),
                "Pre-fight features enforce strict cutoff dates before target bout.",
            ],
        )

    @staticmethod
    def list_fighters(
        *, query: str | None = None, limit: int = 25, cursor: str | None = None
    ) -> FighterPage:
        df = _load_fighters_df()
        if df.is_empty():
            return FighterPage(items=[], next_cursor=None, has_more=False)

        if query:
            clean_query = query.strip().lower()
            df = df.filter(
                pl.col("canonical_display_name").str.to_lowercase().str.contains(clean_query)
            )

        df = df.sort(["canonical_display_name", "canonical_fighter_id"])

        if cursor:
            cursor_dict = decode_cursor(cursor)
            cursor_name = str(cursor_dict["display_name"])
            cursor_id = str(cursor_dict["fighter_id"])
            df = df.filter(
                (pl.col("canonical_display_name") > cursor_name)
                | (
                    (pl.col("canonical_display_name") == cursor_name)
                    & (pl.col("canonical_fighter_id") > cursor_id)
                )
            )

        rows = df.head(limit + 1).to_dicts()
        has_more = len(rows) > limit
        page_rows = rows[:limit]

        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            next_cursor = encode_cursor(
                {
                    "display_name": last["canonical_display_name"],
                    "fighter_id": str(last["canonical_fighter_id"]),
                }
            )

        # Count active aliases per fighter
        aliases_df = _load_aliases_df()
        counts: dict[str, int] = {}
        if not aliases_df.is_empty():
            counts_df = aliases_df.group_by("canonical_fighter_id").len()
            counts = dict(
                zip(
                    counts_df["canonical_fighter_id"].to_list(),
                    counts_df["len"].to_list(),
                    strict=False,
                )
            )

        now = datetime.now(UTC)
        items = [
            FighterSummary(
                fighter_id=row["canonical_fighter_id"],
                display_name=row["canonical_display_name"],
                identity_status="active",
                active_alias_count=counts.get(row["canonical_fighter_id"], 1),
                created_at=now,
            )
            for row in page_rows
        ]
        return FighterPage(items=items, next_cursor=next_cursor, has_more=has_more)

    @staticmethod
    def get_fighter(fighter_id: str | UUID) -> FighterDetail | None:
        fid_str = resolve_canonical_fighter_id(str(fighter_id))

        df = _load_fighters_df()
        if df.is_empty():
            return None

        fighter_rows = df.filter(pl.col("canonical_fighter_id") == fid_str).to_dicts()
        if not fighter_rows:
            return None
        fighter = fighter_rows[0]

        aliases_df = _load_aliases_df()
        aliases_list: list[FighterAliasSummary] = []
        if not aliases_df.is_empty():
            alias_rows = aliases_df.filter(pl.col("canonical_fighter_id") == fid_str).to_dicts()
            for a in alias_rows:
                aid = str(uuid5(NAMESPACE_DNS, f"{fid_str}:{a.get('raw_fighter_name', '')}"))
                aliases_list.append(
                    FighterAliasSummary(
                        alias_id=aid,
                        alias_value=a.get("raw_fighter_name", fighter["canonical_display_name"]),
                        normalized_value=a.get("normalized_lookup_key", ""),
                        alias_type=a.get("mapping_type", "name_variant"),
                        source_id=str(uuid5(NAMESPACE_DNS, a.get("source_name", "kaggle"))),
                        is_current=True,
                        resolution_status="approved",
                    )
                )

        if not aliases_list:
            aliases_list.append(
                FighterAliasSummary(
                    alias_id=str(uuid5(NAMESPACE_DNS, f"{fid_str}:primary")),
                    alias_value=fighter["canonical_display_name"],
                    normalized_value=fighter["canonical_display_name"].lower(),
                    alias_type="canonical_primary",
                    source_id=str(uuid5(NAMESPACE_DNS, "canonical")),
                    is_current=True,
                    resolution_status="approved",
                )
            )

        # Compute career stats from prefight history and performance
        stats = None
        hist_df = _load_prefight_history_df()
        perf_df = _load_prefight_perf_df()
        h_row: dict[str, Any] = {}
        if not hist_df.is_empty():
            sub_h = hist_df.filter(pl.col("canonical_fighter_id") == fid_str)
            if not sub_h.is_empty():
                h_row = sub_h.sort("target_fight_date", descending=True).head(1).to_dicts()[0]
        p_row: dict[str, Any] = {}
        if not perf_df.is_empty():
            sub_p = perf_df.filter(pl.col("canonical_fighter_id") == fid_str)
            if not sub_p.is_empty():
                p_row = sub_p.sort("target_fight_date", descending=True).head(1).to_dicts()[0]

        if h_row or p_row:
            from ufc_api.fighters.schemas import FighterCareerStats

            stats = FighterCareerStats(
                wins=int(h_row.get("prior_wins") or 0),
                losses=int(h_row.get("prior_losses") or 0),
                draws=int(h_row.get("prior_draws") or 0),
                ko_wins=int(h_row.get("prior_knockout_tko_wins") or 0),
                sub_wins=int(h_row.get("prior_submission_wins") or 0),
                dec_wins=int(h_row.get("prior_decision_wins") or 0),
                sig_strike_landed_per_min=p_row.get("career_significant_strikes_landed_per_minute"),
                sig_strike_acc=p_row.get("career_significant_strike_accuracy"),
                sig_strike_absorbed_per_min=p_row.get(
                    "career_significant_strikes_landed_absorbed_per_observed_bout"
                ),
                sig_strike_def=p_row.get("career_significant_strike_defense"),
                td_avg_per_15m=p_row.get("career_takedown_attempts_per_15_minutes"),
                td_acc=p_row.get("career_takedown_accuracy"),
                td_def=p_row.get("career_takedown_defense"),
                sub_avg_per_15m=p_row.get("career_submission_attempts_per_15_minutes"),
            )

        name_parts = fighter["canonical_display_name"].split(" ", 1)
        first_name = name_parts[0] if name_parts else fighter["canonical_display_name"]
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        now = datetime.now(UTC)
        return FighterDetail(
            fighter_id=fid_str,
            display_name=fighter["canonical_display_name"],
            first_name=first_name,
            last_name=last_name,
            identity_status="active",
            merged_into_fighter_id=None,
            retired_at=None,
            created_at=now,
            updated_at=now,
            aliases=aliases_list,
            stats=stats,
        )

    @staticmethod
    def get_fighter_history(
        fighter_id: str | UUID,
        *,
        limit: int = 25,
        cursor: str | None = None,
    ) -> FighterHistoryPage | None:
        fid_str = resolve_canonical_fighter_id(str(fighter_id))

        df_fighters = _load_fighters_df()
        if df_fighters.filter(pl.col("canonical_fighter_id") == fid_str).is_empty():
            return None

        bouts_df = _load_bouts_df()
        if bouts_df.is_empty():
            return FighterHistoryPage(
                fighter_id=fid_str, items=[], next_cursor=None, has_more=False
            )

        matches = bouts_df.filter(
            (pl.col("canonical_fighter_a_id") == fid_str)
            | (pl.col("canonical_fighter_b_id") == fid_str)
        ).sort(["fight_date", "canonical_bout_id"], descending=[True, True])

        if cursor:
            cursor_dict = decode_cursor(cursor)
            c_date = cursor_dict.get("fight_date")
            c_bid = cursor_dict.get("fight_id")
            if c_date and c_bid:
                cursor_dt = date.fromisoformat(c_date)
                matches = matches.filter(
                    (pl.col("fight_date") < cursor_dt)
                    | ((pl.col("fight_date") == cursor_dt) & (pl.col("canonical_bout_id") < c_bid))
                )

        rows = matches.head(limit + 1).to_dicts()
        has_more = len(rows) > limit
        page_rows = rows[:limit]

        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            next_cursor = encode_cursor(
                {"fight_date": str(last["fight_date"]), "fight_id": str(last["canonical_bout_id"])}
            )

        names = _fighter_name_map()
        items: list[FightSummary] = []
        for r in page_rows:
            fid_a = r["canonical_fighter_a_id"]
            fid_b = r["canonical_fighter_b_id"]
            name_a = names.get(fid_a, fid_a)
            name_b = names.get(fid_b, fid_b)
            p_a_id = str(uuid5(NAMESPACE_DNS, f"{r['canonical_bout_id']}:a"))
            p_b_id = str(uuid5(NAMESPACE_DNS, f"{r['canonical_bout_id']}:b"))

            participants = [
                ParticipantSummary(
                    participant_id=p_a_id,
                    fighter_id=fid_a,
                    display_name=name_a,
                    canonical_slot=1,
                    source_corner="red",
                ),
                ParticipantSummary(
                    participant_id=p_b_id,
                    fighter_id=fid_b,
                    display_name=name_b,
                    canonical_slot=2,
                    source_corner="blue",
                ),
            ]

            winner_fid = r.get("winner_canonical_fighter_id")
            winner_pid = (
                p_a_id if winner_fid == fid_a else (p_b_id if winner_fid == fid_b else None)
            )

            outcome_type = "decision"
            if r.get("is_no_contest"):
                outcome_type = "no_contest"
            elif r.get("is_draw"):
                outcome_type = "draw"
            elif winner_fid:
                outcome_type = "winner"

            res = ResultSummary(
                result_id=str(uuid5(NAMESPACE_DNS, f"{r['canonical_bout_id']}:result")),
                outcome_type=outcome_type,
                canonical_method_code=r.get("canonical_finish_method"),
                source_outcome_label=r.get("canonical_outcome"),
                source_method_label=r.get("canonical_finish_method"),
                winner_participant_id=winner_pid,
                winner_fighter_id=winner_fid,
            )

            items.append(
                FightSummary(
                    fight_id=str(uuid5(NAMESPACE_DNS, str(r["canonical_bout_id"]))),
                    fight_date=r.get("fight_date"),
                    division_code=r.get("canonical_scheduled_format"),
                    status="completed",
                    scheduled_rounds=int(r.get("scheduled_rounds") or 3),
                    participants=participants,
                    result=res,
                )
            )

        return FighterHistoryPage(
            fighter_id=fid_str,
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    @staticmethod
    def get_fight(fight_id: str | UUID) -> FightDetail | None:
        target_str = str(fight_id)
        bouts_df = _load_bouts_df()
        if bouts_df.is_empty():
            return None

        # Search either by canonical_bout_id or by uuid5 derivative
        matches = bouts_df.filter(pl.col("canonical_bout_id") == target_str).to_dicts()
        if not matches:
            # Check by uuid5 of canonical_bout_id
            for r in bouts_df.iter_rows(named=True):
                bid = str(r["canonical_bout_id"])
                if str(uuid5(NAMESPACE_DNS, bid)) == target_str:
                    matches = [r]
                    break

        if not matches:
            return None
        r = matches[0]
        bid = str(r["canonical_bout_id"])
        fid_a = r["canonical_fighter_a_id"]
        fid_b = r["canonical_fighter_b_id"]
        names = _fighter_name_map()
        name_a = names.get(fid_a, fid_a)
        name_b = names.get(fid_b, fid_b)
        p_a_id = str(uuid5(NAMESPACE_DNS, f"{bid}:a"))
        p_b_id = str(uuid5(NAMESPACE_DNS, f"{bid}:b"))

        participants = [
            ParticipantSummary(
                participant_id=p_a_id,
                fighter_id=fid_a,
                display_name=name_a,
                canonical_slot=1,
                source_corner="red",
            ),
            ParticipantSummary(
                participant_id=p_b_id,
                fighter_id=fid_b,
                display_name=name_b,
                canonical_slot=2,
                source_corner="blue",
            ),
        ]

        winner_fid = r.get("winner_canonical_fighter_id")
        winner_pid = p_a_id if winner_fid == fid_a else (p_b_id if winner_fid == fid_b else None)

        outcome_type = "decision"
        if r.get("is_no_contest"):
            outcome_type = "no_contest"
        elif r.get("is_draw"):
            outcome_type = "draw"
        elif winner_fid:
            outcome_type = "winner"

        res = ResultSummary(
            result_id=str(uuid5(NAMESPACE_DNS, f"{bid}:result")),
            outcome_type=outcome_type,
            canonical_method_code=r.get("canonical_finish_method"),
            source_outcome_label=r.get("canonical_outcome"),
            source_method_label=r.get("canonical_finish_method"),
            winner_participant_id=winner_pid,
            winner_fighter_id=winner_fid,
        )

        now = datetime.now(UTC)
        return FightDetail(
            fight_id=str(uuid5(NAMESPACE_DNS, bid)),
            fight_date=r.get("fight_date"),
            division_code=r.get("canonical_scheduled_format"),
            status="completed",
            publication_state="published",
            event_context_status="not_observed",
            scheduled_rounds=int(r.get("scheduled_rounds") or 3),
            created_at=now,
            updated_at=now,
            participants=participants,
            result=res,
            source_count=0,
        )

    @staticmethod
    def list_fights(
        *,
        division: str | None = None,
        status: str | None = None,
        limit: int = 25,
        cursor: str | None = None,
    ) -> FightPage:
        """Return paginated fights from Parquet when PostgreSQL is unavailable."""
        from ufc_api.fights.schemas import FightPage

        bouts_df = _load_bouts_df()
        if bouts_df.is_empty():
            return FightPage(items=[], next_cursor=None, has_more=False)

        df = bouts_df.sort(["fight_date", "canonical_bout_id"], descending=[True, True])

        if division and "canonical_scheduled_format" in df.columns:
            df = df.filter(
                pl.col("canonical_scheduled_format").str.to_lowercase() == division.lower()
            )

        if cursor:
            offset = int(cursor)
            df = df.slice(offset)
        else:
            offset = 0

        rows = df.head(limit + 1).to_dicts()
        has_more = len(rows) > limit
        page_rows = rows[:limit]

        names = _fighter_name_map()
        items: list[FightSummary] = []
        for r in page_rows:
            bid = str(r["canonical_bout_id"])
            fid_a = r["canonical_fighter_a_id"]
            fid_b = r["canonical_fighter_b_id"]
            name_a = names.get(fid_a, fid_a)
            name_b = names.get(fid_b, fid_b)
            p_a_id = str(uuid5(NAMESPACE_DNS, f"{bid}:a"))
            p_b_id = str(uuid5(NAMESPACE_DNS, f"{bid}:b"))

            ps = [
                ParticipantSummary(
                    participant_id=p_a_id,
                    fighter_id=fid_a,
                    display_name=name_a,
                    canonical_slot=1,
                    source_corner="red",
                ),
                ParticipantSummary(
                    participant_id=p_b_id,
                    fighter_id=fid_b,
                    display_name=name_b,
                    canonical_slot=2,
                    source_corner="blue",
                ),
            ]

            winner_fid = r.get("winner_canonical_fighter_id")
            winner_pid = (
                p_a_id if winner_fid == fid_a else (p_b_id if winner_fid == fid_b else None)
            )

            outcome_type = "decision"
            if r.get("is_no_contest"):
                outcome_type = "no_contest"
            elif r.get("is_draw"):
                outcome_type = "draw"
            elif winner_fid:
                outcome_type = "winner"

            result = ResultSummary(
                result_id=str(uuid5(NAMESPACE_DNS, f"{bid}:result")),
                outcome_type=outcome_type,
                canonical_method_code=r.get("canonical_finish_method"),
                source_outcome_label=r.get("canonical_outcome"),
                source_method_label=r.get("canonical_finish_method"),
                winner_participant_id=winner_pid,
                winner_fighter_id=winner_fid,
            )

            items.append(
                FightSummary(
                    fight_id=str(uuid5(NAMESPACE_DNS, bid)),
                    fight_date=r.get("fight_date"),
                    division_code=r.get("canonical_scheduled_format"),
                    status="completed",
                    scheduled_rounds=int(r.get("scheduled_rounds") or 3),
                    participants=ps,
                    result=result,
                )
            )

        next_cursor = str(offset + limit) if has_more else None
        return FightPage(items=items, next_cursor=next_cursor, has_more=has_more)

    @staticmethod
    def get_upcoming_bouts() -> list[dict[str, Any]]:
        """Parse authentic upcoming bouts from data/upcoming.csv."""
        if not UPCOMING_CSV.is_file():
            return []
        try:
            df = pl.read_csv(UPCOMING_CSV)
        except Exception:
            return []

        name_to_id = _name_to_fighter_id_map()
        bouts: list[dict[str, Any]] = []

        for row in df.iter_rows(named=True):
            r_name = str(row.get("R_fighter", "")).strip()
            b_name = str(row.get("B_fighter", "")).strip()
            if not r_name or not b_name:
                continue

            r_id = name_to_id.get(r_name.lower())
            b_id = name_to_id.get(b_name.lower())
            if r_id is None or b_id is None:
                continue

            fight_date_str = str(row.get("date", ""))
            try:
                f_date = date.fromisoformat(fight_date_str)
            except ValueError:
                continue
            if f_date <= date.today():
                continue

            weight_class = str(row.get("weight_class", "Catchweight"))
            rounds = int(row.get("no_of_rounds") or 3)
            location = str(row.get("location", "Las Vegas, Nevada, USA"))
            is_title = bool(row.get("title_bout", False))

            bout_id = str(uuid5(NAMESPACE_DNS, f"upcoming:{f_date}:{r_name}:{b_name}"))

            bouts.append(
                {
                    "bout_id": bout_id,
                    "event_name": f"UFC Fight Night: {location}",
                    "fight_date": f_date.isoformat(),
                    "location": location,
                    "fighter_a": {
                        "fighter_id": r_id,
                        "display_name": r_name,
                        "odds": row.get("R_odds"),
                        "reach_cms": row.get("R_Reach_cms"),
                        "height_cms": row.get("R_Height_cms"),
                        "weight_lbs": row.get("R_Weight_lbs"),
                        "stance": row.get("R_Stance"),
                        "age": row.get("R_age"),
                        "wins": row.get("R_wins"),
                        "losses": row.get("R_losses"),
                    },
                    "fighter_b": {
                        "fighter_id": b_id,
                        "display_name": b_name,
                        "odds": row.get("B_odds"),
                        "reach_cms": row.get("B_Reach_cms"),
                        "height_cms": row.get("B_Height_cms"),
                        "weight_lbs": row.get("B_Weight_lbs"),
                        "stance": row.get("B_Stance"),
                        "age": row.get("B_age"),
                        "wins": row.get("B_wins"),
                        "losses": row.get("B_losses"),
                    },
                    "weight_class": weight_class,
                    "scheduled_rounds": rounds,
                    "is_title_bout": is_title,
                    "card_placement": "main_card" if rounds == 5 or is_title else "prelims",
                }
            )

        return bouts
