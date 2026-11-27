# Changelog

All notable changes to Zoha. Versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-28
First public release.

- Voice-first desktop assistant for Windows (wake word, speech in and out, text mode).
- Always asks before acting: shutdown, restart, sleep and website changes need a clear yes.
- Builds checked web pages (starter templates, 3D theme, lint and auto-fix).
- Bring your own brain: Gemini, any OpenAI-compatible API, or any local Ollama model.
- Plugins folder and an optional website/CMS plugin.
- Skills are plain Markdown files with a name/description header; `python -m zoha.skill_install install <url>` adds one.
- Publish a page online with a yes (`site_publish`, Netlify), learnable routines, a business desk plugin (quotations, unpaid invoices, follow-up drafts) and an embeddable chat widget server.
- 92+ automated tests and GitHub Actions CI (Windows and Ubuntu).
- 30-second demo video (`docs/demo/`) and a docs site (MkDocs, published by GitHub Actions).
- Apache-2.0 licence.
