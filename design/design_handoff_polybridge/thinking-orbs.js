// Plain-JS port of Jakubantalik/thinking-orbs (MIT) — dotted 3D thought-orbs on a 2D canvas.
// <thinking-orb state="connecting" size="64" theme="light" ink="#141A2B" speed="1"></thinking-orb>
(function () {
  const lerp = (a, b, f) => a + (b - a) * f, frac = x => x - Math.floor(x);
  const hashD = (a, b) => { const h = Math.sin(a * 12.9898 + b * 78.233) * 43758.5453; return h - Math.floor(h); };
  function vnoise(x, y) {
    const xi = Math.floor(x), yi = Math.floor(y); let fx = x - xi, fy = y - yi;
    fx = fx * fx * (3 - 2 * fx); fy = fy * fy * (3 - 2 * fy);
    const a = hashD(xi, yi), b = hashD(xi + 1, yi), c = hashD(xi, yi + 1), d = hashD(xi + 1, yi + 1);
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
  }
  function fibDir(i, n) { const g = Math.PI * (3 - Math.sqrt(5)); const y = 1 - (2 * (i + .5)) / n; const r = Math.sqrt(1 - y * y); const a = i * g; return [r * Math.cos(a), y, r * Math.sin(a)]; }
  const angleDelta = (a, b) => Math.atan2(Math.sin(a - b), Math.cos(a - b));
  function makeProj(yaw, tilt, cx, cy, s) {
    const st = Math.sin(tilt), ct = Math.cos(tilt), sy = Math.sin(yaw), cw = Math.cos(yaw);
    return (x, y, z) => { const x1 = x * cw + z * sy, z1 = -x * sy + z * cw, y1 = y * ct - z1 * st, z2 = y * st + z1 * ct; return [cx + x1 * s, cy - y1 * s, z2]; };
  }
  const radiusScale = (size, pow) => Math.pow(size / 300, pow);
  function finalizeFrame(dots, lines, rMin) {
    rMin = rMin == null ? .3 : rMin; const v = [];
    for (const d of dots) { if ((d.a == null ? 1 : d.a) < .02) continue; d.r = Math.max(rMin, d.r); v.push(d); }
    v.sort((a, b) => a.z - b.z);
    return { dots: v, lines: lines.filter(l => (l.a == null ? 1 : l.a) >= .02) };
  }

  const frameGlobe = (size, t, o) => {
    const spin = .5, cx = size / 2, cy = size / 2, radius = (size / 2) * .82, tilt = .4 + .06 * Math.sin(t * .35);
    const pt = makeProj(t * spin, tilt, cx, cy, radius);
    const scan = t * (spin + (1.7 - spin) * (o.scanMul ?? 1)), rs = radiusScale(size, o.rsPow ?? .6), dimBase = o.dimBase ?? 1;
    const dots = [], latRings = o.latRings ?? 17, lonDensity = o.lonDensity ?? 44;
    for (let li = 0; li <= latRings; li++) {
      const lat = -Math.PI / 2 + (li / latRings) * Math.PI, cl = Math.cos(lat), sl = Math.sin(lat);
      const lonCount = Math.max(1, Math.round(Math.abs(cl) * lonDensity));
      for (let lj = 0; lj < lonCount; lj++) {
        const lon = (lj / lonCount) * 2 * Math.PI; const [px, py, z] = pt(cl * Math.cos(lon), sl, cl * Math.sin(lon));
        const depth = (z + 1) / 2, d = angleDelta(lon + t * spin, scan), boost = Math.exp(-(d * d) / .18) * Math.max(0, z);
        dots.push({ x: px, y: py, z, r: ((o.rBase ?? .6) + (o.rDepth ?? 1.7) * depth + (o.rBoost ?? 1) * boost) * rs, white: (o.inkFar ?? .62) - (o.inkSpan ?? .54) * depth, a: dimBase + (1 - dimBase) * Math.min(1, boost) });
      }
    }
    return finalizeFrame(dots, [], o.rMin);
  };
  const frameWave = (size, t, o) => {
    const cx = size / 2, cy = size / 2, R = (size / 2) * .874, pt = makeProj(t * .18, .38, cx, cy, 1), rs = radiusScale(size, o.rsPow ?? .6);
    const dots = [], rings = o.rings ?? 15, lonDensity = o.lonDensity ?? 40;
    for (let ri = 0; ri <= rings; ri++) {
      const lat = -Math.PI / 2 + (ri / rings) * Math.PI, cl = Math.cos(lat), sl = Math.sin(lat);
      const w = .62 * Math.sin(t * 2.1 - ri * .52) + .38 * Math.sin(t * 1.27 + ri * .83), rr = R * (.88 + .105 * w);
      const lonCount = Math.max(1, Math.round(Math.abs(cl) * lonDensity));
      for (let lj = 0; lj < lonCount; lj++) {
        const lon = (lj / lonCount) * 2 * Math.PI; const [px, py, z] = pt(cl * Math.cos(lon) * rr, sl * rr, cl * Math.sin(lon) * rr);
        const depth = (z / R + 1) / 2, crest = Math.max(0, w);
        dots.push({ x: px, y: py, z, r: ((o.rBase ?? .6) + (o.rDepth ?? 1.7) * depth) * (1 + .4 * crest) * rs, white: .66 - .56 * depth - .1 * crest });
      }
    }
    return finalizeFrame(dots, [], o.rMin);
  };
  const frameWeb = (size, t, o) => {
    const cx = size / 2, cy = size / 2, R = (size / 2) * .8 * (o.spread ?? 1), pt = makeProj(t * .12, .32, cx, cy, R), rs = radiusScale(size, o.rsPow ?? .6);
    const nodeN = o.nodeN ?? 30, thr = o.thr ?? .72, nodeR = o.nodeR ?? 1.4, nodeRDepth = o.nodeRDepth ?? 1.8;
    const nodes = [];
    for (let i = 0; i < nodeN; i++) {
      const d = fibDir(i, nodeN);
      const x = d[0] + .3 * (vnoise(i * .31 + 9, t * .24) - .5) * 2, y = d[1] + .3 * (vnoise(i * .53 + 27, t * .21) - .5) * 2, z = d[2] + .3 * (vnoise(i * .77 + 55, t * .27) - .5) * 2;
      const l = Math.sqrt(x * x + y * y + z * z); nodes.push([x / l, y / l, z / l]);
    }
    const lines = [], dots = [];
    for (let i = 0; i < nodeN; i++) for (let j = i + 1; j < nodeN; j++) {
      const dx = nodes[i][0] - nodes[j][0], dy = nodes[i][1] - nodes[j][1], dz = nodes[i][2] - nodes[j][2], dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
      if (dist >= thr) continue;
      const [x1, y1, z1] = pt(...nodes[i]), [x2, y2, z2] = pt(...nodes[j]), depth = ((z1 + z2) / 2 + 1) / 2;
      lines.push({ x1, y1, x2, y2, white: .42, a: (1 - dist / thr) * (.3 + .55 * depth), w: Math.max(.6, (o.lineW ?? .8) * rs) });
    }
    for (let i = 0; i < nodeN; i++) {
      const [px, py, z] = pt(...nodes[i]), depth = (z + 1) / 2, pulse = 1 + .25 * Math.sin(t * 1.4 + i * 2.7);
      dots.push({ x: px, y: py, z, r: (nodeR + nodeRDepth * depth) * pulse * rs, white: .55 - .45 * depth });
    }
    const signals = o.signals ?? 5;
    for (let s = 0; s < signals; s++) {
      const seg = Math.floor(t * .55 + s * 7.31), a = Math.floor(hashD(seg, s * 3.1 + 1.7) * nodeN), b = Math.floor(hashD(seg, s * 5.7 + 4.2) * nodeN);
      if (a === b) continue;
      const f = frac(t * .55 + s * 7.31), x = lerp(nodes[a][0], nodes[b][0], f), y = lerp(nodes[a][1], nodes[b][1], f), z = lerp(nodes[a][2], nodes[b][2], f);
      const l = Math.max(1e-6, Math.sqrt(x * x + y * y + z * z)); const [px, py, zr] = pt(x / l, y / l, z / l), depth = (zr + 1) / 2;
      dots.push({ x: px, y: py, z: zr, r: (nodeR * 1.5 + nodeRDepth * depth) * rs, white: .05, a: .5 + .5 * depth });
    }
    return finalizeFrame(dots, lines, o.rMin);
  };
  const frameOrbits = (size, t, o) => {
    const cx = size / 2, cy = size / 2, R = (size / 2) * .82, pt = makeProj(t * .12, .3, cx, cy, 1), rs = radiusScale(size, o.rsPow ?? .6);
    const dots = [], orbitN = o.orbitN ?? 12, ghostN = o.ghostN ?? 40, particles = o.particles ?? 3;
    for (let orb = 0; orb < orbitN; orb++) {
      const h1 = hashD(orb, 1.7), h2 = hashD(orb, 5.2), h3 = hashD(orb, 8.9), ro = R * (.45 + .52 * h1), th = h1 * 2 * Math.PI, phi = Math.acos(2 * h2 - 1);
      const nx = Math.sin(phi) * Math.cos(th), ny = Math.cos(phi), nz = Math.sin(phi) * Math.sin(th);
      let ux = -ny, uy = nx; const uz = 0, ul = Math.max(1e-6, Math.sqrt(ux * ux + uy * uy)); ux /= ul; uy /= ul;
      const vx = ny * uz - nz * uy, vy = nz * ux - nx * uz, vz = nx * uy - ny * ux, speed = (.25 + .55 * h3) * (h3 > .5 ? 1 : -1);
      for (let k = 0; k < ghostN; k++) {
        const a = (k / ghostN) * 2 * Math.PI; const [px, py, z] = pt((ux * Math.cos(a) + vx * Math.sin(a)) * ro, (uy * Math.cos(a) + vy * Math.sin(a)) * ro, (uz * Math.cos(a) + vz * Math.sin(a)) * ro);
        const depth = (z / ro + 1) / 2; dots.push({ x: px, y: py, z, r: (o.ghostR ?? .9) * rs, white: .72, a: (o.ghostA ?? .5) * (.4 + .6 * depth) });
      }
      for (let m = 0; m < particles; m++) {
        const a = t * speed + (m / particles) * 2 * Math.PI + h2 * 6; const [px, py, z] = pt((ux * Math.cos(a) + vx * Math.sin(a)) * ro, (uy * Math.cos(a) + vy * Math.sin(a)) * ro, (uz * Math.cos(a) + vz * Math.sin(a)) * ro);
        const depth = (z / ro + 1) / 2; dots.push({ x: px, y: py, z, r: ((o.partR ?? 1.2) + (o.partRDepth ?? 1.6) * depth) * rs, white: .3 - .22 * depth });
      }
    }
    return finalizeFrame(dots, [], o.rMin);
  };
  const frameRibbon = (size, t, o) => {
    const cx = size / 2, cy = size / 2, R = (size / 2) * .78, spin = o.spin ?? 1, camTilt = .3, pt = makeProj(t * .1 * spin, camTilt, cx, cy, 1), rs = radiusScale(size, o.rsPow ?? .6);
    const dots = [], ghostN = o.ghostN ?? 150;
    for (let i = 0; i < ghostN; i++) { const d = fibDir(i, ghostN); const [px, py, z] = pt(d[0] * R, d[1] * R, d[2] * R), depth = (z / R + 1) / 2; dots.push({ x: px, y: py, z, r: .8 * rs, white: .78, a: .1 + .22 * depth }); }
    const ya = t * .24 * spin, ta = o.faceOn ? -camTilt : .55 + .3 * Math.sin(t * .18) * spin;
    const ux = Math.cos(ya), uy = 0, uz = Math.sin(ya), vx = -uz * Math.sin(ta), vy = Math.cos(ta), vz = ux * Math.sin(ta);
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    const wobAmp = .23 * (o.wobMul ?? 1), baseR = o.faceOn ? R / (1 + .85 * wobAmp) : R;
    const segs = o.segs ?? 88, lanes = Math.max(1, Math.round((o.lanes ?? 5) * (o.bandMul ?? 1)));
    for (let w = 0; w < lanes; w++) {
      const laneOff = (w - (lanes - 1) / 2) * .075, edge = Math.abs(w - (lanes - 1) / 2) / Math.max(1, (lanes - 1) / 2);
      for (let k = 0; k < segs; k++) {
        const a = (k / segs) * 2 * Math.PI, wob = (.16 * Math.sin(a * 3 - t * 1.7 + w * .22) + .07 * Math.sin(a * 5 + t * 1.1)) * (o.wobMul ?? 1);
        const radial = o.faceOn ? 1 + wob : 1, off = o.faceOn ? laneOff : laneOff + wob;
        const x = ux * Math.cos(a) + vx * Math.sin(a) + nx * off, y = uy * Math.cos(a) + vy * Math.sin(a) + ny * off, z = uz * Math.cos(a) + vz * Math.sin(a) + nz * off;
        const l = Math.sqrt(x * x + y * y + z * z), rr = baseR * radial; const [px, py, zr] = pt((x / l) * rr, (y / l) * rr, (z / l) * rr), depth = (zr / R + 1) / 2;
        dots.push({ x: px, y: py, z: zr, r: ((o.rBase ?? 1.1) + (o.rDepth ?? 1.7) * depth) * (1 - .25 * edge) * rs, white: .52 - .44 * depth + .18 * edge, a: .4 + .6 * depth });
      }
    }
    return finalizeFrame(dots, [], o.rMin);
  };

  const MODES = { globe: frameGlobe, wave: frameWave, web: frameWeb, orbits: frameOrbits, ribbon: frameRibbon, ring: frameRibbon };
  const STATE_TO_MODE = { working: 'orbits', searching: 'globe', listening: 'wave', connecting: 'web', composing: 'ribbon', breathing: 'ring' };
  const BASE = {
    globe: { latRings: 17, lonDensity: 44, rBase: .6, rDepth: 1.7, rBoost: 1, inkFar: .62, inkSpan: .54, rsPow: .6, rMin: .3 },
    orbits: { orbitN: 12, ghostN: 40, ghostR: .9, ghostA: .5, particles: 3, partR: 1.2, partRDepth: 1.6, rsPow: .6, rMin: .3 },
    wave: { rings: 15, lonDensity: 40, rBase: .6, rDepth: 1.7, rsPow: .6, rMin: .3 },
    web: { nodeN: 30, thr: .72, signals: 5, nodeR: 1.4, nodeRDepth: 1.8, lineW: .8, rsPow: .6, rMin: .3 },
    ribbon: { lanes: 5, segs: 88, ghostN: 150, rBase: 1.1, rDepth: 1.7, rsPow: .6, rMin: .3 },
    ring: { lanes: 5, segs: 88, ghostN: 0, faceOn: 1, rBase: 1.1, rDepth: 1.7, rsPow: .6, rMin: .3 }
  };
  const PRESETS = {
    orbits: { 64: { speed: 1.885, count: 1, size: 1 }, 20: { speed: 3.9, count: .238, size: 2.4 } },
    globe: { 64: { speed: 2.015, count: .42, size: 1.15, extra: { scanMul: 4.08, dimBase: .45 } }, 20: { speed: 2.665, count: .105, size: 1.75, extra: { scanMul: 4.335, dimBase: .45 } } },
    wave: { 64: { speed: 4.388, count: .341, size: 1 }, 20: { speed: 3.998, count: .105, size: 1.6 } },
    web: { 64: { speed: 3.315, count: 1.35, size: .95 }, 20: { speed: 6.63, count: .25, size: 1.52 } },
    ribbon: { 64: { speed: 2.34, count: .25, size: .85, extra: { spin: 0, bandMul: 3.9, wobMul: 1 } }, 20: { speed: 3.12, count: .051, size: 1.073, extra: { spin: 0, bandMul: 4.94, wobMul: 1 } } },
    ring: { 64: { speed: 3.24, count: .25, size: .956, extra: { spin: 0, bandMul: 3.627, wobMul: .368 } }, 20: { speed: 3.78, count: .028, size: 1.622, extra: { spin: 0, bandMul: 3.968, wobMul: .565 } } }
  };
  const COUNT_PAIRS = [['latRings', 'lonDensity'], ['rings', 'lonDensity'], ['lanes', 'segs']], COUNT_KEYS = ['orbitN', 'ghostN', 'nodeN', 'strandN', 'signals'];
  const RADIUS_KEYS = ['rBase', 'rDepth', 'rActive', 'rDot', 'ghostR', 'partR', 'partRDepth', 'nodeR', 'nodeRDepth'];
  function scaleCounts(o, s) {
    const out = { ...o }, done = new Set(), rt = Math.sqrt(s);
    for (const [a, b] of COUNT_PAIRS) if (out[a] != null && out[b] != null && !done.has(a) && !done.has(b)) { out[a] = Math.max(2, Math.round(out[a] * rt)); out[b] = Math.max(2, Math.round(out[b] * rt)); done.add(a); done.add(b); }
    for (const k of COUNT_KEYS) if (out[k] != null && out[k] !== 0 && !done.has(k)) out[k] = Math.max(1, Math.round(out[k] * s));
    return out;
  }
  function scaleRadii(o, s) { const out = { ...o }; for (const k of RADIUS_KEYS) if (out[k] != null) out[k] *= s; return out; }
  function resolve(state, sizeKey) {
    const mode = STATE_TO_MODE[state] || 'orbits', p = PRESETS[mode][sizeKey]; let opts = { ...BASE[mode] };
    if (p.count !== 1) opts = scaleCounts(opts, p.count); if (p.size !== 1) opts = scaleRadii(opts, p.size); if (p.extra) opts = { ...opts, ...p.extra };
    return { mode, speed: p.speed, opts };
  }
  function parseHex(h) { if (!h) return null; h = h.trim().replace('#', ''); if (h.length === 3) h = h.split('').map(c => c + c).join(''); if (h.length !== 6) return null; return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); }
  function paintFrame(ctx, frame, dark, ink) {
    const bg = dark ? 0 : 255;
    const css = (w, a) => { w = Math.min(1, Math.max(0, w)); const c = ink.map(v => Math.round(v + (bg - v) * w)); return `rgba(${c[0]},${c[1]},${c[2]},${a})`; };
    for (const l of frame.lines) { ctx.strokeStyle = css(l.white, l.a ?? 1); ctx.lineWidth = l.w; ctx.beginPath(); ctx.moveTo(l.x1, l.y1); ctx.lineTo(l.x2, l.y2); ctx.stroke(); }
    for (const d of frame.dots) { ctx.fillStyle = css(d.white, d.a ?? 1); ctx.beginPath(); ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2); ctx.fill(); }
  }

  class ThinkingOrb extends HTMLElement {
    static get observedAttributes() { return ['state', 'size', 'theme', 'speed', 'paused', 'ink', 'count']; }
    connectedCallback() {
      if (!this._c) { this._c = document.createElement('canvas'); this._c.style.display = 'block'; this.style.display = 'inline-block'; this.style.lineHeight = '0'; this.appendChild(this._c); }
      this._setup();
    }
    disconnectedCallback() { this._stop(); if (this._io) { this._io.disconnect(); this._io = null; } if (this._onVis) document.removeEventListener('visibilitychange', this._onVis); }
    attributeChangedCallback() { if (this._c && this.isConnected) this._setup(); }
    _setup() {
      this._stop();
      const size = +this.getAttribute('size') || 64, state = this.getAttribute('state') || 'working', dark = this.getAttribute('theme') === 'dark';
      const speed = +(this.getAttribute('speed') || 1), pausedAttr = this.getAttribute('paused'), paused = pausedAttr != null && pausedAttr !== 'false';
      const ink = parseHex(this.getAttribute('ink')) || (dark ? [255, 255, 255] : [0, 0, 0]);
      const dpr = Math.min(2, window.devicePixelRatio || 1), c = this._c;
      c.width = Math.round(size * dpr); c.height = Math.round(size * dpr); c.style.width = size + 'px'; c.style.height = size + 'px';
      c.setAttribute('role', 'img'); c.setAttribute('aria-label', this.getAttribute('aria-label') || state + '…');
      const ctx = c.getContext('2d'), r = resolve(state, size >= 40 ? 64 : 20);
      let opts = r.opts; const cm = +(this.getAttribute('count') || (size > 64 ? Math.pow(size / 64, .9) : 1)); if (cm !== 1) opts = scaleCounts(opts, cm);
      const draw = MODES[r.mode], eff = r.speed * speed;
      this._frame = () => { ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, size, size); paintFrame(ctx, draw(size, (performance.now() / 1000) * eff, opts), dark, ink); };
      this._frame();
      if (paused || (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches)) return;
      if (!this._io && 'IntersectionObserver' in window) {
        this._visible = true;
        this._io = new IntersectionObserver(([e]) => { this._visible = e.isIntersecting; (this._visible && document.visibilityState !== 'hidden') ? this._start() : this._stop(); });
        this._io.observe(this);
        this._onVis = () => { document.visibilityState === 'hidden' ? this._stop() : (this._visible && this._start()); };
        document.addEventListener('visibilitychange', this._onVis);
      }
      this._start();
    }
    _start() { if (this._running || !this._frame) return; this._running = true; const loop = () => { if (!this._running) return; this._frame(); this._raf = requestAnimationFrame(loop); }; this._raf = requestAnimationFrame(loop); }
    _stop() { this._running = false; if (this._raf) cancelAnimationFrame(this._raf); }
  }
  if (!customElements.get('thinking-orb')) customElements.define('thinking-orb', ThinkingOrb);
  window.ThinkingOrbEngine = { MODES, resolve, paintFrame };
})();
