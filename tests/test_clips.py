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
