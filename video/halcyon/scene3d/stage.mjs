import * as THREE from '/three.module.js';

export const W = 886, H = 976;
export const COLORS = { ink: 0x101828, coral: 0xff6589, cyan: 0x70e7ef, white: 0xf4f8ff, metal: 0x31435c, amber: 0xf2a24d, pink: 0xffc9d6 };
export function stage() {
  if (THREE.REVISION !== '187') throw new Error('The scene requires three@0.187.0');
  const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById('gl'), antialias: false, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
  // Supersample without MSAA, then resolve four fixed texel centres per output pixel.
  // The canvas is final-size so the browser does not choose a resampling filter.
  renderer.setPixelRatio(1); renderer.setSize(W, H, false); renderer.outputColorSpace = THREE.SRGBColorSpace;
  const target = new THREE.WebGLRenderTarget(W * 2, H * 2, {
    samples: 0, minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter,
    generateMipmaps: false, colorSpace: THREE.SRGBColorSpace,
  });
  const resolveScene = new THREE.Scene(), resolveCamera = new THREE.Camera();
  const resolveMaterial = new THREE.ShaderMaterial({
    depthTest: false, depthWrite: false, toneMapped: false,
    uniforms: { source: { value: target.texture }, sourceSize: { value: new THREE.Vector2(W * 2, H * 2) } },
    vertexShader: `void main() { gl_Position = vec4(position.xy, 0.0, 1.0); }`,
    fragmentShader: `
      uniform sampler2D source;
      uniform vec2 sourceSize;
      void main() {
        vec2 corner = floor(gl_FragCoord.xy) * 2.0 + 0.5;
        vec3 resolved = (texture2D(source, corner / sourceSize).rgb
          + texture2D(source, (corner + vec2(1.0, 0.0)) / sourceSize).rgb
          + texture2D(source, (corner + vec2(0.0, 1.0)) / sourceSize).rgb
          + texture2D(source, (corner + vec2(1.0, 1.0)) / sourceSize).rgb) * 0.25;
        gl_FragColor = vec4(resolved, 1.0);
        #include <colorspace_fragment>
      }`,
  });
  const resolveQuad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), resolveMaterial);
  resolveQuad.frustumCulled = false; resolveScene.add(resolveQuad);
  const scene = new THREE.Scene(); scene.background = new THREE.Color(COLORS.ink);
  scene.add(new THREE.HemisphereLight(0xd9eaff, 0x182039, 2));
  const key = new THREE.DirectionalLight(0xffffff, 3); key.position.set(-4, 8, 9); scene.add(key);
  const rim = new THREE.DirectionalLight(COLORS.cyan, 3); rim.position.set(5, 2, -8); scene.add(rim);
  function render(camera) {
    renderer.setRenderTarget(target); renderer.render(scene, camera);
    renderer.setRenderTarget(null); renderer.render(resolveScene, resolveCamera);
  }
  return { renderer, scene, render };
}
export function material(color, opacity = 1, emission = 0) {
  // Translucent geometry never writes depth, including at zero alpha.
  return new THREE.MeshStandardMaterial({ color, roughness: .26, metalness: .45,
    transparent: true, opacity, emissive: color, emissiveIntensity: emission, depthWrite: false });
}
export function box(parent, size, position, color, opacity = 1, emission = 0) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material(color, opacity, emission));
  mesh.position.set(...position); parent.add(mesh); return mesh;
}
// Screen-space capsules: triangle boundaries lie outside the visible alpha ramp.
// Widths are in final CSS pixels, independent of camera angle and clip duration.
// This also handles coincident endpoints (round trail beads).
export function strokes(parent, pairs, color, opacity = 1, width = 2, shaded = false) {
  const positions = [], ends = [], corners = [], widths = [], colors = [];
  const tint = new THREE.Color(color);
  for (let i = 0; i < pairs.length; i += 2) {
    for (const [u, v] of [[0, -1], [1, -1], [1, 1], [0, -1], [1, 1], [0, 1]]) {
      positions.push(...pairs[i]); ends.push(...pairs[i + 1]); corners.push(u, v);
      widths.push(Math.max(2, width)); colors.push(tint.r, tint.g, tint.b);
    }
  }
  const geometry = new THREE.BufferGeometry();
  for (const [name, values, size] of [['position', positions, 3], ['end', ends, 3], ['corner', corners, 2], ['strokeWidth', widths, 1], ['tint', colors, 3]]) {
    geometry.setAttribute(name, new THREE.Float32BufferAttribute(values, size));
  }
  const shader = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, depthTest: false, opacity,
    uniforms: { viewport: { value: new THREE.Vector2(W, H) }, alpha: { value: opacity }, shaded: { value: shaded ? 1 : 0 } },
    vertexShader: `
      attribute vec3 end;
      attribute vec2 corner;
      attribute float strokeWidth;
      attribute vec3 tint;
      uniform vec2 viewport;
      varying vec2 point;
      varying float span;
      varying float radius;
      varying vec3 shade;
      void main() {
        vec4 a = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        vec4 b = projectionMatrix * modelViewMatrix * vec4(end, 1.0);
        vec2 delta = (b.xy / b.w - a.xy / a.w) * viewport * 0.5;
        span = length(delta);
        vec2 along = span > 0.0001 ? delta / span : vec2(1.0, 0.0);
        radius = max(2.0, strokeWidth) * 0.5;
        float extent = radius + 1.5;
        point = vec2(mix(-extent, span + extent, corner.x), corner.y * extent);
        vec2 offset = along * (2.0 * corner.x - 1.0) * extent
                    + vec2(-along.y, along.x) * point.y;
        gl_Position = mix(a, b, corner.x);
        gl_Position.xy += offset * 2.0 / viewport * gl_Position.w;
        shade = tint;
      }`,
    fragmentShader: `
      uniform float alpha;
      uniform float shaded;
      varying vec2 point;
      varying float span;
      varying float radius;
      varying vec3 shade;
      void main() {
        vec2 local = vec2(point.x - clamp(point.x, 0.0, span), point.y);
        float distanceToAxis = length(local);
        // A half-pixel transition preserves a crisp core at the 2x sample rate.
        float coverage = 1.0 - smoothstep(radius - 0.25, radius + 0.25, distanceToAxis);
        // Broad diffuse shading retains the round trail bead form without a specular hot pixel.
        float diffuse = 0.82 + 0.18 * clamp(0.5 + local.y / (2.0 * radius), 0.0, 1.0);
        gl_FragColor = vec4(shade * mix(1.0, diffuse, shaded), alpha * coverage);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
  const mesh = new THREE.Mesh(geometry, shader);
  // The projected expansion is outside the centreline's world-space bounds.
  mesh.frustumCulled = false;
  mesh.onBeforeRender = () => { shader.uniforms.alpha.value = shader.opacity; shader.uniformsNeedUpdate = true; };
  parent.add(mesh); return mesh;
}
export function line(parent, points, color, opacity = 1, width = 2) {
  return strokes(parent, points.slice(1).flatMap((point, i) => [points[i], point]), color, opacity, width);
}
export function edges(mesh, color, opacity = .6) {
  const segments = new THREE.EdgesGeometry(mesh.geometry), ends = segments.getAttribute('position');
  const pairs = Array.from({ length: ends.count }, (_, i) => [ends.getX(i), ends.getY(i), ends.getZ(i)]);
  segments.dispose();
  return strokes(mesh, pairs, color, opacity);
}
export function dots(parent, points, color, width = 8, opacity = 1) {
  return strokes(parent, points.flatMap((point) => [point, point]), color, opacity, width, true);
}
export function nodeSpheres(parent, count, color) {
  const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 20, 16),
    new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: .26, metalness: .45,
      emissive: color, emissiveIntensity: .12 }), count);
  // Matrices and colors are assigned from the current frame before every draw.
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  // Animated instance sizes must not reuse bounds computed during an earlier seek.
  mesh.frustumCulled = false;
  parent.add(mesh); return mesh;
}
let glowMap;
export function glow(parent, color, size) {
  if (!glowMap) {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 64;
    const ctx = canvas.getContext('2d'), gradient = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    // A broad, low-slope centre avoids concentrating brightness into a hot pixel.
    gradient.addColorStop(0, '#ffffffb0'); gradient.addColorStop(.35, '#ffffff70'); gradient.addColorStop(.7, '#ffffff20'); gradient.addColorStop(1, '#ffffff00');
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
// tie break, independent of geometry bounds and the previous sampled frame.
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
