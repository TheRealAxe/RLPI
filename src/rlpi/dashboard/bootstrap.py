"""Tirages avec remise (intervalles par bootstrap) rapides, mais identiques tirage pour tirage à la boucle
d'origine `rng.choice(x, len(x))` répétée.

`rng.choice(x, n)` tire `rng.integers(0, len(x), n)` : avec le générateur PCG64 de numpy, ces entiers viennent
d'un flux de mots de 32 bits (méthode de Lemire). On tire ce flux d'un coup et on refait le calcul de Lemire en
vectoriel ; dans le cas très rare d'un rejet (probabilité ~ n / 2³²), on revient à la boucle d'origine. Au
premier usage, l'équivalence avec la boucle est vérifiée ; sinon (autre version de numpy), boucle d'origine.
"""

from __future__ import annotations

import numpy as np

_U32 = np.uint64(0xFFFFFFFF)
_checked: bool | None = None


def _fast(rng: np.random.Generator, plan: list[tuple[int, int]]) -> np.ndarray | None:
    state = rng.bit_generator.state
    r = np.asarray([r for r, _ in plan], dtype=np.uint64)
    sizes = np.asarray([size for _, size in plan], dtype=np.int64)
    rv = np.repeat(r, sizes)  # borne de chaque tirage
    if (r > 1).all():
        m = rng.integers(0, 0xFFFFFFFF, endpoint=True, size=len(rv), dtype=np.uint32).astype(np.uint64) * rv
        drawn = None
    else:  # borne 1 : aucun mot consommé, résultat 0
        drawn = rv > 1
        u = rng.integers(0, 0xFFFFFFFF, endpoint=True, size=int(drawn.sum()), dtype=np.uint32).astype(np.uint64)
        m = np.zeros(len(rv), dtype=np.uint64)
        m[drawn] = u * rv[drawn]
    # Rejet si la partie basse < (2³² − r) mod r, qui est < r : on ne calcule le seuil que pour ces cas-là
    low = m & _U32
    near = np.flatnonzero((low < rv) if drawn is None else (drawn & (low < rv)))
    if len(near) and (low[near] < (np.uint64(2**32) - rv[near]) % rv[near]).any():  # rejet : flux décalé
        rng.bit_generator.state = state
        return None
    return (m >> np.uint64(32)).astype(np.int64)


def _slow(rng: np.random.Generator, plan: list[tuple[int, int]]) -> np.ndarray:
    return np.concatenate([rng.integers(0, r, size) for r, size in plan]).astype(np.int64)


def flat(rng: np.random.Generator, plan: list[tuple[int, int]]) -> np.ndarray:
    """Mêmes tirages que np.concatenate([rng.integers(0, r, size) for r, size in plan]), dans cet ordre."""
    global _checked
    if _checked is None:
        _checked = _self_check()
    if _checked:
        out = _fast(rng, plan)
        if out is not None:
            return out
    return _slow(rng, plan)


def _self_check() -> bool:
    plan = [(r, s) for r, s in ((51, 51), (7, 7), (1, 1), (2, 2), (25, 24), (1000, 999), (3, 4))] * 50
    a, b = np.random.default_rng(12345), np.random.default_rng(12345)
    try:
        fast = _fast(a, plan)
    except Exception:  # noqa: BLE001
        return False
    slow = _slow(b, plan)
    return (
        fast is not None
        and np.array_equal(fast, slow)
        and np.array_equal(a.integers(0, 10**9, 4), b.integers(0, 10**9, 4))
    )


def draws(rng: np.random.Generator, n: int, k: int) -> np.ndarray:
    """k tirages de n indices parmi n (tableau k × n) : comme k appels successifs à rng.choice(…, n)."""
    return flat(rng, [(n, n)] * k).reshape(k, n)


def means(rng: np.random.Generator, x: np.ndarray, k: int) -> np.ndarray:
    """Moyennes de k tirages avec remise : [rng.choice(x, len(x)).mean() for _ in range(k)]."""
    return x[draws(rng, len(x), k)].mean(axis=1)


def mean_diffs(rng: np.random.Generator, b: np.ndarray, a: np.ndarray, k: int) -> np.ndarray:
    """[rng.choice(b, len(b)).mean() - rng.choice(a, len(a)).mean() for _ in range(k)]."""
    nb, na = len(b), len(a)
    idx = flat(rng, [(nb, nb), (na, na)] * k).reshape(k, nb + na)
    return b[idx[:, :nb]].mean(axis=1) - a[idx[:, nb:]].mean(axis=1)
