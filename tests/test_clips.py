"""Découpe des clips 3D (rlpi.clips) : calage d'une touche dans le replay et carte SwipeCard.

Les tests sur un vrai replay utilisent le premier fichier de data/raw/ (sautés s'il n'y en a pas, en CI par exemple).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from rlpi import clips

ROOT = Path(__file__).resolve().parents[1]
RAW = sorted((ROOT / "data" / "raw").glob("*.replay"))

AXES = "xyz"
GH = [f"Ball - {k} {c}" for k in ("position", "linear velocity") for c in AXES]
PH = [f"{k} {c}" for k in ("position", "linear velocity", "forward", "up") for c in AXES] + [
    "boost level (raw replay units)"
]
META = {"players": [{"slot": k, "team": k // 3, "id": f"Steam:{k}"} for k in range(6)]}


def synthetic(n: int = 1200) -> clips.Track:
    """Partie fictive de n/120 s : balle qui avance de 10 uu par image en x, voitures immobiles."""
    a = np.zeros((n, len(GH) + 6 * len(PH)), np.float32)
    a[:, 0] = np.arange(n) * 10.0
    a[:, 1] = 500.0
    a[:, 2] = 93.0
    for k in range(6):
        b = len(GH) + k * len(PH)
        a[:, b + PH.index("position x")] = k * 100.0
        a[:, b + PH.index("forward x")] = 1.0
        a[:, b + PH.index("up z")] = 1.0
        a[:, b + PH.index("boost level (raw replay units)")] = 255.0
    return clips.Track(a, GH, PH)


def test_world_xy():
    assert clips.world_xy(100.0, -200.0, 0) == (100.0, -200.0)
    assert clips.world_xy(100.0, -200.0, 1) == (-100.0, 200.0)


def test_locate_finds_closest_frame():
    t = synthetic()
    # touche notée à l'image 50 (10 Hz) → autour de l'image 600 (120 Hz) ; la balle est à x = 6050 à l'image 605
    assert clips.locate(t, 50, (6050.0, 500.0)) == 605
    assert clips.locate(t, 50, (6050.0, 500.0 + 49)) == 605
    assert clips.locate(t, 50, (6050.0, 500.0 + 51)) is None  # trop loin de la balle notée
    assert clips.locate(t, 50, (100.0, 500.0)) is None  # hors de la fenêtre de ± 1 s
    assert clips.locate(t, 500, (0.0, 0.0)) is None  # après la fin du replay


def test_cut_shape_and_bounds():
    t = synthetic()
    card = clips.cut(t, META, 600, "Steam:4")
    assert card is not None
    n = int((clips.BEFORE + clips.AFTER) * clips.FPS) + 1
    assert card["fps"] == 30 and card["action_frame"] == 90
    assert len(card["ball"]) == len(card["ball_v"]) == n
    assert card["ball"][90] == [6000, 500, 93]
    assert [c["judged"] for c in card["cars"]] == [k == 4 for k in range(6)]
    assert [c["team"] for c in card["cars"]] == [0, 0, 0, 1, 1, 1]
    for c in card["cars"]:
        assert len(c["pos"]) == len(c["vel"]) == len(c["fw"]) == len(c["up"]) == len(c["boost"]) == n
        assert c["boost"][0] == 100 and c["fw"][0] == [1.0, 0.0, 0.0]
    assert clips.cut(t, META, 300, "Steam:4") is None  # pas 3 s avant
    assert clips.cut(t, META, 1100, "Steam:4") is None  # pas 1 s après
    assert clips.cut(t, META, 600, "Steam:inconnu") is None


def test_cut_with_cameras():
    t = synthetic()  # pas de colonne de temps : temps = index / 120 ; touche à l'image 600 = 5 s
    cams = {
        "players": {
            "Steam:4": {
                "settings": {"fov": 110.0, "distance": 270.0, "height": 100.0, "angle": -3.0, "stiffness": 0.5},
                "ball_cam": [[4.0, 0], [5.5, 1]],
            }
        }
    }
    card = clips.cut(t, META, 600, "Steam:4", cams=cams)
    assert card is not None and card["cam"]["distance"] == 270.0 and card["cam"]["known"]
    bc = card["cam"]["ball_cam"]  # clip de 2 s à 6 s : avant 4 s, état de la 1re bascule
    assert len(bc) == len(card["ball"]) and bc[0] == 0 and bc[60] == 0 and bc[90] == 0 and bc[105] == 1
    assert clips.cut(t, META, 600, "Steam:0", cams=cams)["cam"] is None
    assert "cam" not in clips.cut(t, META, 600, "Steam:4")  # Swipe : cartes inchangées
    only = {"players": {"Steam:4": {"settings": None, "ball_cam": [[1.0, 1]]}}}
    assert clips.cut(t, META, 600, "Steam:4", cams=only)["cam"] == {"known": False, "ball_cam": [1] * len(bc)}


def test_real_replay_cameras():
    if not RAW:
        pytest.skip("aucun replay dans data/raw/")
    cams = clips.read_cameras(RAW[0])["players"]
    assert len(cams) >= 2
    for c in cams.values():
        assert c["settings"] is None or set(c["settings"]) == set(clips.CAM_KEYS)
        assert all(b in (0, 1) for _, b in c["ball_cam"])
        assert [t for t, _ in c["ball_cam"]] == sorted(t for t, _ in c["ball_cam"])


def test_cameras_dans_un_processus_separe(tmp_path):
    """rlpi.game.cameras : lecture lourde (environ 250 Mo) faite dans un processus à part, qui rend sa mémoire."""
    from rlpi import game

    bad = tmp_path / "abime.replay"
    bad.write_bytes(b"pas un replay")
    with pytest.raises(RuntimeError):
        game.cameras(bad, tmp_path / "abime.cameras.json")
    assert not (tmp_path / "abime.cameras.json").exists()
    if not RAW:
        pytest.skip("aucun replay dans data/raw/")
    out = tmp_path / "vrai.cameras.json"
    game.cameras(RAW[0], out)
    assert json.loads(out.read_text(encoding="utf-8")) == clips.read_cameras(RAW[0])


def test_cut_rejects_missing_ball():
    t = synthetic()
    t.a[550, 0] = np.nan
    assert clips.cut(t, META, 600, "Steam:0") is None


# ------------------------------------------------------------------------------------------------ vrai replay


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    if not RAW:
        pytest.skip("aucun replay dans data/raw/")
    from rlpi import frames

    out = tmp_path_factory.mktemp("frames")
    frames.extract(str(RAW[0]), str(out))
    rid = RAW[0].stem
    meta = json.loads((out / f"{rid}.meta.json").read_text(encoding="utf-8"))
    f10 = pl.read_parquet(out / f"{rid}.parquet", columns=["ball_x", "ball_y", "ball_z"])
    touches = pl.read_parquet(out / f"{rid}.touches.parquet").filter(
        (pl.col("slot") >= 0) & (pl.col("i") >= 0) & (pl.col("i") < f10.height)
    )
    return out, rid, meta, f10, touches, clips.read_replay(RAW[0])


def test_real_replay_locate_and_cut(real):
    _, _, meta, f10, touches, track = real
    ids = {p["slot"]: p["id"] for p in meta["players"]}
    n_ok = 0
    for i10, slot in touches.select("i", "slot").iter_rows():
        j = clips.locate(track, i10, (f10["ball_x"][i10], f10["ball_y"][i10]))
        assert j is not None, f"touche {i10} non calée"
        card = clips.cut(track, meta, j, ids[slot])
        if card is None:  # touche trop près du début ou de la fin du replay
            continue
        n_ok += 1
        judged = [c for c in card["cars"] if c["judged"]]
        assert len(judged) == 1 and len(card["cars"]) == 6
        # au moment de la touche, la balle du clip est celle des images à 10 Hz (à quelques uu près)
        bx, by, bz = card["ball"][card["action_frame"]]
        assert abs(bx - f10["ball_x"][i10]) < 60 and abs(by - f10["ball_y"][i10]) < 60
        assert abs(bz - f10["ball_z"][i10]) < 150
    assert n_ok >= 0.9 * touches.height


def test_swipe_extract_uses_clips(real):
    from rlpi import swipe

    out, rid, meta, _, touches, track = real
    ids = {p["slot"]: p["id"] for p in meta["players"]}
    picks = [
        {"i": i, "player_id": ids[s], "origin": "perso", "action": a}
        for i, s, a in touches.select("i", "slot", "action").head(5).iter_rows()
    ]
    cards = swipe.extract("perso", rid, picks, out, RAW[0])
    assert cards and {c["id"] for c in cards} <= {f"perso:{rid}:{p['i']}" for p in picks}
    assert list(cards[0]) == ["id", "origin", "action", "fps", "action_frame", "ball", "ball_v", "cars"]


def test_resample_objet_immobile_tenu_sans_vitesse_perimee():
    """Balle immobile 4 s avant l'engagement avec une vitesse enregistrée périmée : elle reste immobile jusqu'à sa
    mise à jour suivante au lieu de dériver (défaut vu sur les clips de 4 s)."""
    src, n = 120, 5 * 120
    pos = np.zeros((n, 3))
    pos[:, 2] = 93
    pos[481:, 0] = np.arange(1, n - 480) * 10.0  # mise en mouvement à 4 s
    vel = np.zeros((n, 3))
    vel[:481] = [3000.0, -2000.0, 500.0]  # vitesse périmée pendant l'immobilité
    vel[481:, 0] = 1200.0
    p, v = clips.resample(pos, vel, src, 151, 30)
    assert np.abs(p[:121] - [0, 0, 93]).max() < 1e-6  # immobile jusqu'à la touche (image 120 = 4 s)
    assert np.abs(v[:120]).max() == 0
    assert p[-1][0] > 0  # puis la balle part
