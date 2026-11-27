"""
"Showroom" page family – Zhessor's house style for multi-branch shops and dealers, as one self-contained HTML page.

What makes it feel like a real business site instead of a template:
- a top bar (phone, email, hours, towns) + sticky header with a products mega menu
- a scroll-pinned hero: 3 full-bleed slides that dissolve into each other as you scroll, with progress rails
- a navy stats band, an About area with its own sticky sub-nav (Overview · Journey · Leadership · Locations)
- a horizontal navy journey timeline, a proprietor card with a handwritten signature
- branch cards with a LIVE open/closed badge worked out from the hours in India time
- category tiles, brand wall with "authorised" badges, services + a business-quote band
- an enquiry form that opens WhatsApp with the message already typed
Photos: real photos go in the .photo slots (data-photo). Until then each slot is a styled, labelled panel.
"""
from __future__ import annotations

import hashlib
import random

PALETTES = {  # brand, brand-hover, brand-bright, brand-wash, navy, navy-2, bg
    "cobalt":  ("#0e3f8f", "#0b3373", "#2563c9", "#e6eefb", "#071834", "#0c2348", "#f3f5f9"),
    "emerald": ("#0f6b4f", "#0b5640", "#16a37a", "#e3f4ee", "#06231b", "#0b3328", "#f3f7f5"),
    "maroon":  ("#8a1c2b", "#701522", "#c23b4f", "#fbe9ec", "#1d0b10", "#2d1219", "#f8f4f4"),
    "teal":    ("#0d5c6b", "#0a4a57", "#1592a8", "#e2f3f6", "#05222a", "#0a323d", "#f2f7f8"),
    "graphite": ("#1f2937", "#111827", "#d97706", "#fdf3e1", "#0b0f16", "#151b26", "#f5f5f4"),
}

CSS = """
    :root { --bg: {bg}; --surface: #ffffff; --surface-2: #e9edf4; --line: #dbe1ea; --ink: #0b1526; --ink-2: #344055; --muted: #5b6678;
            --brand: {brand}; --brand-hover: {hover}; --brand-bright: {bright}; --brand-wash: {wash}; --navy: {navy}; --navy-2: {navy2};
            --on-dark: #e8eef8; --on-dark-muted: #a9b7cf; --ok: #138a4c; --ok-wash: #e3f4ea;
            --paper: #ffffff; --tint: {wash}; --brand-2: {bright}; --accent: {bright}; --on-brand: #ffffff; --heading: #0b1526;
            --sans: 'Archivo', system-ui, sans-serif; --mono: 'Red Hat Mono', ui-monospace, monospace; --sign: 'Caveat', cursive; }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; scroll-padding-top: 132px; }
    body { font-family: var(--sans); background: var(--bg); color: var(--ink); line-height: 1.6; -webkit-font-smoothing: antialiased; }
    img { max-width: 100%; height: auto; display: block; }
    a { color: inherit; }
    .wrap { width: min(1280px, 100% - 2.5rem); margin-inline: auto; }
    h1, h2, h3 { line-height: 1.08; letter-spacing: -.02em; }
    h2 { font-size: clamp(1.9rem, 4vw, 2.6rem); }
    .flush { padding: 0; } .pt0 { padding-top: 0; } .mt1 { margin-top: 1rem; } .mt2 { margin-top: 2rem; }
    .eyebrow.on-dark { color: var(--on-dark-muted); }
    .eyebrow { font-size: .8rem; font-weight: 600; letter-spacing: .14em; color: var(--brand); }
    .sub { color: var(--muted); max-width: 60ch; margin-top: .6rem; font-size: 1.05rem; }
    section { padding-block: clamp(3.5rem, 8vw, 6rem); }
    .btn { display: inline-flex; align-items: center; gap: .5rem; min-height: 48px; padding: .8rem 1.4rem; border-radius: 8px; font-weight: 600;
           text-decoration: none; background: var(--brand); color: #fff; border: 1px solid var(--brand); transition: background .2s, transform .1s; }
    .btn:hover { background: var(--brand-hover); }
    .btn:active { transform: translateY(1px); }
    .btn.light { background: #fff; color: var(--brand); border-color: #fff; }
    .btn.ghost { background: transparent; color: #fff; border-color: rgba(255,255,255,.4); }
    :focus-visible { outline: 2px solid var(--brand-bright); outline-offset: 3px; }

    /* top bar + header */
    .topbar { background: var(--navy); color: var(--on-dark-muted); font-size: .85rem; }
    .topbar .wrap { display: flex; flex-wrap: wrap; gap: .4rem 1.4rem; justify-content: space-between; padding-block: .5rem; }
    .topbar a { color: var(--on-dark); text-decoration: none; }
    .site-header { position: sticky; top: 0; z-index: 40; background: rgba(255,255,255,.92); backdrop-filter: blur(10px); border-bottom: 1px solid var(--line); }
    .nav { display: flex; align-items: center; justify-content: space-between; gap: 1rem; min-height: 76px; position: relative; }
    .logo { display: flex; align-items: center; gap: .6rem; font-weight: 800; font-size: 1.2rem; text-decoration: none; color: var(--ink); }
    .logo-mark { width: 38px; height: 38px; border-radius: 10px; display: grid; place-items: center; background: var(--brand); color: #fff; font-weight: 800; }
    .menu { display: flex; align-items: center; gap: 1.6rem; list-style: none; }
    .menu > li { position: relative; }
    .menu a { display: inline-flex; align-items: center; min-height: 44px; text-decoration: none; color: var(--ink-2); font-weight: 500; }
    .menu a:hover { color: var(--brand); }
    .menu .btn { color: #fff; }
    .mega { position: absolute; top: 100%; left: -1rem; width: min(640px, 80vw); background: #fff; border: 1px solid var(--line); border-radius: 12px;
            box-shadow: 0 24px 50px rgba(7,24,52,.14); padding: 1rem; display: grid; grid-template-columns: repeat(2, 1fr); gap: .25rem;
            opacity: 0; visibility: hidden; transform: translateY(6px); transition: .2s ease; }
    .has-mega:hover .mega, .has-mega:focus-within .mega { opacity: 1; visibility: visible; transform: none; }
    .mega a { padding: .5rem .7rem; border-radius: 8px; width: 100%; }
    .mega a:hover { background: var(--brand-wash); }
    .menu-btn { display: none; min-height: 44px; min-width: 44px; border: 1px solid var(--line); background: #fff; border-radius: 8px; font-size: 1.2rem; }

    /* photo slots: real photos later (data-photo), styled panels until then */
    .photo { position: relative; overflow: hidden; border-radius: 12px; background:
               radial-gradient(120% 90% at 85% 10%, color-mix(in srgb, var(--brand-bright) 55%, transparent), transparent 60%),
               linear-gradient(150deg, var(--navy-2), var(--brand)); color: #fff; }
    .photo::after { content: attr(data-label); position: absolute; left: 1rem; bottom: .9rem; font-weight: 600; font-size: .95rem; opacity: .9; }
    .photo img { width: 100%; height: 100%; object-fit: cover; }
    .photo:has(img)::after { display: none; }
    .branch .btn { justify-self: start; }

    /* scroll-pinned hero */
    .hero { position: relative; height: 300vh; background: var(--navy); padding: 0; }
    .hero-stage { position: sticky; top: 76px; height: calc(100dvh - 76px); min-height: 540px; overflow: hidden; color: #fff; }
    .slide { position: absolute; inset: 0; opacity: 0; transition: opacity .9s ease; }
    .slide.on { opacity: 1; }
    .slide .photo { position: absolute; inset: 0; border-radius: 0; transform: scale(1.06); transition: transform 1.6s cubic-bezier(.16,1,.3,1); }
    .slide.on .photo { transform: scale(1); }
    .slide .photo::after { display: none; }
    .shade { position: absolute; inset: 0; background: linear-gradient(90deg, rgba(7,24,52,.92), rgba(7,24,52,.45) 55%, transparent),
             linear-gradient(0deg, rgba(7,24,52,.85), transparent 60%); }
    .hero-copy { position: absolute; inset: auto 0 0 0; padding-bottom: clamp(2rem, 6vh, 4rem); }
    .hero-copy .tag { font-size: .8rem; letter-spacing: .18em; color: var(--on-dark-muted); font-weight: 600; }
    .hero-copy h1, .hero-copy h2 { font-size: clamp(2.3rem, 6vw, 4.6rem); max-width: 16ch; margin-top: .8rem; color: #fff; }
    .hero-copy p { max-width: 38rem; margin-top: 1rem; color: var(--on-dark); font-size: 1.1rem; }
    .hero-copy .cta { display: flex; flex-wrap: wrap; gap: .75rem; margin-top: 1.6rem; }
    .slide-copy { display: none; }
    .slide-copy.on { display: block; animation: up .5s cubic-bezier(.16,1,.3,1); }
    @keyframes up { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: none; } }
    .rails { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; max-width: 520px; margin-top: 2.2rem; }
    .rails button { background: none; border: 0; color: var(--on-dark-muted); text-align: left; font: inherit; font-size: .9rem; cursor: pointer; min-height: 44px; }
    .rails button[aria-selected="true"] { color: #fff; }
    .rail { display: block; height: 3px; border-radius: 3px; background: rgba(255,255,255,.25); overflow: hidden; margin-bottom: .55rem; }
    .rail i { display: block; height: 100%; background: #fff; transform-origin: 0 50%; transform: scaleX(0); }
    .count { position: absolute; right: 2rem; bottom: 2.4rem; font-family: var(--mono); color: rgba(255,255,255,.8); }

    /* stats band */
    .statsband { background: var(--navy-2); color: #fff; padding-block: 2.2rem; }
    .statsband .wrap { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; }
    .statsband strong { display: block; font-size: clamp(1.8rem, 4vw, 2.6rem); font-family: var(--mono); font-weight: 600; }
    .statsband span { color: var(--on-dark-muted); font-size: .95rem; }

    /* about + sticky sub-nav */
    .subnav { position: sticky; top: 76px; z-index: 30; background: var(--bg); border-bottom: 1px solid var(--line); }
    .subnav .wrap { display: flex; gap: 1.6rem; overflow-x: auto; }
    .subnav a { flex: none; padding-block: .9rem; text-decoration: none; color: var(--muted); font-weight: 600; border-bottom: 2px solid transparent; min-height: 44px; display: inline-flex; align-items: center; }
    .subnav a.on { color: var(--brand); border-color: var(--brand); }
    .overview { display: grid; grid-template-columns: 1.1fr 1fr; gap: clamp(2rem, 5vw, 4rem); align-items: start; }
    .values { display: grid; gap: .9rem; margin-top: 1.6rem; }
    .value { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 1rem 1.2rem; }
    .value strong { display: block; }
    .value span { color: var(--muted); }
    .mosaic { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 200px 160px; gap: .8rem; }
    .mosaic .photo:first-child { grid-row: span 2; }
    .journey { background: var(--navy); color: #fff; }
    .journey .sub { color: var(--on-dark-muted); }
    .tl { list-style: none; display: grid; grid-template-columns: repeat(4, 1fr); gap: 1.4rem; margin-top: 2.5rem; }
    .tl li { position: relative; padding-top: 1.4rem; border-top: 1px solid rgba(255,255,255,.2); }
    .tl li::before { content: ""; position: absolute; top: -6px; left: 0; width: 11px; height: 11px; border-radius: 50%; background: var(--brand-bright); box-shadow: 0 0 0 4px rgba(255,255,255,.12); }
    .tl .yr { font-family: var(--mono); font-size: 2.2rem; font-weight: 600; }
    .tl p { color: var(--on-dark-muted); margin-top: .4rem; }
    .leader { display: grid; grid-template-columns: 300px 1fr; gap: 2rem; align-items: center; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: clamp(1.4rem, 4vw, 2.4rem); }
    .leader .photo { aspect-ratio: 4/5; }
    .leader blockquote { font-size: clamp(1.2rem, 2.4vw, 1.6rem); line-height: 1.45; }
    .sign { font-family: var(--sign); font-size: 2.4rem; color: var(--brand); margin-top: 1rem; }
    .role { color: var(--muted); }
    .branches { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(320px, 100%), 1fr)); gap: 1.2rem; margin-top: 2rem; }
    .branch { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }
    .branch .photo { height: 180px; border-radius: 0; }
    .branch .body { padding: 1.3rem; display: grid; gap: .5rem; }
    .status { display: inline-flex; align-items: center; gap: .45rem; width: fit-content; border-radius: 999px; padding: .25rem .75rem; font-size: .85rem; font-weight: 600; background: var(--surface-2); color: var(--muted); }
    .status::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
    .status.open { background: var(--ok-wash); color: var(--ok); }

    /* categories, brands, services */
    .cats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-top: 2rem; }
    .cat { text-decoration: none; display: block; }
    .cat .photo { aspect-ratio: 4/3; transition: transform .4s ease; }
    .cat:hover .photo { transform: scale(1.02); }
    .cat h3 { margin-top: .7rem; font-size: 1.1rem; }
    .cat p { color: var(--muted); font-size: .92rem; }
    .brands { display: grid; grid-template-columns: repeat(6, 1fr); gap: .8rem; margin-top: 2rem; }
    .brand { position: relative; display: grid; place-items: center; min-height: 84px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; font-weight: 800; letter-spacing: .02em; color: var(--ink-2); }
    .brand .auth { position: absolute; top: .45rem; right: .5rem; font-size: .66rem; font-weight: 700; color: var(--ok); background: var(--ok-wash); border-radius: 999px; padding: .1rem .45rem; }
    .services { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(260px, 100%), 1fr)); gap: 1rem; margin-top: 2rem; }
    .service { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 1.3rem; }
    .service .ico { width: 44px; height: 44px; border-radius: 10px; display: grid; place-items: center; background: var(--brand-wash); color: var(--brand); font-size: 1.3rem; margin-bottom: .8rem; }
    .service p { color: var(--muted); font-size: .95rem; }
    .quoteband { margin-top: 2rem; background: linear-gradient(120deg, var(--navy), var(--brand)); color: #fff; border-radius: 14px; padding: clamp(1.5rem, 4vw, 2.4rem);
                 display: flex; flex-wrap: wrap; gap: 1.2rem; align-items: center; justify-content: space-between; }
    .quoteband p { color: var(--on-dark); }

    /* contact */
    .contact { display: grid; grid-template-columns: 1fr 1.1fr; gap: clamp(2rem, 5vw, 4rem); }
    .card { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: clamp(1.4rem, 4vw, 2rem); }
    form { display: grid; gap: .8rem; }
    label { font-weight: 600; font-size: .95rem; }
    input, select, textarea { width: 100%; padding: .8rem; border: 1px solid var(--line); border-radius: 8px; font: inherit; background: #fff; color: var(--ink); }
    .form-msg { min-height: 1.4em; font-weight: 600; color: var(--brand); }

    footer { background: var(--navy); color: var(--on-dark-muted); padding-block: 3rem 2rem; }
    footer .cols { display: grid; grid-template-columns: 1.4fr 1fr 1fr 1fr; gap: 2rem; }
    footer strong { color: #fff; display: block; margin-bottom: .6rem; }
    footer a { color: var(--on-dark); text-decoration: none; display: block; padding-block: .2rem; }
    footer .legal { border-top: 1px solid rgba(255,255,255,.12); margin-top: 2rem; padding-top: 1.2rem; font-size: .9rem; }
    .wa-float { position: fixed; right: 1rem; bottom: 1rem; z-index: 50; min-height: 52px; padding: .85rem 1.2rem; border-radius: 999px;
                background: #25D366; color: #053d1c; font-weight: 800; text-decoration: none; box-shadow: 0 10px 26px rgba(0,0,0,.2); }

    @media (max-width: 980px) {
      .cats { grid-template-columns: repeat(2, 1fr); } .brands { grid-template-columns: repeat(3, 1fr); }
      .overview, .contact, .leader { grid-template-columns: 1fr; } .tl { grid-template-columns: 1fr 1fr; }
      footer .cols { grid-template-columns: 1fr 1fr; } .statsband .wrap { grid-template-columns: 1fr 1fr; }
    }
    @media (max-width: 760px) {
      .topbar .hide-sm { display: none; }
      .menu-btn { display: inline-flex; align-items: center; justify-content: center; }
      .menu { display: none; position: absolute; top: 100%; left: 0; right: 0; flex-direction: column; align-items: stretch; gap: 0;
              background: #fff; padding: .5rem 1.25rem 1rem; box-shadow: 0 14px 24px rgba(0,0,0,.12); }
      .menu.open { display: flex; }
      .mega { display: none; }
      .count { display: none; }
      .leader .photo { max-width: 260px; }
    }
    @media (max-width: 520px) { .tl, .cats { grid-template-columns: 1fr; } .brands { grid-template-columns: 1fr 1fr; } }
    @media (prefers-reduced-motion: reduce) { .hero { height: auto; } .hero-stage { position: relative; top: 0; } .slide, .slide .photo { transition: none; } }
"""

PAGE = """<!DOCTYPE html>
<html lang="en-IN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BUSINESS – what they sell or do in AREA</title>
  <meta name="description" content="140–160 characters: what the business offers, where (branches/towns), and why customers choose them.">
  <meta property="og:title" content="BUSINESS – AREA">
  <meta property="og:description" content="One specific sentence about the business.">
  <meta property="og:type" content="website">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&family=Red+Hat+Mono:wght@500;600&family=Caveat:wght@600&display=swap" rel="stylesheet">
  <style>{css}
  </style>
</head>
<body data-motion="none" data-family="showroom">
  <div class="topbar"><div class="wrap">
    <span><a href="tel:+9198XXXXXXXX">+91 98XXX XXXXX</a> · <a href="mailto:hello@example.in">hello@example.in</a></span>
    <span class="hide-sm">Mon–Sat 10 am – 8:30 pm · Town one · Town two</span>
  </div></div>
  <header class="site-header">
    <nav class="wrap nav" aria-label="Main">
      <a class="logo" href="#"><span class="logo-mark" aria-hidden="true">B</span>BUSINESS</a>
      <button class="menu-btn" aria-expanded="false" aria-controls="menu" aria-label="Open menu">☰</button>
      <ul id="menu" class="menu">
        <li><a href="#about">About us</a></li>
        <li class="has-mega"><a href="#products">Products</a>
          <div class="mega"><a href="#products">Category name</a><a href="#products">Category name</a><a href="#products">Category name</a><a href="#products">Category name</a><a href="#products">Category name</a><a href="#products">Category name</a></div></li>
        <li><a href="#brands">Brands</a></li>
        <li><a href="#services">Services</a></li>
        <li><a class="btn" href="#contact">Get a quote</a></li>
      </ul>
    </nav>
  </header>

  <main>
    <section class="hero" aria-label="Highlights">
      <div class="hero-stage">
        <div class="slide on"><div class="photo" data-label="Slide one photo"></div><div class="shade"></div></div>
        <div class="slide"><div class="photo" data-label="Slide two photo"></div><div class="shade"></div></div>
        <div class="slide"><div class="photo" data-label="Slide three photo"></div><div class="shade"></div></div>
        <div class="hero-copy"><div class="wrap">
          <p class="tag">BUSINESS · AREA · since 20XX</p>
          <div class="slide-copy on"><h1>Slide title for the main offer</h1><p>Two specific sentences about it.</p>
            <div class="cta"><a class="btn light" href="#products">Primary action</a><a class="btn ghost" href="https://wa.me/9198XXXXXXXX?text=Hi">Talk to us on WhatsApp</a></div></div>
          <div class="slide-copy"><h2>Slide title for the second offer</h2><p>Two specific sentences about it.</p>
            <div class="cta"><a class="btn light" href="#services">Primary action</a></div></div>
          <div class="slide-copy"><h2>Slide title for the third offer</h2><p>Two specific sentences about it.</p>
            <div class="cta"><a class="btn light" href="#contact">Primary action</a></div></div>
          <div class="rails" role="tablist" aria-label="Highlights">
            <button role="tab" aria-selected="true"><span class="rail"><i></i></span>Tab one</button>
            <button role="tab" aria-selected="false"><span class="rail"><i></i></span>Tab two</button>
            <button role="tab" aria-selected="false"><span class="rail"><i></i></span>Tab three</button>
          </div>
        </div></div>
        <p class="count"><b>01</b> / 03</p>
      </div>
    </section>

    <div class="statsband"><div class="wrap">
      <div><strong>Since 20XX</strong><span>serving AREA</span></div>
      <div><strong>2</strong><span>branches</span></div>
      <div><strong>12</strong><span>product categories</span></div>
      <div><strong>25+</strong><span>brands</span></div>
    </div></div>

    <section id="about" class="flush">
      <nav class="subnav" aria-label="About"><div class="wrap">
        <a href="#overview" class="on">Overview</a><a href="#journey">Journey</a><a href="#leadership">Leadership</a><a href="#locations">Locations</a>
      </div></nav>
    </section>

    <section id="overview" class="wrap overview">
      <div>
        <p class="eyebrow">About BUSINESS</p>
        <h2>Who they are, in one strong line</h2>
        <p class="sub">Two or three specific sentences: how they started, who they serve and what they are known for.</p>
        <div class="values">
          <div class="value"><strong>Value name</strong><span>One line that proves it.</span></div>
          <div class="value"><strong>Value name</strong><span>One line that proves it.</span></div>
          <div class="value"><strong>Value name</strong><span>One line that proves it.</span></div>
        </div>
      </div>
      <div class="mosaic" aria-hidden="true">
        <div class="photo" data-label="Showroom photo"></div><div class="photo" data-label="Team photo"></div><div class="photo" data-label="Product photo"></div>
      </div>
    </section>

    <section id="journey" class="journey"><div class="wrap">
      <p class="eyebrow on-dark">Journey</p>
      <h2>How they grew</h2>
      <p class="sub">One line about the journey.</p>
      <ol class="tl">
        <li><div class="yr">20XX</div><p>Milestone in one line.</p></li>
        <li><div class="yr">20XX</div><p>Milestone in one line.</p></li>
        <li><div class="yr">20XX</div><p>Milestone in one line.</p></li>
        <li><div class="yr">Today</div><p>Where they are now.</p></li>
      </ol>
    </div></section>

    <section id="leadership" class="wrap">
      <p class="eyebrow">Leadership</p>
      <h2>The people behind the counter</h2>
      <div class="leader mt2">
        <div class="photo" data-label="Proprietor portrait"></div>
        <div>
          <blockquote>"A real line the owner would say about how they treat customers."</blockquote>
          <p class="sign">Proprietor name</p>
          <p class="role">Proprietor name · Founder, since 20XX</p>
        </div>
      </div>
    </section>

    <section id="locations" class="wrap pt0">
      <p class="eyebrow">Locations</p>
      <h2>Visit a branch</h2>
      <div class="branches">
        <article class="branch"><div class="photo" data-label="Branch photo"></div><div class="body">
          <span class="status" data-hours="Mo-Sa 10:00-20:30">Checking hours…</span>
          <h3>Branch name</h3><p>Full address, Town, PIN</p><p>Mon–Sat 10 am – 8:30 pm</p>
          <a class="btn" href="https://maps.google.com/?q=BUSINESS+AREA">Get directions</a></div></article>
        <!-- one card per branch -->
      </div>
    </section>

    <section id="products" class="wrap">
      <p class="eyebrow">Shop by category</p>
      <h2>What they stock</h2>
      <div class="cats">
        <a class="cat" href="#contact"><div class="photo" data-label="Category name"></div><h3>Category name</h3><p>One line: what's in it.</p></a>
        <!-- 8 or 12 categories -->
      </div>
    </section>

    <section id="brands" class="wrap pt0">
      <p class="eyebrow">Brands</p>
      <h2>Brands they deal in</h2>
      <div class="brands">
        <div class="brand">Brand name<span class="auth">Authorised</span></div>
        <!-- 6–18 brands; the 'Authorised' badge only where true -->
      </div>
    </section>

    <section id="services" class="wrap pt0">
      <p class="eyebrow">Services</p>
      <h2>More than a shop</h2>
      <div class="services">
        <div class="service"><div class="ico" aria-hidden="true">✦</div><h3>Service name</h3><p>One specific line.</p></div>
        <!-- 6–8 services -->
      </div>
      <div class="quoteband"><div><h3>Buying for an office, school or shop?</h3><p>One line about bulk or business quotes.</p></div>
        <a class="btn light" href="#contact">Get a business quote</a></div>
    </section>

    <section id="contact" class="wrap contact">
      <div>
        <p class="eyebrow">Contact</p>
        <h2>Tell us what you need</h2>
        <p class="sub">The form opens WhatsApp with your message ready – just press send.</p>
        <p class="mt1"><a href="tel:+9198XXXXXXXX">+91 98XXX XXXXX</a></p>
      </div>
      <div class="card">
        <form id="enquiry" novalidate data-wa="9198XXXXXXXX">
          <label for="name">Your name</label><input id="name" name="name" required>
          <label for="phone">Phone</label><input id="phone" name="phone" type="tel" required>
          <label for="need">Looking for</label><select id="need" name="need"><option>Category name</option><option>Something else</option></select>
          <label for="msg">Details (optional)</label><textarea id="msg" name="msg" rows="3"></textarea>
          <button class="btn" type="submit">Send on WhatsApp</button>
          <p class="form-msg" role="status" aria-live="polite"></p>
        </form>
      </div>
    </section>
  </main>

  <footer><div class="wrap">
    <div class="cols">
      <div><strong>BUSINESS</strong><p>One line about the business.</p></div>
      <div><strong>Explore</strong><a href="#about">About us</a><a href="#products">Products</a><a href="#services">Services</a></div>
      <div><strong>Branches</strong><a href="#locations">Branch name</a></div>
      <div><strong>Contact</strong><a href="tel:+9198XXXXXXXX">+91 98XXX XXXXX</a><a href="mailto:hello@example.in">hello@example.in</a></div>
    </div>
    <p class="legal">© YEAR BUSINESS · GSTIN on request</p>
  </div></footer>
  <a class="wa-float" href="https://wa.me/9198XXXXXXXX?text=Hi%2C%20I%20saw%20your%20website" aria-label="Chat on WhatsApp">WhatsApp</a>

  <script type="application/ld+json">
  {{"@context": "https://schema.org", "@type": "LocalBusiness", "name": "BUSINESS",
   "address": {{"@type": "PostalAddress", "streetAddress": "…", "addressLocality": "AREA", "postalCode": "4XXXXX", "addressCountry": "IN"}},
   "telephone": "+9198XXXXXXXX", "openingHours": "Mo-Sa 10:00-20:30"}}
  </script>
  <script>
    const btn = document.querySelector('.menu-btn'), menu = document.getElementById('menu');
    btn.addEventListener('click', () => {{
      const open = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!open));
      menu.classList.toggle('open', !open);
    }});
    menu.addEventListener('click', e => {{ if (e.target.closest('a')) {{ btn.setAttribute('aria-expanded', 'false'); menu.classList.remove('open'); }} }});

    // scroll-pinned hero: slides dissolve as you scroll through it; rails show progress, tap to jump
    (() => {{
      const hero = document.querySelector('.hero'), slides = [...hero.querySelectorAll('.slide')], copies = [...hero.querySelectorAll('.slide-copy')];
      const tabs = [...hero.querySelectorAll('.rails button')], bars = tabs.map(t => t.querySelector('i')), count = hero.querySelector('.count b');
      const n = slides.length, reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
      let cur = 0;
      const show = i => {{ if (i === cur) return; cur = i;
        slides.forEach((s, k) => s.classList.toggle('on', k === i)); copies.forEach((c, k) => c.classList.toggle('on', k === i));
        tabs.forEach((t, k) => t.setAttribute('aria-selected', String(k === i))); if (count) count.textContent = String(i + 1).padStart(2, '0'); }};
      const onScroll = () => {{
        const r = hero.getBoundingClientRect(), travel = hero.offsetHeight - innerHeight, p = Math.min(1, Math.max(0, -r.top / Math.max(1, travel)));
        if (!reduce) show(Math.min(n - 1, Math.floor(p * n)));
        bars.forEach((b, k) => b.style.transform = `scaleX(${{Math.min(1, Math.max(0, p * n - k))}})`);
      }};
      addEventListener('scroll', onScroll, {{ passive: true }}); onScroll();
      tabs.forEach((t, i) => t.addEventListener('click', () => {{
        if (reduce) return show(i);
        const top = hero.getBoundingClientRect().top + scrollY, travel = hero.offsetHeight - innerHeight;
        scrollTo({{ top: top + travel * ((i + .45) / n), behavior: 'smooth' }});
      }}));
    }})();

    // About sub-nav follows the section you're reading
    (() => {{
      const links = [...document.querySelectorAll('.subnav a')];
      const io = new IntersectionObserver(es => es.forEach(e => {{ if (e.isIntersecting) links.forEach(a => a.classList.toggle('on', a.getAttribute('href') === '#' + e.target.id)); }}),
                                          {{ rootMargin: '-40% 0px -55% 0px' }});
      links.forEach(a => {{ const s = document.querySelector(a.getAttribute('href')); if (s) io.observe(s); }});
    }})();

    // live open / closed for each branch, worked out in India time from data-hours="Mo-Sa 10:00-20:30"
    (() => {{
      const days = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
      const tick = () => document.querySelectorAll('.status[data-hours]').forEach(el => {{
        const m = el.dataset.hours.match(/(\\w\\w)-(\\w\\w)\\s+(\\d\\d):(\\d\\d)-(\\d\\d):(\\d\\d)/); if (!m) return;
        const now = new Date(new Date().toLocaleString('en-US', {{ timeZone: 'Asia/Kolkata' }}));
        const d = now.getDay(), a = days.indexOf(m[1]), b = days.indexOf(m[2]), mins = now.getHours() * 60 + now.getMinutes();
        const openDay = a <= b ? d >= a && d <= b : d >= a || d <= b, o = +m[3] * 60 + +m[4], c = +m[5] * 60 + +m[6];
        const open = openDay && mins >= o && mins < c, fmt = t => {{ const h = Math.floor(t / 60), mm = t % 60; return `${{(h % 12) || 12}}${{mm ? ':' + String(mm).padStart(2, '0') : ''}} ${{h < 12 ? 'am' : 'pm'}}`; }};
        el.classList.toggle('open', open);
        el.textContent = open ? `Open now · closes ${{fmt(c)}}` : `Closed · opens ${{fmt(o)}}`;
      }});
      tick(); setInterval(tick, 60000);
    }})();

    // the enquiry form opens WhatsApp with the message already written
    document.getElementById('enquiry').addEventListener('submit', e => {{
      e.preventDefault();
      const f = e.target, msg = f.querySelector('.form-msg');
      if (!f.checkValidity()) {{ msg.textContent = 'Please add your name and phone number.'; return; }}
      const text = `Hi, I'm ${{f.name.value}} (${{f.phone.value}}). I'm looking for: ${{f.need.value}}. ${{f.msg.value}}`.trim();
      msg.textContent = 'Opening WhatsApp with your message…';
      window.open(`https://wa.me/${{f.dataset.wa}}?text=${{encodeURIComponent(text)}}`, '_blank', 'noopener');
      f.reset();
    }});
  </script>
</body>
</html>
"""


def build_showroom(request: str, seed: str | None = None) -> tuple:
    rng = random.Random(int(hashlib.md5(("s" + (seed or request or "")).encode()).hexdigest()[:8], 16))
    name = rng.choice(list(PALETTES))
    brand, hover, bright, wash, navy, navy2, bg = PALETTES[name]
    css = CSS
    for k, v in {"brand": brand, "hover": hover, "bright": bright, "wash": wash, "navy": navy, "navy2": navy2, "bg": bg}.items():
        css = css.replace("{" + k + "}", v)
    return PAGE.format(css=css), f"showroom design (Zhessor house style), palette {name}"
