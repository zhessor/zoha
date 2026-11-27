"""
Zoha's web kit: builds a DIFFERENT correct starter page for every request.

One fixed starter made every site look the same. Here a page is assembled from interchangeable
section designs (4 heroes × 3 offering layouts × 2 story layouts × 2 review layouts × 2 closing bands),
a palette and a font pairing that fit the kind of business – thousands of combinations, and every
piece is pre-tested (nav, phone layout, contrast). The writer then fills in real content.
"""
from __future__ import annotations

import hashlib
import random
import re

FONTS = [  # (display, body, google query)
    ("Fraunces", "Inter", "family=Fraunces:ital,opsz,wght@0,9..144,500;0,9..144,800;1,9..144,500&family=Inter:wght@400;500;600;700"),
    ("Playfair Display", "Manrope", "family=Playfair+Display:ital,wght@0,500;0,800;1,500&family=Manrope:wght@400;500;600;700"),
    ("DM Serif Display", "DM Sans", "family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@400;500;600;700"),
    ("Space Grotesk", "IBM Plex Sans", "family=Space+Grotesk:wght@500;700&family=IBM+Plex+Sans:wght@400;500;600"),
    ("Bricolage Grotesque", "Inter", "family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,800&family=Inter:wght@400;500;600;700"),
    ("Syne", "Work Sans", "family=Syne:wght@600;800&family=Work+Sans:wght@400;500;600;700"),
    ("Cormorant Garamond", "Montserrat", "family=Cormorant+Garamond:ital,wght@0,500;0,700;1,500&family=Montserrat:wght@400;500;600;700"),
    ("Archivo Black", "Archivo", "family=Archivo+Black&family=Archivo:wght@400;500;600;700"),
    ("Outfit", "Lora", "family=Outfit:wght@500;800&family=Lora:ital,wght@0,400;0,600;1,400"),
]

# brand, brand-2, accent, tint, paper, ink, muted, dark (dark = page is dark)
PALETTES = {
    "plum":     ("#5b2a4e", "#b8577e", "#f2b544", "#fbeef3", "#fffdfb", "#1c1820", "#5d5560", False),
    "rose":     ("#8c2f4b", "#e07a8f", "#f6c445", "#fdf0f2", "#fffafa", "#25151a", "#6a5258", False),
    "espresso": ("#3d2418", "#b5651d", "#f4c430", "#fdf3e1", "#fffcf6", "#20140d", "#6b5848", False),
    "chilli":   ("#7a1f12", "#d9472b", "#ffb703", "#fff1e6", "#fffaf5", "#24120d", "#6c4d43", False),
    "forest":   ("#1f3d36", "#5d8a74", "#e0a458", "#eef4ef", "#fbfcfa", "#14211d", "#53625c", False),
    "sea":      ("#0d4d5c", "#2a9d8f", "#f4a261", "#e8f6f4", "#fbfefe", "#0e2328", "#4d6266", False),
    "cobalt":   ("#12263a", "#2f6fb0", "#ff7a3d", "#eaf2fb", "#fbfdff", "#0f1a26", "#4f5d6b", False),
    "violet":   ("#3a2c7a", "#6c5ce7", "#ffb703", "#f1efff", "#fdfcff", "#1b1636", "#5a5675", False),
    "ink-gold": ("#e9c46a", "#f4a261", "#e9c46a", "#1d1d24", "#121217", "#f3f0ea", "#b9b3a8", True),
    "night-lime": ("#c6f24e", "#7ad0ff", "#c6f24e", "#1a1f1c", "#0f1311", "#eef3ec", "#a7b0a8", True),
    "charcoal": ("#ff6b35", "#ffd23f", "#ff6b35", "#22252b", "#16181c", "#f1f1f1", "#b5b8be", True),
}

KINDS = {  # keywords → (palettes, fonts, preferred heroes, preferred offer layouts)
    "salon":    (r"salon|beauty|\bspa\b|bridal|makeup|nail|hair|skin", ["plum", "rose", "ink-gold"], [0, 1, 6, 2], ["split", "centered", "bigtype"], ["menu", "cards"]),
    "food":     (r"caf[eé]|coffee|bakery|cake|restaurant|food|kitchen|tiffin|dhaba|\bbar\b|juice|sweet", ["espresso", "chilli", "forest"], [2, 4, 8, 5], ["bigtype", "split", "poster"], ["menu", "bento"]),
    "interiors": (r"interior|architect|furniture|modular|decor|real.?estate|construction|home", ["forest", "espresso", "ink-gold"], [0, 3, 6, 2], ["centered", "split", "poster"], ["bento", "cards"]),
    "fitness":  (r"gym|fitness|yoga|pilates|dance|sport|swim|martial|crossfit|zumba", ["cobalt", "night-lime", "charcoal"], [7, 5, 3, 4], ["poster", "bigtype"], ["cards", "bento"]),
    "clinic":   (r"clinic|dental|dentist|doctor|physio|health|\blabs?\b|diagnostic|ayurved|hospital|derma|ca firm|chartered|account", ["sea", "cobalt", "forest"], [3, 0, 8, 4], ["split", "centered"], ["cards", "menu"]),
    "retail":   (r"shop|store|boutique|wear|jewel|toy|kids|optical|eyewear|mobile|repair|florist|print|pet|gift", ["violet", "rose", "chilli", "plum"], [4, 1, 5, 8], ["split", "bigtype", "centered"], ["bento", "cards"]),
    "learning": (r"coaching|tuition|academy|class|institute|course|ielts|english|school|music", ["violet", "cobalt", "sea"], [4, 3, 5, 0], ["bigtype", "split"], ["cards", "menu"]),
    "studio":   (r"photo|studio|event|wedding|film|design|agency|creative", ["ink-gold", "charcoal", "plum"], [5, 6, 3, 1], ["poster", "centered", "bigtype"], ["bento", "cards"]),
}

BASE_CSS = """
    :root { --brand: {brand}; --brand-2: {brand2}; --accent: {accent}; --tint: {tint}; --paper: {paper}; --ink: {ink}; --muted: {muted};
            --on-brand: {on_brand}; --display: '{display}', {display_fb}; --body: '{body}', sans-serif; --radius: {radius}; }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; }
    body { font-family: var(--body); color: var(--ink); background: var(--paper); line-height: 1.6; }
    img { max-width: 100%; height: auto; display: block; }
    h1, h2, h3 { font-family: var(--display); line-height: 1.08; color: var(--heading); letter-spacing: -.01em; }
    :root { --heading: {heading}; }
    h1 { font-size: clamp(2.5rem, 7vw, 5.2rem); }
    h2 { font-size: clamp(1.9rem, 4.5vw, 3rem); margin-bottom: .8rem; }
    p { max-width: 62ch; }
    .container { width: min(1160px, 100% - 2.5rem); margin-inline: auto; }
    section { padding-block: clamp(3.5rem, 9vw, 7rem); }
    .lead { font-size: 1.15rem; color: var(--muted); }
    .btn { display: inline-flex; align-items: center; gap: .5rem; min-height: 50px; padding: .85rem 1.5rem; border-radius: {btn_radius};
           background: var(--brand); color: var(--on-brand); font-weight: 700; text-decoration: none; border: 2px solid var(--brand);
           transition: transform .2s ease, box-shadow .2s ease; }
    .btn:hover { transform: translateY(-2px); box-shadow: 0 10px 24px rgba(0,0,0,.18); }
    .btn-ghost { background: transparent; color: var(--heading); border-color: currentColor; }
    a:focus-visible, button:focus-visible, input:focus-visible, textarea:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
    .site-header { position: sticky; top: 0; z-index: 40; background: color-mix(in srgb, var(--paper) 90%, transparent); backdrop-filter: blur(10px); border-bottom: 1px solid color-mix(in srgb, var(--ink) 10%, transparent); }
    .nav { display: flex; align-items: center; justify-content: space-between; min-height: 72px; position: relative; gap: 1rem; }
    .logo { font-family: var(--display); font-size: 1.45rem; font-weight: 800; color: var(--heading); text-decoration: none; }
    .menu { display: flex; align-items: center; gap: 1.8rem; list-style: none; }
    .menu a { display: inline-flex; align-items: center; min-height: 44px; color: var(--ink); text-decoration: none; font-weight: 500; }
    .menu a:hover { color: var(--brand-2); }
    .menu .btn { color: var(--on-brand); }
    .menu-btn { display: none; min-height: 44px; min-width: 44px; background: var(--tint); border: 0; border-radius: 12px; font-size: 1.25rem; color: var(--heading); }
    .art { position: relative; border-radius: var(--radius); display: flex; align-items: flex-end; padding: 1.1rem; color: var(--on-brand); font-weight: 700;
           box-shadow: 0 20px 40px rgba(0,0,0,.15); background: linear-gradient(140deg, var(--brand), var(--brand-2)); overflow: hidden; }
    .art::after { content: ""; position: absolute; inset: 0; background: radial-gradient(circle at 70% 25%, rgba(255,255,255,.35), transparent 45%); }
    .art span { position: relative; z-index: 1; }
    .art > img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
    .art:has(> img)::after { background: linear-gradient(0deg, rgba(0,0,0,.45), transparent 55%); }
    .art.alt { background: linear-gradient(160deg, var(--accent), var(--brand-2)); color: #1b1b1b; }
    .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; padding-block: 2rem; }
    .stat strong { display: block; font-family: var(--display); font-size: clamp(1.8rem, 4vw, 2.6rem); color: var(--heading); }
    .stat span { color: var(--muted); }
    .price { display: inline-block; font-weight: 700; color: var(--heading); background: color-mix(in srgb, var(--accent) 28%, var(--paper)); padding: .25rem .7rem; border-radius: 999px; }
    .contact { display: grid; grid-template-columns: 1fr 1fr; gap: 2.5rem; }
    .card { background: var(--tint); border-radius: var(--radius); padding: clamp(1.5rem, 4vw, 2.2rem); }
    form { display: grid; gap: .8rem; }
    label { font-weight: 600; }
    input, textarea { width: 100%; padding: .85rem; border: 1px solid color-mix(in srgb, var(--ink) 25%, transparent); border-radius: 12px; font: inherit; background: var(--paper); color: var(--ink); }
    .form-msg { min-height: 1.5em; font-weight: 600; color: var(--heading); }
    .info p { margin-bottom: .6rem; }
    .info a { color: var(--heading); font-weight: 600; }
    footer { background: {footer_bg}; color: rgba(255,255,255,.85); padding-block: 2.5rem; }
    footer a { color: #fff; }
    .wa-float { position: fixed; right: 1rem; bottom: 1rem; z-index: 50; min-height: 52px; padding: .85rem 1.2rem; border-radius: 999px;
                background: #25D366; color: #053d1c; font-weight: 800; text-decoration: none; box-shadow: 0 10px 26px rgba(0,0,0,.2); }
    @keyframes rise { from { opacity: 0; transform: translateY(24px); } to { opacity: 1; transform: none; } }
    @media (max-width: 760px) {
      .menu-btn { display: inline-flex; align-items: center; justify-content: center; }
      .menu { display: none; position: absolute; top: 100%; left: 0; right: 0; flex-direction: column; align-items: stretch; gap: 0;
              background: var(--paper); padding: .5rem 1.25rem 1rem; box-shadow: 0 14px 24px rgba(0,0,0,.12); }
      .menu.open { display: flex; }
      .contact { grid-template-columns: 1fr; }
      .stats { grid-template-columns: 1fr; text-align: center; }
    }
    @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; scroll-behavior: auto !important; } }
"""

HEROES = {
    "split": ("""
    .hero { background: radial-gradient(60rem 30rem at 85% -10%, color-mix(in srgb, var(--brand-2) 35%, transparent), transparent 60%),
              radial-gradient(40rem 25rem at -10% 110%, color-mix(in srgb, var(--accent) 30%, transparent), transparent 60%), var(--tint); }
    .hero .container { display: grid; grid-template-columns: 1.15fr 1fr; gap: clamp(2rem, 5vw, 4.5rem); align-items: center; }
    .kicker { display: inline-block; background: var(--paper); color: var(--heading); font-weight: 600; font-size: .9rem; padding: .35rem .8rem; border-radius: 999px; margin-bottom: 1.2rem; }
    .hero .lead { margin-block: 1.3rem 2rem; }
    .cta { display: flex; flex-wrap: wrap; gap: .8rem; }
    .hero-art { position: relative; min-height: 420px; animation: rise .8s ease-out both; }
    .hero-art .art { position: absolute; }
    .hero-art .a1 { inset: 0 18% 18% 0; }
    .hero-art .a2 { right: 0; bottom: 0; width: 46%; height: 52%; }
    .badge { position: absolute; left: -.5rem; bottom: 8%; background: var(--paper); color: var(--ink); border-radius: 14px; padding: .7rem 1rem; box-shadow: 0 12px 30px rgba(0,0,0,.12); z-index: 2; }
    .badge strong { color: var(--heading); font-size: 1.2rem; }
    @media (max-width: 760px) { .hero .container { grid-template-columns: 1fr; } .hero-art { min-height: 300px; } }
""", """
    <section class="hero">
      <div class="container">
        <div>
          <span class="kicker">AREA, Mumbai · since 20XX</span>
          <h1>Specific promise for this business</h1>
          <p class="lead">Two sentences of real, specific copy: what they offer, for whom, and what makes them different.</p>
          <div class="cta"><a class="btn" href="#contact">Primary action</a><a class="btn btn-ghost" href="https://wa.me/9198XXXXXXXX?text=Hi">WhatsApp us</a></div>
        </div>
        <div class="hero-art" aria-hidden="true">
          <div class="art a1"><span>Signature offering</span></div>
          <div class="art alt a2"><span>Second highlight</span></div>
          <div class="badge"><strong>4.9 ★</strong> on Google · 300+ reviews</div>
        </div>
      </div>
    </section>"""),
    "bigtype": ("""
    .hero { background: var(--brand); color: var(--on-brand); padding-bottom: 0; overflow: hidden; }
    .hero h1 { color: var(--on-brand); font-size: clamp(3rem, 10vw, 7.5rem); line-height: .95; max-width: 14ch; animation: rise .8s ease-out both; }
    .hero .lead { color: color-mix(in srgb, var(--on-brand) 85%, transparent); margin-block: 1.5rem 2rem; font-size: 1.2rem; }
    .hero .btn { background: var(--paper); border-color: var(--paper); color: var(--heading); }
    .hero .btn-ghost { background: transparent; color: var(--on-brand); border-color: var(--on-brand); }
    .cta { display: flex; flex-wrap: wrap; gap: .8rem; }
    .ticker { margin-top: clamp(2.5rem, 6vw, 4rem); border-top: 1px solid color-mix(in srgb, var(--on-brand) 25%, transparent); overflow: hidden; white-space: nowrap; }
    .ticker div { display: inline-block; padding-block: 1rem; font-family: var(--display); font-size: 1.3rem; animation: slide 28s linear infinite; }
    .ticker span { margin-inline: 1.2rem; color: var(--accent); }
    @keyframes slide { to { transform: translateX(-50%); } }
""", """
    <section class="hero">
      <div class="container">
        <h1>Specific promise for this business</h1>
        <p class="lead">Two sentences of real, specific copy for AREA, Mumbai: what they offer and what makes them different.</p>
        <div class="cta"><a class="btn" href="#contact">Primary action</a><a class="btn btn-ghost" href="https://wa.me/9198XXXXXXXX?text=Hi">WhatsApp us</a></div>
      </div>
      <div class="ticker" aria-hidden="true"><div>Offering one <span>✦</span> Offering two <span>✦</span> Offering three <span>✦</span> Offering four <span>✦</span> Offering one <span>✦</span> Offering two <span>✦</span> Offering three <span>✦</span> Offering four <span>✦</span></div></div>
    </section>"""),
    "centered": ("""
    .hero { text-align: center; background: linear-gradient(180deg, var(--tint), var(--paper)); }
    .hero .kicker { letter-spacing: .02em; color: var(--brand-2); font-weight: 600; }
    .hero h1 { margin: .8rem auto 0; max-width: 16ch; font-weight: 500; animation: rise .8s ease-out both; }
    .hero .lead { margin: 1.4rem auto 2rem; }
    .cta { display: flex; flex-wrap: wrap; gap: .8rem; justify-content: center; }
    .strip { display: grid; grid-template-columns: 1fr 1.4fr 1fr; gap: 1rem; margin-top: clamp(2.5rem, 6vw, 4rem); }
    .strip .art { min-height: 220px; }
    .strip .art:nth-child(2) { min-height: 280px; margin-top: -30px; }
    @media (max-width: 760px) { .strip { grid-template-columns: 1fr; } .strip .art:nth-child(2) { margin-top: 0; } }
""", """
    <section class="hero">
      <div class="container">
        <p class="kicker">AREA, Mumbai · since 20XX</p>
        <h1>Specific promise for this business</h1>
        <p class="lead">Two sentences of real, specific copy: what they offer, for whom, and what makes them different.</p>
        <div class="cta"><a class="btn" href="#contact">Primary action</a><a class="btn btn-ghost" href="https://wa.me/9198XXXXXXXX?text=Hi">WhatsApp us</a></div>
        <div class="strip" aria-hidden="true">
          <div class="art"><span>Highlight one</span></div><div class="art alt"><span>Signature offering</span></div><div class="art"><span>Highlight two</span></div>
        </div>
      </div>
    </section>"""),
    "poster": ("""
    .hero { position: relative; overflow: hidden; background: var(--ink); color: var(--paper); min-height: min(88vh, 760px); display: grid; align-items: center; }
    .hero::before { content: ""; position: absolute; width: 60vw; height: 60vw; right: -15vw; top: -20vw; border-radius: 50%;
                    background: radial-gradient(circle, var(--brand-2), transparent 65%); opacity: .55; }
    .hero::after { content: ""; position: absolute; left: -10vw; bottom: -25vw; width: 50vw; height: 50vw; transform: rotate(18deg);
                   background: var(--accent); opacity: .18; border-radius: 40px; }
    .hero .container { position: relative; z-index: 1; }
    .hero h1 { color: var(--paper); font-size: clamp(3rem, 9vw, 6.8rem); line-height: .98; max-width: 13ch; animation: rise .8s ease-out both; }
    .hero .lead { color: color-mix(in srgb, var(--paper) 82%, transparent); margin-block: 1.5rem 2rem; }
    .hero .btn { background: var(--accent); border-color: var(--accent); color: #111; }
    .hero .btn-ghost { background: transparent; color: var(--paper); border-color: var(--paper); }
    .cta { display: flex; flex-wrap: wrap; gap: .8rem; }
    .chips { display: flex; flex-wrap: wrap; gap: .6rem; margin-top: 2rem; }
    .chips span { border: 1px solid color-mix(in srgb, var(--paper) 35%, transparent); border-radius: 999px; padding: .35rem .9rem; font-size: .95rem; }
""", """
    <section class="hero">
      <div class="container">
        <h1>Specific promise for this business</h1>
        <p class="lead">Two sentences of real, specific copy for AREA, Mumbai: what they offer and what makes them different.</p>
        <div class="cta"><a class="btn" href="#contact">Primary action</a><a class="btn btn-ghost" href="https://wa.me/9198XXXXXXXX?text=Hi">WhatsApp us</a></div>
        <div class="chips"><span>4.9 ★ Google</span><span>Since 20XX</span><span>Fact about them</span></div>
      </div>
    </section>"""),
}

OFFERS = {
    "cards": ("""
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(250px, 100%), 1fr)); gap: 1.4rem; margin-top: 2rem; }
    .item { background: var(--paper); border-radius: var(--radius); padding: 1.5rem; border: 1px solid color-mix(in srgb, var(--ink) 12%, transparent); transition: transform .2s ease, box-shadow .2s ease; }
    .item:hover { transform: translateY(-4px); box-shadow: 0 16px 34px rgba(0,0,0,.12); }
    .icon { width: 52px; height: 52px; border-radius: 14px; display: grid; place-items: center; font-size: 1.5rem; background: var(--tint); margin-bottom: 1rem; }
    .item h3 { font-size: 1.3rem; margin-bottom: .35rem; }
    .item p { color: var(--muted); margin-bottom: .9rem; }
""", """
    <section id="offer" class="container">
      <h2>What we offer</h2>
      <p class="lead">One line about the range.</p>
      <div class="grid">
        <article class="item"><div class="icon" aria-hidden="true">✦</div><h3>Offering name</h3><p>One specific line about it.</p><span class="price">From ₹1,499</span></article>
        <!-- 3–4 items, each with its own fitting symbol -->
      </div>
    </section>"""),
    "menu": ("""
    .menu-list { display: grid; grid-template-columns: repeat(2, 1fr); gap: .4rem 3rem; margin-top: 2rem; }
    .row { display: flex; align-items: baseline; gap: .6rem; padding-block: 1rem; border-bottom: 1px dashed color-mix(in srgb, var(--ink) 25%, transparent); }
    .row h3 { font-size: 1.2rem; }
    .row .dots { flex: 1; border-bottom: 2px dotted color-mix(in srgb, var(--ink) 25%, transparent); transform: translateY(-4px); }
    .row p { flex-basis: 100%; color: var(--muted); font-size: .95rem; }
    .row-wrap { display: flex; flex-wrap: wrap; align-items: baseline; gap: .6rem; }
    @media (max-width: 760px) { .menu-list { grid-template-columns: 1fr; } }
""", """
    <section id="offer" class="container">
      <h2>Menu &amp; prices</h2>
      <p class="lead">One line about the range – prices shown upfront.</p>
      <div class="menu-list">
        <div class="row row-wrap"><h3>Offering name</h3><span class="dots" aria-hidden="true"></span><span class="price">₹1,499</span><p>One specific line about it.</p></div>
        <!-- 6–8 rows -->
      </div>
    </section>"""),
    "bento": ("""
    .bento { display: grid; grid-template-columns: repeat(4, 1fr); grid-auto-rows: minmax(170px, auto); gap: 1rem; margin-top: 2rem; }
    .tile { border-radius: var(--radius); padding: 1.4rem; background: var(--tint); display: flex; flex-direction: column; justify-content: space-between; gap: .6rem; }
    .tile h3 { font-size: 1.25rem; }
    .tile .price { align-self: flex-start; }
    .tile p { color: var(--muted); }
    .tile.big { grid-column: span 2; grid-row: span 2; background: linear-gradient(150deg, var(--brand), var(--brand-2)); color: var(--on-brand); }
    .tile.big h3, .tile.big p { color: var(--on-brand); }
    .tile.wide { grid-column: span 2; }
    @media (max-width: 900px) { .bento { grid-template-columns: repeat(2, 1fr); } }
    @media (max-width: 560px) { .bento { grid-template-columns: 1fr; } .tile.big, .tile.wide { grid-column: auto; grid-row: auto; } }
""", """
    <section id="offer" class="container">
      <h2>What we offer</h2>
      <p class="lead">One line about the range.</p>
      <div class="bento">
        <article class="tile big"><h3>Signature offering</h3><p>Two specific lines about the flagship service or product.</p><span class="price">From ₹2,999</span></article>
        <article class="tile"><h3>Offering name</h3><p>One specific line.</p><span class="price">From ₹999</span></article>
        <article class="tile"><h3>Offering name</h3><p>One specific line.</p><span class="price">From ₹1,299</span></article>
        <article class="tile wide"><h3>Offering name</h3><p>One specific line.</p><span class="price">From ₹1,799</span></article>
      </div>
    </section>"""),
}

STORIES = {
    "split": ("""
    .story { display: grid; grid-template-columns: 1fr 1fr; gap: clamp(2rem, 5vw, 4rem); align-items: center; }
    .story .art { min-height: 340px; }
    .quote { font-family: var(--display); font-size: clamp(1.4rem, 3vw, 2rem); font-style: italic; color: var(--heading); border-left: 4px solid var(--accent); padding-left: 1.2rem; margin-top: 1.5rem; }
    @media (max-width: 760px) { .story { grid-template-columns: 1fr; } }
""", """
    <section id="story" class="container story">
      <div class="art" aria-hidden="true"><span>Our space in AREA</span></div>
      <div>
        <h2>Our story</h2>
        <p class="lead">Who runs it, since when, what they care about – specific and believable.</p>
        <p class="quote">"One line the owner would actually say."</p>
      </div>
    </section>"""),
    "facts": ("""
    .story-band { background: var(--tint); }
    .story-grid { display: grid; grid-template-columns: 1.2fr 1fr; gap: clamp(2rem, 5vw, 4rem); }
    .facts { list-style: none; display: grid; gap: 1rem; }
    .facts li { background: var(--paper); border-radius: var(--radius); padding: 1rem 1.2rem; border-left: 4px solid var(--brand-2); }
    .facts strong { display: block; color: var(--heading); }
    @media (max-width: 760px) { .story-grid { grid-template-columns: 1fr; } }
""", """
    <section id="story" class="story-band">
      <div class="container story-grid">
        <div>
          <h2>Our story</h2>
          <p class="lead">Who runs it, since when, what they care about – specific and believable.</p>
        </div>
        <ul class="facts">
          <li><strong>Fact about them</strong>One line that backs it up.</li>
          <li><strong>Fact about them</strong>One line that backs it up.</li>
          <li><strong>Fact about them</strong>One line that backs it up.</li>
        </ul>
      </div>
    </section>"""),
}

REVIEWS = {
    "grid": ("""
    .band { background: var(--brand); color: var(--on-brand); }
    .band h2 { color: var(--on-brand); }
    .band p, .band cite { color: color-mix(in srgb, var(--on-brand) 88%, transparent); }
    .reviews { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(280px, 100%), 1fr)); gap: 1.2rem; margin-top: 2rem; }
    .review { background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.15); border-radius: var(--radius); padding: 1.5rem; }
    .stars { color: var(--accent); letter-spacing: .15em; margin-bottom: .6rem; }
    cite { display: block; margin-top: .9rem; font-style: normal; font-weight: 600; }
""", """
    <section id="reviews" class="band">
      <div class="container">
        <h2>What customers say</h2>
        <div class="reviews">
          <blockquote class="review"><div class="stars" aria-label="5 stars">★★★★★</div><p>"Short, believable review."</p><cite>— Priya, Khar West</cite></blockquote>
          <!-- 3 reviews -->
        </div>
      </div>
    </section>"""),
    "spotlight": ("""
    .spot { text-align: center; }
    .spot .stars { color: var(--accent); font-size: 1.4rem; letter-spacing: .2em; }
    .spot blockquote p { font-family: var(--display); font-size: clamp(1.6rem, 4vw, 2.6rem); line-height: 1.25; color: var(--heading); max-width: 26ch; margin: 1rem auto; }
    .spot cite { font-style: normal; font-weight: 600; color: var(--muted); }
    .more { display: flex; flex-wrap: wrap; justify-content: center; gap: .8rem; margin-top: 2rem; }
    .more span { background: var(--tint); border-radius: 999px; padding: .5rem 1rem; color: var(--ink); }
""", """
    <section id="reviews" class="container spot">
      <div class="stars" aria-label="5 stars">★★★★★</div>
      <blockquote><p>"Short, believable review."</p><cite>— Priya, Khar West</cite></blockquote>
      <div class="more"><span>"Short, believable review." — Name, Area</span><span>"Short, believable review." — Name, Area</span></div>
    </section>"""),
}

CLOSERS = {
    "band": ("""
    .cta-band { background: var(--accent); }
    .cta-band .container { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 1.5rem; }
    .cta-band h2 { color: #1b1b1b; margin: 0; }
    .cta-band .btn { background: #1b1b1b; border-color: #1b1b1b; color: #fff; }
""", """
    <section class="cta-band">
      <div class="container"><h2>A clear closing line, e.g. "Book your visit this week"</h2><a class="btn" href="#contact">Book now</a></div>
    </section>"""),
    "card": ("""
    .closing { display: grid; grid-template-columns: 1.4fr 1fr; gap: 1.5rem; align-items: center; background: linear-gradient(135deg, var(--brand), var(--brand-2));
               color: var(--on-brand); border-radius: calc(var(--radius) * 1.5); padding: clamp(2rem, 5vw, 3.5rem); }
    .closing h2 { color: var(--on-brand); margin: 0; }
    .closing p { color: color-mix(in srgb, var(--on-brand) 88%, transparent); }
    .closing .btn { background: var(--accent); border-color: var(--accent); color: #1b1b1b; justify-self: end; }
    @media (max-width: 760px) { .closing { grid-template-columns: 1fr; } .closing .btn { justify-self: start; } }
""", """
    <section class="container">
      <div class="closing"><div><h2>A clear closing line, e.g. "Book your visit this week"</h2><p>One line with the offer or the next step.</p></div><a class="btn" href="#contact">Book now</a></div>
    </section>"""),
}

PAGE = """<!DOCTYPE html>
<html lang="en-IN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BUSINESS – what they do in AREA, Mumbai</title>
  <meta name="description" content="140–160 characters: what the business offers, where, and why it is different.">
  <meta property="og:title" content="BUSINESS – AREA, Mumbai">
  <meta property="og:description" content="One specific sentence about the business.">
  <meta property="og:type" content="website">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?{fonts}&display=swap" rel="stylesheet">
  <style>{css}
  </style>
</head>
<body data-motion="{motion}" data-theme3d="{theme3d}">
  <header class="site-header">
    <nav class="container nav" aria-label="Main">
      <a class="logo" href="#">BUSINESS</a>
      <button class="menu-btn" aria-expanded="false" aria-controls="menu" aria-label="Open menu">☰</button>
      <ul id="menu" class="menu">
        <li><a href="#offer">Services</a></li>
        <li><a href="#story">About</a></li>
        <li><a href="#reviews">Reviews</a></li>
        <li><a class="btn" href="#contact">Book now</a></li>
      </ul>
    </nav>
  </header>

  <main>{hero}
{stats}{offer}
{story}
{reviews}
<!--zoha-extras-->{closer}

    <section id="contact" class="container contact">
      <div class="info">
        <h2>Visit or call</h2>
        <p>Full address, AREA, Mumbai 4000XX</p>
        <p><a href="tel:+9198XXXXXXXX">+91 98XXX XXXXX</a> · Mon–Sat 10 am–8 pm</p>
      </div>
      <div class="card">
        <form id="enquiry" novalidate>
          <label for="name">Your name</label><input id="name" name="name" required>
          <label for="phone">Phone</label><input id="phone" name="phone" type="tel" required>
          <button class="btn" type="submit">Send enquiry</button>
          <p class="form-msg" role="status" aria-live="polite"></p>
        </form>
      </div>
    </section>
  </main>

  <footer><div class="container"><p>© YEAR BUSINESS · AREA, Mumbai</p></div></footer>
  <a class="wa-float" href="https://wa.me/9198XXXXXXXX?text=Hi%2C%20I%20saw%20your%20website" aria-label="Chat on WhatsApp">WhatsApp</a>

  <script type="application/ld+json">
  {{"@context": "https://schema.org", "@type": "LocalBusiness", "name": "BUSINESS",
   "address": {{"@type": "PostalAddress", "streetAddress": "…", "addressLocality": "Mumbai", "postalCode": "4000XX", "addressCountry": "IN"}},
   "telephone": "+9198XXXXXXXX", "openingHours": "Mo-Sa 10:00-20:00"}}
  </script>
  <script>
    const btn = document.querySelector('.menu-btn'), menu = document.getElementById('menu');
    btn.addEventListener('click', () => {{
      const open = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!open));
      menu.classList.toggle('open', !open);
    }});
    menu.addEventListener('click', e => {{ if (e.target.closest('a')) {{ btn.setAttribute('aria-expanded', 'false'); menu.classList.remove('open'); }} }});
    document.getElementById('enquiry').addEventListener('submit', e => {{
      e.preventDefault();
      const f = e.target, msg = f.querySelector('.form-msg');
      if (!f.checkValidity()) {{ msg.textContent = 'Please add your name and phone number.'; return; }}
      msg.textContent = 'Thanks! We will call you back within a day.';
      f.reset();
    }});
  </script>
</body>
</html>
"""

STATS_HTML = """
    <div class="container stats">
      <div class="stat"><strong>12 yrs</strong><span>serving AREA</span></div>
      <div class="stat"><strong>5,000+</strong><span>happy customers</span></div>
      <div class="stat"><strong>4.9 ★</strong><span>average rating</span></div>
    </div>
"""


def _kind(text: str):
    t = (text or "").lower()
    for name, (rx, pals, fonts, heroes, offers) in KINDS.items():
        if re.search(rx, t):
            return name, pals, fonts, heroes, offers
    return "general", list(PALETTES), list(range(len(FONTS))), list(HEROES), list(OFFERS)


def _hex_lum(h: str) -> float:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def build_starter(request: str, seed: str | None = None) -> tuple:
    """(starter html, short description of the design) – different for every request, same for the same request."""
    rng = random.Random(int(hashlib.md5((seed or request or "").encode()).hexdigest()[:8], 16))
    kind, pals, fonts, heroes, offers = _kind(request)
    t = (request or "").lower()
    light = [p for p in pals if not PALETTES[p][7]]
    pal_name = rng.choice(pals if (rng.random() < 0.15 or not light) else light)   # dark pages only now and then
    if re.search(r"\b(dark|night|edgy)\b", t):
        dark = [p for p in PALETTES if PALETTES[p][7]]
        pal_name = rng.choice(dark)
    brand, brand2, accent, tint, paper, ink, muted, is_dark = PALETTES[pal_name]
    display, body, gq = FONTS[rng.choice(fonts)]
    hero = rng.choice(heroes * 2 + list(HEROES))      # leans to what fits the business, but any design can appear
    if re.search(r"premium|luxury|calm|minimal|elegant", t):
        hero = rng.choice(["centered", "editorial"])
    elif re.search(r"energetic|bold|loud|young", t):
        hero = rng.choice(["bigtype", "poster", "halves", "framed"])
    offer = rng.choice(offers * 2 + [o for o in OFFERS if o != "pricing"])
    if re.search(r"\bmenu\b|price list|rate card", t):
        offer = "menu"
    elif re.search(r"package|pricing|plans?\b|membership", t):
        offer = "pricing"
    story = rng.choice(list(STORIES))
    review = rng.choice(list(REVIEWS))
    closer = rng.choice(list(CLOSERS))
    on_brand = "#111111" if _hex_lum(brand) > 0.55 else "#ffffff"
    heading = brand if not is_dark else accent
    serif = any(k in display for k in ("Fraunces", "Playfair", "Serif", "Cormorant", "Lora"))
    fill = {
        "brand": brand, "brand2": brand2, "accent": accent, "tint": tint, "paper": paper, "ink": ink, "muted": muted,
        "on_brand": on_brand, "display": display, "display_fb": "serif" if serif else "sans-serif", "body": body,
        "radius": rng.choice(["8px", "14px", "20px", "28px"]), "btn_radius": rng.choice(["999px", "10px", "4px"]),
        "heading": heading, "footer_bg": "#000000" if is_dark else ink,
    }
    css = BASE_CSS
    for k, v in fill.items():
        css = css.replace("{" + k + "}", v)
    css += HEROES[hero][0] + OFFERS[offer][0] + STORIES[story][0] + REVIEWS[review][0] + CLOSERS[closer][0]
    if is_dark:   # dark pages: tinted surfaces must stay dark, review band uses the brand-2 colour
        css += ("\n    .band { background: color-mix(in srgb, var(--brand-2) 22%, var(--paper)); color: var(--ink); }"
                "\n    .band h2 { color: var(--heading); } .band p, .band cite { color: var(--ink); }\n")
    motion = rng.choice({"fitness": ["words", "drift", "glow"], "food": ["words", "float", "drift"],
                         "salon": ["float", "glow", "drift"], "interiors": ["float", "words", "glow"],
                         "studio": ["glow", "drift", "words"]}.get(kind, ["float", "words", "drift", "glow"]))
    if re.search(r"\b3d\b|three.?d|webgl", t) or (not re.search(r"\b(no 3d|simple|lightweight|fast)\b", t) and rng.random() < 0.55):
        motion = "3d"   # real-time 3D hero (falls back to the normal art if the visitor's device can't)
    from .web3d import theme_for
    html = PAGE.format(motion=motion, theme3d=theme_for(request), fonts=gq, css=css, hero=HEROES[hero][1], stats=STATS_HTML if hero != "poster" else "",
                       offer=OFFERS[offer][1], story=STORIES[story][1], reviews=REVIEWS[review][1], closer=CLOSERS[closer][1])
    desc = (f"{kind} design: {hero} hero, {offer} offerings, {story} story, {review} reviews, {closer} closer, motion {motion}, "
            f"palette {pal_name}{' (dark)' if is_dark else ''}, fonts {display} + {body}")
    return html, desc


# ── more designs (patterns from landing-page research: asymmetric/split/framed heroes, alternating and
#    divider feature layouts, 3-column pricing with a featured card, masonry testimonials, trust rows) ──
HEROES.update({
    "halves": ("""
    .hero { padding: 0; }
    .halves { display: grid; grid-template-columns: 1fr 1fr; min-height: min(80vh, 680px); }
    .halves .left { background: var(--brand); color: var(--on-brand); padding: clamp(2.5rem, 6vw, 5rem); display: flex; flex-direction: column; justify-content: center; }
    .halves h1 { color: var(--on-brand); animation: rise .8s ease-out both; }
    .halves .lead { color: color-mix(in srgb, var(--on-brand) 85%, transparent); margin-block: 1.3rem 2rem; }
    .halves .btn { background: var(--paper); border-color: var(--paper); color: var(--heading); }
    .halves .btn-ghost { background: transparent; color: var(--on-brand); border-color: var(--on-brand); }
    .halves .right { background: var(--tint); padding: clamp(1.5rem, 4vw, 3rem); display: grid; gap: 1rem; align-content: center; }
    .halves .right .art { min-height: 260px; }
    .mini { display: flex; gap: 1rem; flex-wrap: wrap; }
    .mini span { background: var(--paper); border-radius: 999px; padding: .5rem 1rem; font-weight: 600; color: var(--ink); }
    .cta { display: flex; flex-wrap: wrap; gap: .8rem; }
    @media (max-width: 760px) { .halves { grid-template-columns: 1fr; } }
""", """
    <section class="hero">
      <div class="halves">
        <div class="left">
          <h1>Specific promise for this business</h1>
          <p class="lead">Two sentences of real, specific copy for AREA, Mumbai: what they offer and what makes them different.</p>
          <div class="cta"><a class="btn" href="#contact">Primary action</a><a class="btn btn-ghost" href="https://wa.me/9198XXXXXXXX?text=Hi">WhatsApp us</a></div>
        </div>
        <div class="right">
          <div class="art" aria-hidden="true"><span>Signature offering</span></div>
          <div class="mini"><span>4.9 ★ Google</span><span>Since 20XX</span><span>Fact about them</span></div>
        </div>
      </div>
    </section>"""),
    "mosaic": ("""
    .hero .container { display: grid; grid-template-columns: 1fr 1.1fr; gap: clamp(2rem, 5vw, 4rem); align-items: center; }
    .hero .lead { margin-block: 1.3rem 2rem; }
    .cta { display: flex; flex-wrap: wrap; gap: .8rem; }
    .mosaic { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 170px 170px 170px; gap: .9rem; animation: rise .8s ease-out both; }
    .mosaic .art:nth-child(1) { grid-row: span 2; }
    .mosaic .art:nth-child(4) { grid-column: span 2; }
    .rating { margin-top: 1.5rem; color: var(--muted); }
    .rating strong { color: var(--heading); }
    @media (max-width: 760px) { .hero .container { grid-template-columns: 1fr; } .mosaic { grid-template-rows: 140px 140px 140px; } }
""", """
    <section class="hero">
      <div class="container">
        <div>
          <h1>Specific promise for this business</h1>
          <p class="lead">Two sentences of real, specific copy: what they offer, for whom, and what makes them different.</p>
          <div class="cta"><a class="btn" href="#contact">Primary action</a><a class="btn btn-ghost" href="https://wa.me/9198XXXXXXXX?text=Hi">WhatsApp us</a></div>
          <p class="rating"><strong>4.9 ★</strong> from 300+ Google reviews · AREA, Mumbai</p>
        </div>
        <div class="mosaic" aria-hidden="true">
          <div class="art"><span>Signature offering</span></div><div class="art alt"><span>Highlight one</span></div>
          <div class="art"><span>Highlight two</span></div><div class="art alt"><span>Our space in AREA</span></div>
        </div>
      </div>
    </section>"""),
    "editorial": ("""
    .hero { border-bottom: 1px solid color-mix(in srgb, var(--ink) 15%, transparent); }
    .ed { display: grid; grid-template-columns: repeat(12, 1fr); gap: 1.5rem; align-items: end; }
    .ed h1 { grid-column: 1 / -1; font-size: clamp(3rem, 9vw, 7rem); line-height: .95; max-width: 15ch; animation: rise .8s ease-out both; }
    .ed .rule { grid-column: 1 / -1; height: 6px; background: linear-gradient(90deg, var(--brand), var(--brand-2), var(--accent)); border-radius: 6px; }
    .ed .meta { grid-column: 1 / 6; color: var(--muted); font-weight: 600; }
    .ed .side { grid-column: 7 / -1; }
    .ed .lead { margin-bottom: 1.5rem; }
    .cta { display: flex; flex-wrap: wrap; gap: .8rem; }
    @media (max-width: 760px) { .ed .meta, .ed .side { grid-column: 1 / -1; } }
""", """
    <section class="hero">
      <div class="container ed">
        <h1>Specific promise for this business</h1>
        <div class="rule" aria-hidden="true"></div>
        <p class="meta">AREA, Mumbai · since 20XX · 4.9 ★ on Google</p>
        <div class="side">
          <p class="lead">Two sentences of real, specific copy: what they offer, for whom, and what makes them different.</p>
          <div class="cta"><a class="btn" href="#contact">Primary action</a><a class="btn btn-ghost" href="https://wa.me/9198XXXXXXXX?text=Hi">WhatsApp us</a></div>
        </div>
      </div>
    </section>"""),
    "framed": ("""
    .hero { padding-top: clamp(1.5rem, 4vw, 2.5rem); }
    .frame { position: relative; overflow: hidden; border-radius: calc(var(--radius) * 2); padding: clamp(2.5rem, 7vw, 5.5rem);
             background: linear-gradient(135deg, var(--brand), var(--brand-2)); color: var(--on-brand); }
    .frame::after { content: ""; position: absolute; right: -8%; bottom: -30%; width: 45%; aspect-ratio: 1; border-radius: 50%; background: var(--accent); opacity: .35; }
    .frame > * { position: relative; z-index: 1; }
    .frame h1 { color: var(--on-brand); max-width: 14ch; animation: rise .8s ease-out both; }
    .frame .lead { color: color-mix(in srgb, var(--on-brand) 86%, transparent); margin-block: 1.3rem 2rem; }
    .frame .btn { background: var(--paper); border-color: var(--paper); color: var(--heading); }
    .frame .btn-ghost { background: transparent; color: var(--on-brand); border-color: var(--on-brand); }
    .cta { display: flex; flex-wrap: wrap; gap: .8rem; }
    .chips { display: flex; flex-wrap: wrap; gap: .6rem; margin-top: 1.8rem; }
    .chips span { background: color-mix(in srgb, var(--paper) 18%, transparent); border-radius: 999px; padding: .35rem .9rem; }
""", """
    <section class="hero">
      <div class="container">
        <div class="frame">
          <h1>Specific promise for this business</h1>
          <p class="lead">Two sentences of real, specific copy for AREA, Mumbai: what they offer and what makes them different.</p>
          <div class="cta"><a class="btn" href="#contact">Primary action</a><a class="btn btn-ghost" href="https://wa.me/9198XXXXXXXX?text=Hi">WhatsApp us</a></div>
          <div class="chips"><span>4.9 ★ Google</span><span>Since 20XX</span><span>Fact about them</span></div>
        </div>
      </div>
    </section>"""),
})

OFFERS.update({
    "alternating": ("""
    .alt-rows { display: grid; gap: clamp(2rem, 5vw, 3.5rem); margin-top: 2rem; }
    .alt-row { display: grid; grid-template-columns: 1fr 1fr; gap: clamp(1.5rem, 4vw, 3rem); align-items: center; }
    .alt-row:nth-child(even) .art { order: 2; }
    .alt-row .art { min-height: 240px; }
    .alt-row h3 { font-size: clamp(1.4rem, 3vw, 2rem); margin-bottom: .5rem; }
    .alt-row p { color: var(--muted); margin-bottom: 1rem; }
    @media (max-width: 760px) { .alt-row { grid-template-columns: 1fr; } .alt-row:nth-child(even) .art { order: 0; } }
""", """
    <section id="offer" class="container">
      <h2>What we offer</h2>
      <div class="alt-rows">
        <article class="alt-row"><div class="art" aria-hidden="true"><span>Offering name</span></div><div><h3>Offering name</h3><p>Two specific lines about it.</p><span class="price">From ₹1,499</span></div></article>
        <!-- 3 rows in total -->
      </div>
    </section>"""),
    "divider": ("""
    .dlist { list-style: none; margin-top: 2rem; border-top: 2px solid var(--ink); counter-reset: n; }
    .dlist li { display: grid; grid-template-columns: 4rem 1fr auto; gap: 1rem; align-items: baseline; padding-block: 1.4rem; border-bottom: 1px solid color-mix(in srgb, var(--ink) 18%, transparent); counter-increment: n; }
    .dlist li::before { content: "0" counter(n); font-family: var(--display); font-size: 1.4rem; color: var(--brand-2); }
    .dlist h3 { font-size: clamp(1.3rem, 3vw, 1.8rem); }
    .dlist p { color: var(--muted); }
    @media (max-width: 560px) { .dlist li { grid-template-columns: 2.5rem 1fr; } .dlist .price { grid-column: 2; justify-self: start; } }
""", """
    <section id="offer" class="container">
      <h2>What we offer</h2>
      <ol class="dlist">
        <li><div><h3>Offering name</h3><p>One specific line about it.</p></div><span class="price">₹1,499</span></li>
        <!-- 4–5 items -->
      </ol>
    </section>"""),
    "pricing": ("""
    .plans { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.2rem; margin-top: 2rem; align-items: center; }
    .plan { background: var(--paper); border: 1px solid color-mix(in srgb, var(--ink) 14%, transparent); border-radius: var(--radius); padding: 1.8rem; }
    .plan.featured { background: var(--brand); color: var(--on-brand); transform: scale(1.04); box-shadow: 0 20px 40px rgba(0,0,0,.18); }
    .plan.featured h3, .plan.featured .amount { color: var(--on-brand); }
    .plan .amount { font-family: var(--display); font-size: 2.4rem; color: var(--heading); margin-block: .5rem 1rem; }
    .plan ul { list-style: none; display: grid; gap: .5rem; margin-bottom: 1.4rem; }
    .plan li::before { content: "✓ "; color: var(--brand-2); font-weight: 700; }
    .plan.featured li::before { color: var(--accent); }
    .plan.featured .btn { background: var(--paper); border-color: var(--paper); color: var(--heading); }
    @media (max-width: 860px) { .plans { grid-template-columns: 1fr; } .plan.featured { transform: none; } }
""", """
    <section id="offer" class="container">
      <h2>Packages</h2>
      <p class="lead">One line about how the packages work.</p>
      <div class="plans">
        <div class="plan"><h3>Package name</h3><p class="amount">₹1,999</p><ul><li>What's included</li><li>What's included</li><li>What's included</li></ul><a class="btn btn-ghost" href="#contact">Choose</a></div>
        <div class="plan featured"><h3>Package name</h3><p class="amount">₹3,999</p><ul><li>What's included</li><li>What's included</li><li>What's included</li></ul><a class="btn" href="#contact">Most popular</a></div>
        <div class="plan"><h3>Package name</h3><p class="amount">₹6,999</p><ul><li>What's included</li><li>What's included</li><li>What's included</li></ul><a class="btn btn-ghost" href="#contact">Choose</a></div>
      </div>
    </section>"""),
})

STORIES["timeline"] = ("""
    .tl { list-style: none; margin-top: 2rem; display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; }
    .tl li { border-top: 3px solid var(--brand-2); padding-top: 1rem; }
    .tl strong { display: block; font-family: var(--display); font-size: 1.6rem; color: var(--heading); }
    .tl p { color: var(--muted); }
    @media (max-width: 760px) { .tl { grid-template-columns: 1fr 1fr; } }
""", """
    <section id="story" class="container">
      <h2>Our story</h2>
      <p class="lead">Who runs it and what they care about – specific and believable.</p>
      <ol class="tl">
        <li><strong>20XX</strong><p>Milestone in one line.</p></li><li><strong>20XX</strong><p>Milestone in one line.</p></li>
        <li><strong>20XX</strong><p>Milestone in one line.</p></li><li><strong>Today</strong><p>Where they are now.</p></li>
      </ol>
    </section>""")

REVIEWS["masonry"] = ("""
    .wall-band { background: var(--tint); }
    .wall { columns: 3 260px; column-gap: 1.2rem; margin-top: 2rem; }
    .wall blockquote { break-inside: avoid; background: var(--paper); border-radius: var(--radius); padding: 1.3rem; margin-bottom: 1.2rem; box-shadow: 0 6px 18px rgba(0,0,0,.06); }
    .wall .stars { color: var(--accent); letter-spacing: .12em; }
    .wall cite { display: block; margin-top: .7rem; font-style: normal; font-weight: 600; color: var(--muted); }
""", """
    <section id="reviews" class="wall-band">
      <div class="container">
        <h2>What customers say</h2>
        <div class="wall">
          <blockquote><div class="stars" aria-label="5 stars">★★★★★</div><p>"Short, believable review."</p><cite>— Priya, Khar West</cite></blockquote>
          <!-- 5–6 reviews of different lengths -->
        </div>
      </div>
    </section>""")

CLOSERS["minimal"] = ("""
    .close-min { text-align: center; border-top: 1px solid color-mix(in srgb, var(--ink) 12%, transparent); }
    .close-min h2 { font-size: clamp(2.2rem, 6vw, 4rem); max-width: 18ch; margin: 0 auto 1.5rem; }
""", """
    <section class="container close-min">
      <h2>A clear closing line, e.g. "Book your visit this week"</h2>
      <a class="btn" href="#contact">Book now</a>
    </section>""")

EXTRAS = {  # optional sections – picked when the request mentions them, otherwise sometimes at random
    "faq": (r"faq|question", """
    .faq details { border-bottom: 1px solid color-mix(in srgb, var(--ink) 15%, transparent); padding-block: 1rem; }
    .faq summary { cursor: pointer; font-weight: 700; font-size: 1.1rem; min-height: 44px; display: flex; align-items: center; }
    .faq details p { color: var(--muted); margin-top: .5rem; }
""", """
    <section id="faq" class="container faq">
      <h2>Questions people ask</h2>
      <details><summary>Question customers really ask?</summary><p>Clear, specific answer.</p></details>
      <!-- 4–5 questions -->
    </section>"""),
    "steps": (r"how it works|steps|process", """
    .steps { list-style: none; display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.2rem; margin-top: 2rem; counter-reset: s; }
    .steps li { background: var(--tint); border-radius: var(--radius); padding: 1.5rem; counter-increment: s; }
    .steps li::before { content: counter(s); display: grid; place-items: center; width: 42px; height: 42px; border-radius: 50%; background: var(--brand); color: var(--on-brand); font-weight: 800; margin-bottom: .8rem; }
    .steps p { color: var(--muted); }
    @media (max-width: 760px) { .steps { grid-template-columns: 1fr; } }
""", """
    <section id="how" class="container">
      <h2>How it works</h2>
      <ol class="steps"><li><h3>Step name</h3><p>One line.</p></li><li><h3>Step name</h3><p>One line.</p></li><li><h3>Step name</h3><p>One line.</p></li></ol>
    </section>"""),
    "gallery": (r"gallery|portfolio|work|photos", """
    .gallery { display: grid; grid-template-columns: repeat(4, 1fr); grid-auto-rows: 160px; gap: .8rem; margin-top: 2rem; }
    .gallery .art:nth-child(1) { grid-column: span 2; grid-row: span 2; }
    .gallery .art:nth-child(4) { grid-column: span 2; }
    @media (max-width: 760px) { .gallery { grid-template-columns: 1fr 1fr; } }
""", """
    <section id="gallery" class="container">
      <h2>Recent work</h2>
      <div class="gallery" aria-hidden="true">
        <div class="art"><span>Project or item</span></div><div class="art alt"><span>Project or item</span></div><div class="art"><span>Project or item</span></div>
        <div class="art alt"><span>Project or item</span></div><div class="art"><span>Project or item</span></div><div class="art alt"><span>Project or item</span></div>
      </div>
    </section>"""),
    "team": (r"team|staff|doctor|stylist|trainer|teacher|founder", """
    .team { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr)); gap: 1.2rem; margin-top: 2rem; }
    .person { text-align: center; background: var(--tint); border-radius: var(--radius); padding: 1.6rem; }
    .avatar { width: 84px; height: 84px; border-radius: 50%; margin: 0 auto 1rem; display: grid; place-items: center; font-family: var(--display); font-size: 1.8rem;
              background: linear-gradient(140deg, var(--brand), var(--brand-2)); color: var(--on-brand); }
    .person p { color: var(--muted); }
""", """
    <section id="team" class="container">
      <h2>Meet the team</h2>
      <div class="team"><div class="person"><div class="avatar" aria-hidden="true">AB</div><h3>Full name</h3><p>Role · years of experience</p></div><!-- 3 people --></div>
    </section>"""),
    "hours": (r"hours|timing|direction|location|map|parking", """
    .hours { display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; align-items: start; }
    .hours table { width: 100%; border-collapse: collapse; }
    .hours td { padding: .7rem 0; border-bottom: 1px solid color-mix(in srgb, var(--ink) 12%, transparent); }
    .hours td:last-child { text-align: right; font-weight: 600; }
    @media (max-width: 760px) { .hours { grid-template-columns: 1fr; } }
""", """
    <section id="hours" class="container hours">
      <div><h2>Opening hours</h2><p class="lead">Landmark-style directions: near which station or landmark.</p>
        <a class="btn btn-ghost" href="https://maps.google.com/?q=BUSINESS+AREA+Mumbai">Get directions</a></div>
      <table><tr><td>Mon – Fri</td><td>10 am – 8 pm</td></tr><tr><td>Saturday</td><td>10 am – 9 pm</td></tr><tr><td>Sunday</td><td>11 am – 6 pm</td></tr></table>
    </section>"""),
    "trust": (r"trust|certified|award|partner|insurance", """
    .trust { display: flex; flex-wrap: wrap; justify-content: center; gap: .8rem 1.4rem; padding-block: 1.5rem; color: var(--muted); font-weight: 600; }
    .trust span { border: 1px solid color-mix(in srgb, var(--ink) 15%, transparent); border-radius: 999px; padding: .45rem 1rem; }
""", """
    <div class="container trust"><span>Trust signal (e.g. 4.9 ★ Google)</span><span>Trust signal</span><span>Trust signal</span><span>Trust signal</span></div>"""),
}

_BANNER_CSS = """
    .offer-bar { background: var(--accent); color: #1b1b1b; text-align: center; font-weight: 700; padding: .55rem 1rem; }
"""
_BANNER_HTML = """<div class="offer-bar">Offer line for first-time customers, e.g. "15% off your first visit"</div>"""

_build_v1 = build_starter


def build_starter(request: str, seed: str | None = None) -> tuple:   # noqa: F811 – v2 adds extras and section order
    t0 = (request or "").lower()
    pick = random.Random(int(hashlib.md5(("f" + (seed or request or "")).encode()).hexdigest()[:8], 16)).random()
    # Zhessor house style: multi-section showroom pages for shops with
    # ranges, brands, branches – or whenever someone asks for that look.
    showroom = re.search(r"hi.?tech|showroom style|corporate|branches|dealer|distributor|electronics|computer|laptop|mobile|"
                         r"appliance|hardware|furniture store|multi.?brand|wholesale", t0)
    if showroom or (re.search(r"store|shop|showroom|retail|clinic|hospital|school|institute", t0) and pick < 0.45):
        from .web_showroom import build_showroom
        return build_showroom(request, seed)
    html, desc = _build_v1(request, seed)
    rng = random.Random(int(hashlib.md5(("x" + (seed or request or "")).encode()).hexdigest()[:8], 16))
    t = (request or "").lower()
    wanted = [k for k, (rx, _, _) in EXTRAS.items() if re.search(rx, t)]
    pool = [k for k in EXTRAS if k not in wanted]
    rng.shuffle(pool)
    extras = (wanted + pool[: rng.choice([0, 1, 1, 2])])[:3]
    css = "".join(EXTRAS[k][1] for k in extras)
    blocks = "\n".join(EXTRAS[k][2] for k in extras)
    html = html.replace("<!--zoha-extras-->", (blocks + "\n") if extras else "", 1)   # extras go before the closing call to action
    if re.search(r"offer|discount|first.?time|deal", t) or rng.random() < 0.2:
        css += _BANNER_CSS
        html = html.replace('<header class="site-header">', _BANNER_HTML + '\n  <header class="site-header">', 1)
        extras.append("offer banner")
    if css:
        html = html.replace("\n  </style>", css + "\n  </style>", 1)
    if rng.random() < 0.35:   # story before offerings on some pages
        s0 = html.find('<section id="story"')
        s1 = html.find("</section>", s0) + len("</section>")
        o0 = html.find('<section id="offer"')
        if 0 < o0 < s0:
            story = html[s0:s1]
            html = html[:s0] + html[s1:]
            o0 = html.find('<section id="offer"')
            html = html[:o0] + story + "\n\n    " + html[o0:]
            desc += ", story first"
    if extras:
        desc += ", extras: " + ", ".join(extras)
    return html, desc


def count_layouts() -> int:
    """How many different page layouts the kit can build (before palettes and fonts)."""
    n_extras = 1 + len(EXTRAS) + len(EXTRAS) * (len(EXTRAS) - 1) // 2
    return len(HEROES) * len(OFFERS) * len(STORIES) * len(REVIEWS) * len(CLOSERS) * n_extras * 2 * 2
