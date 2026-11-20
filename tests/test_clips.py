"""Ralentis (rlpi.clips) : choix des touches à découper, sans replay."""

import polars as pl

from rlpi import clips


def test_touches_demandees_puis_les_plus_couteuses():
    tv = pl.DataFrame(
        {
            "replay": ["r"] * 6,
            "i": [10, 20, 30, 40, 50, 60],
            "player_id": ["a", "a", "a", "a", "b", "a"],
            "action": ["tir"] * 6,
            "dv": [0.1, -0.5, -0.2, 0.3, -0.9, -0.1],
        }
    )
    got = clips.picks(tv, "a", [40, 999], n_prefetch=3)
    # demandée d'abord (999 inconnue : ignorée), puis les 3 plus coûteuses du joueur, sans doublon ni touche d'un autre
    assert [p["i"] for p in got] == [40, 20, 30, 60]
    assert all(p["player_id"] == "a" and p["origin"] == "perso" for p in got)


def test_roles_des_voitures_et_camera_balle():
    import numpy as np

    from rlpi import pov

    players = [
        {"id": "x", "team": 1},
        {"id": "a", "team": 0},
        {"id": "b", "team": 0},
        {"id": "y", "team": 1},
        {"id": "c", "team": 0},
        {"id": "z", "team": 1},
    ]
    team, role = pov.kinds(players, "b")
    assert team == 0 and role == {"x": "opp", "a": "mate1", "b": "me", "y": "opp", "c": "mate2", "z": "opp"}
    # caméra balle allumée par défaut, puis selon les bascules enregistrées dans le replay
    assert pov.ballcam_at([(1.0, False), (2.5, True)], np.array([0.5, 1.0, 2.0, 3.0])) == [1, 0, 0, 1]
    assert pov.ballcam_at([], np.array([0.0])) == [1]
