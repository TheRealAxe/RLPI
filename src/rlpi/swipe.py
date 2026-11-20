"""Paquet d'actions à juger (« swipe ») : clips de 4 s autour d'une touche, à l'aveugle.

Chaque carte = une touche d'un joueur, 3 s avant et 1 s après (la suite est cachée pour juger la
décision, pas le résultat). Positions, orientation (vecteurs avant / haut), vitesses et boost des
6 voitures et de la balle, à 30 images par seconde (fréquence d'enregistrement du replay).

Tirage stratifié par origine du joueur jugé (cachée à l'écran) : l'utilisateur, ses coéquipiers suivis,
les autres joueurs de ses parties, SSL, RLCS. Chaque carte relit le replay brut (subtr-actor, 120 images/s).

En ligne (phase E de docs/PLAN_REFONTE_WEB.md) :
- cartes SSL / RLCS : un lot fixe fabriqué une fois ici, sur un poste qui a les replays bruts, puis déposé dans
  le volume de données du serveur (<RLPI_DATA>/swipe/reference_cards.json) :
      python -m rlpi.swipe pool [--n 60]
- cartes du joueur, de ses coéquipiers et des lobbies : fabriquées par le worker à la demande (player_cards), à
  partir de quelques-unes de ses parties téléchargées depuis le stockage.

Hors ligne, paquet complet sur un dossier de données classique :
      python -m rlpi.swipe deck --player Steam:7656119800000000x [--peers Pseudo1 Pseudo2] --n 40
      → reports/swipe/deck.json
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
import polars as pl

from rlpi.config import DATA, FEATURES, FRAMES, ROOT, SOURCE

FPS = 30        # images par seconde du clip livré
SRC_FPS = 120   # lecture fine du replay pour dater chaque vraie mise à jour
BEFORE, AFTER = 3.0, 1.0
MIX = {"perso": .4, "peer": .15, "lobby": .15, "ssl": .15, "rlcs": .15}
POOL = DATA / "swipe" / "reference_cards.json"


def label_origins(t: pl.DataFrame, player: str, peers: list[str]) -> pl.DataFrame:
    """Origine de chaque touche des parties du joueur : lui (perso), ses coéquipiers suivis (peer, par pseudo),
    les autres (lobby)."""
    return t.with_columns(pl.when(pl.col("player_id") == player).then(pl.lit("perso"))
                          .when(pl.col("player_name").is_in(list(peers))).then(pl.lit("peer"))
                          .otherwise(pl.lit("lobby")).alias("origin"))


def candidates(player: str | None, peers: list[str], sources: tuple[str, ...] = (SOURCE, "ssl", "rlcs")) -> pl.DataFrame:
    """Touches candidates du dossier de données ; `player` = identifiant du joueur suivi, `peers` = pseudos de ses
    coéquipiers."""
    rows = []
    for src in sources:
        t = pl.read_parquet(FEATURES / f"touch_values_{src}.parquet").select("replay", "i", "player_id", "player_name", "action")
        if src == SOURCE:
            t = label_origins(t, player or "", peers)
        else:
            t = t.with_columns(pl.lit(src).alias("origin"))
        rows.append(t.with_columns(pl.lit(src).alias("source")))
    return pl.concat(rows)


def pick(cand: pl.DataFrame, want: dict[str, int], rng: random.Random) -> list[dict]:
    """Touches tirées au hasard pour chaque origine (le double du nombre voulu : marge pour les cartes écartées)."""
    chosen = []
    for origin, k in want.items():
        pool = cand.filter(pl.col("origin") == origin)
        idx = rng.sample(range(pool.height), min(pool.height, k * 2))
        chosen += [pool.row(x, named=True) for x in idx]
    return chosen


def keep(cards: list[dict], want: dict[str, int]) -> list[dict]:
    out = []
    for origin, k in want.items():
        out += [c for c in cards if c["origin"] == origin][:k]
    return out


def resample(pos: np.ndarray, vel: np.ndarray, src_fps: int, out_n: int, out_fps: int) -> tuple[np.ndarray, np.ndarray]:
    """Les voitures ne sont mises à jour qu'environ 15 fois par seconde dans le replay : entre deux mises à jour,
    la position reste figée puis saute. On garde les vraies mises à jour (position qui change) et on
    reconstruit une trajectoire continue entre elles (Hermite cubique avec les vitesses enregistrées)."""
    keys = [0] + [k for k in range(1, len(pos)) if np.any(pos[k] != pos[k - 1])]
    kt = np.array(keys) / src_fps
    kp, kv = pos[keys], vel[keys]
    out_t = np.arange(out_n) / out_fps
    P, Vv = np.zeros((out_n, 3)), np.zeros((out_n, 3))
    for n, t in enumerate(out_t):
        j = int(np.searchsorted(kt, t, side="right") - 1)
        if j < 0:
            P[n], Vv[n] = kp[0], kv[0]; continue
        if j >= len(kt) - 1:
            dt = t - kt[-1]; P[n], Vv[n] = kp[-1] + kv[-1] * dt, kv[-1]; continue
        h = kt[j + 1] - kt[j]; u = (t - kt[j]) / h
        u2, u3 = u * u, u * u * u
        P[n] = (2 * u3 - 3 * u2 + 1) * kp[j] + (u3 - 2 * u2 + u) * h * kv[j] + (-2 * u3 + 3 * u2) * kp[j + 1] + (u3 - u2) * h * kv[j + 1]
        Vv[n] = kv[j] + (kv[j + 1] - kv[j]) * u
    return P, Vv


def resample_dir(vec: np.ndarray, pos: np.ndarray, src_fps: int, out_n: int, out_fps: int) -> np.ndarray:
    """Même chose pour un vecteur d'orientation : interpolation linéaire normalisée entre vraies mises à jour."""
    keys = [0] + [k for k in range(1, len(pos)) if np.any(pos[k] != pos[k - 1]) or np.any(vec[k] != vec[k - 1])]
    kt, kv = np.array(keys) / src_fps, vec[keys]
    out = np.zeros((out_n, 3))
    for n, t in enumerate(np.arange(out_n) / out_fps):
        j = int(np.clip(np.searchsorted(kt, t, side="right") - 1, 0, len(kt) - 1))
        if j >= len(kt) - 1:
            out[n] = kv[-1]; continue
        u = (t - kt[j]) / (kt[j + 1] - kt[j]); v = kv[j] + (kv[j + 1] - kv[j]) * u
        out[n] = v / (np.linalg.norm(v) or 1)
    return out


def extract(source: str, replay: str, picks: list[dict], frames_dir: Path | None = None,
            replay_path: str | Path | None = None, before: float = BEFORE, after: float = AFTER) -> list[dict]:
    """Cartes des touches `picks` d'un replay. `frames_dir` : dossier des images (défaut frames/<source>/ du
    dossier de données) ; `replay_path` : replay brut (défaut : chemin noté à l'extraction, meta["path"]) ;
    `before` / `after` : secondes gardées avant et après la touche (ralentis plus longs : rlpi.clips)."""
    import subtr_actor as sa

    fd = frames_dir or FRAMES / source
    meta = json.loads((fd / f"{replay}.meta.json").read_text(encoding="utf-8"))
    f10 = pl.read_parquet(fd / f"{replay}.parquet", columns=["ball_x", "ball_y", "ball_z"])
    cols, arr = sa.get_ndarray_with_info_from_replay_filepath(
        str(replay_path or meta["path"]), ["BallRigidBody"], ["PlayerRigidBodyBasis", "PlayerBoost"], fps=SRC_FPS,
        dtype="f32")
    a = np.asarray(arr)
    gh, ph = cols["column_headers"]["global_headers"], cols["column_headers"]["player_headers"]
    ng, npl = len(gh), len(ph)
    gi = {h: gh.index(h) for h in gh}
    bh = next(h for h in ph if "boost" in h.lower())
    out = []
    for p in picks:
        i10 = p["i"]
        target = np.array([f10["ball_x"][i10], f10["ball_y"][i10], f10["ball_z"][i10]])
        r = SRC_FPS // 10
        lo, hi = max(0, r * i10 - 10 * r), min(len(a), r * i10 + 10 * r)
        d = np.linalg.norm(a[lo:hi, [gi["Ball - position x"], gi["Ball - position y"], gi["Ball - position z"]]] - target, axis=1)
        j = lo + int(np.argmin(d))
        if d.min() > 50:
            continue  # alignement douteux : carte écartée
        j0, j1 = j - int(before * SRC_FPS), j + int(after * SRC_FPS) + 1
        if j0 < 0 or j1 > len(a):
            continue
        seg = a[j0:j1]
        n_out = int((before + after) * FPS) + 1
        g = lambda name: seg[:, gi[name]]  # noqa: E731
        pc = lambda k, name: seg[:, ng + k * npl + ph.index(name)]  # noqa: E731
        xyz = lambda f: np.column_stack([f("x"), f("y"), f("z")])  # noqa: E731
        cars = []
        step = SRC_FPS // FPS
        for pl_ in meta["players"]:
            k = pl_["slot"]
            pos = xyz(lambda c: pc(k, f"position {c}")); vel = xyz(lambda c: pc(k, f"linear velocity {c}"))
            P_, V_ = resample(pos, vel, SRC_FPS, n_out, FPS)
            fw = resample_dir(xyz(lambda c: pc(k, f"forward {c}")), pos, SRC_FPS, n_out, FPS)
            up = resample_dir(xyz(lambda c: pc(k, f"up {c}")), pos, SRC_FPS, n_out, FPS)
            cars.append({
                "team": pl_["team"], "judged": pl_["id"] == p["player_id"],
                "pos": np.round(P_).astype(int).tolist(), "vel": np.round(V_).astype(int).tolist(),
                "fw": np.round(fw, 3).tolist(), "up": np.round(up, 3).tolist(),
                "boost": np.round(pc(k, bh)[::step][:n_out] / 2.55).astype(int).tolist(),
            })
        if not any(c["judged"] for c in cars) or np.isnan(seg[:, :3]).any():
            continue
        out.append({
            "id": f"{source}:{replay}:{i10}", "origin": p["origin"], "action": p["action"],
            "fps": FPS, "action_frame": int(before * FPS), **dict(zip(("ball", "ball_v"), (lambda bp, bv: (np.round(bp).astype(int).tolist(), np.round(bv).astype(int).tolist()))(
                *resample(xyz(lambda c: g(f"Ball - position {c}")), xyz(lambda c: g(f"Ball - linear velocity {c}")), SRC_FPS, n_out, FPS)))),
            "cars": cars,
        })
    return out


def by_replay(chosen: list[dict]) -> dict[tuple[str, str], list[dict]]:
    out: dict[tuple[str, str], list[dict]] = {}
    for c in chosen:
        out.setdefault((c["source"], c["replay"]), []).append(c)
    return out


def build(n: int, player: str, peers: list[str], seed: int = 1) -> None:
    """Paquet complet sur le dossier de données (hors ligne)."""
    rng = random.Random(seed)
    want = {o: max(1, round(n * w)) for o, w in MIX.items()}
    cards = []
    for (src, rp), picks in by_replay(pick(candidates(player, peers), want, rng)).items():
        cards += extract(src, rp, picks)
    deck = keep(cards, want)
    rng.shuffle(deck)
    out = ROOT / "reports" / "swipe"
    out.mkdir(parents=True, exist_ok=True)
    (out / "deck.json").write_text(json.dumps({"seed": seed, "cards": deck}), encoding="utf-8")
    from collections import Counter
    print(f"→ {out / 'deck.json'} : {len(deck)} cartes", dict(Counter(c["origin"] for c in deck)))


def build_pool(n: int, seed: int = 1, out: Path = POOL) -> Path:
    """Lot fixe de cartes SSL et RLCS (n par source au plus) pour le swipe en ligne."""
    rng = random.Random(seed)
    sources = tuple(s for s in ("ssl", "rlcs") if (FEATURES / f"touch_values_{s}.parquet").exists())
    if not sources:
        raise SystemExit(f"aucune table touch_values_ssl / _rlcs dans {FEATURES}")
    want = dict.fromkeys(sources, n)
    cards = []
    for (src, rp), picks in by_replay(pick(candidates(None, [], sources), want, rng)).items():
        try:
            cards += extract(src, rp, picks)
        except (OSError, ValueError, KeyError) as e:  # replay brut absent ou illisible : on passe
            print(f"  {src} {rp} : {type(e).__name__}: {e}")
    pool = keep(cards, want)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"seed": seed, "cards": pool}), encoding="utf-8")
    from collections import Counter
    print(f"→ {out} : {len(pool)} cartes", dict(Counter(c["origin"] for c in pool)),
          f"({out.stat().st_size / 1e6:.1f} Mo)")
    return out


def player_cards(games: list[tuple[Path, Path]], player: str, peers: list[str], want: dict[str, int],
                 rng: random.Random) -> list[dict]:
    """Cartes tirées des parties d'un joueur (worker). `games` : (dossier de la partie, sortie de rlpi.game run ;
    replay brut correspondant). `want` : nombre de cartes voulues par origine (perso, peer, lobby)."""
    from rlpi.game import GAME_SOURCE

    tables, where = [], {}
    for d, raw in games:
        f = d / "features" / f"touch_values_{GAME_SOURCE}.parquet"
        if not f.exists():
            continue
        t = pl.read_parquet(f).select("replay", "i", "player_id", "player_name", "action")
        tables.append(label_origins(t, player, peers).with_columns(pl.lit("perso").alias("source")))
        for r in t["replay"].unique().to_list():
            where[r] = (d / "frames" / GAME_SOURCE, raw)
    if not tables:
        return []
    cards = []
    for (_src, rp), picks in by_replay(pick(pl.concat(tables), want, rng)).items():
        frames_dir, raw = where[rp]
        cards += extract("perso", rp, picks, frames_dir, raw)
    return keep(cards, want)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("deck", help="paquet complet sur le dossier de données → reports/swipe/deck.json")
    d.add_argument("--n", type=int, default=40)
    d.add_argument("--seed", type=int, default=1)
    d.add_argument("--player", required=True, help="identifiant du joueur suivi, ex. Steam:7656119800000000x")
    d.add_argument("--peers", nargs="*", default=[], help="pseudos de ses coéquipiers")
    p = sub.add_parser("pool", help=f"lot fixe de cartes SSL / RLCS pour le site → {POOL}")
    p.add_argument("--n", type=int, default=60, help="cartes par source")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", type=Path, default=POOL)
    a = ap.parse_args()
    if a.cmd == "deck":
        build(a.n, a.player, a.peers, a.seed)
    else:
        build_pool(a.n, a.seed, a.out)


if __name__ == "__main__":
    main()
