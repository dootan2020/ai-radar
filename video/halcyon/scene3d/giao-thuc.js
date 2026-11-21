import * as THREE from '/three.module.js';
import { createTimeline, ease, mix, progress, flightHeight } from './timeline.mjs';
import { stage, material, box, line, strokes, dots, nodeSpheres, edges, glow, project, labels, orderedTransparency, ready, H, COLORS as C } from './stage.mjs';

const D = await (await fetch('/data.json')).json();
const timeline = createTimeline(D);
const KIND = { life: C.cyan, text: C.white, state: C.pink, tool: C.amber };
const { renderer, scene, render } = stage();
const camera = new THREE.OrthographicCamera(-6.65, 4.55, 6.17, -6.17, .1, 80);
const assembly = new THREE.Group(); assembly.position.y = 1.25; scene.add(assembly);
const layerY = [2.5, 0, -2.5];
const layerColors = [C.coral, C.cyan, C.white];
const layers = [], tiles = [];
const color = new THREE.Color();
const nodeMatrix = new THREE.Matrix4(), nodePosition = new THREE.Vector3(), nodeScale = new THREE.Vector3(), nodeRotation = new THREE.Quaternion();
layerY.forEach((y, index) => {
  const group = new THREE.Group(); group.position.y = y; assembly.add(group);
  const pane = box(group, [6.4, .065, 4], [0, 0, 0], index === 1 ? 0x467788 : 0x526481, .18, .12);
  edges(pane, layerColors[index], .68);
  const inset = box(group, [6.05, .025, 3.65], [0, .05, 0], 0x152b44, .15, .1); edges(inset, layerColors[index], .25);
  // Machined corner brackets, stand-offs, and a luminous cut edge.
  for (const x of [-3.18, 3.18]) for (const z of [-1.98, 1.98]) {
    box(group, [.62, .09, .09], [x - Math.sign(x) * .24, .03, z], C.white, .8, .1);
    box(group, [.09, .09, .48], [x, .03, z - Math.sign(z) * .18], C.white, .8, .1);
    const collar = new THREE.Mesh(new THREE.CylinderGeometry(.11, .11, .15, 10), material(C.metal)); collar.position.set(x, .02, z); group.add(collar);
  }
  line(group, [[-2.85, .07, 2.02], [2.85, .07, 2.02]], layerColors[index], 1, 2);
  const links = [], nodes = [];
  for (let ix = 0; ix < 9; ix++) for (let iz = 0; iz < 6; iz++) {
    const x = (ix - 4) * .66, z = (iz - 2.5) * .59;
    nodes.push([x, .11, z]);
    if (ix < 8) links.push([x, .1, z], [x + .66, .1, z]);
    if (iz < 5) links.push([x, .1, z], [x, .1, z + .59]);
    if ((ix + iz) % 4 === 0 && ix < 8 && iz < 5) links.push([x, .1, z], [x + .66, .1, z + .59]);
  }
  const lattice = strokes(group, links, layerColors[index], index === 1 ? .3 : .15);
  const nodeMesh = nodeSpheres(group, nodes.length, layerColors[index]);
  const halo = glow(group, layerColors[index], 5); halo.position.y = .12; halo.material.opacity = .12;
  const scan = line(group, [[0, .12, -1.6], [0, .12, 1.6]], layerColors[index], .35);
  layers.push({ group, pane, nodes, nodeMesh, lattice, halo, scan });
});
// Engineering registration guides align the three exploded plates.
for (const x of [-3.18, 3.18]) for (const z of [-1.98, 1.98]) {
  for (let j = 0; j < 25; j++) {
    const y = -3 + j * .25;
    line(assembly, [[x, y, z], [x, y + .10, z]], 0xa4bfd2, .24);
  }
}
// The framework consists of replaceable tiles, above the protocol's continuous lattice.
for (let x = 0; x < 4; x++) for (let z = 0; z < 3; z++) {
  const tile = new THREE.Group(); tile.position.set((x - 1.5) * 1.35, 2.84, (z - 1) * 1.04); assembly.add(tile);
  const body = box(tile, [1.08, .13, .76], [0, 0, 0], 0x5c324b, .88, .18); edges(body, C.coral, .8);
  for (let k = 0; k < 4; k++) line(tile, [[-.39 + k * .22, .1, .17], [-.27 + k * .22, .1, .17]], C.coral, .9, 3);
  line(tile, [[-.335, .1, -.15], [.335, .1, -.15]], C.white, .65);
  tiles.push({ tile, body, index: x * 3 + z });
}
const socket = new THREE.Mesh(new THREE.TorusGeometry(.32, .055, 8, 48), material(C.cyan, 1, .8)); socket.rotation.x = Math.PI / 2; socket.position.set(1.1, .14, .5); assembly.add(socket);
const socketHalo = glow(assembly, C.cyan, 2); socketHalo.position.copy(socket.position); socketHalo.material.opacity = .45;
const lane = line(assembly, [[1.1, 2.7, .5], [1.1, -2.4, .5]], C.cyan, .2);
const request = new THREE.Mesh(new THREE.OctahedronGeometry(.18), material(C.coral, 1, .9)); assembly.add(request);
request.material.depthWrite = false;
const requestGlow = glow(request, C.coral, 1.25);
const packets = timeline.events.map((event) => {
  const group = new THREE.Group(); assembly.add(group);
  const core = new THREE.Mesh(event.kind === 'text' ? new THREE.CapsuleGeometry(.10, .19, 4, 8) : event.kind === 'tool' ? new THREE.OctahedronGeometry(.18) : event.kind === 'state' ? new THREE.BoxGeometry(.20, .20, .20) : new THREE.IcosahedronGeometry(.15, 1), material(KIND[event.kind], 1, .9)); group.add(core);
  core.material.depthWrite = false;
  const halo = glow(group, KIND[event.kind], 1.1);
  const tail = Array.from({ length: event.small ? 0 : 8 }, (_, i) => {
    return dots(assembly, [[0, 0, 0]], KIND[event.kind], 7.6 - i * .3, .8);
  });
  return { group, core, halo, tail, event };
});
// The app's three physical lines illuminate only after the corresponding delta arrives.
const replyBars = Array.from({ length: 3 }, (_, i) => box(assembly, [1, .055, .19], [-1.7, -2.31, .72 - i * .46], C.white, 0, .7));

const ui = labels();
const heads = D.acts.map((act) => { const label = ui.make('', 'head'); label.element.innerHTML = act.head; return label; });
const agentLabel = ui.make('TRỢ LÝ AI', 'name');
const agentSub = ui.make('', 'mono backing');
const protocolLabel = ui.make('AG-UI', 'protocol');
const protocolSub = ui.make('Giao thức chung', 'small');
const appLabel = ui.make('ỨNG DỤNG', 'name');
const strip = ui.make('', 'mono event');
const detail = ui.make('', 'small');
const tallyLabels = D.run2.tallies.map((row) => ui.make(row.label, 'mono event'));
const tallyValues = D.run2.tallies.map(() => ui.make('', 'mono total'));
const appTitle = ui.make('ỨNG DỤNG', 'name dark');
const appStatus = ui.make('', 'small dark');
const userMessage = ui.make(D.request.user_text, 'reply');
const replyChunks = D.run1.filter((event) => event.delta != null).map((event) => ui.make(event.delta, 'reply'));
const stateTag = ui.make('STATE', 'mono state');
const stateNote = ui.make('← STATE_SNAPSHOT', 'mono dark');
const toolTag = ui.make('công cụ', 'small tool');
const bars = Array.from({ length: 3 }, () => {
  const element = document.createElement('div'); element.className = 'state-bar'; document.getElementById('ui').appendChild(element); return element;
});
const cursor = document.getElementById('cursor');
const leaders = layerY.map((_, index) => {
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('fill', 'none'); path.setAttribute('stroke', index === 1 ? '#70e7ef' : '#9eafc6');
  path.setAttribute('stroke-width', '1.5'); document.getElementById('leaders').appendChild(path); return path;
});

function packetPosition(object, p, requestUp = false) {
  const y = flightHeight(p);
  object.position.set(requestUp ? -1.25 : 1.1 + Math.sin(p * Math.PI * 2) * .16, y, requestUp ? .6 : .5);
}

function renderAt(value) {
  const s = timeline.sample(value), t = s.t;
  const drift = ease(t, 0, D.base);
  camera.position.set(mix(8.7, 9.5, drift), 8.6, mix(12.5, 12, drift));
  camera.lookAt(0, 0, 0); camera.updateMatrixWorld();
  packetPosition(request, 1 - s.request.progress, true);
  request.rotation.set(t * .8, t, .4); request.visible = s.request.opacity > 0;
  request.material.opacity = s.request.opacity; requestGlow.material.opacity = s.request.opacity * .6;
  packets.forEach(({ group, core, halo, tail, event }, i) => {
    const f = s.flights[i];
    packetPosition(group, f.progress); group.visible = f.opacity > 0;
    group.scale.setScalar(event.small ? .75 : 1.15);
    core.rotation.set(t * .7, i + t, .3); core.material.opacity = f.opacity; halo.material.opacity = f.opacity * .7;
    tail.forEach((bead, j) => {
      packetPosition(bead, progress(t - j * .012, event.t0, event.t1));
      bead.material.opacity = f.opacity * (1 - j / tail.length) * .6; bead.visible = f.opacity > 0;
    });
  });
  layers.forEach(({ nodes, nodeMesh, lattice, halo, scan }, index) => {
    const activity = timeline.activity(t, index);
    nodes.forEach(([x, y, z], j) => {
      const wave = timeline.activity(t, index, Math.hypot(x - 1.1, z - .5), Math.hypot(x + 1.25, z - .6));
      // Keep a visible, lit sphere even at rest; the arrival wave adds size and light.
      color.setHex(layerColors[index]).multiplyScalar(.55 + .45 * wave);
      const radius = 8 * (1 + wave * .7) * (camera.top - camera.bottom) / (2 * H * camera.zoom);
      nodePosition.set(x, y, z); nodeScale.setScalar(radius);
      nodeMatrix.compose(nodePosition, nodeRotation, nodeScale);
      nodeMesh.setMatrixAt(j, nodeMatrix); nodeMesh.setColorAt(j, color);
    });
    nodeMesh.instanceMatrix.needsUpdate = true; nodeMesh.instanceColor.needsUpdate = true;
    lattice.material.opacity = (index === 1 ? .30 : .15) + activity * .16;
    halo.material.opacity = (index === 1 ? .17 : .06) + activity * .22;
    scan.position.x = 2.8 * Math.sin(t * .22 + index * .8); scan.material.opacity = index === 1 ? .5 : .18;
  });
  tiles.forEach(({ tile, body, index }) => {
    tile.rotation.x = s.tiles[index];
    body.material.color.setHex(0x5c324b).lerp(color.setHex(0x2a6876), ease(t, D.swap[1].a, D.swap.at(-1).a + .5));
    body.material.emissiveIntensity = .18 + .35 * s.toolHot;
  });
  replyBars.forEach((bar, i) => {
    const u = s.tools > 0 ? (i === 2 ? s.textFraction : Math.min(1, Math.max(0, s.state.fraction * 2 - i))) : s.received[i];
    bar.scale.x = .01 + u * (1.1 + i * .18); bar.position.x = -2.3 + bar.scale.x / 2; bar.material.opacity = u * .9;
    bar.material.color.setHex(s.tools > 0 && i < 2 ? C.pink : C.white);
  });
  socketHalo.material.opacity = .35 + .35 * timeline.activity(t, 1);
  lane.material.opacity = .2 + .12 * s.connection;

  // Publish current matrices before both projecting callouts and sorting glass.
  scene.updateMatrixWorld(true); orderedTransparency(scene, camera);
  D.acts.forEach((act, index) => {
    const alpha = act.name === s.act ? ease(t, act.a, act.a + .3) : 0;
    ui.place(heads[index], 48, 30, alpha, 6 * (1 - alpha));
  });
  ui.place(agentLabel, 48, 142);
  agentSub.element.textContent = s.act === 'swap' ? D.swap[s.framework].name : D.agent_subs[s.act === 'tools' ? 1 : 0].text;
  ui.place(agentSub, 48, 190);
  ui.place(protocolLabel, 48, 390); ui.place(protocolSub, 48, 444);
  ui.place(appLabel, 48, 558);
  ui.place(toolTag, 48, 600, s.tools * (.65 + .35 * s.toolHot));

  let stripText = 'app ↔ trợ lý AI', detailText = 'Ba lớp, một chuẩn kết nối';
  if (s.act === 'request') { stripText = `${D.request.method} · ${D.request.type}`; detailText = D.request.carries; }
  if (s.act === 'stream') {
    const event = D.run1[s.currentEvent];
    stripText = event?.name ?? 'HTTP · SSE';
    detailText = event?.delta != null ? `“${event.delta}”` : 'Từng sự kiện → ứng dụng';
  }
  if (s.act === 'tools') { stripText = D.run2.source_line; detailText = 'Gom theo loại · thứ tự xuất hiện đầu'; }
  if (s.act === 'swap') { stripText = 'cùng giao thức ✓'; detailText = 'Tools và state vẫn phải khớp với app'; }
  strip.element.textContent = stripText; detail.element.textContent = detailText;
  ui.place(strip, 48, 636); ui.place(detail, 48, 686);
  D.run2.tallies.forEach((row, index) => {
    const shade = `#${KIND[row.kind].toString(16).padStart(6, '0')}`;
    tallyLabels[index].element.style.borderColor = shade;
    ui.place(tallyLabels[index], 48, 240 + index * 44, s.tools);
    tallyValues[index].element.textContent = s.tallies[index] == null ? '' : String(s.tallies[index]);
    ui.place(tallyValues[index], 430, 240 + index * 44, s.tools);
  });

  ui.place(appTitle, 72, 740);
  appStatus.element.textContent = s.tools > .5 ? 'Đang cập nhật' : s.status;
  ui.place(appStatus, 420, 744);
  const replyOpacity = Math.max(0, 1 - 2 * s.tools), stateOpacity = Math.max(0, 2 * s.tools - 1);
  ui.place(userMessage, 72, 804, ['Sẵn sàng', 'Đang chạy'].includes(s.status) ? replyOpacity : 0);
  let chunkX = 72, receivedWidth = 0;
  replyChunks.forEach((label, index) => {
    const alpha = s.received[index], width = label.element.getBoundingClientRect().width;
    ui.place(label, chunkX, 804, alpha * replyOpacity, 8 * (1 - alpha));
    chunkX += width; receivedWidth += width * alpha;
  });
  ui.place(stateTag, 72, 798, stateOpacity);
  stateTag.element.style.background = `#${color.setHex(C.pink).lerp(new THREE.Color(0xf0446e), s.state.hot).getHexString()}`;
  stateTag.element.style.color = `#${color.setHex(C.ink).lerp(new THREE.Color(C.white), s.state.hot).getHexString()}`;
  ui.place(stateNote, 204, 802, stateOpacity * (s.state.note ? 1 : 0));
  const widths = [Math.min(1, s.state.fraction * 2) * 360, Math.max(0, s.state.fraction * 2 - 1) * 280, s.textFraction * 144];
  bars.forEach((bar, i) => {
    bar.style.transform = `translate(${i === 2 ? 572 : 72}px,${i === 1 ? 868 : 848}px)`;
    bar.style.width = `${Math.max(2, widths[i])}px`; bar.style.opacity = String(s.tools * (widths[i] > 0 ? 1 : .15));
  });
  cursor.style.transform = `translate(${76 + receivedWidth}px,810px)`;
  cursor.style.opacity = String(s.open ? 1 - s.tools : 0);
  document.getElementById('status-light').style.opacity = String(.3 + .7 * (s.tools > 0 ? s.state.hot : s.connection));
  leaders.forEach((path, index) => {
    const anchor = new THREE.Vector3(-3.18, layerY[index], 1.98); assembly.localToWorld(anchor);
    const [x, y] = project(camera, anchor), row = [166, 416, 582][index];
    path.setAttribute('d', `M ${index === 1 ? 176 : 238} ${row} H 260 L ${x.toFixed(3)} ${y.toFixed(3)} l 7 -3 m -7 3 l 7 3`);
  });
  render(camera);
}

await ready(renderer, renderAt, ui.measure, D.duration);
