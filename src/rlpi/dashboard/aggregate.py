"""Agrégats d'une partie : tout ce dont le tableau de bord a besoin, calculé une fois par partie (par le worker).

    compute(GameInput) → {"match_id", "replay", "version", "game": {…}, "players": {joueur: {"cols", "data", "details"}}}

- game     : date, durée de jeu, score, joueurs (équipe, emplacement), courbe de valeur, lignes de synergie ;
- cols     : identité du joueur et indicateurs par partie (colonnes typées de player_game_aggregates) ;
- data     : petits détails lus pour tous les joueurs des parties (touches, passes, indice, traits, présence…) ;
- details  : détails lus seulement pour le joueur affiché (pires touches, courbe, grille des touches, passes perdues).

Les entrées viennent d'un dossier de partie du worker (from_game_dir) ou d'un dossier de données classique, partie
par partie (from_context, ligne de commande). Changer un calcul de ce module : augmenter VERSION ; le worker
recalcule alors les parties (rlpi.dashboard.storage).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from rlpi.dashboard import heat, passes, perf, style, synergy, value
from rlpi.dashboard.common import ensure_columns, stem
from rlpi.dashboard.metrics import COMPO_COLUMNS, KEYS, TECH_KEYS, metrics, tech_metrics

if TYPE_CHECKING:
    from rlpi.context import DataContext

VERSION = 1
GAME_SOURCE = "partie"  # comme rlpi.game
TABLES = ("player_match_stats", "touch_values", "goal_xv", "touch_decisions", "placement", "passes", "perf")
# Colonnes brutes lues par les indicateurs et les traits de style : absentes d'une partie = vides (voir ensure_columns)
RAW_COLUMNS = [
    "boost.amount_collected",
    "boost.amount_collected_small",
    "boost.amount_stolen",
    "boost.amount_used",
    "boost.boost_integral",
    "boost.overfill_total",
    "boost.time_hundred_boost",
    "boost.time_zero_boost",
    "boost.tracked_time",
    "bump.bumps_inflicted",
    "core.goals",
    "core.saves",
    "core.shots",
    "demo.demos_inflicted",
    "fifty_fifty.count",
    "fifty_fifty.kickoff_losses",
    "fifty_fifty.kickoff_wins",
    "fifty_fifty.losses",
    "fifty_fifty.wins",
    "movement.speed_integral",
    "movement.time_high_air",
    "movement.time_on_ground",
    "movement.time_slow_speed",
    "movement.time_supersonic_speed",
    "movement.tracked_time",
    "pass.completed_pass_count",
    "positioning.time_behind_ball",
    "positioning.time_defensive_third",
    "positioning.time_has_possession",
    "positioning.time_in_front_of_ball",
    "positioning.time_offensive_half",
    "positioning.time_shadow_defense",
    "positioning.tracked_time",
    "rotation.active_game_time",
    "rotation.time_first_man",
    "rotation.time_third_man",
    "touch.aerial_touch_count",
    "touch.control_touch_count",
    "touch.hard_hit_count",
    "touch.high_aerial_touch_count",
    "touch.touch_count",
    "touch.wall_touch_count",
    "whiff.aerial_whiff_count",
    "whiff.beaten_to_ball_count",
    "whiff.whiff_count",
]
VALUE_COLUMNS = [*KEYS, *TECH_KEYS]  # indicateurs par partie (colonnes typées en base)


@dataclass
class GameInput:
    match_id: str
    meta: dict
    frames_path: Path | None
    tables: dict[str, pl.DataFrame]
    curves: list[dict] = field(default_factory=list)
    _frames: pl.DataFrame | None = None

    @property
    def replay(self) -> str:
        return self.meta["replay"]

    @property
    def play_s(self) -> float:
        return self.meta["n_play_frames"] / 10

    def frames(self) -> pl.DataFrame | None:
        if self._frames is None and self.frames_path is not None and self.frames_path.exists():
            self._frames = pl.read_parquet(self.frames_path)
        return self._frames


def from_game_dir(d: Path, match_id: str | None = None) -> GameInput:
    """Dossier d'une partie traitée par rlpi.game run (ou téléchargé depuis games/<partie>/)."""
    metas = sorted((d / "frames" / GAME_SOURCE).glob("*.meta.json"))
    if len(metas) != 1:
        raise ValueError(f"{d} : {len(metas)} fichier(s) .meta.json au lieu d'un")
    meta = json.loads(metas[0].read_text(encoding="utf-8"))
    tables = {}
    for t in TABLES:
        f = d / "features" / f"{t}_{GAME_SOURCE}.parquet"
        if f.exists():
            tables[t] = pl.read_parquet(f)
    cf = d / "features" / f"value_curves_{GAME_SOURCE}.json"
    curves = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else []
    return GameInput(match_id or d.name, meta, metas[0].with_name(meta["replay"] + ".parquet"), tables, curves)


def from_context(ctx: DataContext, source: str | None = None) -> Iterator[GameInput]:
    """Parties d'un dossier de données classique (tables de toutes les parties rassemblées), une par une."""
    source = source or ctx.source
    tables = {t: pl.read_parquet(f) for t in TABLES if (f := ctx.feature(t, source)).exists()}
    if "player_match_stats" in tables:
        st = tables["player_match_stats"]
        tables["player_match_stats"] = st.with_columns(
            pl.col("replay_file").map_elements(stem, return_dtype=pl.String).alias("replay")
        )
    cf = ctx.feature("value_curves", source, "json")
    curves = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else []
    by_curve: dict[str, list[dict]] = {}
    for c in curves:
        by_curve.setdefault(c["replay"], []).append(c)
    parts = {t: {str(k[0]): v for k, v in df.partition_by("replay", as_dict=True).items()} for t, df in tables.items()}
    for mp in sorted(ctx.frames(source).glob("*.meta.json")):
        meta = json.loads(mp.read_text(encoding="utf-8"))
        r = meta["replay"]
        own = {t: p[r] for t, p in parts.items() if r in p}
        if "player_match_stats" in own:
            own["player_match_stats"] = own["player_match_stats"].drop("replay")
        yield GameInput(r, meta, mp.with_name(r + ".parquet"), own, by_curve.get(r, []))


def _merge(out: dict, parts: dict[str, dict]) -> None:
    for pid, p in parts.items():
        slot = out.setdefault(pid, {"cols": {}, "data": {}, "details": {}})
        slot["data"].update(p.get("data", {}))
        slot["details"].update(p.get("details", {}))


def compute(g: GameInput) -> dict:
    meta = g.meta
    players: dict[str, dict] = {}
    for p in meta["players"]:
        players.setdefault(
            p["id"],
            {
                "cols": {"player_name": p.get("name"), "team": p.get("team"), "in_stats": False},
                "data": {},
                "details": {},
            },
        )
    st = g.tables.get("player_match_stats")
    if st is not None and st.height:
        present = [c for c in COMPO_COLUMNS if c in st.columns]
        m = tech_metrics(metrics(ensure_columns(st, RAW_COLUMNS)))
        for i, r in enumerate(m.iter_rows(named=True)):
            slot = players.setdefault(r["player_id"], {"cols": {}, "data": {}, "details": {}})
            slot["cols"] = {
                "player_name": r["player_name"],
                "team": r["team"],
                "in_stats": True,
                "is_bot": bool(r["is_bot"]),
                "date": r["date"],
                "won": r["won"],
                "team_goals": r["team_goals"],
                "opp_goals": r["opp_goals"],
                **{k: r[k] for k in VALUE_COLUMNS},
            }
            slot["data"]["row"] = i
            slot["data"]["compo"] = {c: r[c] for c in present}
    for mod in (value, passes, heat, perf, style):
        _merge(players, mod.per_game(g))
    return {
        "match_id": g.match_id,
        "replay": g.replay,
        "version": VERSION,
        "game": {
            "date": meta["date"],
            "play_s": g.play_s,
            "score": [meta["team0_score"], meta["team1_score"]],
            "players": [{k: p.get(k) for k in ("id", "name", "team", "slot")} for p in meta["players"]],
            "curve": value.curve(g),
            "pairs": synergy.per_game(g),
        },
        "players": players,
    }
