"""
Real-time 3D for Zoha's web pages (three.js, MIT licence, loaded from the jsDelivr CDN).

A themed, procedurally modelled scene per business – gems and gold rings for a jeweller, a glazed
donut for a café, capsules for a clinic, dumbbells for a gym, rounded blocks for interiors, soft
pebbles for a spa, a torus-knot sculpture for studios – lit with a studio environment map
(physically based materials: metal, clear-coat, iridescence), floating, following the mouse,
reacting to scroll. No model files to download, nothing to license.

Safe by design: if WebGL, the CDN, a slow phone, data-saver or "reduce motion" says no, the page
keeps its normal art tiles – the 3D only replaces them after it has rendered its first frame.
"""
from __future__ import annotations

import re

THREE_VERSION = "0.170.0"

THEMES = [  # (regex on the request/page, theme)
    (r"jewel|gold|diamond|gem|ring|bridal set", "gems"),
    (r"caf[eé]|coffee|bakery|cake|donut|dessert|sweet|restaurant|food|tiffin|kitchen\b", "donut"),
    (r"clinic|dental|dentist|doctor|physio|health|pharma|lab\b|diagnostic|ayurved|derma", "capsules"),
    (r"gym|fitness|crossfit|strength|yoga|pilates|sport|martial", "dumbbells"),
    (r"interior|architect|furniture|modular|decor|real.?estate|construction", "blocks"),
    (r"salon|spa|beauty|skin|hair|nail|wellness|makeup", "pebbles"),
    (r"photo|studio|design|agency|creative|tech|software|event|film|music", "sculpture"),
]


def theme_for(text: str) -> str:
    t = (text or "").lower()
    for rx, theme in THEMES:
        if re.search(rx, t):
            return theme
    return "sculpture"


SCRIPT = r"""
  <script type="importmap">{"imports": {"three": "https://cdn.jsdelivr.net/npm/three@__V__/build/three.module.min.js",
                                       "three/addons/": "https://cdn.jsdelivr.net/npm/three@__V__/examples/jsm/"}}</script>
  <script type="module">/* zoha-3d */
  import * as THREE from 'three';
  import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
  import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
  const hero = document.querySelector('.hero');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const weak = ((navigator.hardwareConcurrency || 4) < 4 && (navigator.deviceMemory || 4) < 4) || (navigator.connection && navigator.connection.saveData);
  const gl = (() => { try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); } catch (e) { return false; } })();
  const slot = hero && hero.querySelector('.hero-art, .mosaic, .strip, .halves .right .art');
  // without an art slot the 3D sits on the right half of the hero – only on wide screens, never under an editorial layout
  const okLayer = hero && !slot && innerWidth > 900 && !hero.querySelector('.ed');
  if (hero && gl && !weak && (slot || okLayer)) {
    const host = document.createElement('div');
    host.className = 'zoha-3d' + (slot ? ' in-slot' : ' as-layer');
    host.setAttribute('aria-hidden', 'true');
    (slot || hero).prepend(host);
    const box = slot || hero;
    if (getComputedStyle(box).position === 'static') box.style.position = 'relative';
    if (!slot) box.style.overflow = 'hidden';
    const css = getComputedStyle(document.documentElement);
    const col = (n, f) => new THREE.Color((css.getPropertyValue(n) || f).trim() || f);
    const brand = col('--brand', '#5b2a4e'), brand2 = col('--brand-2', '#b8577e'), accent = col('--accent', '#f2b544');
    const theme = document.body.dataset.theme3d || 'sculpture';

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
    camera.position.set(0, 0, 9);
    const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(3, 4, 5); scene.add(key);
    const rim = new THREE.PointLight(accent, 30, 20); rim.position.set(-4, -2, 3); scene.add(rim);

    const metal = c => new THREE.MeshPhysicalMaterial({ color: c, metalness: 1, roughness: 0.22, clearcoat: 0.6 });
    const gloss = c => new THREE.MeshPhysicalMaterial({ color: c, metalness: 0.05, roughness: 0.28, clearcoat: 1, clearcoatRoughness: 0.15 });
    const gem = c => new THREE.MeshPhysicalMaterial({ color: c, metalness: 0, roughness: 0.04, transmission: 0.9, thickness: 1.2,
                                                     ior: 2.2, iridescence: 1, iridescenceIOR: 1.6, flatShading: true });
    const satin = c => new THREE.MeshPhysicalMaterial({ color: c, roughness: 0.55, sheen: 1, sheenColor: new THREE.Color('#ffffff'), sheenRoughness: 0.4 });
    const group = new THREE.Group(); scene.add(group);
    const items = [];
    const add = (mesh, x, y, z, s = 1) => { mesh.position.set(x, y, z); mesh.scale.setScalar(s);
      mesh.userData = { y, ph: Math.random() * 6.28, sp: 0.4 + Math.random() * 0.5, rx: (Math.random() - .5) * .6, ry: 0.2 + Math.random() * .5 };
      group.add(mesh); items.push(mesh); return mesh; };
    const gold = new THREE.Color('#d4a64a');

    if (theme === 'gems') {
      add(new THREE.Mesh(new THREE.OctahedronGeometry(1.1, 0), gem(brand2)), -1.2, 0.4, 0, 1.2);
      add(new THREE.Mesh(new THREE.IcosahedronGeometry(0.7, 0), gem(accent)), 1.6, 1.2, -1);
      add(new THREE.Mesh(new THREE.TorusGeometry(1, 0.12, 32, 120), metal(gold)), 1.2, -0.9, 0.5);
      add(new THREE.Mesh(new THREE.TorusGeometry(0.6, 0.08, 24, 100), metal(gold)), -1.9, -1.4, -0.5);
    } else if (theme === 'donut') {
      const d = add(new THREE.Group(), 0, 0, 0, 1.25);
      d.add(new THREE.Mesh(new THREE.TorusGeometry(1, 0.48, 48, 96), satin(new THREE.Color('#d9a066'))));
      const icing = new THREE.Mesh(new THREE.TorusGeometry(1, 0.5, 48, 96, Math.PI * 2), gloss(brand2));
      icing.scale.set(1.02, 1.02, 0.62); icing.position.z = 0.14; d.add(icing);
      const sp = new THREE.CapsuleGeometry(0.03, 0.14, 4, 8);
      for (let i = 0; i < 60; i++) { const a = Math.random() * 6.28, r = 0.65 + Math.random() * 0.7;
        const m = new THREE.Mesh(sp, gloss([accent, brand, new THREE.Color('#ffffff')][i % 3]));
        m.position.set(Math.cos(a) * r, Math.sin(a) * r, 0.52); m.rotation.z = Math.random() * 6.28; d.add(m); }
      d.rotation.x = -0.5;
      add(new THREE.Mesh(new THREE.SphereGeometry(0.35, 32, 32), gloss(accent)), 2, 1.3, -1);
      add(new THREE.Mesh(new THREE.SphereGeometry(0.22, 32, 32), gloss(brand)), -2, -1.2, -0.5);
    } else if (theme === 'capsules') {
      const cap = (c1, c2, x, y, z, rz) => { const g = add(new THREE.Group(), x, y, z);
        const a = new THREE.Mesh(new THREE.CapsuleGeometry(0.42, 0.7, 12, 32), gloss(c1)); a.scale.y = 0.999;
        const b = new THREE.Mesh(new THREE.CylinderGeometry(0.425, 0.425, 0.72, 32), gloss(c2)); b.position.y = -0.36;
        g.add(a, b); g.rotation.z = rz; };
      cap(new THREE.Color('#ffffff'), brand2, -1, 0.3, 0, 0.6); cap(new THREE.Color('#ffffff'), accent, 1.4, 0.9, -1, -0.8);
      add(new THREE.Mesh(new THREE.SphereGeometry(0.3, 32, 32), gloss(brand2)), 1.2, -1.2, 0.5);
      add(new THREE.Mesh(new THREE.TorusGeometry(0.7, 0.18, 24, 80), gloss(accent)), -1.8, -1.2, -0.8);
    } else if (theme === 'dumbbells') {
      const bell = (x, y, z, rz, s) => { const g = add(new THREE.Group(), x, y, z, s);
        const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 2.2, 24), metal(new THREE.Color('#c9ced6'))); bar.rotation.z = Math.PI / 2; g.add(bar);
        for (const sx of [-0.85, 0.85]) { const p = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.32, 40), gloss(brand2)); p.rotation.z = Math.PI / 2; p.position.x = sx; g.add(p); }
        g.rotation.z = rz; };
      bell(-0.6, 0.5, 0, 0.35, 1.1); bell(1.5, -0.9, -1, -0.5, 0.8);
      add(new THREE.Mesh(new THREE.IcosahedronGeometry(0.45, 1), gloss(accent)), 1.8, 1.3, -0.5);
    } else if (theme === 'blocks') {
      const rb = (w, h, d, c, x, y, z) => add(new THREE.Mesh(new RoundedBoxGeometry(w, h, d, 6, 0.12), c), x, y, z);
      rb(1.6, 1.6, 1.6, gloss(brand), -0.8, 0.2, 0); rb(1, 1, 1, satin(new THREE.Color('#e8dccb')), 1.2, 1, -0.8);
      rb(0.7, 1.6, 0.7, gloss(brand2), 1.4, -1, 0.3); add(new THREE.Mesh(new THREE.SphereGeometry(0.4, 40, 40), metal(accent)), -1.8, -1.3, 0.6);
    } else if (theme === 'pebbles') {
      const peb = (c, x, y, z, s) => { const m = add(new THREE.Mesh(new THREE.SphereGeometry(1, 64, 64), satin(c)), x, y, z, s); m.scale.set(s, s * 0.6, s); };
      peb(brand2, -0.7, 0.2, 0, 1.2); peb(new THREE.Color('#f4e7e1'), 1.2, 0.9, -0.8, 0.8); peb(brand, 1.1, -0.9, 0.3, 0.6);
      add(new THREE.Mesh(new THREE.TorusGeometry(0.55, 0.06, 24, 100), metal(gold)), -1.9, -1.1, 0.4);
    } else {
      add(new THREE.Mesh(new THREE.TorusKnotGeometry(0.9, 0.3, 220, 32), gloss(brand2)), -0.3, 0.1, 0, 1.15);
      add(new THREE.Mesh(new THREE.SphereGeometry(0.4, 48, 48), metal(accent)), 1.7, 1.2, -0.6);
      add(new THREE.Mesh(new RoundedBoxGeometry(0.7, 0.7, 0.7, 4, 0.1), gloss(brand)), -1.9, -1.2, 0.2);
    }

    let w = 0, h = 0, px = 0, py = 0, tx = 0, ty = 0, scrollK = 0, visible = true, t0 = performance.now(), shown = false;
    const fit = () => { const r = host.getBoundingClientRect(); w = Math.max(1, r.width); h = Math.max(1, r.height);
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
      group.scale.setScalar(Math.min(1, Math.max(0.6, (w / h) / 1.1))); };
    new ResizeObserver(fit).observe(host); fit();
    addEventListener('pointermove', e => { tx = (e.clientX / innerWidth - .5); ty = (e.clientY / innerHeight - .5); }, { passive: true });
    addEventListener('scroll', () => { scrollK = Math.min(1, scrollY / (hero.offsetHeight || 1)); }, { passive: true });
    new IntersectionObserver(es => { visible = es[0].isIntersecting; }).observe(hero);
    const frame = now => {
      const t = (now - t0) / 1000;
      if (visible) {
        px += (tx - px) * 0.05; py += (ty - py) * 0.05;
        group.rotation.y = px * 0.6; group.rotation.x = py * 0.35 + scrollK * 0.5;
        for (const m of items) { const u = m.userData;
          m.position.y = u.y + Math.sin(t * u.sp + u.ph) * 0.18; m.rotation.x += u.rx * 0.01; m.rotation.y += u.ry * 0.01; }
        renderer.render(scene, camera);
        if (!shown) { shown = true; host.classList.add('ready'); box.classList.add(slot ? 'has-3d-slot' : 'has-3d-layer'); }
      }
      if (!reduce) requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }
  </script>"""

CSS = """
    /* zoha-3d: real-time 3D in the hero (falls back to the art tiles) */
    .zoha-3d { pointer-events: none; opacity: 0; transition: opacity .9s ease; }
    .zoha-3d.ready { opacity: 1; }
    .zoha-3d canvas { display: block; width: 100% !important; height: 100% !important; }
    .zoha-3d.in-slot { position: absolute; inset: 0; z-index: 2; }
    .has-3d-slot.hero-art, .has-3d-slot.mosaic, .has-3d-slot.strip { display: block; min-height: 420px; }
    .has-3d-slot.strip { min-height: 340px; }
    .has-3d-slot > :not(.zoha-3d):not(.badge) { visibility: hidden; }
    .has-3d-slot.art { background: radial-gradient(circle at 50% 40%, rgba(255,255,255,.35), transparent 70%), var(--tint, #f4f4f4); }
    .zoha-3d.as-layer { position: absolute; top: 0; bottom: 0; right: 0; left: 52%; z-index: 0; }
    .has-3d-layer > :not(.zoha-3d) { position: relative; z-index: 1; }
    .has-3d-layer h1, .has-3d-layer .lead, .has-3d-layer .chips { max-width: 50%; }
    .has-3d-layer .frame h1, .has-3d-layer .frame .lead { max-width: 55%; }
    @media (max-width: 900px) { .zoha-3d.as-layer { display: none; } .has-3d-layer h1, .has-3d-layer .lead, .has-3d-layer .chips { max-width: none; } }
    @media (max-width: 760px) { .has-3d-slot.hero-art, .has-3d-slot.mosaic { min-height: 300px; } .has-3d-slot.strip { min-height: 260px; } }
"""


def add_3d(html: str) -> str:
    """Add the 3D hero to a page whose <body> has data-motion="3d" (idempotent)."""
    if "zoha-3d" in html or 'data-motion="3d"' not in html or "</body>" not in html:
        return html
    if "data-theme3d" not in html:
        title = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        theme = theme_for((title.group(1) if title else "") + " " + html[:4000])
        html = html.replace('data-motion="3d"', f'data-motion="3d" data-theme3d="{theme}"', 1)
    i = html.lower().rfind("</style>")
    if i < 0:
        return html
    html = html[:i] + CSS + "  " + html[i:]
    j = html.lower().rfind("</body>")
    return html[:j] + SCRIPT.replace("__V__", THREE_VERSION) + "\n" + html[j:]
