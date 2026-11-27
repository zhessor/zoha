# Site Agent API (for the website/CMS plugin)

Zoha's `site_*` tools talk to **your** website through a small JSON API. Build these endpoints on
your site (any stack), set `SITE_API_URL`, `SITE_API_KEY` and `SITE_NAME` in `.env`, and Zoha can
read your content, enquiries and analytics and *propose* changes.

## Safety model (keep it when you implement this)

1. Zoha can never change the site directly. `POST /changes` only creates a **proposal** with a
   human-readable `summary`.
2. Zoha reads the summary out loud. Only when the user's very next words are a clear "yes" does it call
   `POST /changes/{id}/apply`. Anything else cancels it (`POST /changes/{id}/cancel`).
3. A proposal must expire on the server after **5 minutes** and be applicable **once** (return `410` when expired).
4. Auth: `Authorization: Bearer <SITE_API_KEY>`. Zoha never logs, speaks or puts the key in URLs. Rotate it if leaked.

## Endpoints (all JSON, relative to `SITE_API_URL`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/describe` | What content types exist and their editable fields, so the model knows what it can change |
| GET | `/read?type=&q=&id=` | Read items of a type (pricing, testimonials, posts…), optionally filtered |
| GET | `/enquiries?limit=5` | Latest contact-form enquiries and the unread count |
| POST | `/enquiries/{id}/status` | `{ "status": "archived" }` and similar |
| POST | `/enquiries/{id}/reply` | `{ "body": "..." }` → a reply **draft** with an id and summary |
| POST | `/replies/{id}/apply` | Send that draft (only after the user's yes) |
| GET | `/analytics?range=7d` | Visitors and KPIs vs the previous period, top pages and sources |
| POST | `/changes` | `{ type, action: create/update/delete, id?, fields, reason }` → proposal `{ id, summary, expiresAt }` |
| POST | `/changes/{id}/apply` | Apply a proposal (once, within 5 minutes) |
| POST | `/changes/{id}/cancel` | Drop a proposal |
| GET | `/changes?limit=10` | History of changes with status |
| POST | `/undo` | `{ "changeId": "..." }` → a proposal that reverses it (same confirm flow) |

Errors: return `{ "error": "plain sentence" }` with a normal HTTP status. Zoha reads the sentence to the user.
