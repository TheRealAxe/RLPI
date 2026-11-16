"""Contenu du tableau de bord à partir des agrégats des parties (rlpi.dashboard.aggregate) et de la référence
(rlpi.dashboard.reference) : aucune lecture de fichier, seulement des petites tables en mémoire.

    games = Games(agrégats des parties du joueur connecté)
    page(games, référence, joueur connecté, j, du, au, avec, sans)   → contenu de la page /moi
    make_payload(games, référence, joueur, comparés, …)              → profil d'un joueur (même structure qu'avant)

Les parties sont rangées dans l'ordre de leur identifiant : c'est l'ordre dans lequel elles étaient rassemblées
avant les agrégats ; les tirages (intervalles de l'indice) restent donc les mêmes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime

import polars as pl

from rlpi.dashboard import advice, heat, passes, perf, style, synergy, value
from rlpi.dashboard import peers as peers_mod
from rlpi.dashboard.aggregate import VALUE_COLUMNS
from rlpi.dashboard.metrics import COMPO_COLUMNS, compare, composition_parts, compositions, tech_section

MIN_GAMES_TOGETHER = 5  # coéquipier comparé : au moins 5 parties ensemble


class NoGames(Exception):
    """Aucune partie du joueur pour ces filtres."""


class PlayerGame:
    __slots__ = ("cols", "data", "details")

    def __init__(self, cols: dict, data: dict, details: dict | None):
        self.cols, self.data, self.details = cols, data, details if details is not None else {}


class GameRow:
    def __init__(self, agg: dict):
        g = agg["game"]
        self.match_id: str = agg["match_id"]
        self.replay: str = agg["replay"]
        self.date: str = g["date"]
        self.play_s: float = g["play_s"]
        self.score: list[int] = g["score"]
        self.team_of: dict[str, int] = {p["id"]: p["team"] for p in g["players"]}
        self.curve: dict | None = g.get("curve")
        self.pairs: list[dict] = g.get("pairs") or []
        self.players: dict[str, PlayerGame] = {
            pid: PlayerGame(p.get("cols", {}), p.get("data", {}), p.get("details")) for pid, p in agg["players"].items()
        }


class Games:
    """Les parties d'un joueur (toutes, avant filtres). `details_loader(joueur)` : {partie: détails} du joueur,
    pour les agrégats lus en base sans leurs détails."""

    def __init__(self, aggs: Iterable[dict], details_loader: Callable[[str], dict[str, dict]] | None = None):
        self.games = sorted((GameRow(a) for a in aggs), key=lambda g: g.match_id)
        self.by_replay = {g.replay: g for g in self.games}
        self._loader = details_loader
        self._loaded: set[str] = set()
        pgs = [pg for g in self.games for pg in g.players.values()]
        self.has_touches = any("touch" in pg.data for pg in pgs)
        self.has_passes = any("passes" in pg.data for pg in pgs)
        self.has_perf = any("perf" in pg.data for pg in pgs)
        self.has_synergy = any(g.pairs for g in self.games)
        # ΔV moyen de chaque joueur sur toutes les parties (bonus des enchaînements, voir rlpi.dashboard.synergy)
        n: dict[str, int] = {}
        s: dict[str, float] = {}
        for g in self.games:
            for pid, pg in g.players.items():
                t = pg.data.get("touch")
                if t:
                    n[pid] = n.get(pid, 0) + t["n"]
                    s[pid] = s.get(pid, 0.0) + t["dv_sum"]
        self.mean_dv = {pid: s[pid] / n[pid] for pid in n}
        self._stats: pl.DataFrame | None = None
        self.version = 0  # version des données du joueur (rlpi.dashboard.storage), clé des caches

    def __len__(self) -> int:
        return len(self.games)

    def ordered(self, replays: Iterable[str]) -> list[GameRow]:
        keep = set(replays)
        return [g for g in self.games if g.replay in keep]

    def ensure_details(self, player: str) -> None:
        if self._loader is None or player in self._loaded:
            return
        for mid, det in self._loader(player).items():
            for g in self.games:
                if g.match_id == mid and player in g.players:
                    g.players[player].details = det
        self._loaded.add(player)

    def stats(self) -> pl.DataFrame:
        """Une ligne par joueur et par partie en ligne 3v3 (stats subtr-actor), dans l'ordre des parties."""
        if self._stats is None:
            rows = []
            for g in self.games:
                part = sorted(
                    ((pid, pg) for pid, pg in g.players.items() if pg.cols.get("in_stats")),
                    key=lambda x: x[1].data.get("row", 0),
                )
                for pid, pg in part:
                    c = pg.cols
                    rows.append(
                        {
                            "replay": g.replay,
                            "date": c["date"],
                            "player_id": pid,
                            "player_name": c["player_name"],
                            "team": c["team"],
                            "is_bot": c["is_bot"],
                            "won": c["won"],
                            "team_goals": c["team_goals"],
                            "opp_goals": c["opp_goals"],
                            **{k: c.get(k) for k in VALUE_COLUMNS},
                            **pg.data.get("compo", {}),
                        }
                    )
            schema = {
                "replay": pl.String,
                "date": pl.String,
                "player_id": pl.String,
                "player_name": pl.String,
                "team": pl.Int64,
                "is_bot": pl.Boolean,
                "won": pl.Int64,
                "team_goals": pl.Int64,
                "opp_goals": pl.Int64,
            } | dict.fromkeys(VALUE_COLUMNS, pl.Float64)
            present = [c for c in COMPO_COLUMNS if any(c in r for r in rows)]
            schema |= dict.fromkeys(present, pl.Float64)
            self._stats = pl.DataFrame(rows, schema=schema)
        return self._stats


def filter_games(
    df: pl.DataFrame,
    since: str | None = None,
    until: str | None = None,
    with_ids: list[str] | None = None,
    without_ids: list[str] | None = None,
) -> pl.DataFrame:
    """Garde les parties dans la plage de dates (jours inclus) et selon la présence de joueurs."""
    if since:  # date du replay « AAAA-MM-JJ HH-MM-SS »
        df = df.filter(pl.col("date") >= since)
    if until:
        df = df.filter(pl.col("date") <= until + " 99")
    keep = None
    present = df.group_by("replay").agg(pl.col("player_id"))
    for pid in with_ids or []:
        ok = set(present.filter(pl.col("player_id").list.contains(pid))["replay"].to_list())
        keep = ok if keep is None else keep & ok
    for pid in without_ids or []:
        ok = set(present.filter(~pl.col("player_id").list.contains(pid))["replay"].to_list())
        keep = ok if keep is None else keep & ok
    return df if keep is None else df.filter(pl.col("replay").is_in(list(keep)))


def make_payload(
    games: Games,
    ref: dict,
    player: str,
    compare_with: list[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    with_ids: list[str] | None = None,
    without_ids: list[str] | None = None,
) -> dict:
    perso = filter_games(games.stats(), since, until, with_ids, without_ids)
    me = perso.filter(pl.col("player_id") == player).sort("date")
    # Joueurs comparés : identifiants ou pseudos présents dans les parties de l'utilisateur
    peers = {}
    for q in compare_with or []:
        d = perso.filter((pl.col("player_id") == q) | (pl.col("player_name").str.to_lowercase() == q.lower()))
        if d.is_empty():
            continue
        pid = d["player_id"].mode()[0]
        peers[pid] = d.filter(pl.col("player_id") == pid).sort("date")
    if me.is_empty():
        raise NoGames(f"Joueur {player} absent des replays")
    games.ensure_details(player)
    # Les autres joueurs des parties de l'utilisateur ne servent pas de référence (niveau inconnu).
    refs = {key: {"label": r["label"], **compare(me, r, player, peers)} for key, r in ref["compare"].items()}
    my_replays = me["replay"].to_list()
    my_value = value.section(ref["value"], games, player, my_replays)
    payload = {
        "player": me["player_name"][-1],
        "n_matches": me.height,
        "wins": int(me["won"].sum()),
        "first": me["date"][0][:10],
        "last": me["date"][-1][:10],
        "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "refs": refs,
        "default_ref": "ssl" if "ssl" in refs and refs["ssl"]["n_ref_players"] >= 30 else "rlcs",
        "value": my_value,
        "peers": peers_mod.section(ref["value"], games, my_value, me, peers),
        "passes": passes.section(ref["passes"], games, player, my_replays, peers),
        "heat": heat.section(ref["heat"], games, player, my_replays) if games.has_touches else None,
        "perf": perf.section(ref["perf"], games, player, my_replays, peers),
        "synergy": synergy.section(ref["synergy"], games, player, my_replays, peers),
    }
    lobby_df = perso.filter(
        pl.col("replay").is_in(my_replays) & ~pl.col("player_id").is_in([player, *peers]) & ~pl.col("is_bot")
    )
    groups = [("me", payload["player"], composition_parts(me))]
    groups += [(pid, d["player_name"][-1], composition_parts(d)) for pid, d in peers.items()]
    groups.append(("lobby", "Lobbies", composition_parts(lobby_df)))
    groups += [tuple(g) for g in ref["compo"]]
    payload["compo"] = compositions(groups)  # type: ignore[arg-type]
    payload["tech"] = tech_section(ref["tech"], me, peers, lobby_df) if ref["tech"] else None
    payload["record"] = [
        {"d": d, "w": bool(w), "s": f"{g}-{o}"}
        for d, w, g, o in me.select("date", "won", "team_goals", "opp_goals").iter_rows()
    ]
    payload["filters"] = {"since": since, "until": until, "with": with_ids or [], "without": without_ids or []}
    payload["style"] = style.section(ref["style"], games, player, my_replays, peers)
    payload["advice"] = advice.advice_section(payload)
    payload["progress"] = advice.progress_section(payload)
    return payload


def profile_ids(games: Games, me: str) -> tuple[list[str], dict[str, str], list[dict]]:
    """Le joueur et ses coéquipiers les plus fréquents (2 au plus), leurs pseudos, ses parties par jour."""
    st = games.stats().select("player_id", "player_name", "date", "replay", "team")
    mine = st.filter(pl.col("player_id") == me).select("replay", "team")
    mates = st.join(mine, on=["replay", "team"]).filter(pl.col("player_id") != me)
    top = (
        mates.group_by("player_id")
        .agg(pl.len().alias("n"))
        .filter(pl.col("n") >= MIN_GAMES_TOGETHER)
        .sort(["n", "player_id"], descending=[True, False])
    )
    ids = [me, *top["player_id"].head(2).to_list()]
    names = {pid: st.filter(pl.col("player_id") == pid).sort("date")["player_name"][-1] for pid in ids}
    days = (
        st.filter(pl.col("player_id") == me)
        .unique("replay")
        .with_columns(pl.col("date").str.slice(0, 10).alias("d"))
        .group_by("d")
        .agg(pl.len().alias("n"))
        .sort("d")
        .to_dicts()
    )
    return ids, names, days


def page(
    games: Games,
    ref: dict,
    player_id: str,
    j: str | None,
    since: str | None,
    until: str | None,
    avec: list[str],
    sans: list[str],
) -> dict:
    """Contenu de la page /moi du joueur connecté (structure attendue par le gabarit)."""
    ids, names, days = profile_ids(games, player_id)
    d = dashboard(games, ref, player_id, j, since, until, avec, sans, ids)
    return {
        "dynamic": True,
        "default": d["joueur"],
        "order": ids,
        "names": names,
        "days": days,
        "filters": d["filtres"],
        "profiles": {d["joueur"]: d["contenu"]} if d["contenu"] else {},
        "error": d["erreur"],
    }


def dashboard(
    games: Games,
    ref: dict,
    player_id: str,
    j: str | None,
    since: str | None,
    until: str | None,
    avec: list[str],
    sans: list[str],
    ids: list[str] | None = None,
) -> dict:
    """Tableau de bord du joueur connecté (API : GET /api/joueurs/{id}/tableau). `j` : joueur affiché, le joueur
    connecté ou un de ses coéquipiers proposés (toujours sur les parties du joueur connecté). Les identifiants
    inconnus sont retirés des filtres."""
    if ids is None:
        ids = profile_ids(games, player_id)[0]
    sel = j if j in ids else ids[0]
    avec = [x for x in avec if x in ids and x != sel]
    sans = [x for x in sans if x in ids and x != sel and x not in avec]
    try:
        pay, err = make_payload(games, ref, sel, [i for i in ids if i != sel], since, until, avec, sans), None
    except NoGames as e:  # aucune partie pour ce filtre
        pay, err = None, str(e)
    return {
        "joueur": sel,
        "filtres": {"j": sel, "du": since, "au": until, "avec": avec, "sans": sans},
        "contenu": pay,
        "erreur": err,
    }
