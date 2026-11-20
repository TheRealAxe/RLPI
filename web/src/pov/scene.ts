// Player 3D d'une touche (repris de la vue embarquée locale reports/pov.html, sans fantôme) : terrain, murs et buts,
// balle, 6 voitures en volume (silhouette type Octane, phares, flamme de boost, anneau de saut, noms), et les
// caméras du jeu : « ta caméra » (réglages et caméra balle enregistrés dans le replay), caméra balle, caméra voiture,
// vue libre. Les données (rlpi.pov) sont dans le repère de Rocket League (x vers la GAUCHE) : x est retourné une fois.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

type Arr = number[];
export interface PovCar {
  name: string;
  kind: "me" | "mate1" | "mate2" | "opp";
  x: Arr;
  y: Arr;
  z: Arr;
  fwd: [Arr, Arr, Arr];
  up: [Arr, Arr, Arr];
  boost: Arr;
  jump: Arr;
  djump: Arr;
  dodge: Arr;
}
export interface CamSettings {
  fov: number;
  distance: number;
  height: number;
  angle: number;
  stiffness: number;
  transition: number;
}
export interface PovClip {
  format: number;
  fps: number;
  t0: number;
  ball: { x: Arr; y: Arr; z: Arr };
  cars: PovCar[];
  cam: { settings: Partial<CamSettings>; ballcam: Arr } | null;
}
export type CamMode = "mine" | "ball" | "car" | "free";
export interface Hud {
  rel: number; // secondes depuis la touche
  ballcam: boolean;
  kmh: number;
  boost: number;
  move: string; // SAUT, DOUBLE SAUT, DODGE ou ""
  nose: string;
}

const COL = { me: "#d4ff3a", mate1: "#ff9a5c", mate2: "#5fd0a4", opp: "#8f98a6" } as const;
const DEFAULT_CAM: CamSettings = { fov: 110, distance: 270, height: 100, angle: -3, stiffness: 0.5, transition: 1.2 };

export function createPov(canvas: HTMLCanvasElement, input: PovClip, onHud: (h: Hud) => void) {
  // ------------------------------------------------ données, repère « comme dans le jeu »
  const neg = (a: Arr) => a.map((v) => -v);
  const ballD = { x: neg(input.ball.x), y: input.ball.y, z: input.ball.z };
  const carsD = input.cars.map((c) => ({
    ...c,
    x: neg(c.x),
    fwd: [neg(c.fwd[0]), c.fwd[1], c.fwd[2]] as [Arr, Arr, Arr],
    up: [neg(c.up[0]), c.up[1], c.up[2]] as [Arr, Arr, Arr],
  }));
  const me = carsD.find((c) => c.kind === "me") ?? carsD[0];
  const FPS = input.fps,
    T0 = input.t0,
    N = ballD.x.length;
  const CS: CamSettings = { ...DEFAULT_CAM, ...(input.cam?.settings ?? {}) };
  const BALLCAM = input.cam?.ballcam ?? Array<number>(N).fill(1);

  const lerp = (a: Arr, i: number) => {
    const k = Math.max(0, Math.min(a.length - 1, i)),
      f = Math.floor(k),
      c = Math.min(a.length - 1, f + 1);
    return a[f] + (a[c] - a[f]) * (k - f);
  };
  const v3 = (a: [Arr, Arr, Arr], i: number) => new THREE.Vector3(lerp(a[0], i), lerp(a[1], i), lerp(a[2], i));
  const posAt = (c: { x: Arr; y: Arr; z: Arr }, i: number) => new THREE.Vector3(lerp(c.x, i), lerp(c.y, i), lerp(c.z, i));
  const velAt = (c: { x: Arr; y: Arr; z: Arr }, i: number) =>
    posAt(c, Math.min(N - 1, i + 1))
      .sub(posAt(c, Math.max(0, i - 1)))
      .multiplyScalar(FPS / 2);
  const ballAt = (i: number) => posAt(ballD, i);
  function basis(fwd: THREE.Vector3, up: THREE.Vector3) {
    const f = fwd.clone().normalize();
    const u = up.clone().sub(f.clone().multiplyScalar(up.dot(f))).normalize();
    return { fwd: f, up: u, left: new THREE.Vector3().crossVectors(u, f) };
  }
  const B0 = ballAt(T0);
  const disposables: { dispose(): void }[] = [];
  const keep = <T extends { dispose(): void }>(x: T) => (disposables.push(x), x);

  // ------------------------------------------------ scène
  THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0e131b);
  scene.fog = new THREE.Fog(0x0e131b, 7000, 16000);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x1b2433, 1.0));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(2500, -3500, 7000);
  scene.add(sun);
  const allX = [...ballD.x, ...me.x],
    allY = [...ballD.y, ...me.y];
  const pad = 2000;
  const X0 = Math.max(-4096, Math.min(...allX) - pad),
    X1 = Math.min(4096, Math.max(...allX) + pad);
  const Y0 = Math.max(-5120, Math.min(...allY) - pad),
    Y1 = Math.min(5120, Math.max(...allY) + pad);
  const floor = new THREE.Mesh(
    keep(new THREE.PlaneGeometry(X1 - X0, Y1 - Y0)),
    keep(new THREE.MeshStandardMaterial({ color: 0x1b2a22, roughness: 1 })),
  );
  floor.position.set((X0 + X1) / 2, (Y0 + Y1) / 2, 0);
  scene.add(floor);
  const grid: number[] = [];
  for (let x = Math.ceil(X0 / 512) * 512; x <= X1; x += 512) grid.push(x, Y0, 1, x, Y1, 1);
  for (let y = Math.ceil(Y0 / 512) * 512; y <= Y1; y += 512) grid.push(X0, y, 1, X1, y, 1);
  const lineSeg = (pts: number[], color: number) => {
    const g = keep(new THREE.BufferGeometry());
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    scene.add(new THREE.LineSegments(g, keep(new THREE.LineBasicMaterial({ color }))));
  };
  lineSeg(grid, 0x2f4637);
  const marks: number[] = [];
  if (Y0 < 0 && Y1 > 0) marks.push(X0, 0, 2, X1, 0, 2);
  for (const y of [-5120, 5120]) if (y >= Y0 - 1 && y <= Y1 + 1) marks.push(X0, y, 2, X1, y, 2);
  for (let a = 0; a < 64; a++) {
    const a0 = (a / 64) * 2 * Math.PI,
      a1 = ((a + 1) / 64) * 2 * Math.PI;
    marks.push(1000 * Math.cos(a0), 1000 * Math.sin(a0), 2, 1000 * Math.cos(a1), 1000 * Math.sin(a1), 2);
  }
  lineSeg(marks, 0xc8d2c0);
  const padMat = keep(new THREE.MeshBasicMaterial({ color: 0xffa040 }));
  const padGeo = keep(new THREE.CylinderGeometry(160, 160, 6, 24));
  for (const [px, py] of [
    [3072, 4096],
    [-3072, 4096],
    [3072, -4096],
    [-3072, -4096],
    [3584, 0],
    [-3584, 0],
  ]) {
    if (px < X0 || px > X1 || py < Y0 || py > Y1) continue;
    const p = new THREE.Mesh(padGeo, padMat);
    p.rotation.x = Math.PI / 2;
    p.position.set(px, py, 3);
    scene.add(p);
  }
  const wallMat = keep(
    new THREE.MeshBasicMaterial({ color: 0x6eb0ff, transparent: true, opacity: 0.07, side: THREE.DoubleSide, depthWrite: false }),
  );
  const hl: number[] = [];
  function sideWall(x: number) {
    const w = new THREE.Mesh(keep(new THREE.PlaneGeometry(Y1 - Y0, 2044)), wallMat);
    w.rotation.set(Math.PI / 2, Math.PI / 2, 0);
    w.position.set(x, (Y0 + Y1) / 2, 1022);
    scene.add(w);
    for (let z = 256; z < 2044; z += 256) hl.push(x, Y0, z, x, Y1, z);
  }
  function backWall(y: number) {
    for (const [a, b] of [
      [X0, -893],
      [893, X1],
    ]) {
      if (b <= a) continue;
      const w = new THREE.Mesh(keep(new THREE.PlaneGeometry(b - a, 2044)), wallMat);
      w.rotation.set(Math.PI / 2, 0, 0);
      w.position.set((a + b) / 2, y, 1022);
      scene.add(w);
    }
    const top = new THREE.Mesh(keep(new THREE.PlaneGeometry(1786, 2044 - 643)), wallMat);
    top.rotation.set(Math.PI / 2, 0, 0);
    top.position.set(0, y, 643 + (2044 - 643) / 2);
    scene.add(top);
    for (let z = 256; z < 2044; z += 256) {
      if (z > 643) hl.push(X0, y, z, X1, y, z);
      else hl.push(X0, y, z, -893, y, z, 893, y, z, X1, y, z);
    }
    const col = y > 0 ? 0xe2622e : 0x4f9bff,
      post = keep(new THREE.MeshStandardMaterial({ color: col }));
    for (const px of [-893, 893]) {
      const p = new THREE.Mesh(keep(new THREE.BoxGeometry(40, 40, 643)), post);
      p.position.set(px, y, 321);
      scene.add(p);
    }
    const bar = new THREE.Mesh(keep(new THREE.BoxGeometry(1826, 40, 40)), post);
    bar.position.set(0, y, 643);
    scene.add(bar);
    const net = new THREE.Mesh(
      keep(new THREE.PlaneGeometry(1786, 643)),
      keep(new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.14, side: THREE.DoubleSide })),
    );
    net.rotation.set(Math.PI / 2, 0, 0);
    net.position.set(0, y + Math.sign(y) * 880, 321);
    scene.add(net);
  }
  if (X1 >= 3900) sideWall(4096);
  if (X0 <= -3900) sideWall(-4096);
  if (Y1 >= 4900) backWall(5120);
  if (Y0 <= -4900) backWall(-5120);
  if (hl.length) lineSeg(hl, 0x2c3a52);

  // balle (texture à motif), ombre, fil de hauteur
  const bc = document.createElement("canvas");
  bc.width = 256;
  bc.height = 128;
  const bctx = bc.getContext("2d")!;
  bctx.fillStyle = "#f3f3ee";
  bctx.fillRect(0, 0, 256, 128);
  bctx.fillStyle = "#9aa1ab";
  for (let i = 0; i < 8; i++)
    for (let j = 0; j < 4; j++) {
      bctx.beginPath();
      bctx.arc(16 + i * 32 + (j % 2) * 16, 16 + j * 32, 7, 0, 7);
      bctx.fill();
    }
  const ball = new THREE.Mesh(
    keep(new THREE.SphereGeometry(93, 40, 20)),
    keep(new THREE.MeshStandardMaterial({ map: keep(new THREE.CanvasTexture(bc)), roughness: 0.45 })),
  );
  scene.add(ball);
  const ballShadow = new THREE.Mesh(
    keep(new THREE.CircleGeometry(95, 32)),
    keep(new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.45 })),
  );
  scene.add(ballShadow);
  const stemGeo = keep(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]));
  const stem = new THREE.Line(stemGeo, keep(new THREE.LineDashedMaterial({ color: 0xf3f3ee, dashSize: 40, gapSize: 40 })));
  scene.add(stem);

  // ------------------------------------------------ voitures (silhouette type Octane)
  const carGeo = (() => {
    const s = new THREE.Shape();
    (
      [
        [-59, -14],
        [59, -14],
        [60, -3],
        [52, 4],
        [22, 9],
        [4, 24],
        [-26, 25],
        [-44, 14],
        [-59, 10],
      ] as const
    ).forEach(([x, z], k) => (k ? s.lineTo(x, z) : s.moveTo(x, z)));
    s.closePath();
    const g = new THREE.ExtrudeGeometry(s, { depth: 80, bevelEnabled: true, bevelSize: 3, bevelThickness: 3, bevelSegments: 1 });
    g.rotateX(Math.PI / 2);
    g.translate(0, 40, 0);
    return keep(g);
  })();
  const glassGeo = (() => {
    const s = new THREE.Shape();
    (
      [
        [20, 10],
        [4, 23],
        [-24, 24],
        [-40, 14],
        [-40, 11],
      ] as const
    ).forEach(([x, z], k) => (k ? s.lineTo(x, z) : s.moveTo(x, z)));
    s.closePath();
    const g = new THREE.ExtrudeGeometry(s, { depth: 84, bevelEnabled: false });
    g.rotateX(Math.PI / 2);
    g.translate(0, 42, 0.6);
    return keep(g);
  })();
  const wheelGeo = keep(new THREE.CylinderGeometry(13, 13, 12, 18));
  const glassMat = keep(new THREE.MeshStandardMaterial({ color: 0x10161f, roughness: 0.2 }));
  const wheelMat = keep(new THREE.MeshStandardMaterial({ color: 0x15181d, roughness: 0.9 }));
  const headMat = keep(new THREE.MeshBasicMaterial({ color: 0xffffff })),
    tailMat = keep(new THREE.MeshBasicMaterial({ color: 0xff3a2e }));
  const lampGeo = keep(new THREE.BoxGeometry(4, 16, 6));
  interface CarView {
    g: THREE.Group;
    flame: THREE.Mesh;
    ring: THREE.Mesh;
    shadow: THREE.Mesh;
    label: THREE.Sprite | null;
  }
  function makeCar(color: string, label: string | null): CarView {
    const g = new THREE.Group();
    g.add(new THREE.Mesh(carGeo, keep(new THREE.MeshStandardMaterial({ color, roughness: 0.5, metalness: 0.1 }))));
    g.add(new THREE.Mesh(glassGeo, glassMat));
    for (const [wx, wy] of [
      [36, 37],
      [36, -37],
      [-36, 37],
      [-36, -37],
    ]) {
      const w = new THREE.Mesh(wheelGeo, wheelMat);
      w.position.set(wx, wy, -14);
      g.add(w);
    }
    for (const y of [26, -26]) {
      const h = new THREE.Mesh(lampGeo, headMat);
      h.position.set(61, y, -4);
      g.add(h);
      const t = new THREE.Mesh(lampGeo, tailMat);
      t.position.set(-61, y, 4);
      g.add(t);
    }
    const flame = new THREE.Mesh(
      keep(new THREE.ConeGeometry(14, 90, 12)),
      keep(new THREE.MeshBasicMaterial({ color: 0xffa040, transparent: true, opacity: 0.9 })),
    );
    flame.rotation.z = Math.PI / 2;
    flame.position.set(-108, 0, 2);
    flame.visible = false;
    g.add(flame);
    const ring = new THREE.Mesh(
      keep(new THREE.TorusGeometry(70, 4, 6, 32)),
      keep(new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.8 })),
    );
    ring.position.z = -20;
    ring.visible = false;
    g.add(ring);
    const shadow = new THREE.Mesh(
      keep(new THREE.PlaneGeometry(118, 84)),
      keep(new THREE.MeshBasicMaterial({ color: 0, transparent: true, opacity: 0.35 })),
    );
    scene.add(shadow);
    let sp: THREE.Sprite | null = null;
    if (label) {
      const c = document.createElement("canvas");
      c.width = 256;
      c.height = 64;
      const x = c.getContext("2d")!;
      x.fillStyle = "rgba(11,13,17,.75)";
      x.fillRect(0, 8, 256, 48);
      x.fillStyle = color;
      x.font = "800 30px 'Sofia Sans', Arial";
      x.textAlign = "center";
      x.textBaseline = "middle";
      x.fillText(label, 128, 33);
      sp = new THREE.Sprite(keep(new THREE.SpriteMaterial({ map: keep(new THREE.CanvasTexture(c)), depthTest: false, transparent: true })));
      sp.scale.set(190, 48, 1);
      scene.add(sp);
    }
    scene.add(g);
    return { g, flame, ring, shadow, label: sp };
  }
  const cars = carsD.map((c) => ({ c, v: makeCar(COL[c.kind], c.kind === "me" ? null : c.name.slice(0, 14)) }));
  function placeCar(v: CarView, pos: THREE.Vector3, fwd: THREE.Vector3, up: THREE.Vector3) {
    const b = basis(fwd, up);
    v.g.matrixAutoUpdate = false;
    v.g.matrix.makeBasis(b.fwd, b.left, b.up).setPosition(pos);
    v.shadow.position.set(pos.x, pos.y, 1.5);
    v.shadow.rotation.z = Math.atan2(b.fwd.y, b.fwd.x);
    v.label?.position.set(pos.x, pos.y, pos.z + 150);
  }
  // trace de ta voiture (1,2 s)
  const TRAIL_MAX = 64,
    trailBuf = new Float32Array(TRAIL_MAX * 3);
  const trailGeo = keep(new THREE.BufferGeometry());
  trailGeo.setAttribute("position", new THREE.BufferAttribute(trailBuf, 3));
  scene.add(new THREE.Line(trailGeo, keep(new THREE.LineBasicMaterial({ color: COL.me }))));

  // ------------------------------------------------ caméras « comme en jeu »
  // Caméra balle : elle tourne autour de ta voiture pour faire face à la balle, à « distance » derrière et « hauteur »
  // au-dessus, et vise la balle en gardant ta voiture dans le bas de l'image. Caméra voiture : derrière la voiture
  // dans son cap, inclinée de « angle », alignée sur la surface au mur. Rigidité : la caméra recule un peu quand tu
  // vas vite. Transition entre les deux à ta vitesse réglée, au moment où tu as appuyé sur la touche.
  const vfov = (aspect: number) => (2 * Math.atan(Math.tan((CS.fov * Math.PI) / 360) / aspect) * 180) / Math.PI;
  let lastVfov = 70;
  const onSurface = (p: THREE.Vector3, up: THREE.Vector3) =>
    p.z < 40 || ((Math.abs(p.x) > 3900 || Math.abs(p.y) > 4950 || p.z > 1950) && up.z < 0.7);
  function carYawDir(i: number) {
    const f = v3(me.fwd, i),
      h = new THREE.Vector3(f.x, f.y, 0);
    if (h.length() < 0.25) {
      const v = velAt(me, i);
      h.set(v.x, v.y, 0);
    }
    return h.lengthSq() ? h.normalize() : new THREE.Vector3(0, 1, 0);
  }
  function camDir(kind: "ball" | "car", i: number, carPos: THREE.Vector3, carFwd: THREE.Vector3, carUp: THREE.Vector3, ballPos: THREE.Vector3) {
    if (kind === "ball") {
      const d = ballPos.clone().sub(carPos);
      d.z = 0;
      return { dir: d.lengthSq() > 1 ? d.normalize() : carYawDir(i), up: new THREE.Vector3(0, 0, 1) };
    }
    const surf = onSurface(carPos, carUp);
    const up = surf ? carUp.clone().normalize() : new THREE.Vector3(0, 0, 1);
    const dir = surf ? carFwd.clone().sub(up.clone().multiplyScalar(carFwd.dot(up))).normalize() : carYawDir(i);
    return { dir, up };
  }
  const TAU = 0.06,
    TRANS = 0.35 / Math.max(0.2, CS.transition);
  interface Pre {
    q: THREE.Quaternion;
    blend: number;
    up: THREE.Vector3;
  }
  function precompute(forced: "ball" | "car" | null): Pre[] {
    const out: Pre[] = [];
    let yawQ: THREE.Quaternion | null = null;
    const want = (k: number) => (forced ? (forced === "ball" ? 1 : 0) : BALLCAM[k] ? 1 : 0);
    let blend = want(0);
    const a = 1 - Math.exp(-1 / (FPS * TAU)),
      step = 1 / (FPS * TRANS);
    for (let k = 0; k < N; k++) {
      const pos = posAt(me, k),
        fwd = v3(me.fwd, k),
        up = v3(me.up, k),
        b = ballAt(k);
      const w = want(k);
      blend += Math.sign(w - blend) * Math.min(step, Math.abs(w - blend));
      const pb = camDir("ball", k, pos, fwd, up, b),
        pc = camDir("car", k, pos, fwd, up, b);
      const dir = pc.dir.clone().lerp(pb.dir, blend).normalize();
      const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(1, 0, 0), dir);
      yawQ = yawQ ? yawQ.slerp(q, a) : q;
      out.push({ q: yawQ.clone(), blend, up: pc.up.clone().lerp(pb.up, blend).normalize() });
    }
    return out;
  }
  let pre = precompute(null);
  const camMain = new THREE.PerspectiveCamera(75, 16 / 9, 10, 30000);
  const camFree = new THREE.PerspectiveCamera(60, 16 / 9, 10, 30000);
  camFree.position.set(B0.x - 1600, B0.y - 2200, B0.z + 1400);
  const orbit = new OrbitControls(camFree, canvas);
  orbit.target.set(B0.x, B0.y, Math.max(93, B0.z));
  orbit.enabled = false;
  orbit.update();
  orbit.addEventListener("change", () => (need = true));
  function applyCam(i: number, pos: THREE.Vector3, ballPos: THREE.Vector3) {
    const k = Math.max(0, Math.min(N - 1, i)),
      f = Math.floor(k),
      c = Math.min(N - 1, f + 1),
      w = k - f;
    const q = pre[f].q.clone().slerp(pre[c].q, w),
      blend = pre[f].blend + (pre[c].blend - pre[f].blend) * w;
    const up = pre[f].up.clone().lerp(pre[c].up, w).normalize();
    const dir = new THREE.Vector3(1, 0, 0).applyQuaternion(q);
    const dist = CS.distance * (1 + (1 - CS.stiffness) * 0.5 * Math.min(1, velAt(me, i).length() / 2300));
    camMain.position.copy(pos).sub(dir.clone().multiplyScalar(dist)).add(up.clone().multiplyScalar(CS.height));
    camMain.up.copy(up);
    const pitch = (CS.angle * Math.PI) / 180;
    const lookCar = pos
      .clone()
      .add(up.clone().multiplyScalar(CS.height))
      .add(dir.clone().multiplyScalar(1000 * Math.cos(pitch)))
      .add(up.clone().multiplyScalar(1000 * Math.sin(pitch)));
    // caméra balle : vise la balle sans jamais perdre ta voiture du bas de l'image (recherche continue)
    const toCar = pos.clone().sub(camMain.position).normalize(),
      maxA = ((lastVfov / 2 - 7) * Math.PI) / 180;
    const mix = (x: number) => ballPos.clone().multiplyScalar(x).add(pos.clone().multiplyScalar(1 - x));
    const fits = (x: number) => mix(x).sub(camMain.position).normalize().angleTo(toCar) <= maxA;
    let wb = 1;
    if (!fits(1)) {
      let lo = 0,
        hi = 1;
      for (let it = 0; it < 22; it++) {
        const mid = (lo + hi) / 2;
        if (fits(mid)) lo = mid;
        else hi = mid;
      }
      wb = lo;
    }
    camMain.lookAt(lookCar.clone().lerp(mix(wb), blend));
    return blend;
  }

  // ------------------------------------------------ état, image, rendu
  let t = Math.max(0, T0 - 2 * FPS),
    playing = false,
    speed = 0.5,
    camMode: CamMode = "mine",
    pausedAtTouch = false,
    need = true,
    raf = 0,
    last: number | null = null;
  const tmax = N - 1;
  const listeners: ((s: { t: number; playing: boolean }) => void)[] = [];
  const emit = () => listeners.forEach((f) => f({ t, playing }));

  function frame(i: number) {
    const k = Math.round(i);
    for (const { c, v } of cars) {
      placeCar(v, posAt(c, i), v3(c.fwd, i), v3(c.up, i));
      const back = Math.max(0, k - Math.round(0.3 * FPS));
      v.flame.visible = c.boost[k] < c.boost[back] - 0.5; // la jauge baisse par à-coups dans le replay
      v.ring.visible = !!(c.jump[k] || c.djump[k] || c.dodge[k]);
    }
    const b = ballAt(i);
    ball.position.copy(b);
    ballShadow.position.set(b.x, b.y, 1.2);
    const sp = stemGeo.attributes.position as THREE.BufferAttribute;
    sp.setXYZ(0, b.x, b.y, 1);
    sp.setXYZ(1, b.x, b.y, b.z);
    sp.needsUpdate = true;
    stem.computeLineDistances();
    const from = Math.max(0, Math.floor(i) - Math.min(TRAIL_MAX - 1, Math.round(1.2 * FPS))),
      cnt = Math.floor(i) - from + 1;
    for (let n = 0; n < cnt; n++) {
      trailBuf[3 * n] = me.x[from + n];
      trailBuf[3 * n + 1] = me.y[from + n];
      trailBuf[3 * n + 2] = me.z[from + n];
    }
    trailGeo.attributes.position.needsUpdate = true;
    trailGeo.setDrawRange(0, cnt);
    trailGeo.computeBoundingSphere();
    const pos = posAt(me, i);
    const bl = applyCam(i, pos, b);
    const v = velAt(me, i).length();
    const f = v3(me.fwd, i).normalize(),
      pitch = (Math.asin(Math.max(-1, Math.min(1, f.z))) * 180) / Math.PI;
    onHud({
      rel: (i - T0) / FPS,
      ballcam: bl > 0.5,
      kmh: Math.round(v * 0.036),
      boost: Math.round(lerp(me.boost, i)),
      move: me.dodge[k] ? "DODGE" : me.djump[k] ? "DOUBLE SAUT" : me.jump[k] ? "SAUT" : "",
      nose: Math.abs(pitch) < 15 ? "nez à plat" : pitch > 0 ? `nez vers le haut (${Math.round(pitch)}°)` : `nez vers le bas (${Math.round(-pitch)}°)`,
    });
  }
  function render() {
    const w = canvas.clientWidth,
      h = canvas.clientHeight;
    if (!w || !h) return;
    if (canvas.width !== Math.floor(w * renderer.getPixelRatio()) || canvas.height !== Math.floor(h * renderer.getPixelRatio()))
      renderer.setSize(w, h, false);
    const cam = camMode === "free" ? camFree : camMain;
    cam.aspect = w / h;
    if (cam !== camFree) {
      cam.fov = vfov(cam.aspect);
      lastVfov = cam.fov;
    }
    cam.updateProjectionMatrix();
    renderer.render(scene, cam);
  }
  function loop(ts: number) {
    if (playing) {
      if (last !== null) {
        const nt = t + ((ts - last) / 1000) * FPS * speed;
        if (!pausedAtTouch && t < T0 && nt >= T0) {
          t = T0; // arrêt sur la touche au premier passage
          pausedAtTouch = true;
          playing = false;
        } else t = Math.min(tmax, nt);
        if (t >= tmax) playing = false;
        need = true;
        emit();
      }
      last = ts;
    } else last = null;
    if (need) {
      frame(t);
      render();
      need = false;
    }
    raf = requestAnimationFrame(loop);
  }
  const ro = new ResizeObserver(() => (need = true));
  ro.observe(canvas);
  raf = requestAnimationFrame(loop);

  return {
    T0,
    FPS,
    tmax,
    get t() {
      return t;
    },
    get playing() {
      return playing;
    },
    onState(f: (s: { t: number; playing: boolean }) => void) {
      listeners.push(f);
      f({ t, playing });
    },
    toggle() {
      if (!playing && t >= tmax) {
        t = Math.max(0, T0 - 2 * FPS);
        pausedAtTouch = false;
      }
      playing = !playing;
      need = true;
      emit();
    },
    restart() {
      t = Math.max(0, T0 - 2 * FPS);
      pausedAtTouch = false;
      playing = true;
      need = true;
      emit();
    },
    seek(v: number) {
      t = Math.max(0, Math.min(tmax, v));
      pausedAtTouch = t >= T0;
      playing = false;
      need = true;
      emit();
    },
    setSpeed(s: number) {
      speed = s;
    },
    setCam(m: CamMode) {
      const forcedOld = camMode === "ball" ? "ball" : camMode === "car" ? "car" : null;
      camMode = m;
      orbit.enabled = m === "free";
      const forced = m === "ball" ? "ball" : m === "car" ? "car" : null;
      if (forced !== forcedOld) pre = precompute(forced);
      need = true;
    },
    dispose() {
      cancelAnimationFrame(raf);
      ro.disconnect();
      orbit.dispose();
      disposables.forEach((d) => d.dispose());
      renderer.dispose();
    },
  };
}
export type Pov = ReturnType<typeof createPov>;
