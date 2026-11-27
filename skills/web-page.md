---
name: web-page
description: Write one complete, mobile-first web page for a real business: distinctive design, local SEO, no placeholders.
---

# Skill: web pages (agency quality)

You are writing a page the way a senior agency designer-developer would: for ONE real business,
in Mumbai/India, that has to look distinctive and work perfectly on a phone.

## 1. Think before writing (do this silently, don't print it)
- Who is the business, who are its customers, what ONE action should a visitor take (call, WhatsApp, book, buy)?
- Pick a visual identity that fits THIS business: a boutique in Bandra ≠ a CA firm in Thane ≠ a gym in Andheri.
- Decide the sections the business actually needs. Typical: hero → offerings → why us / story → proof
  (testimonials, numbers, clients) → location & contact → footer. Leave out what doesn't fit.

## 2. Look
- Fonts: one deliberate Google Fonts pairing loaded with <link> (e.g. "Fraunces + Inter", "Playfair Display + Manrope",
  "Space Grotesk + IBM Plex Sans", "DM Serif Display + DM Sans"). Never Helvetica/Arial/system-only.
- Colour: 4–5 CSS variables with names (--ink, --paper, --brand, --accent, --muted). Fit the brand; avoid the
  default "navy + gold" and "cream + terracotta" looks unless the brief asks.
- Type scale: clamp() sizes, e.g. h1 clamp(2.2rem, 6vw, 4rem); body 1rem–1.125rem, line-height 1.6; max line ~70ch.
- Spacing: generous (sections padding-block clamp(3rem, 8vw, 6rem)); one container max-width ~1120px.
- One memorable element (a bold hero headline, an unusual layout, a signature colour) – everything else calm.
- Buttons: real hierarchy (one primary, one secondary). Border-radius consistent, not on everything the same.

## 2b. Looks that scream "AI made this" – avoid unless the user asks
- Cream background + big serif + terracotta/clay accent. Near-black page + one neon green accent.
- Every section chopped into identical rounded cards with the same soft grey shadow and gradient blobs.
- A tiny ALL-CAPS label above every heading; "01 / 02 / 03" numbers on things that aren't steps;
  "→" glued to every button; emoji as icons on every card.
- Fade-and-slide-up animation on every section. One deliberate moment beats ten small effects.

## 3. Content (most AI pages fail here)
- Real, specific copy for this business: concrete products/services, neighbourhood, timings, what makes it different.
- India: ₹ with Indian grouping (₹1,499 · ₹12,500), +91 98xxx xxxxx, Indian addresses, IST timings, © {year}.
- No lorem ipsum, no "Welcome to our website", no "We are the best", no fake awards.
- Testimonials: short, believable, first name + area ("— Priya, Khar West").
- Call to action text says exactly what happens: "WhatsApp us", "Book a fitting", not "Submit".

## 4. Build rules
- ONE self-contained file: <style> in head, <script> before </body>, no frameworks, no external JS.
- Semantic HTML: header/nav/main/section/footer, one h1, headings in order.
- No random stock photos (picsum/unsplash show laptops on a salon site and make the page look dead). Use the
  starter's colourful .art tiles with a short label ("Bridal & party styling") until the client sends real photos.
  Real photos later: always alt, width, height, loading="lazy" (except the hero image).
- Make it feel ALIVE: Zoha's starter is a different design every time (hero style, offering layout, palette, fonts).
  Keep that design and fill it with rich, specific content – never fall back to a plain or generic layout.
- Mobile first. Nav MUST have a working hamburger on small screens (pattern below). Never just hide links.
- Forms: <label> for every input, inline success/error message (pattern below). Never alert()/prompt().
- WhatsApp button: <a href="https://wa.me/9198XXXXXXXX?text=Hi">WhatsApp us</a> (keep the X's if the number is unknown).
- Accessibility: contrast ≥ 4.5:1, :focus-visible styles, tap targets ≥ 44px, prefers-reduced-motion respected.
- Motion: at most one subtle entrance or hover effect. No animation on every card.

## 4b. Local SEO (every business page – this is what gets them found on Google)
- <title>: "Business – what they do in Area, City" (≤ 60 chars). <meta name="description"> 140–160 chars, specific.
- Open Graph: og:title, og:description, og:type=website (so WhatsApp/Instagram link previews look good).
- One JSON-LD block of type LocalBusiness (or a better subtype: Store, ClothingStore, HomeAndConstructionBusiness…)
  with name, address (streetAddress, addressLocality, postalCode, addressCountry "IN"), telephone, openingHours, url.
- The area name appears naturally in the h1 or hero text and in the contact section ("in Bandra West, Mumbai").

## 5. Patterns to reuse (these are correct – adapt names, keep the logic)
Nav – links visible on desktop, hamburger only on phones (the .menu is NOT hidden outside the media query):
```html
<header class="site-header"><nav class="container nav">
  <a class="logo" href="#">Brand</a>
  <button class="menu-btn" aria-expanded="false" aria-controls="menu" aria-label="Open menu">☰</button>
  <ul id="menu" class="menu"><li><a href="#about">About</a></li>…</ul>
</nav></header>
<script>
const btn = document.querySelector('.menu-btn'), menu = document.getElementById('menu');
btn.addEventListener('click', () => {
  const open = btn.getAttribute('aria-expanded') === 'true';
  btn.setAttribute('aria-expanded', String(!open));
  menu.classList.toggle('open', !open);
});
</script>
```
```css
.nav{display:flex;align-items:center;justify-content:space-between;position:relative}
.menu{display:flex;gap:2rem;list-style:none}
.menu-btn{display:none}
@media (max-width: 760px){
  .menu-btn{display:inline-flex;min-height:44px}
  .menu{display:none;flex-direction:column}
  .menu.open{display:flex}
}
```
Form with inline message:
```html
<form id="enquiry" novalidate>
  <label for="name">Your name</label><input id="name" name="name" required>
  <label for="phone">Phone</label><input id="phone" name="phone" type="tel" required>
  <button type="submit">Send enquiry</button>
  <p class="form-msg" role="status" aria-live="polite"></p>
</form>
<script>
document.getElementById('enquiry').addEventListener('submit', e => {
  e.preventDefault();
  const f = e.target, msg = f.querySelector('.form-msg');
  if (!f.checkValidity()) { msg.textContent = 'Please fill your name and phone.'; return; }
  msg.textContent = 'Thanks! We will call you back within a day.';
  f.reset();
});
</script>
```
WhatsApp floating button:
```html
<a class="wa-float" href="https://wa.me/9198XXXXXXXX?text=Hi%2C%20I%20saw%20your%20website" aria-label="Chat on WhatsApp">WhatsApp</a>
```
```css
.wa-float{position:fixed;right:1rem;bottom:1rem;min-height:48px;padding:.8rem 1.1rem;border-radius:999px;background:#25D366;color:#063;font-weight:600;text-decoration:none;z-index:50}
```
Focus that stays visible (never just `outline:none`):
```css
a:focus-visible,button:focus-visible,input:focus-visible,textarea:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
```
Hero image (above the fold – NOT lazy):
```html
<img src="https://picsum.photos/seed/hero/1200/800" alt="…" width="1200" height="800" fetchpriority="high">
```
Reduced motion:
```css
@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
```

## Common mistakes to avoid (seen in earlier drafts)
- Hiding the .menu with display:none OUTSIDE the @media query → desktop has no navigation at all.
- Grey body text (--muted) on a dark section → unreadable. In dark sections set p { color: rgba(255,255,255,.8) }.
- `outline: none` on inputs without a :focus-visible style.
- loading="lazy" on the hero image (slows the first screen).
- `display: contents` on the .container (kills its max-width and padding).
- Inline style="" attributes – use classes.
- Unrealistic prices or facts: if unsure of a real price, write "Starting at ₹X" with a believable number or "Call for a quote".
- Forgetting the WhatsApp button.
- Inconsistent facts: opening hours, phone, address and years must be IDENTICAL everywhere (hours table, contact, JSON-LD).
- The owner's quote in "Our story" must sound like the owner, not a customer review.
- Misspelling the area: use the exact spelling from the request (Ghatkopar, not Ghatkopur).
- Pale brand colours (gold, pastel) with white text on buttons – unreadable. (Zoha fixes contrast automatically, but pick readable colours.)
- Leaving starter example text such as "Offer line for…", "Package name", "Trust signal".

## Checklist (check every line before finishing)
- [ ] Copy is specific to this business; no placeholder or generic slogans
- [ ] ₹ prices, +91 numbers, Indian places, © {year}
- [ ] Google Fonts pairing loaded and used; colour variables used everywhere
- [ ] Desktop shows the nav links; hamburger only below 760px and it toggles aria-expanded
- [ ] WhatsApp button present (wa.me link)
- [ ] Text readable on every background (light text on dark sections)
- [ ] Every input has a label; no alert()/prompt(); inline messages
- [ ] Images have alt, width, height, loading="lazy"
- [ ] One h1, semantic sections, focus styles, reduced motion
- [ ] <title>, meta description, og: tags and a LocalBusiness JSON-LD block
- [ ] All tags closed; the file ends with </html>
