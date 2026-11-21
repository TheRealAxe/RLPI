"""Clips au format du player 3D (rlpi.pov), faits à partir du replay lu par rlpi.clips."""

from __future__ import annotations

import numpy as np

from rlpi import clips, pov
from tests.test_clips import GH, META, PH, RAW

JH = ["dodge active", "jump active", "double jump active"]


def track_with_jumps(n: int = 1200) -> clips.Track:
    """Partie fictive de test_clips, avec les compteurs de saut : la voiture 4 saute de l'image 500 à 559 (compteur
    impair pendant le saut), puis fait un dodge de 600 à 629."""
    from tests.test_clips import synthetic

    base = synthetic(n)
    ph = PH + JH
    a = np.zeros((n, len(GH) + 6 * len(ph)), np.float32)
    a[:, : len(GH)] = base.a[:, : len(GH)]
    for k in range(6):
        a[:, len(GH) + k * len(ph) : len(GH) + k * len(ph) + len(PH)] = base.a[
            :, len(GH) + k * len(PH) : len(GH) + (k + 1) * len(PH)
        ]
    b = len(GH) + 4 * len(ph)
    a[500:560, b + ph.index("jump active")] = 3
    a[560:, b + ph.index("jump active")] = 4
    a[600:630, b + ph.index("dodge active")] = 5
    a[630:, b + ph.index("dodge active")] = 6
    a[:, b + ph.index("double jump active")] = np.nan  # compteur absent : 0
    return clips.Track(a, GH, ph)


def test_roles_des_voitures():
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


def test_clip_repere_de_l_auteur_et_sauts():
    tr = track_with_jumps()
    meta = {"players": [p | {"name": f"J{p['slot']}"} for p in META["players"]]}
    c = pov.clip(tr, meta, 600, "Steam:4", before=4.0, after=2.0, cams=None)
    assert c is not None and c["format"] == 2 and c["fps"] == 30 and c["t0"] == 120
    assert len(c["ball"]["x"]) == 181
    # l'auteur est dans l'équipe 1 : x et y retournés (balle en (6000, 500) sur le terrain), z inchangé
    assert [c["ball"][k][120] for k in "xyz"] == [-6000, -500, 93]
    me = c["cars"][4]
    assert me["kind"] == "me" and me["name"] == "J4" and me["x"][0] == -400
    assert me["fwd"][0][0] == -1.0 and me["up"][2][0] == 1.0  # avant retourné avec le repère, haut inchangé
    assert me["boost"][0] == 100
    # image k du clip = image 120 + 4k du replay (la touche, image 600, est l'image 120 du clip)
    assert me["jump"][93:97] == [0, 0, 1, 1] and me["jump"][108:112] == [1, 1, 0, 0]  # saut : images 500 à 559
    assert me["dodge"][119:130] == [0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0]  # dodge : images 600 à 629
    assert set(me["djump"]) == {0} and set(c["cars"][0]["jump"]) == {0}
    assert c["cam"] is None


def test_clip_camera_de_l_auteur():
    tr = track_with_jumps()
    cams = {"players": {"Steam:0": {"settings": None, "ball_cam": [[0.0, 1], [4.9, 0]]}}}
    c = pov.clip(tr, META, 600, "Steam:0", before=4.0, after=2.0, cams=cams)
    assert c is not None and c["cam"] is not None
    assert c["cam"]["settings"] == {}  # réglages non relevés : ceux du jeu par défaut dans le player
    assert c["cam"]["ballcam"][116] == 1 and c["cam"]["ballcam"][120] == 0
    assert [c["ball"][k][120] for k in "xyz"] == [6000, 500, 93]  # équipe 0 : repère du terrain


def test_clip_trop_pres_du_bord():
    assert pov.clip(track_with_jumps(), META, 100, "Steam:4", before=4.0, after=2.0) is None


def test_clip_vrai_replay_sauts():
    """Sur un vrai replay : les colonnes de saut sont lues et quelqu'un saute pendant une partie entière."""
    if not RAW:
        import pytest

        pytest.skip("aucun replay dans data/raw/")
    tr = clips.read_replay(RAW[0])
    assert all(h in tr.player_headers for h in JH)
    col = tr.car_col(0, "jump active")
    assert np.nanmax(tr.a[:, col]) >= 3
