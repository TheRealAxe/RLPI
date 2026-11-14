"""Indice de performance RLPI : « as-tu bien joué ce match ? », sur 100, par match et en global.

Principe
- Chaque joueur-match est décrit par 7 composantes mesurables, chacune orientée « plus haut = mieux » :
    impact      gain de valeur apporté par ses touches, par 5 min de jeu (modèle de valeur)
    placement   écart à la position qu'aurait un pro dans la même situation (signe inversé)
    duels       part des 50/50 gagnés
    boost       temps à 0 boost (signe inversé)
    vitesse     vitesse moyenne
    fiabilite   balles ratées par 5 min (signe inversé)
    collectif   passes réussies par 5 min
- Référence : les joueurs-matchs des parties classées 3v3 où les 6 joueurs sont SSL. Chaque composante
  est centrée-réduite sur cette référence.
- Poids : appris sur la référence SSL, en cherchant quelles composantes distinguent les joueurs des
  équipes qui gagnent (régression logistique régularisée, poids négatifs ramenés à 0). Les buts et le
  score ne sont pas des composantes : l'indice juge le jeu, pas le résultat.
- Indice d'un match = centile du score pondéré parmi les joueurs-matchs SSL :
  50 = performance médiane d'un SSL dans une partie SSL.
- Indice global = moyenne des indices de match, avec un intervalle (bootstrap sur les matchs).

Usage : python -m rlpi.perf  → data/features/perf_{ssl,theo}.parquet + data/models/perf_report.json
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from rlpi.config import FEATURES, FRAMES, MODELS

COMPONENTS = [
    # (clé, libellé, sens)
    ("impact", "Impact de tes touches", +1),
    ("placement", "Placement hors ballon", +1),
    ("duels", "50/50 gagnés", +1),
    ("boost", "Gestion du boost", +1),
    ("vitesse", "Vitesse", +1),
    ("fiabilite", "Fiabilité (peu de ratés)", +1),
    ("collectif", "Jeu collectif (passes)", +1),
]
KEYS = [c[0] for c in COMPONENTS]


def _meta(source: str) -> dict[str, dict]:
    return {p.name.removesuffix(".meta.json"): json.loads(p.read_text(encoding="utf-8"))
            for p in (FRAMES / source).glob("*.meta.json")}


def player_matches(source: str) -> pl.DataFrame:
    """Une ligne par joueur et par match, avec les composantes brutes (orientées plus haut = mieux)."""
    from rlpi.dashboard import metrics

    st = metrics(pl.read_parquet(FEATURES / f"player_match_stats_{source}.parquet")).filter(~pl.col("is_bot"))
    st = st.with_columns(pl.col("replay_file").map_elements(lambda f: Path(f).stem, return_dtype=pl.Utf8).alias("replay"))
    metas = _meta(source)
    play_s = {r: m["n_play_frames"] / 10 for r, m in metas.items()}

    tv = pl.read_parquet(FEATURES / f"touch_values_{source}.parquet")
    imp = tv.group_by("replay", "player_id").agg(pl.col("dv").sum().alias("dv_sum"), pl.len().alias("n_touches"))

    plc = pl.read_parquet(FEATURES / f"placement_{source}.parquet").group_by("replay", "slot").agg(
        pl.col("err").median().alias("plc_err"), pl.len().alias("n_plc"))
    slot_rows = [{"replay": r, "slot": p["slot"], "player_id": p["id"]} for r, m in metas.items() for p in m["players"]]
    plc = plc.join(pl.DataFrame(slot_rows), on=["replay", "slot"], how="inner").drop("slot")

    df = (st.join(imp, on=["replay", "player_id"], how="left")
            .join(plc, on=["replay", "player_id"], how="left")
            .filter(pl.col("replay").is_in(list(play_s))))
    df = df.with_columns(pl.col("replay").replace_strict(play_s, default=None).alias("play_s"))
    return df.with_columns(
        impact=pl.col("dv_sum").fill_null(0) / pl.col("play_s") * 300,
        placement=-pl.col("plc_err"),
        duels=pl.col("ff_gagnes"),
        boost=-pl.col("boost_zero"),
        vitesse=pl.col("vitesse"),
        fiabilite=-pl.col("ratees"),
        collectif=pl.col("passes"),
    ).filter(pl.col("play_s") > 120)


def _z(df: pl.DataFrame, mu: dict, sd: dict) -> np.ndarray:
    X = np.column_stack([df[k].to_numpy().astype(float) for k in KEYS])
    for j, k in enumerate(KEYS):
        X[:, j] = np.where(np.isfinite(X[:, j]), X[:, j], mu[k])  # composante manquante → valeur médiane
        X[:, j] = (X[:, j] - mu[k]) / sd[k]
    return np.clip(X, -4, 4)


def fit_and_score() -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score

    ref = player_matches("ssl")
    mu = {k: float(np.nanmedian(ref[k].to_numpy().astype(float))) for k in KEYS}
    sd = {k: float(np.nanstd(ref[k].to_numpy().astype(float))) or 1.0 for k in KEYS}
    Xr, yr = _z(ref, mu, sd), ref["won"].cast(pl.Int8).to_numpy()
    groups = ref["replay"].to_numpy()

    # Poids : régression logistique sur la victoire, validée par matchs (5 plis)
    uniq = np.unique(groups)
    rng = np.random.default_rng(0)
    fold_of = dict(zip(uniq, rng.permutation(len(uniq)) % 5))
    folds = np.array([fold_of[g] for g in groups])
    oof = np.zeros(len(yr))
    for k in range(5):
        trn = folds != k
        lr = LogisticRegression(C=0.5).fit(Xr[trn], yr[trn])
        w = np.clip(lr.coef_[0], 0, None)
        oof[~trn] = Xr[~trn] @ w
    lr = LogisticRegression(C=0.5).fit(Xr, yr)
    raw_w = lr.coef_[0]
    w = np.clip(raw_w, 0, None)
    w = w / w.sum()
    auc_player = float(roc_auc_score(yr, oof))

    ref_score = Xr @ w
    srt = np.sort(ref_score)

    def index(score: np.ndarray) -> np.ndarray:
        return 100 * np.searchsorted(srt, score, side="right") / len(srt)

    def comp_pct(X: np.ndarray) -> np.ndarray:  # centile de chaque composante face aux SSL
        return np.column_stack([100 * np.searchsorted(np.sort(Xr[:, j]), X[:, j], side="right") / len(Xr)
                                for j in range(len(KEYS))])

    # Validation équipe : l'équipe dont l'indice moyen est le plus haut gagne-t-elle ?
    ref = ref.with_columns(pl.Series("index", index(ref_score)), pl.Series("oof", oof))
    team = ref.group_by("replay", "team").agg(pl.col("oof").mean(), pl.col("won").first())
    pairs = team.sort("replay", "team").group_by("replay", maintain_order=True).agg(pl.col("oof"), pl.col("won"))
    ok = [(o[0] > o[1]) == w0[0] for o, w0 in zip(pairs["oof"], pairs["won"]) if len(o) == 2 and o[0] != o[1]]
    team_acc = float(np.mean(ok))

    out = {}
    for src, df, X in (("ssl", ref, Xr), ("theo", None, None)):
        if df is None:
            df = player_matches("theo")
            X = _z(df, mu, sd)
            df = df.with_columns(pl.Series("index", index(X @ w)))
        cp = comp_pct(X)
        df = df.with_columns([pl.Series(f"c_{k}", cp[:, j]) for j, k in enumerate(KEYS)])
        df.select("replay", "date", "player_id", "player_name", "team", "won", "play_s", "index",
                  *KEYS, *[f"c_{k}" for k in KEYS]).write_parquet(FEATURES / f"perf_{src}.parquet")
        out[src] = df

    # Validation sur les parties de Théo (indice jamais ajusté dessus)
    t = out["theo"]
    tt = t.group_by("replay", "team").agg(pl.col("index").mean(), pl.col("won").first()).sort("replay", "team")
    tp = tt.group_by("replay", maintain_order=True).agg(pl.col("index"), pl.col("won"))
    ok_t = [(o[0] > o[1]) == w0[0] for o, w0 in zip(tp["index"], tp["won"]) if len(o) == 2]
    report = {
        "n_ref_player_matches": int(len(yr)), "n_ref_matches": int(len(uniq)),
        "weights": {k: float(x) for k, x in zip(KEYS, w)}, "raw_coef": {k: float(x) for k, x in zip(KEYS, raw_w)},
        "auc_player_oof": auc_player, "team_acc_oof": team_acc,
        "theo_team_acc": float(np.mean(ok_t)) if ok_t else None, "theo_n_matches": len(ok_t),
        "median": mu, "sd": sd,
    }
    (MODELS / "perf_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> None:
    r = fit_and_score()
    print(f"Référence : {r['n_ref_player_matches']} joueurs-matchs SSL ({r['n_ref_matches']} parties)")
    print("Poids :", {k: round(v, 3) for k, v in r["weights"].items()})
    print("Coefficients bruts :", {k: round(v, 3) for k, v in r["raw_coef"].items()})
    print(f"AUC joueur (victoire, hors échantillon) : {r['auc_player_oof']:.3f}")
    print(f"Équipe au meilleur indice moyen = gagnante : {r['team_acc_oof']:.1%} (SSL, hors échantillon), "
          f"{r['theo_team_acc']:.1%} sur {r['theo_n_matches']} parties de Théo")


if __name__ == "__main__":
    main()
