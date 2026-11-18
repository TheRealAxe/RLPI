"""Indice de performance RLPI (voir rlpi.perf) : par match et global, pour le joueur, ses coéquipiers et ses lobbies.

Par partie : la ligne de chaque joueur dans la table de l'indice (calculée par le worker). Le contenu (moyennes,
intervalles par tirage) est calculé à la volée sur ces lignes : elles sont peu nombreuses.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from rlpi.dashboard import bootstrap

if TYPE_CHECKING:
    from rlpi.context import DataContext
    from rlpi.dashboard.aggregate import GameInput
    from rlpi.dashboard.content import Games

VALIDATION = (
    "n_ref_player_matches",
    "n_ref_matches",
    "auc_player_oof",
    "team_acc_oof",
    "perso_team_acc",
    "perso_n_matches",
    "rlcs_team_acc",
    "rlcs_team_acc_prod",
    "rlcs_team_acc_fond",
    "rlcs_n_matches",
    "retest",
    "split_half",
    "version",
)


def per_game(g: GameInput) -> dict[str, dict]:
    t = g.tables.get("perf")
    if t is None:
        return {}
    return {
        r["player_id"]: {"data": {"perf": r | {"row": i}}, "details": {}} for i, r in enumerate(t.iter_rows(named=True))
    }


def reference(ctx: DataContext) -> dict | None:
    from rlpi.perf import COMPONENTS

    rp = ctx.models / "perf_report.json"
    if not rp.exists():
        return None
    rep = json.loads(rp.read_text(encoding="utf-8"))
    return {
        "components": [{"key": k, "label": lab, "weight": rep["weights"][k]} for k, lab, _ in COMPONENTS],
        "validation": {k: rep.get(k) for k in VALIDATION},
    }


def table(games: Games, my_replays: list[str]) -> pl.DataFrame | None:
    """Lignes de l'indice des parties retenues, dans l'ordre des parties puis de la table de chaque partie."""
    rows = []
    for gm in games.ordered(my_replays):
        part = sorted((pg.data["perf"] for pg in gm.players.values() if "perf" in pg.data), key=lambda r: r["row"])
        rows += [{k: v for k, v in r.items() if k != "row"} for r in part]
    return pl.DataFrame(rows, infer_schema_length=None) if rows else None


def section(
    ref: dict | None, games: Games, player: str, my_replays: list[str], peers: dict[str, pl.DataFrame]
) -> dict | None:
    if ref is None or not games.has_perf:
        return None
    from rlpi.perf import KEYS

    t = table(games, my_replays)
    if t is None:
        t = pl.DataFrame(schema={"replay": pl.String, "player_id": pl.String, "date": pl.String, "index": pl.Float64})
    me = t.filter(pl.col("player_id") == player).sort("date")
    rng = np.random.default_rng(0)

    def summary(df: pl.DataFrame) -> dict | None:
        if df.is_empty():
            return None
        x = df["index"].to_numpy()
        boots = bootstrap.means(rng, x, 2000)
        return {
            "mean": float(x.mean()),
            "lo": float(np.percentile(boots, 10)),
            "hi": float(np.percentile(boots, 90)),
            "n": len(x),
            "comps": {k: float(df[f"c_{k}"].mean()) for k in KEYS},  # type: ignore[arg-type]
            "prod": float(df["prod"].mean()) if "prod" in df.columns else None,  # type: ignore[arg-type]
            "fond": float(df["fond"].mean()) if "fond" in df.columns else None,  # type: ignore[arg-type]
            "win_good": float(df.filter(pl.col("index") >= 50)["won"].mean()) if (df["index"] >= 50).any() else None,  # type: ignore[arg-type]
            "win_bad": float(df.filter(pl.col("index") < 50)["won"].mean()) if (df["index"] < 50).any() else None,  # type: ignore
        }  # type: ignore[arg-type]

    matches = []
    by_game: dict[str, list[dict]] = {}
    for x in t.iter_rows(named=True):
        by_game.setdefault(x["replay"], []).append(x)
    for r in me.iter_rows(named=True):
        game = sorted(by_game[r["replay"]], key=lambda x: -x["index"])  # indice décroissant
        ids = [x["player_id"] for x in game]
        opps = [x for x in game if x["team"] != r["team"]]
        matches.append(
            {
                "replay": r["replay"],
                "date": r["date"],
                "won": bool(r["won"]),
                "index": r["index"],
                "prod": r.get("prod"),
                "fond": r.get("fond"),
                "rank": ids.index(player) + 1,
                "n_players": len(ids),
                "comps": {k: r[f"c_{k}"] for k in KEYS},
                "peers": {
                    pid: float(next(x["index"] for x in game if x["player_id"] == pid)) for pid in peers if pid in ids
                },
                "mates": [
                    {"name": m["player_name"], "index": m["index"]}
                    for m in game
                    if m["team"] == r["team"] and m["player_id"] != player
                ],
                "opp_mean": float(np.mean([o["index"] for o in opps])) if opps else float("nan"),
                "opps": [{"name": o["player_name"], "index": o["index"]} for o in opps],
            }
        )
    last = me.tail(5)["index"].to_numpy()
    mine = summary(me)
    return {
        "components": ref["components"],
        "me": (mine or {}) | {"last5": float(last.mean()) if len(last) else None},
        "peers": {pid: summary(t.filter(pl.col("player_id") == pid)) for pid in peers},
        "lobby": summary(t.filter(~pl.col("player_id").is_in([player, *peers]))),
        "matches": matches,
        "validation": ref["validation"],
    }
