"""Resume des sorties de audit.py. Usage : python notebooks/audit_impact/resume.py <dossier>"""

import sys

import polars as pl

pl.Config.set_tbl_rows(40)
pl.Config.set_tbl_width_chars(220)
pl.Config.set_fmt_str_lengths(40)
S = sys.argv[1]


def L(n):
    return pl.read_parquet(f"{S}/audit_{n}.parquet")


B = L("buts")
print("== 1. BUTS ==", B.height)
B = B.with_columns(
    pl.when(pl.col("contre_son_camp"))
    .then(pl.lit("contre son camp"))
    .when(pl.col("delai_s") > 1.0)
    .then(pl.lit("tir > 1 s avant le but"))
    .otherwise(pl.lit("tir ≤ 1 s"))
    .alias("cas")
)
print(
    B.group_by("cas").agg(
        pl.len(),
        pl.col("credit").mean().round(3),
        pl.col("credit").median().round(3).alias("credit_med"),
        pl.col("xv_but").mean().round(3),
        pl.col("delai_s").median(),
    )
)
print(
    "délais (s) :",
    B.filter(~pl.col("contre_son_camp"))["delai_s"].quantile(0.5),
    B.filter(~pl.col("contre_son_camp") & (pl.col("delai_s") > 1)).height,
)
print(
    B.filter(pl.col("cas") == "tir > 1 s avant le but")
    .sort("credit")
    .select("replay", "clock", "dernier", "action", "delai_s", "credit", "v_before", "v_after", "xv_but")
    .head(15)
)
print(
    B.filter(pl.col("contre_son_camp")).select("replay", "clock", "dernier", "action", "delai_s", "credit", "v_before")
)
D = L("defense")
print("== 2. DÉFENSE SUR BALLE QUI RENTRAIT ==", D.height, "touches, coût total", round(D["dv"].sum(), 2))
print(
    D.with_columns((pl.col("v_after") <= -0.999).alias("but_juste_apres"))
    .group_by("but_juste_apres")
    .agg(pl.len(), pl.col("dv").sum().round(2), pl.col("dv").mean().round(3).alias("dv_moy"))
)
print(D.group_by("joueur").agg(pl.len(), pl.col("dv").sum().round(2)).sort("dv").head(8))
M = L("manquees")
print(
    "== 3. TOUCHES MANQUÉES ==",
    M.height,
    "dont joueur à <300 uu :",
    M.filter(pl.col("dist") < 300).height,
    "| à <300 uu et |ΔV|>0,1 :",
    M.filter((pl.col("dist") < 300) & (pl.col("dV0").abs() > 0.1)).height,
)
print(M.filter(pl.col("dist") < 300).sort(pl.col("dV0").abs(), descending=True).head(10))
U = L("non_attr")
print(
    "== 4. VALEUR NON ATTRIBUÉE ==",
    round(U["non_attribue"].sum() / U["total"].sum() * 100, 1),
    "% des variations de V tombent hors des fenêtres de touche",
)
Si = L("simult")
print("== 5. TOUCHES SIMULTANÉES ==", Si.height, "dont même équipe :", Si.filter(pl.col("meme_equipe")).height)
print(
    Si.filter(pl.col("meme_equipe"))
    .with_columns(pl.col("dv").list.sum().alias("somme"))
    .sort("somme", descending=True)
    .head(6)
)
C = L("calib")
print("== 6. CALIBRATION 0,5 S AVANT LE BUT ==")
print(
    C.with_columns(pl.col("physique").fill_null("pas but").alias("phys"))
    .group_by("phys")
    .agg(
        pl.len(),
        pl.col("V_05s").mean().round(2),
        pl.col("V_05s").median().round(2).alias("V_med"),
        (pl.col("V_05s") < 0.3).sum().alias("V<0,3"),
    )
)
print(
    C.filter(pl.col("V_05s") < 0.3)
    .with_columns((pl.col("z") > 300).alias("aérien"))
    .group_by("aérien")
    .agg(pl.len(), pl.col("dist_but").median())
)
W = L("fenetre")
print(
    "== 7. FENÊTRE D'1 S == |dv_3s − dv| > 0,2 :",
    W.filter((pl.col("dv_3s") - pl.col("dv")).abs() > 0.2).height,
    "/",
    W.height,
)
print(
    W.with_columns((pl.col("dv_3s") - pl.col("dv")).alias("ecart"))
    .group_by("action")
    .agg(pl.len(), pl.col("ecart").mean().round(3), pl.col("ecart").abs().mean().round(3).alias("ecart_abs"))
)
