import * as THREE from '/three.module.js';

export const W = 886, H = 976;
export const COLORS = { ink: 0x101828, coral: 0xff6589, cyan: 0x70e7ef, white: 0xf4f8ff, metal: 0x31435c, amber: 0xf2a24d, pink: 0xffc9d6 };
export function stage() {
  if (THREE.REVISION !== '187') throw new Error('The scene requires three@0.187.0');
  const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById('gl'), antialias: true, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(2); renderer.setSize(W, H, false); renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene(); scene.background = new THREE.Color(COLORS.ink);
  scene.add(new THREE.HemisphereLight(0xd9eaff, 0x182039, 2));
  const key = new THREE.DirectionalLight(0xffffff, 3); key.position.set(-4, 8, 9); scene.add(key);
  const rim = new THREE.DirectionalLight(COLORS.cyan, 3); rim.position.set(5, 2, -8); scene.add(rim);
  return { renderer, scene };
}
export function material(color, opacity = 1, emission = 0) {
  // Translucent geometry never writes depth, including at zero alpha. Solid nodes
  // use a separate opaque material so their depth does not depend on blend order.
  return new THREE.MeshStandardMaterial({ color, roughness: .26, metalness: .45,
    transparent: true, opacity, emissive: color, emissiveIntensity: emission, depthWrite: false });
}
export function box(parent, size, position, color, opacity = 1, emission = 0) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material(color, opacity, emission));
  mesh.position.set(...position); parent.add(mesh); return mesh;
}
export function line(parent, points, color, opacity = 1) {
  const geometry = new THREE.BufferGeometry().setFromPoints(points.map((p) => new THREE.Vector3(...p)));
  const mesh = new THREE.Line(geometry, new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthWrite: false })); parent.add(mesh); return mesh;
}
export function edges(mesh, color, opacity = .6) {
  // Thin triangle tubes keep glass outlines on the same rasterization path as
  // the plates. Reverse-seek PNG outliers follow the native GL lower outline
  // across a corner bracket; avoid that subpixel line-coverage path.
  // Merge the strokes so each outline still takes one draw call.
  const segments = new THREE.EdgesGeometry(mesh.geometry);
  const ends = segments.getAttribute('position');
  const cylinder = new THREE.CylinderGeometry(.005, .005, 1, 6, 1, true);
  const profile = cylinder.toNonIndexed(), vertices = profile.getAttribute('position');
  const positions = [], a = new THREE.Vector3(), b = new THREE.Vector3();
  const direction = new THREE.Vector3(), middle = new THREE.Vector3(), point = new THREE.Vector3();
  const rotation = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
  for (let i = 0; i < ends.count; i += 2) {
    a.fromBufferAttribute(ends, i); b.fromBufferAttribute(ends, i + 1);
    direction.subVectors(b, a); const length = direction.length();
    rotation.setFromUnitVectors(up, direction.normalize()); middle.addVectors(a, b).multiplyScalar(.5);
    for (let j = 0; j < vertices.count; j++) {
      point.fromBufferAttribute(vertices, j); point.y *= length;
      point.applyQuaternion(rotation).add(middle); positions.push(point.x, point.y, point.z);
    }
  }
  segments.dispose(); cylinder.dispose(); profile.dispose();
  const geometry = new THREE.BufferGeometry(); geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  const wire = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false }));
  mesh.add(wire); return wire;
}
let glowMap;
export function glow(parent, color, size) {
  if (!glowMap) {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 64;
    const ctx = canvas.getContext('2d'), gradient = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    gradient.addColorStop(0, '#fff'); gradient.addColorStop(.2, '#ffffff88'); gradient.addColorStop(1, '#ffffff00');
    ctx.fillStyle = gradient; ctx.fillRect(0, 0, 64, 64); glowMap = new THREE.CanvasTexture(canvas);
  }
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowMap, color, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
  sprite.scale.set(size, size, 1); parent.add(sprite); return sprite;
}
export function project(camera, point) {
  const v = point.clone().project(camera); return [(v.x + 1) * W / 2, (1 - v.y) * H / 2];
}
export function labels() {
  const list = [], ui = document.getElementById('ui');
  function make(text, cls = 'name') {
    const element = document.createElement('div'); element.className = `lb ${cls}`; element.textContent = text; ui.appendChild(element);
    const label = { element, opacity: 0 }; list.push(label); return label;
  }
  function place(label, x, y, opacity = 1, dy = 0) {
    label.opacity = opacity; label.element.style.opacity = String(opacity);
    label.element.style.transform = `translate(${x}px,${y + dy}px)`;
  }
  function measure() {
    return list.filter((item) => item.opacity >= .02).map(({ element, opacity }) => {
      const r = element.getBoundingClientRect();
      let size = Infinity;
      for (const child of [element, ...element.querySelectorAll('*')]) {
        if ([...child.childNodes].some((node) => node.nodeType === 3 && node.textContent.trim())) size = Math.min(size, parseFloat(getComputedStyle(child).fontSize));
      }
      return { text: element.textContent, x: r.x, y: r.y, w: r.width, h: r.height, size, op: opacity };
    });
  }
  return { make, place, measure };
}

// Fix a painter's order from current world-space centres, with a creation-order
// tie break. Do not let a stale InstancedMesh bounding sphere choose blend order.
export function orderedTransparency(scene, camera) {
  const origin = new THREE.Vector3(), items = [];
  scene.traverse((object) => {
    if (object.material?.transparent) {
      origin.setFromMatrixPosition(object.matrixWorld).applyMatrix4(camera.matrixWorldInverse);
      items.push({ object, z: origin.z, index: items.length });
    }
  });
  items.sort((a, b) => a.z - b.z || a.index - b.index);
  items.forEach(({ object }, index) => { object.renderOrder = index + 1; });
}

export async function ready(renderer, renderAt, measure, duration) {
  const fonts = ['600 32px BVP', '500 28px BVPM', '800 46px BarlowXB', '500 28px Mono'];
  await Promise.all(fonts.map((font) => document.fonts.load(font, 'Ấ AG-UI')));
  await document.fonts.ready;
  const gl = renderer.getContext(), debug = gl.getExtension('WEBGL_debug_renderer_info');
  window.sceneInfo = { renderer: gl.getParameter(debug ? debug.UNMASKED_RENDERER_WEBGL : gl.RENDERER), vendor: debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : '', three: THREE.REVISION, duration };
  window.sceneFonts = fonts.map((font) => [font, document.fonts.check(font, 'Ấ')]);
  document.getElementById('fallback').hidden = true;
  window.renderAt = renderAt; window.labels = measure; renderAt(0); window.sceneReady = true;
}
