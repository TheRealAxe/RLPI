"""Outils communs aux sections du tableau de bord : centiles, colonnes brutes, JSON qui garde NaN et ±infini."""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

UU_TO_KMH = 0.036  # 1 uu = 1 cm


def col(df: pl.DataFrame, name: str) -> pl.Expr:
    """Colonne brute des stats, 0 si la colonne n'existe pas du tout."""
    return pl.col(name) if name in df.columns else pl.lit(0.0)


def ensure_columns(df: pl.DataFrame, names: Iterable[str]) -> pl.DataFrame:
    """Ajoute (vides) les colonnes absentes de la table d'une partie.

    Avant les agrégats, les tables de toutes les parties d'un joueur étaient concaténées : une colonne absente d'une
    partie mais présente dans une autre y valait « vide » (null), pas 0. Calculer partie par partie avec la même
    règle donne les mêmes indicateurs."""
    missing = [n for n in names if n not in df.columns]
    return df.with_columns([pl.lit(None, dtype=pl.Float64).alias(n) for n in missing]) if missing else df


def as_array(ref: Iterable[float | None] | np.ndarray) -> np.ndarray:
    if isinstance(ref, np.ndarray):
        return ref
    return np.asarray([r for r in ref if r is not None], dtype=float)


class Sorted:
    """Valeurs de référence triées une fois : centiles par recherche dichotomique, résultat identique à
    percentile() (mêmes comptes d'inférieurs et d'égaux ; les NaN ne sont jamais comptés mais pèsent dans le total)."""

    __slots__ = ("a", "n", "vals")

    def __init__(self, ref: Iterable[float | None] | np.ndarray):
        self.a = np.sort(as_array(ref))  # NaN rangés à la fin
        self.n = len(self.a)
        self.vals = self.a[~np.isnan(self.a)].tolist()


def percentile(value: float | None, ref: Iterable[float | None] | np.ndarray | Sorted) -> float | None:
    """Centile de `value` dans `ref` (moitié des égalités comptée). `ref` : liste, tableau numpy sans None, ou
    Sorted (plus rapide quand on calcule beaucoup de centiles dans la même référence)."""
    if value is None:
        return None
    if isinstance(ref, Sorted):
        if not ref.n:
            return None
        if value != value:  # NaN : aucune valeur inférieure ni égale
            return 0.0
        lo = bisect_left(ref.vals, value)
        hi = bisect_right(ref.vals, value)
        return float(100 * (lo + 0.5 * (hi - lo)) / ref.n)
    a = as_array(ref)
    if not len(a):
        return None
    return float(100 * ((a < value).sum() + 0.5 * (a == value).sum()) / len(a))


def stem(f: str) -> str:
    return Path(f).stem


# -------------------------------------------------------------------------------------------- JSON (jsonb)
# Postgres (jsonb) refuse NaN et ±infini, que les indicateurs produisent parfois (0 / 0), et perd le signe de
# −0,0 (nombre décimal). Ils sont écrits {"$f": "nan"}, {"$f": "-0"}… et relus tels quels : le tableau de bord
# calculé depuis la base est le même qu'avant, au bit près.

_SPECIAL = {"nan": math.nan, "inf": math.inf, "-inf": -math.inf, "-0": -0.0}


def encode(x: Any) -> Any:
    if isinstance(x, float):
        if math.isfinite(x):
            return {"$f": "-0"} if x == 0 and math.copysign(1.0, x) < 0 else x
        return {"$f": "nan" if math.isnan(x) else ("inf" if x > 0 else "-inf")}
    if isinstance(x, dict):
        return {k: encode(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [encode(v) for v in x]
    if isinstance(x, np.generic):
        return encode(x.item())
    return x


def decode(x: Any) -> Any:
    if isinstance(x, dict):
        if len(x) == 1 and "$f" in x:
            return _SPECIAL[x["$f"]]
        return {k: decode(v) for k, v in x.items()}
    if isinstance(x, list):
        return [decode(v) for v in x]
    return x
