"""Balles données (vers l'avant / le côté / l'arrière) : récupérées par un coéquipier ou perdues.

Par partie et par joueur, on garde des comptes (additifs) ; les 10 balles perdues « dans le vide » les plus
coûteuses du joueur sont gardées dans ses détails.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from rlpi.context import DataContext
    from rlpi.dashboard.aggregate import GameInput
    from rlpi.dashboard.content import Games

ACT_FR = {"forward": "Vers l'avant", "side": "Latérale", "back": "En retrait"}
N_VOID = 10
MATE = "coéquipier"


def _void(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter((~pl.col("mate_closer")) & (pl.col("next") == "adversaire")).sort("dv_2s").head(N_VOID)


def counts(df: pl.DataFrame) -> dict:
    """Comptes additifs des passes d'un joueur dans une partie."""
    ok = df.filter(pl.col("next").is_not_null())
    rec = ok["next"] == MATE
    mate = ok["mate_closer"]
    nobody = ok.filter(~pl.col("mate_closer"))
    dv = nobody["dv_2s"].drop_nulls()
    return {
        "n": df.height,
        "n_mate": int(df["mate_closer"].sum()),
        "n_ok": ok.height,
        "tt": int((mate & rec).sum()),
        "ft": int((~mate & rec).sum()),
        "tf": int((mate & ~rec).sum()),
        "ff": int((~mate & ~rec).sum()),
        "void": int(((~mate) & (ok["next"] == "adversaire")).sum()),
        "dv_nobody": [float(dv.sum()), dv.len()],
        "date": df["date"][0],
    }


def per_game(g: GameInput) -> dict[str, dict]:
    t = g.tables.get("passes")
    out: dict[str, dict] = {}
    if t is None or not t.height:
        return out
    for (pid,), d in t.group_by("player_id", maintain_order=True):
        out[str(pid)] = {
            "data": {"passes": counts(d)},
            "details": {
                "void": [
                    {
                        "date": x["date"],
                        "clock": x["clock"],
                        "act": ACT_FR.get(x["act"], x["act"]),
                        "dv": x["dv_2s"],
                        "x": x["ball_x"],
                        "y": x["ball_y"],
                        "d_mate": x["d_mate"] / 100,
                        "d_opp": x["d_opp"] / 100,
                        "delay": x["delay_s"],
                    }
                    for x in _void(d).iter_rows(named=True)
                ]
            },
        }
    return out


def summary(rows: list[tuple[dict, float]], key: str, label: str) -> dict:
    """rows : (comptes d'un joueur dans une partie, durée de jeu de la partie)."""
    s = {k: sum(c[k] for c, _ in rows) for k in ("n", "n_mate", "n_ok", "tt", "ft", "tf", "ff", "void")}
    dv_sum = sum(c["dv_nobody"][0] for c, _ in rows)
    dv_n = sum(c["dv_nobody"][1] for c, _ in rows)
    play = sum(p for _, p in rows)
    n, ok = s["n"], s["n_ok"]
    n_mate_ok, n_nobody = s["tt"] + s["tf"], s["ft"] + s["ff"]
    return {
        "key": key,
        "label": label,
        "n": n,
        "n_games": len(rows),
        "per5": n / play * 300 if play else None,
        "recovered": (s["tt"] + s["ft"]) / ok if ok else None,
        "mate_pos": s["n_mate"] / n if n else None,
        "rec_mate": s["tt"] / n_mate_ok if n_mate_ok else None,
        "rec_nobody": s["ft"] / n_nobody if n_nobody else None,
        "dv_nobody": (dv_sum / dv_n if dv_n else None) if n_nobody else None,
        "void_lost": s["void"] / ok if ok else None,
        # issues exactes (somme = 100 %) : récupérée en position / récupérée sans / perdue en position / dans le vide
        "split": [s[k] / ok for k in ("tt", "ft", "tf", "ff")] if ok else None,
    }


def reference(ctx: DataContext, play_seconds) -> dict | None:
    """Groupe « Pros RLCS », calculé sur toutes les passes de la référence."""
    fr_ = ctx.feature("passes", "rlcs")
    if not fr_.exists():
        return None
    r = pl.read_parquet(fr_)
    secs = play_seconds(ctx, "rlcs")
    rows = []
    for (rp, _pid), d in r.group_by("replay", "player_id", maintain_order=True):
        rows.append((counts(d), secs.get(rp, 0)))
    return summary(rows, "rlcs", "Pros RLCS")


def section(
    ref: dict | None, games: Games, player: str, my_replays: list[str], peers: dict[str, pl.DataFrame]
) -> dict | None:
    if ref is None or not games.has_passes:
        return None
    by: dict[str, list[tuple[dict, float]]] = {}
    mine = []
    for r in my_replays:
        gm = games.by_replay[r]
        for pid, pg in gm.players.items():
            c = pg.data.get("passes")
            if c is None:
                continue
            grp = "me" if pid == player else (pid if pid in peers else "lobby")
            by.setdefault(grp, []).append((c, gm.play_s))
            if pid == player:
                mine.append((gm, pg, c))
    groups = [summary(by.get("me", []), "me", "Toi")]
    for pid, d in peers.items():
        groups.append(summary(by.get(pid, []), pid, d["player_name"][-1]))
    groups.append(summary(by.get("lobby", []), "lobby", "Lobbies"))
    groups.append(ref)

    per_match = []
    for gm, _pg, c in mine:
        ok = c["n_ok"]
        per_match.append(
            {
                "replay": gm.replay,
                "date": c["date"],
                "n": c["n"],
                "per5": c["n"] / gm.play_s * 300,
                "recovered": (c["tt"] + c["ft"]) / ok if ok else None,
                "void_lost": c["void"] / ok if ok else None,
            }
        )
    per_match.sort(key=lambda m: m["date"])
    cand = [x for _gm, pg, _c in mine for x in pg.details.get("void", [])]
    void = pl.DataFrame(cand, infer_schema_length=None).sort("dv").head(N_VOID).to_dicts() if cand else []
    return {"groups": groups, "matches": per_match, "void": void}
