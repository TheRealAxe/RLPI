<script setup lang="ts">
// Page d'accueil (maquette rlpi-accueil, 24/11/2026) : présentation animée de RLPI et connexion Steam (obligatoire,
// plus aucun tableau de bord public). Affichée d'office aux visiteurs non connectés ; une fois connecté, on y revient
// par /accueil (lien du tableau de bord) et les boutons de connexion mènent au tableau de bord et au jeu.
// Un retour de Steam refusé arrive ici avec ?connexion=echec. En développement (RLPI_DEV_LOGIN=1), /dev/joueurs
// répond et la page propose d'ouvrir une session pour un joueur connu, sans Steam ; ailleurs, cette route est une 404.
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { RouterLink } from "vue-router";
import { getJson, type Accueil } from "../api/client";
import { mountAccueil } from "../lib/accueil";
import { store } from "../lib/store";
import "../styles/accueil.css";

type DevPlayer = { id: string; pseudo: string | null; parties: number };

// Connecté : la page est ouverte depuis le tableau de bord (route /accueil).
const connected = computed(() => !!store.moi);
const tdb = { name: "ma-forme" } as const;
const failed = new URLSearchParams(location.search).get("connexion") === "echec";
const devPlayers = ref<DevPlayer[] | null>(null);
const root = ref<HTMLElement | null>(null);
// Parties analysées, parties SSL et matchs RLCS de la référence (route publique /api/accueil, chiffres lus à chaque
// chargement) ; un chiffre absent n'est pas affiché, et rien si l'API ne répond pas.
const chiffres = reactive<{ parties: string | null; ssl: string | null; rlcs: string | null }>({
  parties: null,
  ssl: null,
  rlcs: null,
});
const fr = (n: number | null | undefined) => (n ? n.toLocaleString("fr-FR") : null);
let stop: (() => void) | null = null;

// Cartes de démonstration du jeu « Juger à l'aveugle » (trajectoire de la voiture, balle, légende).
const judgeCards = [
  { t: "1:12", path: "M30 92 C55 86,80 70,112 56", ball: "M112 56 C140 44,165 52,190 58", cx: 112, cy: 56, bx: 120, by: 52, cap: "Challenge au centre, balle poussée vers le but" },
  { t: "3:47", path: "M150 30 C120 40,90 40,64 62", ball: "M70 58 C60 70,40 82,14 64", cx: 64, cy: 62, bx: 56, by: 66, cap: "Retour en défense, au second poteau" },
  { t: "0:25", path: "M40 30 C70 34,96 56,104 84", ball: "M110 88 C130 96,150 96,176 90", cx: 104, cy: 84, bx: 112, by: 88, cap: "Passe tentée vers un coéquipier" },
  { t: "4:58", path: "M170 90 C150 80,130 60,124 40", ball: "", cx: 124, cy: 40, bx: 118, by: 32, cap: "Saut pour couper la balle" },
];

const devHref =(id: string) => `/dev/connexion?${new URLSearchParams({ joueur: id })}`;

onMounted(async () => {
  document.title = "RLPI · Rocket League Player Index";
  document.documentElement.style.scrollBehavior = "smooth";
  if (root.value) stop = mountAccueil(root.value);
  getJson<Accueil>("/api/accueil")
    .then((a) => {
      chiffres.parties = fr(a.parties);
      chiffres.ssl = fr(a.parties_ssl);
      chiffres.rlcs = fr(a.matchs_rlcs);
    })
    .catch(() => {});
  if (connected.value) return;
  try {
    const r = await fetch("/dev/joueurs", { credentials: "same-origin" });
    if (r.ok) devPlayers.value = (await r.json()) as DevPlayer[];
  } catch {
    // pas de connexion de développement
  }
});

onBeforeUnmount(() => {
  stop?.();
  document.documentElement.style.scrollBehavior = "";
});
</script>

<template>
<div ref="root" class="accueil">
  <header>
    <div class="wrap">
      <a class="brand" :href="connected ? '/accueil' : '/'" aria-label="Rocket League Player Index, accueil">
        <span class="tag">RLPI</span>
        <span class="titlebox">Rocket League Player Index</span>
      </a>
      <nav>
        <a class="link" href="#fonctionnement">Comment ça marche</a>
        <a class="link" href="#methode">Méthode</a>
        <RouterLink v-if="connected" class="btn btn-steam" :to="tdb">Mon tableau de bord</RouterLink>
        <a v-else class="btn btn-steam" href="/auth/steam">Se connecter avec Steam</a>
      </nav>
    </div>
  </header>

  <main>
    <!-- HERO -->
    <section class="hero">
      <div class="wrap">
        <div>
          <p v-if="failed && !connected" class="alert" role="alert">La connexion Steam n’a pas abouti. Tu peux réessayer.</p>
          <h1><span>Une note</span><span>sur 100</span><span>pour chaque match</span></h1>
          <p class="lead">RLPI analyse tes parties classées 3v3 et les compare au niveau SSL et aux pros RLCS. Tu sais ce qui a marché, ce qui t’a coûté des points, et quoi travailler ensuite.<template v-if="chiffres.parties"> Déjà <b class="count">{{ chiffres.parties }}</b> parties analysées<template
              v-if="chiffres.ssl || chiffres.rlcs">, comparées à <template v-if="chiffres.ssl"><b class="count">{{ chiffres.ssl }}</b> parties SSL</template><template
              v-if="chiffres.ssl && chiffres.rlcs"> et </template><template v-if="chiffres.rlcs"><b class="count">{{ chiffres.rlcs }}</b> matchs RLCS</template></template>.</template></p>
          <div class="actions">
            <RouterLink v-if="connected" class="btn btn-steam" :to="tdb">Mon tableau de bord</RouterLink>
            <a v-else class="btn btn-steam" href="/auth/steam">Se connecter avec Steam</a>
            <a class="btn btn-ghost" href="#fonctionnement">Voir comment ça marche</a>
          </div>
          <p v-if="connected" class="fine">
            Connecté<template v-if="store.moi?.nom"> en tant que <b>{{ store.moi.nom }}</b></template><template
              v-if="store.moi?.parties"> · {{ store.moi.parties }} parties dans ton tableau de bord</template>.
          </p>
          <p v-else class="fine">Après connexion, RLPI récupère tes parties classées 3v3.</p>
        </div>

        <div class="hcard panel" data-demo="hero" aria-label="Exemple d’indice de performance : 48 sur 100">
          <div class="top"><span class="label">Indice de performance</span><span class="chip">Exemple</span></div>
          <div class="index">
            <div class="score"><b class="idx">48</b><small>/100</small></div>
            <div class="spark" aria-hidden="true">
              <svg viewBox="-6 0 212 72">
                <line class="ref" x1="0" y1="37" x2="200" y2="37"/>
                <path class="line" pathLength="1" d="M0 14.6 L18.2 18.5 L36.4 9.3 L54.5 47.6 L72.7 55.5 L90.9 63.4 L109.1 67.4 L127.3 64.1 L145.5 7.3 L163.6 7.3 L181.8 46.9 L200 54.8"/>
                <circle cx="200" cy="54.8" r="5"/>
              </svg>
              <p>12 derniers matchs, repère 50</p>
            </div>
          </div>
          <p>Au niveau d’une performance SSL médiane (50).</p>
          <div class="meters">
            <div class="meter"><span>Production</span><b data-v="44">44</b><i><u style="--v:44"></u></i></div>
            <div class="meter"><span>Fondamentaux</span><b data-v="52">52</b><i><u style="--v:52"></u></i></div>
          </div>
          <div class="trio">
            <div class="trow"><span class="dot"></span><strong class="ps-mate">Polaris</strong><span class="num" data-v="48">48</span></div>
            <div class="trow"><span class="dash"></span><strong>Lobbies</strong><span class="num" data-v="46">46</span></div>
          </div>
        </div>
      </div>
    </section>

    <!-- FONCTIONNEMENT -->
    <section class="block" id="fonctionnement">
      <div class="wrap">
        <div class="sec-head">
          <h2>De ta partie à ton indice</h2>
          <p>Tu joues tes parties classées, RLPI récupère les replays et note chaque match.</p>
        </div>

        <div class="pipe" data-demo="pipe" aria-hidden="true">
          <div class="node"><div class="box"><b>Ta partie</b><small class="st1">Terminée</small><span class="up"><i></i></span></div></div>
          <div class="node"><div class="box"><b>Replay</b><small><span class="cnt ib">96</span> replays</small></div></div>
          <div class="node"><div class="box"><b>RLPI</b><small class="st3">Match noté</small>
            <div class="n3-out"><span class="scan"><i></i><i></i><i></i><i></i><i></i></span><span class="mini-tile">D <b>23</b></span></div></div></div>
          <div class="token">.replay</div>
        </div>

        <ol class="steps">
          <li><h3>Tu joues tes parties classées 3v3</h3><p>Rien à changer dans ta façon de jouer : chaque partie terminée laisse un replay.</p></li>
          <li><h3>Tu te connectes avec Steam</h3><p>RLPI retrouve tes parties classées 3v3 grâce à ton identifiant Steam.</p></li>
          <li><h3>Chaque match reçoit sa note</h3><p>Tu retrouves ton indice, le détail de chaque match et ce qu’il y a à travailler.</p></li>
        </ol>
      </div>
    </section>

    <!-- FONCTIONNALITÉS -->
    <section class="block" id="fonctionnalites">
      <div class="wrap">
        <div class="sec-head">
          <h2>Ce que tu retrouves</h2>
          <p>Cinq onglets, chacun répond à une question précise sur ton jeu.</p>
        </div>

        <!-- Ma forme -->
        <div class="feature">
          <div class="ftext">
            <span class="tab">Ma forme</span>
            <h3>La note ne regarde pas le score</h3>
            <p>Chaque match est noté sur 100. Bleu à partir de 50, orange en dessous.</p>
            <p>Une défaite peut être bien jouée, une victoire peut être portée par tes coéquipiers. Ta forme se lit sur ce que tu as fait.</p>
          </div>
          <div class="demo dark-panel" data-demo="forme" data-replay aria-label="Douze matchs : le résultat, puis la note de chaque match">
            <div class="demo-head"><span class="label phase">Note du match</span><span class="sum">5 au-dessus de 50</span></div>
            <div class="tiles">
              <div class="tile"><div class="card"><div class="f front">V</div><div class="f back up"><small>V</small><b>84</b></div></div></div>
              <div class="tile"><div class="card"><div class="f front">V</div><div class="f back up"><small>V</small><b>78</b></div></div></div>
              <div class="tile"><div class="card"><div class="f front">V</div><div class="f back up"><small>V</small><b>92</b></div></div></div>
              <div class="tile"><div class="card"><div class="f front">D</div><div class="f back down"><small>D</small><b>34</b></div></div></div>
              <div class="tile"><div class="card"><div class="f front">D</div><div class="f back down"><small>D</small><b>22</b></div></div></div>
              <div class="tile"><div class="card"><div class="f front">D</div><div class="f back down"><small>D</small><b>10</b></div></div></div>
              <div class="tile"><div class="card"><div class="f front">D</div><div class="f back down"><small>D</small><b>4</b></div></div></div>
              <div class="tile spot"><span class="ring"></span><div class="card"><div class="f front">V</div><div class="f back down"><small>V</small><b>9</b></div></div></div>
              <div class="tile"><div class="card"><div class="f front">V</div><div class="f back up"><small>V</small><b>95</b></div></div></div>
              <div class="tile spot"><span class="ring"></span><div class="card"><div class="f front">D</div><div class="f back up"><small>D</small><b>95</b></div></div></div>
              <div class="tile"><div class="card"><div class="f front">D</div><div class="f back down"><small>D</small><b>35</b></div></div></div>
              <div class="tile"><div class="card"><div class="f front">D</div><div class="f back down last"><small>D</small><b>23</b></div></div></div>
            </div>
            <p class="forme-cap">Une <b>victoire à 9</b>, une <b>défaite à 95</b> : le résultat et la note racontent deux choses différentes.</p>
          </div>
        </div>

        <!-- Matchs -->
        <div class="feature flip">
          <div class="ftext">
            <span class="tab">Matchs</span>
            <h3>Les touches qui ont fait ta note</h3>
            <p>Ouvre un match pour voir toutes tes touches sur la durée de la partie, et ce que chacune a rapporté ou coûté.</p>
            <p>Celles qui ont le plus pesé sont isolées : tu sais quel moment revoir dans le replay, sans tout regarder.</p>
          </div>
          <div class="demo dark-panel" data-demo="match" data-replay aria-label="Timeline d’un match : une touche ratée fait chuter la note jusqu’à 23">
            <div class="demo-head mt-head">
              <div><span class="label">23.11, défaite</span><div class="t">Tes touches</div></div>
              <div class="mt-score"><b class="score low">23</b><small>/100</small></div>
            </div>
            <div class="mt-track">
              <span class="ph"><em>0:00</em></span>
              <span class="pt pos" style="--x:5%;--y:30%"></span>
              <span class="pt neu" style="--x:11%;--y:48%"></span>
              <span class="pt pos" style="--x:17%;--y:22%;--s:16px"></span>
              <span class="pt neg" style="--x:24%;--y:64%"></span>
              <span class="pt pos" style="--x:31%;--y:36%"></span>
              <span class="pt neu" style="--x:38%;--y:52%"></span>
              <span class="pt pos" style="--x:45%;--y:28%"></span>
              <span class="pt neg" style="--x:52%;--y:62%"></span>
              <span class="pt pos" style="--x:58%;--y:38%"></span>
              <span class="pt neu" style="--x:64%;--y:47%"></span>
              <span class="pt neg big" style="--x:71%;--y:86%;--s:24px"></span>
              <span class="pt pos" style="--x:80%;--y:34%"></span>
              <span class="pt neg" style="--x:88%;--y:70%;--s:16px"></span>
              <span class="pt neu" style="--x:95%;--y:50%"></span>
              <div class="mt-note">Dégagement manqué, but encaissé : −24</div>
            </div>
            <div class="mt-axis"><span>0:00</span><span>2:30</span><span>5:00</span></div>
            <div class="mt-legend">
              <span><i style="background:var(--blue)"></i>rapporte</span>
              <span><i style="background:var(--muted)"></i>neutre</span>
              <span><i style="background:var(--orange)"></i>coûte</span>
            </div>
          </div>
        </div>

        <!-- Mon jeu -->
        <div class="feature">
          <div class="ftext">
            <span class="tab">Mon jeu</span>
            <h3>Tes repères, face aux bons étalons</h3>
            <p>Placement hors ballon, résultat de tes touches, passes récupérées. Chaque repère est comparé à ce qui compte : tes lobbies, ou les pros RLCS quand c’est plus parlant.</p>
            <p>L’écart est affiché directement, pour voir en un coup d’œil où tu prends ou perds des points.</p>
          </div>
          <div class="demo dark-panel" data-demo="jeu" data-replay aria-label="Trois repères comparés à une référence, avec l’écart">
            <div class="bars">
              <div class="bar">
                <div class="bar-top"><span>Placement hors ballon</span><span class="vals"><em class="delta plus">+2</em><b class="val" data-v="32">32</b><small>/100</small></span></div>
                <div class="btrack"><i class="fill" style="--v:32"></i><i class="gap plus" style="--a:30;--w:2"></i><span class="ref" style="--r:30"><em>lobbies 30</em></span></div>
              </div>
              <div class="bar">
                <div class="bar-top"><span>Résultat de tes touches</span><span class="vals"><em class="delta minus">−4</em><b class="val" data-v="46">46</b><small>/100</small></span></div>
                <div class="btrack"><i class="fill" style="--v:46"></i><i class="gap minus" style="--a:46;--w:4"></i><span class="ref" style="--r:50"><em>médiane 50</em></span></div>
              </div>
              <div class="bar">
                <div class="bar-top"><span>Passes récupérées</span><span class="vals"><em class="delta minus">−7</em><b class="val" data-v="28">28</b><small>%</small></span></div>
                <div class="btrack"><i class="fill" style="--v:28"></i><i class="gap minus" style="--a:28;--w:7"></i><span class="ref" style="--r:35"><em>lobbies 35 %</em></span></div>
              </div>
            </div>
            <p class="verdict">Placement au-dessus de tes lobbies. À travailler en priorité : les passes récupérées.</p>
          </div>
        </div>

        <!-- À travailler -->
        <div class="feature flip">
          <div class="ftext">
            <span class="tab">À travailler</span>
            <h3>Le play joué, face au play attendu</h3>
            <p>Sur les actions qui ont compté, RLPI montre ce que les pros RLCS font le plus souvent dans une situation proche, et note l’écart avec ce que tu as joué.</p>
            <p>Pas une vérité absolue : un point de comparaison pour décider quoi changer.</p>
          </div>
          <div class="demo dark-panel" data-demo="field" data-replay aria-label="Vue du terrain : challenge en double joué, puis repli au second poteau attendu. Adéquation 38 sur 100">
            <div class="fhead"><span class="phase-chip p-best">Ce qui était attendu</span></div>
            <div class="fwrap">
              <svg class="field" viewBox="0 0 360 214" aria-hidden="true">
                <rect x="10" y="10" width="340" height="194" rx="30" fill="none" stroke="#3a3c43" stroke-width="2"/>
                <line x1="180" y1="10" x2="180" y2="204" stroke="#3a3c43" stroke-width="2"/>
                <circle cx="180" cy="107" r="26" fill="none" stroke="#3a3c43" stroke-width="2"/>
                <rect x="2" y="82" width="8" height="50" fill="#1f63e6"/>
                <rect x="350" y="82" width="8" height="50" fill="#f26a2c"/>
                <path class="g p-mate" d="M150 60 C162 64,176 70,186 76"/>
                <path class="g p-ball1" d="M196 80 C188 98,166 116,140 114"/>
                <path class="g p-oppb" d="M270 133 C236 132,186 122,152 116"/>
                <path class="g p-ball2" d="M196 80 C232 70,270 58,306 66"/>
                <path class="pl played" pathLength="1" stroke="#f26a2c" d="M118 150 C140 128,162 100,184 84"/>
                <path class="pl best" pathLength="1" stroke="#d4ff3a" d="M118 150 C96 168,62 150,44 124"/>
                <circle class="burst" cx="190" cy="80" r="22" fill="none" stroke="#f26a2c" stroke-width="2.5"/>
                <g class="opp-a" transform="translate(218 61) rotate(200)"><rect x="-9" y="-5" width="18" height="10" rx="2" fill="none" stroke="#9d9fa4" stroke-width="2"/></g>
                <g class="opp-b" transform="translate(270 133) rotate(180)"><rect x="-9" y="-5" width="18" height="10" rx="2" fill="none" stroke="#9d9fa4" stroke-width="2"/></g>
                <g class="mate" transform="translate(186 76) rotate(25)"><rect x="-9" y="-5" width="18" height="10" rx="2" fill="#7fa7f2"/></g>
                <g class="ball" transform="translate(306 66)"><circle r="7" fill="#ecece7"/></g>
                <g class="you" transform="translate(44 124) rotate(-125)"><rect x="-11" y="-6.5" width="22" height="13" rx="2" fill="#d4ff3a"/><rect x="4" y="-4.5" width="4" height="9" fill="#17181b" opacity=".45"/></g>
                <g class="l-a"><rect x="198" y="26" width="112" height="22" fill="#f26a2c"/><text x="206" y="41" fill="#17181b" font-family="Barlow, sans-serif" font-size="11" font-weight="700">Challenge en double</text></g>
                <g class="l-loss"><rect x="150" y="124" width="98" height="22" fill="#dcddd6"/><text x="158" y="139" fill="#17181b" font-family="Barlow, sans-serif" font-size="11" font-weight="700">Balle perdue, 2v1</text></g>
                <g class="l-b"><rect x="22" y="174" width="168" height="22" fill="#d4ff3a"/><text x="30" y="189" fill="#17181b" font-family="Barlow, sans-serif" font-size="11" font-weight="700">Repli au second poteau</text></g>
              </svg>
              <div class="rw">◀◀</div>
            </div>
            <div class="adq">
              <svg class="gauge" viewBox="0 0 120 66" aria-hidden="true">
                <path class="g-bg" pathLength="100" d="M10 60 A50 50 0 0 1 110 60"/>
                <path class="g-val" pathLength="100" d="M10 60 A50 50 0 0 1 110 60"/>
              </svg>
              <div><b class="adq-n ib">38</b><span> /100 d’adéquation</span><p>Ton coéquipier était déjà sur la balle.</p></div>
            </div>
          </div>
        </div>

        <!-- Mon trio -->
        <div class="feature">
          <div class="ftext">
            <span class="tab">Mon trio</span>
            <h3>Ton trio, face à tes lobbies</h3>
            <p>Compare ton indice à celui de tes coéquipiers réguliers et au niveau moyen des parties que vous jouez ensemble.</p>
            <p>Change de période pour voir qui porte l’équipe en ce moment.</p>
          </div>
          <div class="demo dark-panel" data-demo="trio" data-replay aria-label="Indices du trio et des lobbies, sur la période puis sur les 5 derniers matchs (pseudos d’exemple)">
            <div class="demo-head">
              <span class="label">Indice du trio</span>
              <div class="switch" role="group" aria-label="Période comparée"><span class="knob"></span><button type="button" class="sw on" data-m="p" aria-pressed="true">Période</button><button type="button" class="sw" data-m="r" aria-pressed="false">5 derniers</button></div>
            </div>
            <div class="rows">
              <div class="row"><span class="who"><span class="dot" style="background:var(--lime)"></span><span class="ps-me">Kestrel</span></span><span class="t"><i style="transform:scaleX(.48);background:var(--lime)"></i></span><b class="v">48</b></div>
              <div class="row"><span class="who"><span class="dot"></span><span class="ps-mate">Polaris</span></span><span class="t"><i style="transform:scaleX(.48);background:var(--orange)"></i></span><b class="v">48</b></div>
              <div class="row"><span class="who"><span class="dash" style="background:var(--muted)"></span>Lobbies</span><span class="t"><i style="transform:scaleX(.46);background:var(--muted)"></i></span><b class="v">46</b></div>
              <span class="mid"><em>SSL médian</em></span>
            </div>
            <div class="trio-stats">
              <div class="panel"><b><span class="s-rank">3,7</span><small> /6</small></b><p>Ton rang moyen dans la partie</p></div>
              <div class="panel"><b><span class="s-win">42</span><small> %</small></b><p>Victoires, <span class="s-wl">5 V et 7 D</span></p></div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- JUGER À L'AVEUGLE : encart volt, à part des onglets -->
    <section class="block" id="aveugle">
      <div class="wrap">
        <div class="judge">
          <div class="j-text">
            <span class="j-tag">Juger à l’aveugle</span>
            <h2>À toi de juger les actions</h2>
            <p>Un paquet d’actions mélangées : les tiennes, celles de tes coéquipiers, de tes lobbies, de joueurs SSL et de pros RLCS. Rien n’indique qui a joué.</p>
            <p>Glisse à droite si c’est une bonne action, à gauche sinon, vers le haut si tu ne sais pas. Tes jugements servent à repérer où les modèles de RLPI se trompent.</p>
            <RouterLink v-if="connected" class="btn j-btn" :to="{ name: 'swipe' }">Juger des actions</RouterLink>
            <a v-else class="btn j-btn" href="/auth/steam">Se connecter pour jouer</a>
          </div>
          <div class="j-demo" data-demo="judge" data-replay aria-label="Trois actions jugées à la suite : bien, pas bien, je ne sais pas">
            <div class="jdeck">
              <div v-for="(c, i) in judgeCards" :key="i" class="jcard" :style="{ zIndex: 4 - i }">
                <div class="sc-top"><span>Joueur <b>masqué</b></span><span>{{ c.t }}</span></div>
                <svg viewBox="0 0 200 116" aria-hidden="true">
                  <rect x="6" y="6" width="188" height="104" rx="16" fill="none" stroke="#3a3c43" stroke-width="1.5" />
                  <line x1="100" y1="6" x2="100" y2="110" stroke="#3a3c43" stroke-width="1.5" />
                  <rect x="2" y="44" width="4" height="28" fill="#1f63e6" />
                  <rect x="194" y="44" width="4" height="28" fill="#f26a2c" />
                  <path class="sc-ball" :d="c.ball" fill="none" stroke="#ecece7" stroke-width="1.5" stroke-dasharray="2 4" />
                  <path class="sc-path" pathLength="1" :d="c.path" fill="none" stroke="#d4ff3a" stroke-width="3" stroke-linecap="round" />
                  <circle :cx="c.bx" :cy="c.by" r="5" fill="#ecece7" />
                  <rect :x="c.cx - 7" :y="c.cy - 4" width="14" height="8" rx="2" fill="#d4ff3a" />
                </svg>
                <p class="sc-cap">{{ c.cap }}</p>
                <span class="jstamp s-good">Bien</span>
                <span class="jstamp s-bad">Pas bien</span>
                <span class="jstamp s-maybe">?</span>
              </div>
            </div>
            <div class="j-votes">
              <span class="jv jv-bad">✕ Pas bien</span>
              <span class="jv jv-maybe">? Je sais pas</span>
              <span class="jv jv-good">✓ Bien</span>
            </div>
            <p class="j-count"><b class="j-n">0</b> / 3 jugées</p>
          </div>
        </div>
      </div>
    </section>

    <!-- MÉTHODE -->
    <section class="block" id="methode">
      <div class="wrap method">
        <div class="txt">
          <div class="sec-head" style="margin-bottom:28px"><h2>Ce que veut dire 48</h2></div>
          <p>50 correspond à une performance SSL médiane. En dessous, tu joues moins bien qu’un SSL médian sur ce match ; au-dessus, mieux.</p>
          <p>L’indice combine la production, ce que tes actions rapportent, et les fondamentaux : placement, qualité des touches, récupérations.</p>
          <p>Sur peu de parties, la moyenne bouge beaucoup. Elle devient fiable vers 50 parties, et RLPI te dit où tu en es.</p>
        </div>
        <div class="scale demo dark-panel" data-demo="scale" data-replay aria-label="Échelle de 0 à 100 : ton indice 48, la médiane SSL à 50, fourchette 35 à 62 sur 12 parties">
          <div class="track">
            <span class="band"></span>
            <span class="m50"><em>performance SSL médiane</em></span>
            <span class="you"><b>48</b></span>
          </div>
          <div class="ticks"><span>0</span><span>100</span></div>
          <span class="band-lab">Fourchette sur tes 12 parties : 35 à 62</span>
          <div class="reli">
            <div class="r-top"><span>Parties analysées</span><span><b>12</b> sur 50 pour une moyenne fiable</span></div>
            <div class="segs"></div>
          </div>
        </div>
      </div>
    </section>

    <!-- CONNEXION -->
    <section class="block">
      <div class="wrap">
        <div class="login panel">
          <div v-if="connected">
            <h2>Retrouver tes statistiques</h2>
            <p>Ton tableau de bord t’attend : ta forme, tes matchs, ton jeu et ce qu’il y a à travailler.</p>
            <p class="small">Tes nouvelles parties classées 3v3 y arrivent toutes seules.</p>
          </div>
          <div v-else>
            <h2>Voir les statistiques de tes parties</h2>
            <p>Connecte-toi avec ton compte Steam pour voir tes parties 3v3.</p>
            <p class="small">Tes parties classées 3v3 apparaissent dans ton tableau de bord après connexion.</p>
          </div>
          <RouterLink v-if="connected" class="btn btn-steam" :to="tdb">Mon tableau de bord</RouterLink>
          <a v-else class="btn btn-steam" href="/auth/steam">Se connecter avec Steam</a>
        </div>
        <div v-if="devPlayers && !connected" class="dev dark-panel">
          <p class="label">Connexion de développement · sans Steam (RLPI_DEV_LOGIN=1, jamais en production)</p>
          <ul>
            <li v-for="p in devPlayers" :key="p.id">
              <a :href="devHref(p.id)">{{ p.pseudo || p.id }}</a>
              <span> · {{ p.id }} · {{ p.parties }} partie(s)</span>
            </li>
            <li v-if="!devPlayers.length">Aucune partie traitée.</li>
          </ul>
          <form method="get" action="/dev/connexion">
            <input name="joueur" placeholder="Steam:7656119800000000x" aria-label="Identifiant du joueur" />
            <button class="btn btn-steam" type="submit">Se connecter</button>
          </form>
        </div>
      </div>
    </section>
    <!-- REMERCIEMENTS -->
    <section class="block" id="remerciements">
      <div class="wrap">
        <div class="sec-head">
          <h2>Merci</h2>
          <p>RLPI s’appuie sur des modèles et des outils créés par d’autres. Sans leur travail, rien de tout ça ne tournerait.</p>
        </div>
        <ul class="credits"></ul>
      </div>
    </section>
  </main>

  <footer>
    <div class="wrap">
      <p>RLPI n’est affilié ni à Psyonix ni à Epic Games.</p>
      <nav><a href="#remerciements">Remerciements</a><a href="#methode">Méthode</a><a href="/modeles">Les modèles</a><a href="/swipe">Juger des actions à l’aveugle</a></nav>
    </div>
  </footer>
</div>
</template>
