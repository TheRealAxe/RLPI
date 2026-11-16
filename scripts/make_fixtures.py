"""Fabrique le jeu d'essai versionné des tests (tests/fixtures/) à partir de rlpi-data-lainox/ (non versionné).

    .venv/Scripts/python scripts/make_fixtures.py [--data rlpi-data-lainox] [--games 8]

Contenu produit :
- tests/fixtures/games/<partie>/ : quelques vraies parties du joueur suivi, au format exact écrit par le worker dans
  Garage (games/<partie>/ : frames/partie/…, features/<table>_partie.parquet, value_curves_partie.json, result.json) ;
- tests/fixtures/reference/ : références réduites (quelques parties RLCS et SSL) et rapports des modèles (JSON) ;
- tests/fixtures/joueurs.json : faux identifiants du joueur principal et de ses deux coéquipiers.

Anonymisation, cohérente d'une partie à l'autre : chaque identifiant de joueur devient un faux identifiant de la
même plateforme (un même joueur garde le même), chaque pseudo devient « Joueur NNN », chaque replay « partie-NN »,
« rlcs-NN » ou « ssl-NN », chaque GUID de match une valeur fictive, chaque chemin de fichier un chemin neutre.
À la fin, tous les fichiers produits sont relus : le script échoue si une seule valeur réelle (identifiant,
pseudo, nom de replay, GUID, chemin du poste) y apparaît encore.

Relancer ce script change l'instantané du tableau de bord (tests/snapshots/) : le régénérer ensuite avec
    .venv/Scripts/python -m pytest tests/test_snapshot.py --update-snapshot
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
from collections import Counter
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures"
GAME_SOURCE = "partie"  # comme rlpi.game
# Tables par partie produites par rlpi.game run (comme scripts/dev_setup.py)
TABLES = [
    "player_match_stats",
    "touch_values",
    "goal_xv",
    "touch_decisions",
    "placement",
    "passes",
    "perf",
    "defense",
    "kickoffs",
]
# Références lues par le tableau de bord
REF_TABLES = [
    "player_match_stats_rlcs",
    "touch_values_rlcs",
    "touch_decisions_rlcs",
    "placement_rlcs",
    "passes_rlcs",
    "player_match_stats_ssl",
    "synergy_ssl",
]
MODEL_REPORTS = ["styles.json", "perf_report.json", "value_h5_report.json"]
ID_COLS = {"player_id": "player_name", "a": "a_name", "b": "b_name"}  # identifiant → colonne du pseudo


def stem(s: str) -> str:
    return Path(str(s).replace("\\", "/")).name.removesuffix(".replay")


class Anon:
    """Correspondances valeur réelle → valeur fictive, et liste de tout ce qui ne doit plus apparaître."""

    def __init__(self) -> None:
        self.ids: dict[str, str] = {}
        self.names: dict[str, str] = {}  # identifiant réel → faux pseudo
        self.replays: dict[str, str] = {}
        self.guids: dict[str, str] = {}
        self.real_names: set[str] = set()

    def pid(self, real: str | None) -> str | None:
        if real is None:
            return None
        if real not in self.ids:
            n = len(self.ids) + 1
            plat, _, rest = real.partition(":")
            if rest.isdigit():
                fake = f"{plat}:{76561190000000000 + n}"
            elif re.fullmatch(r"[0-9a-fA-F]{32}", rest):
                fake = f"{plat}:{n:032x}"
            else:
                fake = f"{plat}:joueur{n:04d}"
            self.ids[real] = fake
            self.names[real] = f"Joueur {n:03d}"
        return self.ids[real]

    def name(self, real_id: str | None, real_name: str | None) -> str | None:
        if real_name:
            self.real_names.add(real_name)
        if real_id is None:
            return None
        self.pid(real_id)
        return self.names[real_id]

    def replay(self, real: str, prefix: str) -> str:
        real = stem(real)
        if real not in self.replays:
            n = sum(1 for v in self.replays.values() if v.startswith(prefix + "-")) + 1
            self.replays[real] = f"{prefix}-{n:02d}"
        return self.replays[real]

    def guid(self, real: str | None) -> str | None:
        if not real:
            return real
        if real not in self.guids:
            self.guids[real] = f"{len(self.guids) + 1:032X}"
        return self.guids[real]

    # ---------------------------------------------------------------------------------------------- tables
    def frame(self, df: pl.DataFrame, prefix: str) -> pl.DataFrame:
        def m(col: str, fn) -> pl.Expr:
            return pl.col(col).map_elements(fn, return_dtype=pl.String, skip_nulls=True)

        cols = df.columns
        exprs = []
        for idc, namec in ID_COLS.items():
            if idc in cols and namec in cols:
                exprs.append(
                    pl.struct(idc, namec)
                    .map_elements(lambda s, i=idc, n=namec: self.name(s[i], s[n]), return_dtype=pl.String)
                    .alias(namec)
                )
        for idc in ID_COLS:
            if idc in cols:
                exprs.append(m(idc, self.pid))
        if "replay" in cols:
            exprs.append(m("replay", lambda v: self.replay(v, prefix)))
        if "replay_file" in cols:
            exprs.append(m("replay_file", lambda v: self.replay(v, prefix) + ".replay"))
        if "replay_path" in cols:
            exprs.append(m("replay_path", lambda v: f"replays/{self.replay(v, prefix)}.replay"))
        if "replay_id" in cols:  # identifiant du replay dans le jeu : remplacé par un faux, propre à la partie
            exprs.append(
                pl.struct("replay_file", "replay_id")
                .map_elements(
                    lambda s: (
                        f"{int(self.replay(s['replay_file'], prefix).split('-')[1]):032X}" if s["replay_id"] else None
                    ),
                    return_dtype=pl.String,
                )
                .alias("replay_id")
            )
        if "match_guid" in cols:
            exprs.append(m("match_guid", self.guid))
        if "recorder" in cols:
            exprs.append(pl.lit(None, dtype=pl.String).alias("recorder"))
        return df.with_columns(exprs) if exprs else df

    def meta(self, m: dict, prefix: str) -> dict:
        m = dict(m)
        m["replay"] = self.replay(m["replay"], prefix)
        m["path"] = f"replays/{m['replay']}.replay"
        m["players"] = [{**p, "name": self.name(p["id"], p.get("name")), "id": self.pid(p["id"])} for p in m["players"]]
        return m

    def json(self, x, prefix: str):
        """Rapports des modèles : tout objet {"id": <joueur>, "name": <pseudo>} (exemples de joueurs) est anonymisé."""
        if isinstance(x, dict):
            x = {k: self.json(v, prefix) for k, v in x.items()}
            if isinstance(x.get("id"), str) and re.fullmatch(r"[A-Za-z0-9]+:\S+", x["id"]):
                x["name"] = self.name(x["id"], x.get("name"))
                x["id"] = self.pid(x["id"])
            return x
        if isinstance(x, list):
            return [self.json(v, prefix) for v in x]
        return x

    def forbidden(self) -> tuple[list[str], set[str]]:
        """Ce qui ne doit plus apparaître : (valeurs distinctives, cherchées partout ; pseudos, comparés à chaque
        valeur texte entière, pour ne pas confondre un pseudo comme « zen » avec un mot ou une colonne)."""
        vals = set(self.ids) | {i.partition(":")[2] for i in self.ids} | set(self.replays) | set(self.guids)
        vals |= {"theol", "Users\\", "rlpi-v2-kit", "TAGame"}
        return (
            sorted((v for v in vals if v and len(v) >= 4), key=len, reverse=True),
            {n.strip().lower() for n in self.real_names if n.strip()},
        )


def write_parquet(df: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path, compression="zstd", compression_level=19, statistics=False)


# ------------------------------------------------------------------------------------------------- choix
def choose_games(st: pl.DataFrame, frames: Path, n: int) -> tuple[str, list[str], list[str]]:
    """Joueur principal (présent dans le plus de parties), ses 2 coéquipiers les plus fréquents et n parties :
    surtout avec les deux coéquipiers (au moins 5, pour qu'ils soient comparés), plus deux sans eux."""
    st = st.with_columns(pl.col("replay_file").map_elements(stem, return_dtype=pl.String).alias("r"))
    st = st.filter(pl.col("r").map_elements(lambda r: (frames / f"{r}.parquet").exists(), return_dtype=pl.Boolean))
    main = (
        st.group_by("player_id")
        .agg(pl.col("r").n_unique().alias("n"))
        .sort("n", "player_id", descending=True)["player_id"][0]
    )
    mine = st.filter(pl.col("player_id") == main).select("r", "team", "date")
    mates = st.join(mine.select("r", "team"), on=["r", "team"]).filter(pl.col("player_id") != main)
    top = mates.group_by("player_id").agg(pl.len().alias("n")).sort("n", "player_id", descending=True)
    m1, m2 = top["player_id"][:2].to_list()
    with_ = {r: set(g["player_id"].to_list()) for (r,), g in mates.group_by("r")}
    games = sorted(mine.unique("r").rows(), key=lambda x: x[2])  # (r, team, date) par date
    both = [r for r, _, _ in games if {m1, m2} <= with_.get(r, set())]
    none = [r for r, _, _ in games if not ({m1, m2} & with_.get(r, set()))]
    chosen = both[-(n - 2) :] + none[-2:]
    if len(chosen) < n:
        chosen += [r for r, _, _ in games if r not in chosen][-(n - len(chosen)) :]
    return main, [m1, m2], sorted(chosen)


def choose_rlcs(frames: Path, n_series: int = 2, per_series: int = 4) -> list[str]:
    """Quelques parties RLCS avec images (carte de chaleur des pros), regroupées par affiche : les mêmes joueurs
    reviennent dans plusieurs parties (au moins 2 parties par joueur pour la référence RLCS)."""
    series: dict[frozenset, list[str]] = {}
    for mp in sorted(frames.glob("*.meta.json")):
        r = mp.name.removesuffix(".meta.json")
        if not (frames / f"{r}.parquet").exists():
            continue
        m = json.loads(mp.read_text(encoding="utf-8"))
        series.setdefault(frozenset(p["id"] for p in m["players"]), []).append(r)
    best = sorted(series.values(), key=lambda v: (-len(v), v[0]))[:n_series]
    return sorted(r for v in best for r in v[:per_series])


# ------------------------------------------------------------------------------------------------- écriture
def make(data: Path, n_games: int, seed: int = 2026) -> None:
    anon = Anon()
    feats, fr_perso, fr_rlcs = data / "features", data / "frames" / "perso", data / "frames" / "rlcs"
    st = pl.read_parquet(feats / "player_match_stats_perso.parquet")
    main, mates, games = choose_games(st, fr_perso, n_games)
    print(f"{len(games)} parties retenues")

    if OUT.exists():
        shutil.rmtree(OUT)
    # Joueurs suivis d'abord : faux identifiants stables (Joueur 001 = joueur principal)
    for pid in (main, *mates):
        anon.pid(pid)

    # 1. Parties du joueur, au format écrit par le worker
    curves = {c["replay"]: c for c in json.loads((feats / "value_curves_perso.json").read_text(encoding="utf-8"))}
    tables = {}
    for t in TABLES:
        f = feats / f"{t}_perso.parquet"
        if f.exists():
            df = pl.read_parquet(f)
            key = "replay_file" if t == "player_match_stats" else "replay"
            tables[t] = df.with_columns(pl.col(key).map_elements(stem, return_dtype=pl.String).alias("_game"))
    for r in games:
        meta = anon.meta(json.loads((fr_perso / f"{r}.meta.json").read_text(encoding="utf-8")), "partie")
        fake = meta["replay"]
        d = OUT / "games" / fake
        fd = d / "frames" / GAME_SOURCE
        fd.mkdir(parents=True)
        (fd / f"{fake}.meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        for suffix in (".parquet", ".touches.parquet"):
            write_parquet(pl.read_parquet(fr_perso / f"{r}{suffix}"), fd / f"{fake}{suffix}")
        parts = {t: anon.frame(df.filter(pl.col("_game") == r).drop("_game"), "partie") for t, df in tables.items()}
        for t, df in parts.items():
            if df.height:
                write_parquet(df, d / "features" / f"{t}_{GAME_SOURCE}.parquet")
        cv = [{**curves[r], "replay": fake}] if r in curves else []
        (d / "features" / f"value_curves_{GAME_SOURCE}.json").write_text(json.dumps(cv), encoding="utf-8")
        st_g = parts["player_match_stats"]
        guid = next((g for g in st_g["match_guid"].unique().to_list() if g), None)
        result = {
            "replay": fake,
            "file": f"{fake}.replay",
            "status": "ok",
            "date": meta["date"],
            "match_type": meta.get("match_type"),
            "n_frames": meta.get("n_frames"),
            "n_touches": meta.get("n_touches"),
            "players": meta["players"],
            "score": [meta.get("team0_score"), meta.get("team1_score")],
            "match_guid": guid,
            "online_3v3": bool(st_g.height),
            "steps": {},
            "errors": {},
            "rempli_par": "scripts/make_fixtures.py",
        }
        (d / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    # 2. Références réduites
    ref = OUT / "reference"
    rlcs = choose_rlcs(fr_rlcs)
    rng = random.Random(seed)
    ssl_all = sorted(
        pl.read_parquet(feats / "player_match_stats_ssl.parquet", columns=["replay_file"])["replay_file"]
        .map_elements(stem, return_dtype=pl.String)
        .unique()
        .to_list()
    )
    ssl = sorted(rng.sample(ssl_all, 40))
    print(f"références : {len(rlcs)} parties RLCS, {len(ssl)} parties SSL")
    for name in REF_TABLES:
        keep, prefix = (rlcs, "rlcs") if name.endswith("_rlcs") else (ssl, "ssl")
        df = pl.read_parquet(feats / f"{name}.parquet")
        key = "replay_file" if "replay_file" in df.columns else "replay"
        df = df.filter(pl.col(key).map_elements(stem, return_dtype=pl.String).is_in(keep))
        write_parquet(anon.frame(df, prefix), ref / "features" / f"{name}.parquet")
    for r in rlcs:
        meta = anon.meta(json.loads((fr_rlcs / f"{r}.meta.json").read_text(encoding="utf-8")), "rlcs")
        out = ref / "frames" / "rlcs"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{meta['replay']}.meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        # Le tableau de bord ne lit que la phase de jeu et les positions x, y (carte de chaleur des pros)
        cols = ["phase"] + [f"p{p['slot']}_{a}" for p in meta["players"] for a in ("x", "y")]
        write_parquet(pl.read_parquet(fr_rlcs / f"{r}.parquet", columns=cols), out / f"{meta['replay']}.parquet")
    (ref / "models").mkdir(parents=True)
    for name in MODEL_REPORTS:
        rep = anon.json(json.loads((data / "models" / name).read_text(encoding="utf-8")), "ref")
        (ref / "models" / name).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    players = {"principal": anon.pid(main), "coequipiers": [anon.pid(m) for m in mates]}
    (OUT / "joueurs.json").write_text(json.dumps(players, indent=1) + "\n", encoding="utf-8")
    check(anon.forbidden())
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(
        f"→ {OUT} : {sum(1 for f in OUT.rglob('*') if f.is_file())} fichiers, {size / 1e6:.1f} Mo ; joueurs {players}"
    )


def _strings(x, out: list[str]) -> None:
    if isinstance(x, dict):
        for k, v in x.items():
            out.append(str(k))
            _strings(v, out)
    elif isinstance(x, list):
        for v in x:
            _strings(v, out)
    elif isinstance(x, str):
        out.append(x)


def check(forbidden: tuple[list[str], set[str]]) -> None:
    """Relit tout ce qui a été produit : aucune valeur réelle ne doit rester."""
    distinct, names = forbidden
    pattern = re.compile("|".join(re.escape(v) for v in distinct), re.IGNORECASE)
    found = Counter()
    for f in sorted(OUT.rglob("*")):
        values: list[str] = []
        names_ok = [f.name]  # noms de fichiers et de colonnes : seulement les valeurs distinctives
        if f.suffix == ".parquet":
            df = pl.read_parquet(f)
            names_ok += df.columns
            for c in df.columns:
                if df[c].dtype == pl.String:
                    values += [v for v in df[c].unique().to_list() if v is not None]
        elif f.suffix == ".json":
            _strings(json.loads(f.read_text(encoding="utf-8")), values)
        elif f.is_file():
            values.append(f.read_text(encoding="utf-8"))
        else:
            continue
        rel = f.relative_to(OUT).as_posix()
        for v in names_ok:
            for m in pattern.finditer(v):
                found[(rel, "valeur", len(m.group(0)))] += 1
        for v in values:
            for m in pattern.finditer(v):
                found[(rel, "valeur", len(m.group(0)))] += 1
            if v.strip().lower() in names:
                found[(rel, "pseudo", len(v))] += 1
    if found:
        for (f, kind, n_chars), n in sorted(found.items())[:40]:
            print(f"  {kind} réel restant : {f} ({n} fois, {n_chars} caractères)")
        raise SystemExit(f"Anonymisation incomplète : {len(found)} cas (valeurs non affichées)")
    print(f"vérification : aucune des {len(distinct) + len(names)} valeurs réelles ne figure dans le jeu d'essai")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=str(ROOT / "rlpi-data-lainox"))
    ap.add_argument("--games", type=int, default=8)
    a = ap.parse_args()
    make(Path(a.data), a.games)


if __name__ == "__main__":
    main()
