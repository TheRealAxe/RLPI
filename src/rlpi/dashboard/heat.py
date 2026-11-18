"""Cartes de chaleur : où le joueur passe son temps (jeu en cours) et où il touche la balle, terrain orienté
vers l'attaque. Par partie : une grille de comptes par joueur (additive) ; la référence RLCS est calculée une fois."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

if TYPE_CHECKING:
    from rlpi.context import DataContext
    from rlpi.dashboard.aggregate import GameInput
    from rlpi.dashboard.content import Games

GRID_X, GRID_Y = 8, 10  # cases du terrain (largeur × longueur) : ~1 000 × 1 000 uu, assez pour 24 parties
CELLS = GRID_X * GRID_Y
STEP = 5  # une image sur 5 (2 par seconde)
N_PRO = 200


def _bins(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    gx = np.clip(((x + 4096) / 8192 * GRID_X).astype(int), 0, GRID_X - 1)
    gy = np.clip(((y + 5120) / 10240 * GRID_Y).astype(int), 0, GRID_Y - 1)
    return gy * GRID_X + gx


def occupancy(meta: dict, frames: pl.DataFrame | None, step: int = STEP) -> dict[str, np.ndarray]:
    """Comptes de présence par case, pour chaque joueur de la partie (jeu en cours seulement)."""
    out: dict[str, np.ndarray] = {}
    if frames is None:
        return out
    play = frames["phase"].to_numpy() == 1
    for p in meta["players"]:
        s = 1 if p["team"] == 0 else -1
        x = s * frames[f"p{p['slot']}_x"].to_numpy()[play][::step]
        y = s * frames[f"p{p['slot']}_y"].to_numpy()[play][::step]
        h = np.bincount(_bins(x, y), minlength=CELLS)
        out[p["id"]] = out[p["id"]] + h if p["id"] in out else h
    return out


def touch_grid(df: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Nombre de touches et somme des ΔV par case."""
    b = _bins(df["ball_x"].to_numpy(), df["ball_y"].to_numpy())
    n = np.bincount(b, minlength=CELLS)
    sdv = np.bincount(b, weights=df["dv"].to_numpy(), minlength=CELLS)
    return n, sdv


def _r(a: np.ndarray) -> list:
    return [None if not np.isfinite(v) else round(float(v), 5) for v in a]


def per_game(g: GameInput) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for pid, h in occupancy(g.meta, g.frames()).items():
        out[pid] = {"data": {"occ": h.tolist()}, "details": {}}
    tv = g.tables.get("touch_values")
    if tv is not None and tv.height:
        for (pid,), d in tv.group_by("player_id", maintain_order=True):
            n, sdv = touch_grid(d)
            slot = out.setdefault(str(pid), {"data": {}, "details": {}})
            slot["details"]["touch_grid"] = {"n": n.tolist(), "sdv": sdv.tolist()}
    return out


def reference(ctx: DataContext) -> dict:
    frames = ctx.frames("rlcs")
    pros = sorted(p.name.removesuffix(".meta.json") for p in frames.glob("*.meta.json"))
    pros = pros[:: max(1, len(pros) // N_PRO)][:N_PRO]
    h = np.zeros(CELLS)
    for r in pros:
        mp = frames / f"{r}.meta.json"
        m = json.loads(mp.read_text(encoding="utf-8"))
        cols = ["phase"] + [f"p{p['slot']}_{a}" for p in m["players"] for a in ("x", "y")]
        for g in occupancy(m, pl.read_parquet(mp.with_name(r + ".parquet"), columns=cols)).values():
            h += g
    occ = h / h.sum() if h.sum() else h
    rl = pl.read_parquet(ctx.feature("touch_values", "rlcs"))
    n_pro_t, sdv = touch_grid(rl)
    dv_pro = np.where(n_pro_t > 0, sdv / np.maximum(n_pro_t, 1), np.nan)
    return {
        "n_pro_replays": len(pros),
        "occ_pro": _r(occ),
        "touch_share_pro": _r(n_pro_t / n_pro_t.sum()),
        "touch_dv_pro": _r(dv_pro),
    }


def section(ref: dict | None, games: Games, player: str, my_replays: list[str]) -> dict | None:
    if ref is None:
        return None
    occ_me, occ_lobby = np.zeros(CELLS), np.zeros(CELLS)
    n_me, sdv_me = np.zeros(CELLS, dtype=np.int64), np.zeros(CELLS)
    for r in my_replays:
        for pid, pg in games.by_replay[r].players.items():
            occ = pg.data.get("occ")
            if occ is not None:
                if pid == player:
                    occ_me += occ
                else:
                    occ_lobby += occ
            if pid == player and "touch_grid" in pg.details:
                n_me += np.asarray(pg.details["touch_grid"]["n"], dtype=np.int64)
                sdv_me += pg.details["touch_grid"]["sdv"]
    norm = lambda h: h / h.sum() if h.sum() else h  # noqa: E731
    dv_me = np.where(n_me > 0, sdv_me / np.maximum(n_me, 1), np.nan)
    return {
        "gx": GRID_X,
        "gy": GRID_Y,
        "n_pro_replays": ref["n_pro_replays"],
        "occ_me": _r(norm(occ_me)),
        "occ_lobby": _r(norm(occ_lobby)),
        "occ_pro": ref["occ_pro"],
        "touch_n": [int(v) for v in n_me],
        "touch_dv": _r(dv_me),
        "touch_share_pro": ref["touch_share_pro"],
        "touch_dv_pro": ref["touch_dv_pro"],
        "n_touches": int(n_me.sum()),
    }
