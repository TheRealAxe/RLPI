"""Partie fixe du tableau de bord : tout ce qui dépend des références (RLCS, SSL) et des rapports des modèles.

Calculée une fois (au démarrage du serveur, si les fichiers ont changé : voir rlpi.dashboard.storage), puis lue
à chaque calcul de contenu. Les distributions de référence sont gardées en entier (pas en quantiles) : les
centiles affichés sont exactement ceux d'avant les agrégats.

    python -m rlpi.dashboard.reference          # recalcule et enregistre dans Postgres (dossiers RLPI_DATA, RLPI_MODELS)
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import polars as pl

from rlpi.context import DataContext
from rlpi.dashboard import heat, passes, perf, style, synergy, value
from rlpi.dashboard.metrics import REFS, compare_reference, composition_parts, metrics, tech_metrics, tech_reference

VERSION = 1  # à augmenter quand le calcul de la référence change


@lru_cache(maxsize=8)
def _play_seconds(frames: Path, stamp: int) -> tuple:
    out = []
    for p in frames.glob("*.meta.json"):
        m = json.loads(p.read_text(encoding="utf-8"))
        out.append((m["replay"], m["n_play_frames"] / 10))
    return tuple(out)


def play_seconds(ctx: DataContext, source: str) -> dict[str, float]:
    d = ctx.frames(source)
    try:
        stamp = d.stat().st_mtime_ns
    except FileNotFoundError:
        stamp = 0
    return dict(_play_seconds(d, stamp))


def inputs(ctx: DataContext) -> list[Path]:
    """Fichiers lus par la référence (leur empreinte décide s'il faut la recalculer)."""
    feats = [
        ctx.features(src) / f
        for src, f in (
            ("rlcs", "player_match_stats_rlcs.parquet"),
            ("ssl", "player_match_stats_ssl.parquet"),
            ("rlcs", "touch_values_rlcs.parquet"),
            ("rlcs", "placement_rlcs.parquet"),
            ("rlcs", "touch_decisions_rlcs.parquet"),
            ("rlcs", "passes_rlcs.parquet"),
            ("ssl", "synergy_ssl.parquet"),
        )
    ]
    models = [ctx.models / f for f in ("value_h5_report.json", "perf_report.json", "styles.json")]
    frames = sorted(ctx.frames("rlcs").glob("*.meta.json"))
    return feats + models + frames + [f.with_name(f.name.removesuffix(".meta.json") + ".parquet") for f in frames]


def fingerprint(ctx: DataContext) -> str:
    from rlpi.dashboard.aggregate import VERSION as AGG_VERSION

    h = hashlib.sha1(f"ref{VERSION}/agg{AGG_VERSION}".encode())
    for f in inputs(ctx):
        try:
            s = f.stat()
            h.update(f"{f.name}:{s.st_size}:{s.st_mtime_ns};".encode())
        except FileNotFoundError:
            h.update(f"{f.name}:-;".encode())
    return h.hexdigest()


def build(ctx: DataContext) -> dict:
    compare, compo = {}, []
    for key, (fname, label, min_n) in REFS.items():
        path = ctx.features(key) / fname
        if not path.exists():
            continue
        raw = pl.read_parquet(path)
        ref_df = metrics(raw)
        if ref_df.is_empty():
            continue
        compare[key] = {"label": label, **compare_reference(ref_df, min_n)}
        compo.append((key, f"Joueurs {label}", composition_parts(raw.filter(~pl.col("is_bot")))))
    tech = None
    if all((ctx.features(k) / REFS[k][0]).exists() for k in ("ssl", "rlcs")):
        read = lambda k: tech_metrics(pl.read_parquet(ctx.features(k) / REFS[k][0])).filter(~pl.col("is_bot"))  # noqa: E731
        tech = tech_reference(read("ssl"), read("rlcs"))
    has_tv = ctx.feature("touch_values", "rlcs").exists()
    return {
        "version": VERSION,
        "compare": compare,
        "compo": compo,
        "tech": tech,
        "value": value.reference(ctx, play_seconds),
        "passes": passes.reference(ctx, play_seconds),
        "heat": heat.reference(ctx) if has_tv else None,
        "perf": perf.reference(ctx),
        "synergy": synergy.reference(ctx),
        "style": style.reference(ctx),
    }


def main() -> None:
    from rlpi.dashboard import storage

    ctx = DataContext.default()
    storage.ensure_reference(ctx, force=True)
    print("référence du tableau de bord recalculée et enregistrée")


if __name__ == "__main__":
    main()
