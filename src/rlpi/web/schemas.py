"""Schémas des réponses de l'API (documentation OpenAPI, types TypeScript générés pour l'interface en phase F).

Le contenu du tableau de bord (`Tableau`) est calculé par rlpi.dashboard.content et envoyé tel quel (JSON déjà
sérialisé, mis en cache) : ces schémas le décrivent, sans le revalider à chaque requête. tests/test_api.py vérifie
que le contenu du jeu d'essai (toutes les combinaisons de l'instantané) leur correspond exactement : une clé ajoutée,
retirée ou renommée dans une section fait échouer le test.

Nombres à virgule : `Num` (float ou null). Les valeurs non finies (NaN, ±infini) sont envoyées en null, le JSON ne
sachant pas les écrire.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

Num = float | None


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ------------------------------------------------------------------------------------------------ compte


class Import(Strict):
    last_sync: datetime | None = Field(description="Dernière recherche terminée sur ballchasing")
    running: bool = Field(description="Recherche en cours")
    done: int = Field(description="Parties du joueur déjà traitées")
    waiting: int = Field(description="Parties en attente de traitement (tous joueurs)")


class Moi(Strict):
    id: str = Field(description="Identifiant du joueur connecté (« Steam:7656… »)")
    nom: str | None = Field(description="Dernier pseudo vu dans ses parties")
    parties: int = Field(description="Parties prêtes (agrégées) dans le tableau de bord")
    en_preparation: int = Field(description="Parties traitées dont les agrégats ne sont pas encore prêts")
    version: int = Field(description="Version des données du joueur (augmente à chaque nouvelle partie)")
    import_: Import = Field(alias="import")


class Actualisation(Strict):
    lancee: bool = Field(description="False si la recherche précédente date de moins de 5 minutes")
    message: str


class Jour(Strict):
    d: str = Field(description="Jour AAAA-MM-JJ")
    n: int = Field(description="Parties jouées ce jour-là")


class Profil(Strict):
    id: str
    joueurs: list[str] = Field(description="Le joueur puis ses coéquipiers proposés (au plus 2)")
    noms: dict[str, str] = Field(description="Pseudo de chacun")
    jours: list[Jour] = Field(description="Parties par jour (sélecteur de dates)")


# ------------------------------------------------------------------------------------------------ tableau de bord


class Filtres(Strict):
    since: str | None
    until: str | None
    with_: list[str] = Field(alias="with")
    without: list[str]


class Advice(Strict):
    kind: str
    title: str
    text: str
    why: str


class CompoRow(Strict):
    key: str
    label: str
    n: int
    parts: list[Num]


class Compo(Strict):
    key: str
    title: str
    labels: list[str]
    rows: list[CompoRow]


class Heat(Strict):
    gx: int
    gy: int
    n_pro_replays: int
    n_touches: int
    occ_me: list[Num]
    occ_lobby: list[Num]
    occ_pro: list[Num]
    touch_n: list[int]
    touch_dv: list[Num]
    touch_dv_pro: list[Num]
    touch_share_pro: list[Num]


class PassGroup(Strict):
    key: str
    label: str
    n: int
    n_games: int
    per5: Num
    recovered: Num
    void_lost: Num
    rec_mate: Num
    rec_nobody: Num
    dv_nobody: Num
    mate_pos: Num
    split: list[Num]


class PassMatch(Strict):
    replay: str
    date: str
    n: int
    per5: Num
    recovered: Num
    void_lost: Num


class VoidPass(Strict):
    date: str
    act: str
    clock: Num
    delay: Num
    dv: Num
    x: Num
    y: Num
    d_mate: Num
    d_opp: Num


class Passes(Strict):
    groups: list[PassGroup]
    matches: list[PassMatch]
    void: list[VoidPass]


class H2H(Strict):
    key: str
    label: str
    unit: str
    sens: int
    me: Num
    peer: Num
    value: bool = Field(default=False, description="Indicateur issu du modèle de valeur (absent pour les stats)")


class PeerValue(Strict):
    lobby_note: Num
    lobby_rank: Num
    plc_note: Num
    dec_note: Num


class Peer(Strict):
    id: str
    name: str
    n: int
    first: str
    last: str
    n_shared: int
    wins_shared: int
    h2h: list[H2H]
    value: PeerValue | None


class PerfComponent(Strict):
    key: str
    label: str
    weight: Num


class PerfSummary(Strict):
    n: int
    mean: Num
    lo: Num
    hi: Num
    fond: Num
    prod: Num
    win_good: Num
    win_bad: Num
    comps: dict[str, Num] = Field(description="Note moyenne de chaque composante (clé de `components`)")
    last5: Num = Field(default=None, description="Moyenne des 5 derniers matchs (joueur affiché seulement)")


class NamedIndex(Strict):
    name: str
    index: Num


class PerfMatch(Strict):
    replay: str
    date: str
    won: bool
    index: Num
    fond: Num
    prod: Num
    rank: int
    n_players: int
    opp_mean: Num
    comps: dict[str, Num]
    mates: list[NamedIndex]
    opps: list[NamedIndex]
    peers: dict[str, Num] = Field(description="Indice des coéquipiers comparés présents dans ce match")


class Retest(Strict):
    players: int
    matches_per_player: Num
    reliability_1: Num
    reliability_mean: Num
    matches_for_08: int | None


class SplitHalf(Strict):
    source: str
    n: int
    index: Num
    fond: Num
    prod: Num
    impact: Num
    placement: Num
    boost: Num
    vitesse: Num


class PerfValidation(Strict):
    version: int
    auc_player_oof: Num
    team_acc_oof: Num
    n_ref_matches: int
    n_ref_player_matches: int
    rlcs_n_matches: int
    rlcs_team_acc: Num
    rlcs_team_acc_fond: Num
    rlcs_team_acc_prod: Num
    perso_n_matches: int | None
    perso_team_acc: Num
    retest: dict[str, Retest]
    split_half: SplitHalf | None


class Perf(Strict):
    components: list[PerfComponent]
    me: PerfSummary | None
    lobby: PerfSummary | None
    peers: dict[str, PerfSummary | None]
    matches: list[PerfMatch]
    validation: PerfValidation


class ProgressChange(Strict):
    key: str
    label: str
    unit: str
    before: Num
    after: Num
    delta: Num
    lo: Num
    hi: Num
    effect: Num
    clear: bool
    headline: bool


class Progress(Strict):
    n: int
    half: int
    dates: list[str]
    index: list[Num]
    roll5: list[Num]
    won: list[bool]
    changes: list[ProgressChange]


class Record(Strict):
    d: str = Field(description="Date du replay")
    w: bool = Field(description="Victoire")
    s: str = Field(description="Score « pour-contre »")


class MetricMatch(Strict):
    d: str
    s: str
    v: Num
    w: int


class PeerMetric(Strict):
    value: Num
    pct: Num
    note: Num


class RefPoint(Strict):
    n: str = Field(description="Joueur de référence")
    v: Num


class Metric(Strict):
    key: str
    label: str
    cat: str
    unit: str
    sens: int
    value: Num
    pct: Num
    note: Num
    ref_med: Num
    ref: list[RefPoint]
    matches: list[MetricMatch]
    peers: dict[str, PeerMetric]


class RadarCat(Strict):
    cat: str
    n: int
    note: Num
    peers: dict[str, Num]


class Reference(Strict):
    label: str
    n_ref_matches: int
    n_ref_players: int
    ref_period: str
    metrics: list[Metric]
    radar: list[RadarCat]


class Signature(Strict):
    t: str
    pct: Num
    txt: str


class Like(Strict):
    name: str
    n: int


class StyleProfile(Strict):
    n: int
    main: int
    second: int | None
    pct: list[Num]
    regular: int
    signature: list[Signature]
    like: list[Like]
    polyvalent: bool


class StyleDef(Strict):
    name: str
    tagline: str
    trap: str
    factor: int
    pole: int
    retest: Num


class Style(Strict):
    styles: list[StyleDef]
    me: StyleProfile | None
    peers: dict[str, StyleProfile | None]
    team: list[int] = Field(description="Styles partagés par tout le trio (indices dans `styles`)")
    n_ref: int
    n_rlcs: int


class ChainStats(Strict):
    n: int
    sert: Num
    bonus: Num


class SynergyRow(Strict):
    key: str
    label: str
    unit: str
    sens: int
    v: Num
    lo: Num
    hi: Num
    ssl: Num
    random: Num


class SynergyPair(Strict):
    n: int
    n_chains: int
    won: Num
    me_to: ChainStats
    to_me: ChainStats
    rows: list[SynergyRow]


class Synergy(Strict):
    n_random: int
    pairs: dict[str, SynergyPair] = Field(description="Une entrée par coéquipier comparé")


class TechRow(Strict):
    key: str
    label: str
    unit: str
    sens: int
    def_: str = Field(alias="def", description="Définition de l'indicateur")
    me: Num
    lobby: Num
    ssl: Num
    rlcs: Num
    pct_ssl: Num
    ssl_q: list[Num]
    matches: list[Num]
    peers: dict[str, Num]


class Tech(Strict):
    n_lobby: int
    n_ssl: int
    n_rlcs: int
    rows: list[TechRow]


class Touch(Strict):
    replay: str
    match: str | None = Field(default=None, description="Identifiant de la partie (ralenti : POST /api/clips)")
    i: int | None = Field(default=None, description="Image de la touche à 10 images/s (absente des anciens agrégats)")
    date: str
    clock: Num
    action: str
    kind: str
    role: str
    dv: Num
    va: Num
    vb: Num
    x: Num
    y: Num


class ByAction(Strict):
    label: str
    n: int
    n5: Num
    me: Num
    ref: Num
    me_pos: Num
    ref_pos: Num


class CurveGoal(Strict):
    k: int = Field(description="Indice dans `v` (pas de 0,5 s)")
    pour: bool


class CurveTouch(Strict):
    k: int
    a: str
    clock: Num
    dv: Num
    va: Num
    vb: Num


class Curve(Strict):
    v: list[Num] = Field(description="Valeur de la situation (−1 à +1) du point de vue de l'équipe du joueur")
    goals: list[CurveGoal]
    touches: list[CurveTouch]
    score: str


class DecInfo(Strict):
    n_ref: int
    ref_med: Num
    ref_ppro: Num
    lobby_note: Num
    me_note: Num
    me_regret: Num
    me_ppro: Num


class PlcInfo(Strict):
    n_ref: int
    ref_med: Num
    lobby_med: Num
    lobby_note: Num
    me_note: Num
    me_med: Num


class Calibration(Strict):
    tranche: str
    n: int
    predit: Num
    observe: Num


class ValueModel(Strict):
    auc: Num
    horizon_s: int
    n_matches: int
    n_test_matches: int
    calibration: list[Calibration]


class ValueMatch(Strict):
    replay: str
    date: str
    n: int
    dv5: Num
    dv_mean: Num
    pos: Num
    lobby_rank: int | None
    lobby_note: Num
    rlcs_note: Num
    plc_err: Num
    plc_note: Num
    dec_regret: Num
    dec_note: Num
    dec_ppro: Num


class Value(Strict):
    matches: list[ValueMatch]
    by_action: list[ByAction]
    worst: list[Touch]
    best: list[Touch]
    curves: dict[str, Curve] = Field(description="Courbe de chaque match (clé : replay)")
    me_dv5: Num
    ref_dv5_med: Num
    lobby_dv5_med: Num
    me_lobby_note: Num
    me_lobby_rank: Num
    plc: PlcInfo | None
    dec: DecInfo | None
    ranked_goal_ratio: Num
    n_ref_pm: int
    n_ref_matches: int
    model: ValueModel | None


class Contenu(Strict):
    """Profil d'un joueur sur les parties retenues par les filtres."""

    player: str = Field(description="Pseudo")
    n_matches: int
    wins: int
    first: str
    last: str
    generated: str
    refs: dict[str, Reference] = Field(description="Comparaisons aux références (ssl, rlcs)")
    default_ref: str
    value: Value | None
    peers: list[Peer]
    passes: Passes | None
    heat: Heat | None
    perf: Perf | None
    synergy: Synergy | None
    compo: list[Compo]
    tech: Tech | None
    record: list[Record]
    filters: Filtres
    style: Style | None
    advice: list[Advice]
    progress: Progress | None


class FiltresTableau(Strict):
    j: str = Field(description="Joueur affiché (le joueur connecté ou un de ses coéquipiers proposés)")
    du: str | None
    au: str | None
    avec: list[str]
    sans: list[str]


class Tableau(Strict):
    joueur: str = Field(description="Joueur affiché")
    filtres: FiltresTableau = Field(description="Filtres réellement appliqués (les identifiants inconnus sont retirés)")
    contenu: Contenu | None = Field(description="Null si aucune partie ne correspond aux filtres")
    erreur: str | None


# ------------------------------------------------------------------------------------------------ match


class MatchJoueur(Strict):
    id: str
    nom: str | None
    equipe: int
    bot: bool


class Match(Strict):
    id: str
    replay: str
    date: str
    duree_s: Num = Field(description="Temps de jeu")
    score: list[int] = Field(description="Buts des équipes 0 et 1")
    equipe: int = Field(description="Équipe du joueur connecté")
    victoire: bool | None
    joueurs: list[MatchJoueur]
    courbe: Curve | None = Field(description="Déroulé du match du point de vue du joueur connecté")
    indices: list[PerfMatch] = Field(description="Indice de performance du joueur dans ce match (0 ou 1 ligne)")
    pires: list[Touch] = Field(description="Ses touches les plus coûteuses dans ce match")
    meilleures: list[Touch]


# ------------------------------------------------------------------------------------------------ modèles


class Score(Strict):
    axe: str = Field(description="Pertinence, Vérité, Efficacité ou Fiabilité")
    valeur: str
    reference: str
    lecture: str
    niveau: str = Field(description="ok, mid ou bad")


class Verdict(Strict):
    label: str
    niveau: str


class Fiche(Strict):
    """Textes avec un peu de HTML fixe (<b>), écrit dans rlpi.models_page : jamais de donnée de joueur."""

    title: str
    anchor: str
    role: str
    where: str
    how: list[str]
    scores: list[Score]
    verdict: Verdict
    limits: list[str]


class Resume(Strict):
    titre: str
    ancre: str
    verdict: str
    niveau: str
    chiffre: str


class Analyse(Strict):
    analyse: str
    donnees: str
    credible: str
    limite: str


class Modeles(Strict):
    resume: list[Resume]
    fiches: list[Fiche]
    analyses: list[Analyse]
    a_faire: list[str]
    absents: list[str] = Field(description="Fichiers absents du volume de données (fiches correspondantes omises)")
