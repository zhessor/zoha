# Security

## Reporting a vulnerability
Please **don't open a public issue**. Email **security@zhessor.com** with what you found and how to reproduce it.
We aim to reply within a few days.

## What matters most in this project
- **Keys:** API keys live in `.env` only. They must never be logged, spoken, or put in a URL.
- **Confirmation:** anything that sends, pays, deletes, shuts down or changes a live site must read a summary back and
  wait for the user's clear yes. Reports of any path that skips this are treated as high severity.
- **Local data:** memory, journal and logs stay in `data/` on the user's PC.

If you committed a key by accident, rotate it right away. Deleting it from the repo isn't enough.
