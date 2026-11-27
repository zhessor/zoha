# Features

## Talk a website into existence
Say "Zoha, make a website for my bakery". If you give no details she asks one short question at a time (name, city, what you sell, colours), builds the page, tests it and opens it. Edit it by talking ("make the heading bigger", "add a menu section"). Then say "publish it".

Publishing needs a free Netlify personal access token in `.env` as `NETLIFY_TOKEN`. Zoha **asks first** and only publishes after a clear yes. Only the page and its own `_files` / `_photos` folders are uploaded. The token is never logged or spoken. The same page keeps the same address when you publish it again.

## Business desk (plugin)
`plugins/business_desk.py`, for small businesses:
- "Make a quotation for Mr Shah: cabinets 2 at 45000, hob 1 at 12k, 18 percent GST" makes a printable quotation in Documents/Zoha Quotes (use Print to save a PDF). Amounts use lakh/crore grouping.
- "Mr Shah owes 30000, due the 5th", "who hasn't paid?", "he paid" keep a simple list in `data/business.json` on your computer.
- "Write a follow-up for Mr Shah" (English or Hinglish) only **drafts** a message to copy. Zoha never sends anything for you.

## Routines (teach by showing)
"Learn this as work mode", then ask for your steps as usual (open your editor, set the volume, play music), then say "that's it". Later: "start work mode". Zoha records the **safe tool actions** you ask for, not mouse clicks. She never records shutdown, restart, sleep, website changes, publishing, file writing, browser actions or other routines, and tells you what she left out.

## Chat widget for a business website
A small chat and call-back box that answers only from the facts you give it.

```powershell
python -m zoha.widget_server init     # creates widget_config.json: fill in the business and the site's address
python -m zoha.widget_server serve
```
Paste the printed `<script>` tag into the website. It is public, so it is limited: only the origins in `allowed_origins` may use it, 12 messages a minute per visitor, a daily reply cap, short messages and answers, and it never invents prices. Call-back requests are saved to `data/widget_leads.jsonl`. Put it behind HTTPS (a small server or a tunnel) before using it on a real site. It uses the brain set in `.env`, so a cloud model costs money per reply; the cap is there to limit that.
