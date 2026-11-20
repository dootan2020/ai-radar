// The AG-UI "giao thuc" scene: how one app talks to one agent. Every pixel is a pure function of the time t passed to window.renderAt(t);
// the timeline (acts, beads, tallies, framework swaps) comes from /data.json, which halcyon_canh.py computes from the real sources.
// No clock, no randomness, no animation loop: the renderer draws once per call, the producer screenshots, then calls again.
import * as THREE from '/three.module.js';

const D = await (await fetch('/data.json')).json();
const W = D.w, H = D.h;
const C = { ink: 0x101828, slab: 0x1d2741, slabEdge: 0x2c3a5e, coral: 0xF0446E, plum: 0x5B1738, pink: 0xFFC9D6, amber: 0xF2A24D, white: 0xffffff, win: 0xEEF1F6 };
const KIND = { life: C.coral, text: C.white, tool: C.amber, state: C.pink };
const CSS = { life: '#F0446E', text: '#FFFFFF', tool: '#F2A24D', state: '#FFC9D6' };

// ---------- easing (no library) ----------
const cl = (x) => Math.min(1, Math.max(0, x));
const seg = (t, a, b) => cl((t - a) / (b - a));
const lerp = (a, b, k) => a + (b - a) * k;
const outQ = (k) => 1 - Math.pow(1 - k, 4);                                  // entrances: fast start, soft landing
const inC = (k) => k * k * k;                                                 // exits
const io = (k) => (k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2); // movement on screen
const ioS = (k) => -(Math.cos(Math.PI * k) - 1) / 2;                          // camera drift
const fade = (t, a, b, c, d) => Math.min(outQ(seg(t, a, b)), 1 - inC(seg(t, c, d)));   // in over a..b, out over c..d

// ---------- renderer, camera, light ----------
const canvas = document.getElementById('gl');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(2);                     // drawn at 2x, composited to 1x by the browser: a 2x2 box filter on top of MSAA, no shimmer on thin edges
renderer.setSize(W, H, false);
renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene();
scene.background = new THREE.Color(C.ink);
const camera = new THREE.PerspectiveCamera(28, W / H, 0.1, 100);
const TARGET = new THREE.Vector3(0.15, 0.25, 0);
scene.add(new THREE.HemisphereLight(0xdfe6ff, 0x101828, 1.15));
const key = new THREE.DirectionalLight(0xffffff, 2.0); key.position.set(-4, 7, 9); scene.add(key);
const rim = new THREE.DirectionalLight(0xF0446E, 0.9); rim.position.set(6, -2, -6); scene.add(rim);
const laneLight = new THREE.PointLight(0xF0446E, 0, 9, 1.6); laneLight.position.set(-1.6, .9, 1.4); scene.add(laneLight);

// ---------- geometry helpers ----------
function rounded(w, h, r) {
  const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r); s.lineTo(x + w, y + h - r);
  s.quadraticCurveTo(x + w, y + h, x + w - r, y + h); s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y); return s;
}
function slab(w, h, r, depth, color, opts = {}) {
  const g = new THREE.ExtrudeGeometry(rounded(w, h, r), { depth, bevelEnabled: true, bevelThickness: .04, bevelSize: .04, bevelSegments: 3, curveSegments: 10 });
  g.translate(0, 0, -depth / 2);
  const m = new THREE.MeshStandardMaterial({ color, roughness: opts.rough ?? .55, metalness: .08, transparent: true });
  const mesh = new THREE.Mesh(g, m);
  if (opts.edge) {
    const e = new THREE.LineSegments(new THREE.EdgesGeometry(g, 30), new THREE.LineBasicMaterial({ color: opts.edge, transparent: true, opacity: .55 }));
    mesh.add(e); mesh.userData.edge = e;
  }
  return mesh;
}
function glowTexture() {                     // drawn once, deterministic
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const x = c.getContext('2d'), gr = x.createRadialGradient(64, 64, 0, 64, 64, 64);
  gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(.25, 'rgba(255,255,255,.45)'); gr.addColorStop(1, 'rgba(255,255,255,0)');
  x.fillStyle = gr; x.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
const GLOW = glowTexture();
function glow(color, size) {
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
  s.scale.set(size, size, 1); return s;
}
function setOpacity(obj, o) {
  obj.traverse((n) => { if (n.material) { n.material.opacity = (n.userData.baseOpacity ?? 1) * o; n.visible = o > .002; } });
}

// ---------- the actors ----------
const LANE_X = -1.95, LANE_TOP = 2.48, LANE_BOT = -0.92;
// agent (server) block, top
const agent = new THREE.Group(); scene.add(agent);
const agentBody = slab(6.0, 1.25, .22, 1.0, C.slab, { edge: C.slabEdge }); agent.add(agentBody);
agentBody.userData.edge.userData.baseOpacity = .55;
const core = new THREE.Mesh(new THREE.IcosahedronGeometry(.36, 0), new THREE.MeshStandardMaterial({ color: C.coral, emissive: C.coral, emissiveIntensity: .55, roughness: .35, flatShading: true, transparent: true }));
core.position.set(2.25, 0, .62); agent.add(core);
const coreGlow = glow(C.coral, 2.2); coreGlow.position.set(2.25, 0, .5); agent.add(coreGlow);
agent.position.set(0, 3.12, 0);
// tool chip on the agent (act 4)
const tool = slab(.62, .42, .1, .34, C.amber, { rough: .4 }); tool.material.emissive = new THREE.Color(C.amber); tool.material.emissiveIntensity = .0;
tool.position.set(1.2, -.05, .62); agent.add(tool);
const toolGlow = glow(C.amber, 1.6); toolGlow.position.set(1.2, -.05, .7); agent.add(toolGlow);
// app window, bottom
const app = new THREE.Group(); scene.add(app);
const appBody = slab(7.1, 3.0, .26, .3, C.win, { rough: .7 }); appBody.material.emissive = new THREE.Color(C.win); appBody.material.emissiveIntensity = .42; app.add(appBody);
const appBar = new THREE.Mesh(new THREE.PlaneGeometry(7.0, .02), new THREE.MeshBasicMaterial({ color: 0xd4d9e3, transparent: true }));
appBar.position.set(0, 0.98, .136); app.add(appBar);
app.position.set(-0.05, -2.45, 0);
// lane: a glass tube, its lit core is the open connection
const lane = new THREE.Group(); scene.add(lane);
const LANE_LEN = LANE_TOP - LANE_BOT;
const tube = new THREE.Mesh(new THREE.CylinderGeometry(.21, .21, LANE_LEN, 48, 1, true), new THREE.MeshStandardMaterial({ color: 0x31406a, roughness: .3, metalness: .1, transparent: true, side: THREE.DoubleSide }));
tube.userData.baseOpacity = .55; tube.material.depthWrite = false;
const wire = new THREE.Mesh(new THREE.CylinderGeometry(.055, .055, LANE_LEN, 16), new THREE.MeshBasicMaterial({ color: C.coral, transparent: true }));
const wireGlow = new THREE.Mesh(new THREE.CylinderGeometry(.15, .15, LANE_LEN, 32, 1, true), new THREE.MeshBasicMaterial({ color: C.coral, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
wireGlow.userData.baseOpacity = .22;
lane.add(tube, wire, wireGlow);
lane.position.set(LANE_X, (LANE_TOP + LANE_BOT) / 2, 0);
// request packet (act 2)
const packet = slab(.9, .46, .12, .26, C.white, { edge: C.coral, rough: .4 }); packet.userData.edge.userData.baseOpacity = 1; scene.add(packet);
const packetGlow = glow(C.white, 1.7); scene.add(packetGlow);
// beads: shape and colour say the kind (life ring sphere, text capsule, tool octahedron, state diamond)
const GEO = {
  life: new THREE.SphereGeometry(.2, 32, 16),
  text: new THREE.CapsuleGeometry(.1, .2, 6, 16).rotateZ(Math.PI / 2),
  tool: new THREE.OctahedronGeometry(.21, 0),
  state: new THREE.BoxGeometry(.24, .24, .24).rotateZ(Math.PI / 4),
};
const pool = [];
function bead(i) {
  while (pool.length <= i) {
    const g = new THREE.Group();
    const meshes = {};
    for (const k of Object.keys(GEO)) {
      const m = new THREE.Mesh(GEO[k], new THREE.MeshStandardMaterial({ color: KIND[k], emissive: KIND[k], emissiveIntensity: .35, roughness: .3, transparent: true, flatShading: k === 'tool' }));
      g.add(m); meshes[k] = m;
    }
    const gl = glow(C.white, .9); g.add(gl);
    g.userData = { meshes, gl }; scene.add(g); pool.push(g);
  }
  return pool[i];
}

// ---------- DOM labels ----------
const ui = document.getElementById('ui');
const LB = [];
function mk(cls, html) { const e = document.createElement('div'); e.className = 'lb ' + cls; e.innerHTML = html; ui.appendChild(e); const o = { e, op: 0 }; LB.push(o); return o; }
function place(o, x, y, op, ax = 0, ay = 0) {            // ax/ay: anchor share of the label's own box
  o.op = op; o.e.style.opacity = op.toFixed(4);
  o.e.style.transform = `translate(${x}px, ${y}px) translate(${-ax * 100}%, ${-ay * 100}%)`;
}
const tmp = new THREE.Vector3();
function px(obj, lx, ly, lz) { tmp.set(lx, ly, lz); obj.localToWorld(tmp); tmp.project(camera); return [(tmp.x + 1) / 2 * W, (1 - tmp.y) / 2 * H]; }

const heads = D.acts.map((a) => mk('head', a.head));
const agentName = mk('name', 'TRỢ LÝ AI');
const agentSub = D.agent_subs.map((s) => mk('sub', s.text));
const appName = mk('name', '<span style="color:#101828">ỨNG DỤNG CỦA BẠN</span>');
const laneTag = mk('', '<span class="head" style="font-size:44px;color:#F0446E">AG-UI</span>');
const laneSub = mk('sub', 'chuẩn kết nối app ↔ trợ lý');
const userB = mk('bubble user', D.request.user_text);
const botB = mk('bubble bot', '');
const reqA = mk('mono big', `<span style="color:#F0446E">${D.request.method}</span> · ${D.request.type}`);
const reqB = mk('sub', D.request.carries);
const logRows = D.run1.map((e) => mk('mono', `<span class="dot" style="background:${CSS[e.kind]}"></span>${e.name}`));
const deltaTags = D.run1.map((e) => (e.delta == null ? null : mk('mono', `<span style="color:#FFC9D6">"${e.delta.replace(/ /g, '&nbsp;')}"</span>`)));
const tallyRows = D.run2.tallies.map((r) => mk('mono', `<span class="dot" style="background:${CSS[r.kind]}"></span>${r.label}`));
const tallyNums = D.run2.tallies.map(() => mk('num', ''));
const tallySrc = mk('sub', D.run2.source_line);
const toolTag = mk('tag', 'công cụ');
const stateTag = mk('tag', 'STATE');
const keepTag = mk('tag', 'cùng giao thức ✓');
const stateNote = mk('mono', '<span style="color:#5B1738">← STATE_SNAPSHOT</span>');
const fwNames = D.swap.map((s) => mk('sub', s.name));
// bars inside the app window (act 4): two notes of the shared state, and the reply growing
const bars = [0, 1, 2].map(() => { const e = document.createElement('div'); e.style.cssText = 'position:absolute;left:0;top:0;height:20px;border-radius:10px;opacity:0;will-change:transform,opacity,width;'; ui.appendChild(e); return e; });

function botText(t) {             // what the assistant bubble holds at t: the deltas whose bead has landed, a caret while the message is open
  let s = '', open = false, any = false;
  for (const e of D.run1) {
    if (t < e.t1) continue;
    if (e.name === 'TEXT_MESSAGE_START') { open = true; any = true; }
    if (e.name === 'TEXT_MESSAGE_CONTENT') s += e.delta;
    if (e.name === 'TEXT_MESSAGE_END') open = false;
  }
  return { s, open, any };
}

// ---------- one frame ----------
function renderAt(tReal) {
  const t = tReal / D.scale;            // the timeline is authored on a base length (D.base); the clip plays it in D.duration
  const A = Object.fromEntries(D.acts.map((a) => [a.name, a]));
  const T = D.base;
  // camera: one slow drift across the whole clip, nothing else moves the frame
  const az = THREE.MathUtils.degToRad(lerp(-5, 5, ioS(t / T))), el = THREE.MathUtils.degToRad(lerp(20, 16, ioS(t / T))), R = 20.5;
  camera.position.set(TARGET.x + R * Math.cos(el) * Math.sin(az), TARGET.y + R * Math.sin(el), TARGET.z + R * Math.cos(el) * Math.cos(az));
  camera.lookAt(TARGET); camera.updateMatrixWorld();

  // act headings: one at a time, crossfade with a short rise
  D.acts.forEach((a, i) => {
    const o = fade(t, a.a + .05, a.a + .5, a.b - .35, a.b - .02);
    place(heads[i], 64, 30 + 10 * (1 - outQ(seg(t, a.a + .05, a.a + .5))), i === D.acts.length - 1 ? Math.min(outQ(seg(t, a.a + .05, a.a + .5)), 1) : o);
  });

  // act 1: the two ends rise, then the lane is drawn between them
  const kA = outQ(seg(t, .15, 1.05)), kP = outQ(seg(t, .6, 1.5)), kL = io(seg(t, 1.4, 2.3));
  // act 5: the agent is swapped; the app never moves
  let ax = 0, aop = kA;
  for (let i = 1; i < D.swap.length; i++) {
    const s = D.swap[i].a;
    if (t >= s - .3 && t < s) { ax = 2.4 * inC(seg(t, s - .3, s)); aop = 1 - seg(t, s - .3, s); }
    if (t >= s && t < s + .45) { ax = -2.4 * (1 - outQ(seg(t, s, s + .45))); aop = outQ(seg(t, s, s + .3)); }
  }
  agent.position.set(ax, 3.12 - .55 * (1 - kA), 0); setOpacity(agent, aop);
  const toolOn = fade(t, A.tools.a + .3, A.tools.a + .7, A.tools.b - .6, A.tools.b - .2);
  setOpacity(tool, aop * toolOn); setOpacity(toolGlow, 0);
  core.rotation.set(.35 + t * .35, t * .5, 0);
  app.position.set(-0.05, -2.45 - .55 * (1 - kP), 0); setOpacity(app, kP);
  lane.scale.set(1, Math.max(kL, .001), 1); lane.position.y = LANE_BOT + LANE_LEN * Math.max(kL, .001) / 2;
  setOpacity(tube, kL);

  // the connection: lit while a run streams, dim otherwise
  let conn = 0;
  for (const r of D.runs) conn = Math.max(conn, fade(t, r.a, r.a + .25, r.b, r.b + .35));
  wire.material.opacity = kL * lerp(.32, 1, conn); laneLight.intensity = kL * (1.5 + 14 * conn); wire.visible = kL > .002;
  wireGlow.material.opacity = .22 * kL * conn; wireGlow.visible = conn > .002;

  // core pulse when the request arrives
  const pulse = Math.exp(-Math.pow((t - D.request.t1) / .25, 2));
  core.material.emissiveIntensity = .55 + 1.1 * pulse + .4 * conn; core.scale.setScalar(1 + .18 * pulse);
  coreGlow.material.opacity = aop * (.25 + .55 * pulse + .25 * conn);

  // act 2: the request climbs the lane
  const rq = D.request;
  const kr = io(seg(t, rq.t0, rq.t1));
  const ry = lerp(LANE_BOT - .1, LANE_TOP + .05, kr);
  const rop = fade(t, rq.t0 - .3, rq.t0, rq.t1 - .12, rq.t1 + .05);
  packet.position.set(LANE_X, ry, .42); packet.rotation.set(0, -.15, 0); setOpacity(packet, rop);
  packetGlow.position.set(LANE_X, ry, .3); packetGlow.material.opacity = .5 * rop;

  // beads of both runs
  let n = 0;
  const all = D.run1.map((e) => ({ kind: e.kind, t0: e.t0, t1: e.t1, small: false })).concat(D.run2.beads, D.pulses);
  for (const b of all) {
    if (t < b.t0 - .05 || t > b.t1 + .2) continue;
    const g = bead(n++);
    const k = b.small ? seg(t, b.t0, b.t1) : io(seg(t, b.t0, b.t1));   // a dense stream runs at constant speed so its beads keep their spacing
    const y = lerp(LANE_TOP - .05, LANE_BOT + .08, k);
    const pop = .62 + .38 * outQ(seg(t, b.t0 - .05, b.t0 + .16));
    const land = b.small ? seg(t, b.t1 - .04, b.t1 + .06) : seg(t, b.t1 - .02, b.t1 + .18);
    const sc = (b.small ? .9 : 1.3) * pop * (1 - .4 * land);
    const u = seg(t, b.t0, b.t1), v = b.small ? 0 : (u < .5 ? 12 * u * u : 12 * (1 - u) * (1 - u)) / 3;   // speed of an eased bead, 0..1 of its peak
    g.visible = true; g.position.set(LANE_X, y, .02); g.scale.set(sc, sc * (1 + .22 * v), sc);   // a slight stretch along the lane at speed
    g.rotation.set(0, b.kind === 'tool' ? t * 2 : 0, 0);
    for (const kk of Object.keys(GEO)) { const m = g.userData.meshes[kk]; m.visible = kk === b.kind; m.material.opacity = 1 - land; }
    g.userData.gl.material.color.setHex(KIND[b.kind]); g.userData.gl.material.opacity = .55 * (1 - land) * (b.kind === 'text' ? .7 : 1);
  }
  for (let i = n; i < pool.length; i++) pool[i].visible = false;

  renderer.render(scene, camera);

  // ---------- labels ----------
  const [agx, agy] = px(agent, -2.75, .28, .55);
  const nop = aop * (1 - cl((Math.abs(ax) - .3) / .6));   // the face labels leave before the block does, so no label is ever cut by the frame edge
  place(agentName, agx, agy, nop);
  D.agent_subs.forEach((s, i) => place(agentSub[i], agx, agy + 42, nop * fade(t, s.a, s.a + .35, s.b - .3, s.b)));
  const [apx, apy] = px(app, -1.5, 1.38, .12);   // right of the lane, which enters the window at its top left
  place(appName, apx, apy, kP);
  // lane caption (act 1 only)
  const [lx, ly] = px(lane, .45, 0, 0);
  const lop = fade(t, 2.0, 2.5, A.request.a + .1, A.request.a + .45);
  place(laneTag, LANE_X < 0 ? 330 : lx, 330, lop); place(laneSub, 330, 384, lop);
  // the user's message, then the reply assembling chunk by chunk
  const [ux, uy] = px(app, 3.25, .62, .12);
  const uop = Math.max(fade(t, rq.t0 - .9, rq.t0 - .55, A.tools.a, A.tools.a + .35), outQ(seg(t, A.swap.a + .6, A.swap.a + 1.0)));   // back in act 5: the app is unchanged
  place(userB, ux, uy, uop, 1, 0);
  const bt = botText(t);
  botB.e.innerHTML = (bt.s ? bt.s.replace(/ /g, '&nbsp;') : '&nbsp;') + (bt.open ? '<span class="caret"></span>' : '');
  const [bx, by] = px(app, -3.25, -.15, .12);
  place(botB, bx, by, bt.any ? Math.min(uop, outQ(seg(t, D.run1.find((e) => e.name === 'TEXT_MESSAGE_START')?.t1 ?? 1e9, (D.run1.find((e) => e.name === 'TEXT_MESSAGE_START')?.t1 ?? 1e9) + .2))) : 0);
  // request label rides with the packet
  const [qx, qy] = px(scene, LANE_X + .8, ry, 0);
  const qop = rop * outQ(seg(kr, .3, .5)) * (1 - inC(seg(kr, .7, .84)));          // the label joins the packet once it has left the app window
  place(reqA, qx, qy, qop, 0, .5); place(reqB, qx, qy + 38, qop, 0, .5);
  // act 3: the wire log, one row per event, appearing as its bead leaves the agent
  const logOut = 1 - inC(seg(t, A.tools.a - .05, A.tools.a + .3));
  D.run1.forEach((e, i) => {
    const k = outQ(seg(t, e.t0 - .05, e.t0 + .3));
    const lit = e.t0 <= t && t < e.t1 + .1 ? 1 : .62;
    place(logRows[i], 330 + 14 * (1 - k), D.log_y0 + i * D.log_dy, k * logOut * lit);
    if (deltaTags[i]) {
      const kk = io(seg(t, e.t0, e.t1));
      const yy = lerp(LANE_TOP - .05, LANE_BOT + .08, kk);
      const [dx, dy] = px(scene, LANE_X - .32, yy, 0);
      place(deltaTags[i], dx, dy, outQ(seg(kk, .16, .3)) * (1 - inC(seg(kk, .76, .9))), 1, .5);   // shown while its bead is clear of both ends
    }
  });
  // act 4: tallies tick as beads land
  D.run2.tallies.forEach((r, i) => {
    const k = fade(t, A.tools.a + .2, A.tools.a + .6, A.tools.b - .4, A.tools.b - .05);
    place(tallyRows[i], 330, D.log_y0 + 20 + i * 58, k);
    const c = r.ticks.filter((x) => x <= t).length;
    tallyNums[i].e.textContent = r.total == null ? '' : String(c);
    place(tallyNums[i], 718, D.log_y0 + 20 + i * 58, r.total == null ? 0 : k);
  });
  place(tallySrc, 330, D.log_y0 + 20 + D.run2.tallies.length * 58 + 6, fade(t, A.tools.a + .4, A.tools.a + .8, A.tools.b - .4, A.tools.b - .05));
  const [tx, ty] = px(agent, 1.2, .3, .62);
  place(toolTag, tx, ty, aop * toolOn, .5, 1);
  // tool chip and its glow light while tool beads leave
  const toolHot = D.run2.beads.filter((b) => b.kind === 'tool').some((b) => t >= b.t0 - .1 && t <= b.t0 + .25) ? 1 : 0;
  tool.material.emissiveIntensity = .15 + .9 * toolHot;
  // shared state inside the app window: a STATE card whose two notes fill as snapshots land; the reply grows as text lands
  const sop = fade(t, A.tools.a + .3, A.tools.a + .7, A.swap.a + .2, A.swap.a + .6);
  const [sx, sy] = px(app, -3.25, .62, .12);
  // the app redraws its notes because a STATE_SNAPSHOT landed: the tag lights while snapshots arrive, and says which event it was
  const stB = D.run2.beads.filter((b) => b.kind === 'state');
  const hot = stB.length ? Math.max(...stB.map((b) => Math.exp(-Math.pow((t - b.t1 - .06) / .14, 2)))) : 0;
  const mix = (a, b) => a.map((x, i) => Math.round(x + (b[i] - x) * hot));
  stateTag.e.style.background = `rgb(${mix([255, 228, 234], [240, 68, 110]).join(',')})`; stateTag.e.style.color = hot > .5 ? '#FFFFFF' : '#101828';
  place(stateTag, sx, sy, sop);
  const [nx2, ny2] = px(app, -1.8, .62, .12);
  place(stateNote, nx2, ny2 + 2, stB.length ? sop * fade(t, stB[0].t1 - .1, stB[0].t1 + .15, stB[stB.length - 1].t1 + .5, stB[stB.length - 1].t1 + .8) : 0);
  const st = D.run2.beads.filter((b) => b.kind === 'state'), tx2 = D.run2.beads.filter((b) => b.kind === 'text');
  const fs = st.length ? st.filter((b) => b.t1 <= t).length / st.length : 0, ft = tx2.length ? tx2.filter((b) => b.t1 <= t).length / tx2.length : 0;
  const [b0x, b0y] = px(app, -3.25, .02, .12), [b2x, b2y] = px(app, -3.25, -.62, .12);
  const span = (px(app, 3.25, 0, .12)[0] - b0x);
  [[b0x, b0y, '#F0446E', Math.min(1, fs * 2) * .62], [b0x, b0y + 36, '#F0446E', Math.max(0, fs * 2 - 1) * .48], [b2x, b2y, '#98A2B3', ft * .9]].forEach(([x, y, col, wk], i) => {
    const e = bars[i]; e.style.background = col; e.style.width = `${Math.max(16, span * wk).toFixed(2)}px`;
    e.style.transform = `translate(${x}px, ${y}px)`; e.style.opacity = (sop * (wk > 0 ? 1 : .25)).toFixed(4);
  });
  // act 5: framework name on the agent, the app keeps its tag
  D.swap.forEach((s, i) => {
    const nx = i + 1 < D.swap.length ? D.swap[i + 1].a : A.swap.b + 1;
    place(fwNames[i], agx, agy + 42, nop * fade(t, s.a + .1, s.a + .45, nx - .32, nx - .15));
  });
  const [kx, ky] = px(app, -3.25, .62, .12);
  place(keepTag, kx, ky, outQ(seg(t, A.swap.a + .5, A.swap.a + 1.0)));
}

// What the producer measures each frame: every label it can see, with its box and type size.
function labels() {
  const out = [];
  for (const o of LB) {
    if (o.op < .02) continue;
    const r = o.e.getBoundingClientRect(), cs = getComputedStyle(o.e);
    let fsz = 1e9;                     // the size of every element that holds text itself
    for (const c of [o.e, ...o.e.querySelectorAll('*')]) { if ([...c.childNodes].some((x) => x.nodeType === 3 && x.textContent.trim())) fsz = Math.min(fsz, parseFloat(getComputedStyle(c).fontSize)); }
    out.push({ text: o.e.textContent, x: r.left, y: r.top, w: r.width, h: r.height, size: fsz, op: o.op });
  }
  return out;
}

const gl = renderer.getContext();
const dbg = gl.getExtension('WEBGL_debug_renderer_info');
window.sceneInfo = { renderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER), vendor: dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : '', three: THREE.REVISION };
window.renderAt = renderAt;
window.labels = labels;
await document.fonts.ready;
window.sceneFonts = ['600 32px BVP', '500 28px BVPM', '800 46px BarlowXB', '500 29px Mono'].map((f) => [f, document.fonts.check(f, 'Ấ')]);
window.sceneReady = true;
