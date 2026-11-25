"""Corrections de l'audit de l'impact (docs/AUDIT_IMPACT_2026-11-24.md) : F1, F2, F3 et simulateur de balle."""

from __future__ import annotations

import numpy as np
import polars as pl

from rlpi import ballsim, perf, value


def test_ballsim_chute_libre_et_rebond():
    # balle lâchée à 1 000 uu : touche le sol après √(2·(1000−R)/650) ≈ 1,67 s puis remonte (restitution 0,6)
    _, _, P = ballsim.simulate([0, 0, 1000], [0, 0, 0], None, 3.0, sample_every=0.05)
    z = P[:, 0, 2]
    assert z.min() >= ballsim.R - 5
    k = int(np.argmin(z[:40]))
    assert 1.55 <= (k + 1) * 0.05 <= 1.8
    assert 300 < z[k:].max() < 600  # rebond plus bas que la hauteur de départ


def test_ballsim_but_et_ligne_droite():
    goal, t, _ = ballsim.simulate(
        [[0, 3000, 200], [0, -3000, 200], [3000, 0, 200]], [[0, 2500, 0], [0, -2500, 0], [0, 0, 0]], None, 3.0
    )
    assert goal.tolist() == [0, 1, -1]
    assert 0.8 < t[0] < 1.2 and np.isinf(t[2])


def test_ballsim_poteau_et_mur():
    # à côté du cadre : rebond sur le mur du fond, pas de but
    goal, _, P = ballsim.simulate([2000, 3000, 300], [0, 2500, 0], None, 2.0, sample_every=0.5)
    assert goal[0] == -1 and P[-1, 0, 1] < ballsim.BACK_Y


def test_goal_lines_coherent_avec_simulate():
    rng = np.random.default_rng(1)
    x = np.column_stack([rng.uniform(-3000, 3000, 300), rng.uniform(-4000, 4000, 300), rng.uniform(100, 1500, 300)])
    v = rng.normal(0, 1500, (300, 3))
    g, _, _ = ballsim.simulate(x, v, None, 4.0)
    o = ballsim.goal_lines(x, v, None, 4.0)
    assert np.mean((g == 0) == (o["in_pos"] == 1)) > 0.97
    assert np.mean((g == 1) == (o["in_neg"] == 1)) > 0.97


def _touches(rows):
    return pl.DataFrame(
        rows,
        schema={
            "i": pl.Int64,
            "slot": pl.Int64,
            "team": pl.Int64,
            "action": pl.Utf8,
            "kind": pl.Utf8,
            "height": pl.Utf8,
            "role": pl.Utf8,
            "ball_speed_change": pl.Float64,
        },
        orient="row",
    )


def test_f3_une_touche_par_joueur_et_par_image():
    t = value.merge_same_frame(
        _touches(
            [
                (100, 0, 0, None, "control", None, None, 100.0),
                (100, 0, 0, "shot", "hard_hit", None, None, 900.0),
                (100, 1, 0, None, "control", None, None, 50.0),  # coéquipier sur la même image
                (100, 3, 1, None, "hard_hit", None, None, 300.0),  # adversaire (50/50) : crédit non partagé
                (120, 0, 0, "pass", "medium_hit", None, None, 400.0),
            ]
        )
    )
    assert t.height == 4
    r = t.filter((pl.col("i") == 100) & (pl.col("slot") == 0)).row(0, named=True)
    assert r["action"] == "shot" and r["ball_speed_change"] == 1000.0 and r["share"] == 0.5
    assert t.filter(pl.col("slot") == 3)["share"].item() == 1.0
    assert t.filter(pl.col("i") == 120)["share"].item() == 1.0


def test_f1_but_de_loin_rattache_au_tireur():
    goals = [{"i": 130, "team": 0}]
    # tir à 100, but à 130 (3 s), aucune touche entre : la fenêtre va jusqu'au but
    assert value.touch_window(100, 500, 1000, goals, team=0) == 130
    # pour l'équipe qui encaisse, fenêtre habituelle (1 s)
    assert value.touch_window(100, 500, 1000, goals, team=1) == 110
    # une touche entre le tir et le but : fenêtre habituelle
    assert value.touch_window(100, 120, 1000, goals, team=0) == 110
    # but trop tard (> 4 s)
    assert value.touch_window(100, 500, 1000, [{"i": 150, "team": 0}], team=0) == 110


def test_f2_arret_sur_balle_qui_rentrait_non_puni():
    tv = pl.DataFrame(
        {
            "replay": ["r", "r"],
            "i": [100, 200],
            "team": [1, 1],
            "v_before": [-0.3, -0.3],
            "v_after": [-1.0, -1.0],
            "dv": [-0.7, -0.7],
            "share": [1.0, 1.0],
            "going_in_own": [True, False],
        }
    )
    gx = pl.DataFrame({"replay": ["r", "r"], "goal_i": [110, 210], "scorer_team": [0, 0], "v_team0": [0.8, 0.8]})
    out = perf.xv(tv, gx).sort("i")
    assert out["dv_xv"].to_list()[0] == 0.0
    assert out["dv_xv"].to_list()[1] < -0.4
