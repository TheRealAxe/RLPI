"""Indice de performance RLPI (v2, 14/11/2026) : « as-tu bien joué ce match ? », sur 100, par match et en global.

Principe
- Chaque joueur-match est décrit par 7 composantes mesurables, chacune orientée « plus haut = mieux » :
    impact      gain de valeur apporté par ses touches, par 5 min de jeu (modèle de valeur). Une touche qui
                finit en but est créditée de la valeur du modèle 0,2 s avant la ligne (« xV », ≈ 0,75 en
                médiane), pas d'un +1 automatique : un tir marqué et un tir arrêté de même qualité valent
                presque pareil. (v1 : +1 forcé → un tiers de la variance de l'impact venait des seuls buts.)
    placement   écart à la position qu'aurait un pro dans la même situation (signe inversé)
    duels       part des 50/50 gagnés
    boost       temps à 0 boost (signe inversé)
    vitesse     vitesse moyenne
    fiabilite   balles ratées par 5 min (signe inversé)
    collectif   passes réussies par 5 min
- Référence : les joueurs-matchs des parties classées 3v3 où les 6 joueurs sont SSL. Chaque composante
  est centrée-réduite sur cette référence.
- Poids : appris sur la référence SSL (régression logistique régularisée sur la victoire de l'équipe, poids
  négatifs ramenés à 0).
- Indice d'un match = centile du score pondéré parmi les joueurs-matchs SSL (50 = SSL médian en partie SSL).
- Deux sous-notes, sur la même échelle :
    production    = centile de l'impact seul : ce que tes touches ont produit (volatile d'un match à l'autre) ;
    fondamentaux  = centile des 6 autres composantes, pondérées de la même façon mais sans l'impact (stable).
- Indice global = moyenne des indices de match, avec un intervalle (bootstrap sur les matchs).

Fiabilité (rapport data/models/perf_report.json)
- validation externe sur RLCS (jamais vu à l'apprentissage) : l'équipe au meilleur indice gagne-t-elle ?
- test-retest RLCS : même joueur, matchs pairs vs impairs → nombre de matchs pour une moyenne fiable (≥ 0,8) ;
- moitiés de match (`python -m rlpi.perf fiabilite`) : minutes paires vs impaires d'un même match.

Usage : python -m rlpi.perf [fiabilite]  → data/features/perf_{ssl,<source>}.parquet + data/models/perf_report.json
        python -m rlpi.perf score --source <source>  → note une source avec la référence data/models/perf_reference.npz
Prérequis : python -m rlpi.value goals --source {ssl,rlcs,perso}
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl

from rlpi.config import FEATURES, FRAMES, MODELS, SOURCE
from rlpi.context import DataContext, resolve

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
FOND = [k for k in KEYS if k != "impact"]


def _meta(source: str) -> dict[str, dict]:
    return {p.name.removesuffix(".meta.json"): json.loads(p.read_text(encoding="utf-8"))
            for p in (FRAMES / source).glob("*.meta.json")}


def touch_xv(source: str, ctx: DataContext | None = None) -> pl.DataFrame:
    """Touches valorisées, avec dv_xv : les touches de but créditées de la valeur du modèle avant la ligne."""
    ctx = resolve(ctx)
    return xv(pl.read_parquet(ctx.feature("touch_values", source)), pl.read_parquet(ctx.feature("goal_xv", source)))


GOAL_XV_SCHEMA = {"replay": pl.String, "goal_i": pl.Int64, "scorer_team": pl.Int64, "v_team0": pl.Float64}


def xv(tv: pl.DataFrame, gx: pl.DataFrame | None) -> pl.DataFrame:
    """touch_xv à partir des tables (toute une source, ou une seule partie ; gx None : partie sans but)."""
    tv = tv.sort("replay", "i")
    gx = (gx if gx is not None else pl.DataFrame(schema=GOAL_XV_SCHEMA)).sort("replay", "goal_i")
    tv = tv.join_asof(gx, left_on="i", right_on="goal_i", by="replay", strategy="forward", check_sortedness=False)
    v_goal = pl.when(pl.col("team") == 0).then(pl.col("v_team0")).otherwise(-pl.col("v_team0"))
    return tv.with_columns(pl.when(pl.col("v_after").abs() >= 0.999).then(v_goal - pl.col("v_before"))
                           .otherwise(pl.col("dv")).alias("dv_xv"))


def player_matches(source: str) -> pl.DataFrame:
    """Une ligne par joueur et par match, avec les composantes brutes (orientées plus haut = mieux)."""
    from rlpi.dashboard.metrics import metrics

    st = metrics(pl.read_parquet(FEATURES / f"player_match_stats_{source}.parquet")).filter(~pl.col("is_bot"))
    st = st.with_columns(pl.col("replay_file").map_elements(lambda f: Path(f).stem, return_dtype=pl.Utf8).alias("replay"))
    metas = _meta(source)
    play_s = {r: m["n_play_frames"] / 10 for r, m in metas.items()}

    imp = touch_xv(source).group_by("replay", "player_id").agg(pl.col("dv_xv").sum().alias("dv_sum"),
                                                                pl.len().alias("n_touches"))
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


def _z(df: pl.DataFrame, mu: dict, sd: dict, keys: list[str] = KEYS) -> np.ndarray:
    X = np.column_stack([df[k].to_numpy().astype(float) for k in keys])
    for j, k in enumerate(keys):
        X[:, j] = np.where(np.isfinite(X[:, j]), X[:, j], mu[k])  # composante manquante → valeur médiane
        X[:, j] = (X[:, j] - mu[k]) / sd[k]
    return np.clip(X, -4, 4)


def _weights(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from sklearn.linear_model import LogisticRegression
    raw = LogisticRegression(C=0.5).fit(X, y).coef_[0]
    w = np.clip(raw, 0, None)
    return w / w.sum(), raw


def team_acc(df: pl.DataFrame, col: str) -> float:
    """Part des matchs où l'équipe à la moyenne `col` la plus haute gagne."""
    t = df.group_by("replay", "team").agg(pl.col(col).mean(), pl.col("won").first()).sort("replay", "team")
    p = t.group_by("replay", maintain_order=True).agg(pl.col(col), pl.col("won"))
    ok = [(a[0] > a[1]) == w[0] for a, w in zip(p[col], p["won"]) if len(a) == 2 and a[0] != a[1]]
    return float(np.mean(ok)) if ok else float("nan")


def test_retest(df: pl.DataFrame, col: str, min_n: int = 10) -> dict:
    """Même joueur, matchs pairs vs impairs : fiabilité d'un match et nombre de matchs pour une moyenne ≥ 0,8."""
    d = df.sort("date").with_columns(pl.int_range(pl.len()).over("player_id").alias("k"),
                                     pl.len().over("player_id").alias("n")).filter(pl.col("n") >= min_n)
    h = d.group_by("player_id").agg(pl.col(col).filter(pl.col("k") % 2 == 0).mean().alias("a"),
                                    pl.col(col).filter(pl.col("k") % 2 == 1).mean().alias("b"), pl.col("n").first())
    r = float(np.corrcoef(h["a"], h["b"])[0, 1])
    full = 2 * r / (1 + r)
    nb = float(h["n"].mean())
    single = full / (nb - (nb - 1) * full)
    return {"players": h.height, "matches_per_player": nb, "reliability_mean": full, "reliability_1": single,
            "matches_for_08": int(np.ceil(0.8 * (1 - single) / (0.2 * single))) if single > 0 else None}


REFERENCE = MODELS / "perf_reference.npz"
PERF_COLS = ["replay", "date", "player_id", "player_name", "team", "won", "play_s", "index", "prod", "fond",
             *KEYS, *[f"c_{k}" for k in KEYS]]


def _score(df: pl.DataFrame, X: np.ndarray, ref: dict) -> pl.DataFrame:
    """Indice, sous-notes et centiles par composante, à partir de la référence SSL (voir fit_and_score)."""
    fi = [KEYS.index(k) for k in FOND]
    pct = lambda s, ref_sorted: 100 * np.searchsorted(ref_sorted, s, side="right") / len(ref_sorted)  # noqa: E731
    cs = ref["comp_sorted"]  # chaque composante SSL triée (centile de chaque composante face aux SSL)
    cp = np.column_stack([100 * np.searchsorted(cs[:, j], X[:, j], side="right") / len(cs) for j in range(len(KEYS))])
    return df.with_columns(pl.Series("index", pct(X @ ref["w"], ref["srt"])),
                           pl.Series("fond", pct(X[:, fi] @ ref["w_f"], ref["srt_f"])),
                           pl.Series("prod", cp[:, 0]),
                           *[pl.Series(f"c_{k}", cp[:, j]) for j, k in enumerate(KEYS)])


def load_reference() -> dict:
    z = np.load(REFERENCE)
    return {"mu": dict(zip(KEYS, z["mu"].tolist())), "sd": dict(zip(KEYS, z["sd"].tolist())),
            **{k: z[k] for k in ("w", "w_f", "srt", "srt_f", "comp_sorted")}}


def score_source(source: str) -> pl.DataFrame | None:
    """Note les joueurs-matchs d'une source avec la référence enregistrée, sans réapprendre les poids.

    Même résultat que fit_and_score pour cette source (référence SSL figée dans perf_reference.npz).
    Sert au traitement partie par partie (rlpi.game). Retourne None s'il n'y a aucun joueur-match notable.
    """
    ref = load_reference()
    df = player_matches(source)
    if df.is_empty():
        return None
    out = _score(df, _z(df, ref["mu"], ref["sd"]), ref).select(PERF_COLS)
    out.write_parquet(FEATURES / f"perf_{source}.parquet")
    return out


def fit_and_score() -> dict:
    from sklearn.metrics import roc_auc_score

    ref = player_matches("ssl")
    mu = {k: float(np.nanmedian(ref[k].to_numpy().astype(float))) for k in KEYS}
    sd = {k: float(np.nanstd(ref[k].to_numpy().astype(float))) or 1.0 for k in KEYS}
    Xr, yr = _z(ref, mu, sd), ref["won"].cast(pl.Int8).to_numpy()
    groups = ref["replay"].to_numpy()

    # Validation croisée par matchs (5 plis) sur SSL
    uniq = np.unique(groups)
    rng = np.random.default_rng(0)
    fold_of = dict(zip(uniq, rng.permutation(len(uniq)) % 5))
    folds = np.array([fold_of[g] for g in groups])
    oof = np.zeros(len(yr))
    for k in range(5):
        trn = folds != k
        oof[~trn] = Xr[~trn] @ _weights(Xr[trn], yr[trn])[0]
    w, raw_w = _weights(Xr, yr)
    fi = [KEYS.index(k) for k in FOND]
    w_f, _ = _weights(Xr[:, fi], yr)
    auc_player = float(roc_auc_score(yr, oof))

    # Référence figée : réutilisée telle quelle pour noter une partie isolée (score_source)
    refd = {"mu": mu, "sd": sd, "w": w, "w_f": w_f, "srt": np.sort(Xr @ w), "srt_f": np.sort(Xr[:, fi] @ w_f),
            "comp_sorted": np.sort(Xr, axis=0)}
    np.savez(REFERENCE, mu=np.array([mu[k] for k in KEYS]), sd=np.array([sd[k] for k in KEYS]),
             **{k: refd[k] for k in ("w", "w_f", "srt", "srt_f", "comp_sorted")})

    ref = ref.with_columns(pl.Series("oof", oof))
    out = {}
    for src in ("ssl", SOURCE, "rlcs"):
        df = ref if src == "ssl" else player_matches(src)
        X = Xr if src == "ssl" else _z(df, mu, sd)
        df = _score(df, X, refd)
        if src != "rlcs":
            df.select(PERF_COLS).write_parquet(FEATURES / f"perf_{src}.parquet")
        out[src] = df

    rl = out["rlcs"]
    report = {
        "version": 2, "impact": "xV (but crédité de la valeur du modèle avant la ligne)",
        "n_ref_player_matches": int(len(yr)), "n_ref_matches": int(len(uniq)),
        "weights": {k: float(x) for k, x in zip(KEYS, w)}, "raw_coef": {k: float(x) for k, x in zip(KEYS, raw_w)},
        "weights_fond": {k: float(x) for k, x in zip(FOND, w_f)},
        "auc_player_oof": auc_player, "team_acc_oof": team_acc(ref, "oof"),
        "rlcs_team_acc": team_acc(rl, "index"), "rlcs_team_acc_prod": team_acc(rl, "prod"),
        "rlcs_team_acc_fond": team_acc(rl, "fond"), "rlcs_n_matches": rl["replay"].n_unique(),
        "perso_team_acc": team_acc(out[SOURCE], "index"), "perso_n_matches": out[SOURCE]["replay"].n_unique(),
        "retest": {c: test_retest(rl, c) for c in ("index", "prod", "fond")},
        "median": mu, "sd": sd,
    }
    rp = MODELS / "perf_report.json"
    if rp.exists():  # conserver la mesure par moitiés de match si elle existe
        old = json.loads(rp.read_text(encoding="utf-8"))
        if old.get("version") == 2 and "split_half" in old:
            report["split_half"] = old["split_half"]
    rp.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


def split_half(source: str = "ssl") -> dict:
    """Minutes paires vs impaires d'un même match : les deux moitiés racontent-elles la même chose ?
    Composantes recalculables par moitié : impact, placement, boost, vitesse (les autres sont des cumuls
    du match entier fournis par subtr-actor). Fiabilité du match entier = Spearman-Brown."""
    rep = json.loads((MODELS / "perf_report.json").read_text(encoding="utf-8"))
    tv = touch_xv(source)
    plc = pl.read_parquet(FEATURES / f"placement_{source}.parquet")
    rows = []
    for mp in sorted((FRAMES / source).glob("*.meta.json")):
        m = json.loads(mp.read_text(encoding="utf-8"))
        f = pl.read_parquet(mp.with_name(m["replay"] + ".parquet"))
        play = f["phase"].to_numpy() == 1
        half = (np.arange(f.height) // 600) % 2
        t = tv.filter(pl.col("replay") == m["replay"])
        th_half = half[np.minimum(t["i"].to_numpy(), f.height - 1)]
        pr = plc.filter(pl.col("replay") == m["replay"])
        pr_half = (pr["i"].to_numpy() // 600) % 2
        for p in m["players"]:
            k = p["slot"]
            sp = np.hypot(f[f"p{k}_vx"].to_numpy(), f[f"p{k}_vy"].to_numpy()) * 0.036
            b = f[f"p{k}_boost"].to_numpy()
            for h in (0, 1):
                mk = play & (half == h)
                T = mk.sum() / 10
                if T < 60:
                    continue
                pe = pr.filter(pl.Series((pr_half == h) & (pr["slot"].to_numpy() == k)))
                rows.append({"replay": m["replay"], "pid": p["id"], "h": h,
                             "impact": float(t.filter(pl.Series((th_half == h) & (t["player_id"].to_numpy() == p["id"])))["dv_xv"].sum()) / T * 300,
                             "placement": -float(pe["err"].median()) if pe.height else None,
                             "boost": -100 * float((b[mk] < 1).mean()), "vitesse": float(sp[mk].mean())})
    d = pl.DataFrame(rows)
    keys = ["impact", "placement", "boost", "vitesse"]
    w = d.pivot(on="h", index=["replay", "pid"], values=keys).drop_nulls()
    res = {"source": source, "n": w.height}
    za, zb = {}, {}
    for c in keys:
        a, b = w[f"{c}_0"].to_numpy().astype(float), w[f"{c}_1"].to_numpy().astype(float)
        r = float(np.corrcoef(a, b)[0, 1])
        res[c] = 2 * r / (1 + r)
        za[c] = np.clip((a - rep["median"][c]) / rep["sd"][c], -4, 4)
        zb[c] = np.clip((b - rep["median"][c]) / rep["sd"][c], -4, 4)
    for name, wts in (("index", rep["weights"]), ("fond", rep["weights_fond"])):
        ks = [c for c in keys if wts.get(c, 0) > 0]
        tot = sum(wts[c] for c in ks)
        sa = sum(wts[c] / tot * za[c] for c in ks); sb = sum(wts[c] / tot * zb[c] for c in ks)
        r = float(np.corrcoef(sa, sb)[0, 1])
        res[name] = 2 * r / (1 + r)
    res["prod"] = res["impact"]
    rep["split_half"] = res
    (MODELS / "perf_report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="fit", choices=["fit", "fiabilite", "score"])
    ap.add_argument("--source", default=SOURCE, help="source à noter avec « score » (référence déjà enregistrée)")
    a = ap.parse_args()
    if a.cmd == "fiabilite":
        r = split_half("ssl")
        print("Fiabilité d'un match (moitiés paires / impaires, SSL) :", {k: round(v, 2) if isinstance(v, float) else v for k, v in r.items()})
        return
    if a.cmd == "score":
        df = score_source(a.source)
        print(f"→ perf_{a.source}.parquet : {0 if df is None else df.height} joueurs-matchs notés (référence enregistrée)")
        return
    r = fit_and_score()
    print(f"Référence : {r['n_ref_player_matches']} joueurs-matchs SSL ({r['n_ref_matches']} parties)")
    print("Poids :", {k: round(v, 3) for k, v in r["weights"].items()})
    print("Poids fondamentaux :", {k: round(v, 3) for k, v in r["weights_fond"].items()})
    print(f"AUC joueur (victoire, hors échantillon SSL) : {r['auc_player_oof']:.3f} ; équipe gagnante SSL {r['team_acc_oof']:.1%}")
    print(f"RLCS (jamais vu) : équipe gagnante {r['rlcs_team_acc']:.1%} (production {r['rlcs_team_acc_prod']:.1%}, "
          f"fondamentaux {r['rlcs_team_acc_fond']:.1%}) sur {r['rlcs_n_matches']} matchs")
    print(f"Tes parties : {r['perso_team_acc']:.1%} sur {r['perso_n_matches']}")
    for c, v in r["retest"].items():
        print(f"  test-retest RLCS {c:<6} fiabilité 1 match {v['reliability_1']:.2f} · matchs pour 0,8 : {v['matches_for_08']}")


if __name__ == "__main__":
    main()
