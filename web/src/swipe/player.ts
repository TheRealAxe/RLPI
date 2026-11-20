// Lecteur isométrique d'une carte swipe (canvas) : terrain, buts, voitures (boîtes orientées, face blanche = avant),
// balle, ombres et hauteurs. Repris de l'ancienne page reports/swipe/index.html, avec en plus une vue joueur
// (pov) : caméra en perspective placée comme celle du jeu (caméra balle ou voiture, réglages du joueur relevés dans
// le replay quand le clip les donne). Les couleurs de la scène (équipes, pelouse) sont celles du rendu d'origine : elles décrivent le jeu,
// pas l'interface (les jetons Plateau habillent la page autour).

type V3 = number[];
export interface SwipeCar {
  team: number;
  judged: boolean;
  pos: V3[];
  vel: V3[];
  fw: V3[];
  up: V3[];
  boost: number[];
}
/** Caméra du joueur mis en avant, relevée dans le replay (réglages absents : ceux par défaut du jeu). */
export interface SwipeCam {
  fov?: number | null;
  distance?: number | null;
  height?: number | null;
  angle?: number | null;
  stiffness?: number | null;
  known: boolean;
  /** Caméra balle (1) ou voiture (0) à chaque image. */
  ball_cam: number[];
}
export interface SwipeCard {
  id: string;
  action?: string;
  fps: number;
  action_frame: number;
  ball: V3[];
  ball_v: V3[];
  cars: SwipeCar[];
  cam?: SwipeCam | null;
}
interface CarState {
  pos: V3;
  vel: V3;
  fw: V3;
  up: V3;
  boost: number;
  boosting: boolean;
  team: number;
  judged: boolean;
}
export interface FrameState {
  i: number;
  ball: V3;
  bv: V3;
  cars: CarState[];
  /** Vue joueur seulement : caméra balle (true) ou voiture (false). */
  ballCam?: boolean;
}
export interface Player {
  t: number;
  playing: boolean;
  speed: number;
  stopAt: number;
  last: number | null;
  resize(): void;
  rotate(d: number): void;
  top(on: boolean): void;
  /** Vue joueur : caméra du jeu derrière la voiture mise en avant. */
  pov(on: boolean): void;
  draw(): FrameState;
}

const FX = 4096,
  FY = 5120,
  GW = 893,
  GD = 880,
  GH = 642,
  WALL = 2044;
const K = 1.8; // vue isométrique : voitures dessinées 1,8× plus grandes pour rester lisibles
const NEAR = 12; // vue joueur : plan de coupe devant la caméra (uu)
const Z: V3 = [0, 0, 1];
const num = (v: number | null | undefined, d: number) => (typeof v === "number" && Number.isFinite(v) ? v : d);
const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));

export function createPlayer(canvas: HTMLCanvasElement, card: SwipeCard): Player {
  const ctx = canvas.getContext("2d")!,
    N = card.ball.length,
    FPS = card.fps,
    dt = 1 / FPS;
  const J = card.cars.findIndex((c) => c.judged),
    flip = card.cars[J].team === 0 ? 1 : -1;
  const myTeam = card.cars[J].team;
  let W = 0,
    H = 0,
    DPR = 1,
    S = 1,
    OX = 0,
    OY = 0,
    focus: number[] | null = null,
    span = 6500;
  let az = (28 * Math.PI) / 180,
    el = (38 * Math.PI) / 180,
    azT = az,
    elT = el;
  // vue joueur : position et repère de la caméra (droite, haut, avant), focale en pixels, direction lissée
  const CS = {
    fov: num(card.cam?.fov, 110),
    dist: num(card.cam?.distance, 270),
    height: num(card.cam?.height, 100),
    angle: (num(card.cam?.angle, -3) * Math.PI) / 180,
    stiff: clamp(num(card.cam?.stiffness, 0.5), 0, 1),
  };
  let pov = false,
    ballCam = true,
    fpx = 1,
    cp: V3 = [0, 0, 0],
    cR: V3 = [1, 0, 0],
    cU: V3 = [0, 0, 1],
    cF: V3 = [0, 1, 0],
    sm: { h: V3; e: number; t: number } | null = null;
  const KK = () => (pov ? 1 : K);

  // monde RL → vue : équipe du joueur jugé vers le haut ; x inversé (RL est en repère main gauche)
  const V = (x: number, y: number) => [-flip * x, flip * y];
  // Vue joueur : [x écran, y écran, profondeur, x, y, z caméra] ; le z caméra sert à couper ce qui est derrière.
  function projC(xc: number, yc: number, zc: number): number[] {
    const zz = Math.max(zc, NEAR);
    return [W / 2 + (xc / zz) * fpx, H / 2 - (yc / zz) * fpx, zc, xc, yc, zc];
  }
  const seen = (p: number[]) => !pov || p[5] >= NEAR;
  function proj(x: number, y: number, z: number): number[] {
    if (pov) {
      const d: V3 = [x - cp[0], y - cp[1], z - cp[2]];
      return projC(dot(d, cR), dot(d, cU), dot(d, cF));
    }
    const [X, Y] = V(x, y),
      ca = Math.cos(az),
      sa = Math.sin(az);
    const xr = X * ca - Y * sa,
      yr = X * sa + Y * ca;
    return [OX + xr * S, OY - (yr * Math.sin(el) + z * Math.cos(el)) * S, yr * Math.cos(el) - z * Math.sin(el)];
  }
  function herm(p0: V3, v0: V3, p1: V3, v1: V3, u: number): V3 {
    const u2 = u * u,
      u3 = u2 * u;
    return [0, 1, 2].map((k) => (2 * u3 - 3 * u2 + 1) * p0[k] + (u3 - 2 * u2 + u) * dt * v0[k] + (-2 * u3 + 3 * u2) * p1[k] + (u3 - u2) * dt * v1[k]);
  }
  const nrm = (v: V3) => {
    const l = Math.hypot(...v) || 1;
    return v.map((x) => x / l);
  };
  const lv = (a: V3, b: V3, u: number) => a.map((x, k) => x + (b[k] - x) * u);
  const cross = (a: V3, b: V3) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  function state(t: number): FrameState {
    t = Math.max(0, Math.min(t, N - 1.0001));
    const i = Math.floor(t),
      u = t - i;
    return {
      i,
      ball: herm(card.ball[i], card.ball_v[i], card.ball[i + 1], card.ball_v[i + 1], u),
      bv: lv(card.ball_v[i], card.ball_v[i + 1], u),
      cars: card.cars.map((c) => ({
        pos: herm(c.pos[i], c.vel[i], c.pos[i + 1], c.vel[i + 1], u),
        vel: lv(c.vel[i], c.vel[i + 1], u),
        fw: nrm(lv(c.fw[i], c.fw[i + 1], u)),
        up: nrm(lv(c.up[i], c.up[i + 1], u)),
        boost: c.boost[i] + (c.boost[i + 1] - c.boost[i]) * u,
        boosting: c.boost[Math.min(i + 1, N - 1)] < c.boost[i],
        team: c.team,
        judged: c.judged,
      })),
    };
  }
  /** Caméra du jeu : derrière la voiture, à `distance` et `height`, tournée vers la balle (caméra balle) ou dans
   * l'axe de la voiture (caméra voiture) ; la raideur règle la vitesse à laquelle elle suit. */
  function povCamera(s: FrameState, t: number) {
    const me = s.cars[J],
      p = me.pos,
      b = s.ball,
      bc = card.cam?.ball_cam;
    ballCam = bc && bc.length ? !!bc[clamp(Math.round(t), 0, bc.length - 1)] : true;
    const flat = (v: V3): V3 | null => {
      const l = Math.hypot(v[0], v[1]);
      return l > 1e-3 ? [v[0] / l, v[1] / l, 0] : null;
    };
    let h: V3, e: number;
    if (ballCam) {
      const d: V3 = [b[0] - p[0], b[1] - p[1], b[2] - p[2]],
        dxy = Math.hypot(d[0], d[1]);
      h = (dxy > 1 ? flat(d) : null) ?? flat(me.fw) ?? sm?.h ?? [0, 1, 0];
      e = clamp(Math.atan2(d[2], Math.max(dxy, 1)), -0.25, 0.25);
    } else {
      h = flat(me.fw) ?? flat(me.vel) ?? sm?.h ?? [0, 1, 0];
      e = 0;
    }
    const now = t / FPS;
    if (!sm || now < sm.t || now - sm.t > 0.25) sm = { h, e, t: now };
    else {
      const a = 1 - Math.exp(-(3 + 22 * CS.stiff) * (now - sm.t)),
        m = lv(sm.h, h, a),
        l = Math.hypot(m[0], m[1]);
      sm = { h: l > 1e-3 ? [m[0] / l, m[1] / l, 0] : h, e: sm.e + (e - sm.e) * a, t: now };
    }
    const ce = Math.cos(sm.e),
      se = Math.sin(sm.e);
    cp = [p[0] - sm.h[0] * ce * CS.dist, p[1] - sm.h[1] * ce * CS.dist, Math.max(30, p[2] - se * CS.dist + CS.height)];
    if (ballCam) {
      // vers la balle, inclinaison bornée comme dans le jeu (balle haute : en haut de l'écran, voiture visible)
      const d: V3 = [b[0] - cp[0], b[1] - cp[1], b[2] - cp[2]],
        fh = flat(d) ?? sm.h,
        pitch = clamp(Math.atan2(d[2], Math.hypot(d[0], d[1])), -0.5, 0.3);
      cF = [fh[0] * Math.cos(pitch), fh[1] * Math.cos(pitch), Math.sin(pitch)];
    } else cF = [sm.h[0] * Math.cos(CS.angle), sm.h[1] * Math.cos(CS.angle), Math.sin(CS.angle)];
    const r = cross(Z, cF);
    cR = Math.hypot(...r) > 1e-3 ? nrm(r) : nrm(cross(Z, sm.h));
    cU = cross(cF, cR);
    // FOV horizontal en 16:9 ; sur un autre format, le jeu garde le champ vertical
    fpx = H / 2 / (Math.tan((CS.fov * Math.PI) / 360) * (9 / 16));
  }
  function camera(s: FrameState) {
    const me = s.cars[J].pos,
      b = s.ball,
      cx = me[0] * 0.5 + b[0] * 0.5,
      cy = me[1] * 0.5 + b[1] * 0.5;
    const d = s.cars.map((c) => Math.hypot(c.pos[0] - cx, c.pos[1] - cy)).sort((x, y) => x - y)[3];
    const want = Math.max(4200, Math.min(12000, 2.2 * Math.max(Math.hypot(me[0] - b[0], me[1] - b[1]), d)));
    focus = focus ? [focus[0] + (cx - focus[0]) * 0.07, focus[1] + (cy - focus[1]) * 0.07] : [cx, cy];
    span += (want - span) * 0.05;
    az += (azT - az) * 0.12;
    el += (elT - el) * 0.12;
    S = Math.min(W, H * 1.25) / span;
    OX = W / 2;
    OY = H * 0.56;
    const [fx, fy] = proj(focus[0], focus[1], 0);
    OX += W / 2 - fx;
    OY += H * 0.56 - fy;
  }
  // ------------------------------------------------ terrain
  /** Vue joueur : polygone coupé au plan proche (Sutherland-Hodgman en repère caméra). */
  function clipNear(pts: number[][]): number[][] {
    if (!pov || pts.every((p) => p[5] >= NEAR)) return pts;
    const out: number[][] = [];
    pts.forEach((a, k) => {
      const b = pts[(k + 1) % pts.length],
        ain = a[5] >= NEAR,
        bin = b[5] >= NEAR;
      if (ain) out.push(a);
      if (ain !== bin) {
        const u = (NEAR - a[5]) / (b[5] - a[5]);
        out.push(projC(a[3] + (b[3] - a[3]) * u, a[4] + (b[4] - a[4]) * u, NEAR));
      }
    });
    return out;
  }
  /** Segment entre deux points projetés (coupé au plan proche en vue joueur). */
  function seg(a: number[], b: number[], stroke: string, lw: number, dash = false) {
    if (pov) {
      const ain = a[5] >= NEAR,
        bin = b[5] >= NEAR;
      if (!ain && !bin) return;
      if (ain !== bin) {
        const u = (NEAR - a[5]) / (b[5] - a[5]),
          c = projC(a[3] + (b[3] - a[3]) * u, a[4] + (b[4] - a[4]) * u, NEAR);
        if (ain) b = c;
        else a = c;
      }
    }
    if (dash) ctx.setLineDash([4 * DPR, 4 * DPR]);
    ctx.beginPath();
    ctx.moveTo(a[0], a[1]);
    ctx.lineTo(b[0], b[1]);
    ctx.strokeStyle = stroke;
    ctx.lineWidth = lw * DPR;
    ctx.stroke();
    if (dash) ctx.setLineDash([]);
  }
  function poly(pts: number[][], fill: string | null, stroke?: string | null, lw = 1) {
    pts = clipNear(pts);
    if (pts.length < 3) return;
    ctx.beginPath();
    pts.forEach((p, k) => (k ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
    ctx.closePath();
    if (fill) {
      ctx.fillStyle = fill;
      ctx.fill();
    }
    if (stroke) {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = lw * DPR;
      ctx.stroke();
    }
  }
  function outline(z: number) {
    const r = 1150,
      pts: number[][] = [];
    (
      [
        [FX - r, FY - r, 0],
        [-FX + r, FY - r, Math.PI / 2],
        [-FX + r, -FY + r, Math.PI],
        [FX - r, -FY + r, 1.5 * Math.PI],
      ] as const
    ).forEach(([cx, cy, a0]) => {
      for (let k = 0; k <= 6; k++) {
        const a = a0 + ((k / 6) * Math.PI) / 2;
        pts.push(proj(cx + r * Math.cos(a), cy + r * Math.sin(a), z));
      }
    });
    return pts;
  }
  function field() {
    poly(outline(0), "#1e3a2c", "rgba(255,255,255,.28)", 1.5);
    // moitiés teintées : ton camp (bas) bleu, camp adverse orange
    (
      [
        [1, "rgba(240,112,47,.08)"],
        [-1, "rgba(61,139,239,.08)"],
      ] as const
    ).forEach(([s, col]) => {
      const yy = s * flip;
      poly([proj(-FX, 0, 0), proj(FX, 0, 0), proj(FX, yy * (FY - 600), 0), proj(-FX, yy * (FY - 600), 0)], col);
    });
    seg(proj(-FX, 0, 0), proj(FX, 0, 0), "rgba(255,255,255,.3)", 1.2);
    const circ = [];
    for (let a = 0; a <= 40; a++) circ.push(proj(Math.cos((a / 20) * Math.PI) * 900, Math.sin((a / 20) * Math.PI) * 900, 0));
    poly(circ, null, "rgba(255,255,255,.3)", 1.2);
    [
      [3072, 4096],
      [-3072, 4096],
      [3072, -4096],
      [-3072, -4096],
      [3584, 0],
      [-3584, 0],
    ].forEach(([x, y]) => {
      const c = [];
      for (let a = 0; a < 16; a++) c.push(proj(x + 160 * Math.cos((a / 8) * Math.PI), y + 160 * Math.sin((a / 8) * Math.PI), 0));
      poly(c, "rgba(255,176,46,.55)");
    });
    // murs : arête du haut + montants aux coins (repères de hauteur) ; en vue joueur, les murs sont voilés
    if (pov) {
      const lo = outline(0),
        hi = outline(WALL);
      lo.forEach((a, k) => {
        const n = (k + 1) % lo.length;
        poly([a, lo[n], hi[n], hi[k]], "rgba(150,175,200,.07)");
      });
    }
    poly(outline(WALL), null, "rgba(180,200,220,.14)", 1);
    [
      [FX, FY],
      [-FX, FY],
      [FX, -FY],
      [-FX, -FY],
    ].forEach(([x, y]) => {
      seg(proj(x * 0.86, y * 0.89, 0), proj(x * 0.86, y * 0.89, WALL), "rgba(180,200,220,.12)", 1);
    });
    goals();
  }
  function goals() {
    [-1, 1].forEach((s) => {
      const yw = s * FY,
        yb = s * (FY + GD),
        tm = s * flip > 0 ? 1 - myTeam : myTeam,
        col = tm === myTeam ? "61,139,239" : "240,112,47";
      const q = proj;
      poly([q(-GW, yb, 0), q(GW, yb, 0), q(GW, yb, GH), q(-GW, yb, GH)], `rgba(${col},.22)`, `rgba(${col},.8)`, 1.2);
      [-GW, GW].forEach((x) => poly([q(x, yw, 0), q(x, yb, 0), q(x, yb, GH), q(x, yw, GH)], `rgba(${col},.16)`, `rgba(${col},.8)`, 1.2));
      poly([q(-GW, yw, GH), q(GW, yw, GH), q(GW, yb, GH), q(-GW, yb, GH)], `rgba(${col},.12)`, `rgba(${col},.8)`, 1.2);
      poly([q(-GW, yw, 0), q(GW, yw, 0), q(GW, yw, 3), q(-GW, yw, 3)], null, "rgba(255,255,255,.7)", 2);
    });
  }
  // ------------------------------------------------ objets
  const TEAMC = (t: number) => (t === myTeam ? [61, 139, 239] : [240, 112, 47]);
  const rgb = (c: number[], f: number, a = 1) => `rgba(${Math.round(c[0] * f)},${Math.round(c[1] * f)},${Math.round(c[2] * f)},${a})`;
  function carBox(c: CarState) {
    const k = KK(),
      L = (118 * k) / 2,
      Wd = (84 * k) / 2,
      Hh = (36 * k) / 2,
      left = cross(c.up, c.fw),
      p = c.pos;
    const pt = (a: number, b: number, h: number): [number, number, number] => [
      p[0] + c.fw[0] * a + left[0] * b + c.up[0] * h,
      p[1] + c.fw[1] * a + left[1] * b + c.up[1] * h,
      p[2] + c.fw[2] * a + left[2] * b + c.up[2] * h,
    ];
    const faces = [
      { n: c.up, pts: [pt(L, Wd, Hh), pt(L, -Wd, Hh), pt(-L, -Wd, Hh), pt(-L, Wd, Hh)], kind: "top" },
      { n: c.up.map((x) => -x), pts: [pt(L, Wd, -Hh), pt(-L, Wd, -Hh), pt(-L, -Wd, -Hh), pt(L, -Wd, -Hh)], kind: "bottom" },
      { n: c.fw, pts: [pt(L, Wd, Hh), pt(L, Wd, -Hh), pt(L, -Wd, -Hh), pt(L, -Wd, Hh)], kind: "nose" },
      { n: c.fw.map((x) => -x), pts: [pt(-L, Wd, Hh), pt(-L, -Wd, Hh), pt(-L, -Wd, -Hh), pt(-L, Wd, -Hh)], kind: "back" },
      { n: left, pts: [pt(L, Wd, Hh), pt(-L, Wd, Hh), pt(-L, Wd, -Hh), pt(L, Wd, -Hh)], kind: "side" },
      { n: left.map((x) => -x), pts: [pt(L, -Wd, Hh), pt(L, -Wd, -Hh), pt(-L, -Wd, -Hh), pt(-L, -Wd, Hh)], kind: "side" },
    ];
    return { faces, pt, L, Wd, Hh };
  }
  function viewNormal(n: V3) {
    const [X, Y] = V(n[0], n[1]),
      ca = Math.cos(az),
      sa = Math.sin(az);
    return [X * ca - Y * sa, X * sa + Y * ca, n[2]];
  }
  function drawCarShadow(c: CarState) {
    const { pt, L, Wd } = carBox(c),
      p = c.pos,
      z = Math.max(0, p[2]);
    const g = [
      [L, Wd],
      [L, -Wd],
      [-L, -Wd],
      [-L, Wd],
    ].map(([a, b]) => {
      const q = pt(a, b, 0);
      return proj(q[0], q[1], 0);
    });
    poly(g, `rgba(0,0,0,${Math.max(0.18, 0.5 - z / 4000)})`);
    if (c.judged) {
      const r = [];
      for (let a = 0; a <= 32; a++) r.push(proj(p[0] + 230 * Math.cos((a / 16) * Math.PI), p[1] + 230 * Math.sin((a / 16) * Math.PI), 0));
      poly(r, null, "rgba(245,197,66,.9)", 2.5);
    }
    if (z > 80) seg(proj(p[0], p[1], 0), proj(p[0], p[1], z), "rgba(255,255,255,.45)", 1.3, true);
  }
  function drawCar(c: CarState) {
    const { faces, pt, L, Wd, Hh } = carBox(c),
      base = TEAMC(c.team);
    const facing = (f: { n: V3; pts: V3[]; vn: number[] }) => {
      if (!pov) return f.vn[1] * Math.cos(el) * -1 + f.vn[2] * Math.sin(el) > 0.02;
      const c = [0, 1, 2].map((k) => f.pts.reduce((x, q) => x + q[k], 0) / f.pts.length);
      return dot(f.n, [cp[0] - c[0], cp[1] - c[1], cp[2] - c[2]]) > 0;
    };
    const vis = faces.map((f) => ({ ...f, vn: viewNormal(f.n) })).filter(facing);
    vis.forEach((f) => {
      const shade = 0.55 + 0.45 * Math.max(0, f.vn[2] * 0.8 + 0.2);
      const fill = f.kind === "nose" ? "rgba(245,245,245,.95)" : f.kind === "bottom" ? rgb([60, 60, 60], 1) : rgb(base, shade);
      poly(
        f.pts.map((q) => proj(...q)),
        fill,
        c.judged ? "rgba(245,197,66,1)" : "rgba(0,0,0,.45)",
        c.judged ? 2.2 : 1,
      );
    });
    // flèche sur le toit (sens de la voiture), si le toit est visible
    if (vis.some((f) => f.kind === "top")) {
      const a = [pt(L * 0.75, 0, Hh + 1), pt(-L * 0.1, Wd * 0.55, Hh + 1), pt(-L * 0.1, -Wd * 0.55, Hh + 1)].map((q) => proj(...q));
      poly(a, "rgba(255,255,255,.85)");
    }
    // flamme si boost
    if (c.boosting) {
      const a = [pt(-L, Wd * 0.35, 0), pt(-L - 70 * KK(), 0, 0), pt(-L, -Wd * 0.35, 0)].map((q) => proj(...q));
      poly(a, "rgba(255,176,46,.95)");
    }
    // jauge de boost au-dessus (vue joueur : pas pour sa propre voiture, le bandeau la donne)
    const top = proj(c.pos[0], c.pos[1], c.pos[2] + 150);
    if ((pov && c.judged) || !seen(top)) return;
    const
      bw = 34 * DPR,
      bh = 4.5 * DPR;
    ctx.fillStyle = "rgba(0,0,0,.55)";
    ctx.fillRect(top[0] - bw / 2 - 1, top[1] - 1, bw + 2, bh + 2);
    ctx.fillStyle = "#ffb02e";
    ctx.fillRect(top[0] - bw / 2, top[1], (bw * c.boost) / 100, bh);
    if (c.judged) {
      ctx.fillStyle = "#f5c542";
      ctx.beginPath();
      const y0 = top[1] - 8 * DPR;
      ctx.moveTo(top[0], y0);
      ctx.lineTo(top[0] - 7 * DPR, y0 - 10 * DPR);
      ctx.lineTo(top[0] + 7 * DPR, y0 - 10 * DPR);
      ctx.fill();
    }
  }
  function drawBallShadow(b: V3) {
    const c = [];
    for (let a = 0; a < 24; a++) c.push(proj(b[0] + 95 * Math.cos((a / 12) * Math.PI), b[1] + 95 * Math.sin((a / 12) * Math.PI), 0));
    poly(c, `rgba(0,0,0,${Math.max(0.2, 0.55 - b[2] / 4000)})`);
    if (b[2] > 140) seg(proj(b[0], b[1], 0), proj(b[0], b[1], b[2] - 93), "rgba(255,255,255,.5)", 1.3, true);
  }
  function drawBall(b: V3, bv: V3, trail: V3[]) {
    const tp = trail.map((q) => proj(q[0], q[1], q[2]));
    tp.slice(1).forEach((q, k) => seg(tp[k], q, "rgba(255,255,255,.4)", 2));
    const p = proj(b[0], b[1], b[2]);
    if (!seen(p)) return;
    const r = pov ? (93 * fpx) / Math.max(p[2], NEAR) : 93 * 1.25 * S;
    const g = ctx.createRadialGradient(p[0] - r * 0.35, p[1] - r * 0.35, r * 0.1, p[0], p[1], r);
    g.addColorStop(0, "#ffffff");
    g.addColorStop(1, "#b9bec6");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(p[0], p[1], r, 0, 7);
    ctx.fill();
    ctx.strokeStyle = "rgba(0,0,0,.5)";
    ctx.lineWidth = 1.2 * DPR;
    ctx.stroke();
    seg(p, proj(b[0] + bv[0] * 0.35, b[1] + bv[1] * 0.35, Math.max(93, b[2] + bv[2] * 0.35 - 40)), "rgba(255,255,255,.85)", 2);
    if (b[2] > 160) {
      ctx.font = `600 ${11 * DPR}px system-ui`;
      ctx.fillStyle = "#fff";
      ctx.fillText(`${(b[2] / 100).toFixed(1).replace(".", ",")} m`, p[0] + r + 4 * DPR, p[1] + 4 * DPR);
    }
  }

  return {
    t: 0,
    playing: true,
    speed: 1,
    stopAt: Math.min(N - 1, card.action_frame + FPS),
    last: null,
    resize() {
      const r = canvas.getBoundingClientRect();
      DPR = devicePixelRatio || 1;
      W = canvas.width = r.width * DPR;
      H = canvas.height = r.height * DPR;
    },
    rotate(d: number) {
      azT += (d * Math.PI) / 6;
    },
    top(on: boolean) {
      elT = on ? Math.PI / 2 - 0.001 : (38 * Math.PI) / 180;
    },
    pov(on: boolean) {
      pov = on;
      sm = null;
    },
    draw() {
      const s = state(this.t);
      if (pov) povCamera(s, this.t);
      else camera(s);
      ctx.clearRect(0, 0, W, H);
      if (pov) {
        ctx.fillStyle = "#121a22"; // ciel du stade
        ctx.fillRect(0, 0, W, H);
      }
      field();
      // ombres d'abord, puis objets du plus loin au plus proche
      s.cars.forEach(drawCarShadow);
      drawBallShadow(s.ball);
      const items = s.cars.map((c) => ({ d: proj(c.pos[0], c.pos[1], c.pos[2])[2], f: () => drawCar(c) }));
      const back = Math.round(0.6 * FPS),
        tr = card.ball.slice(Math.max(0, s.i - back), s.i + 1).concat([s.ball]);
      items.push({ d: proj(s.ball[0], s.ball[1], s.ball[2])[2], f: () => drawBall(s.ball, s.bv, tr) });
      items.sort((a, b) => b.d - a.d).forEach((o) => o.f());
      return pov ? { ...s, ballCam } : s;
    },
  };
}
