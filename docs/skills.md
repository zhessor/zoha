# Skills

A skill is a Markdown file in `skills/` that tells Zoha how you want something done (for example, how to write an email or what a good landing page includes). It is plain text and never runs code.

```markdown
---
name: email
description: Write short, polite emails
---

# Steps
...
```

Install one from a link:

```powershell
python -m zoha.skill_install install https://github.com/someone/repo/blob/main/skills/report.md
python -m zoha.skill_install list
```

The file must have a `name` and `description` header and be under 64 KB. An existing skill is never replaced unless you add `--force`.
