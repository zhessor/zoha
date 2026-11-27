# Contributing to Zoha

Thanks for helping. A few rules:

1. **New tools go in `plugins/`** unless they need core changes. See `plugins/README.md`.
2. **Safety first.** Anything that sends, pays, deletes, posts or changes a live system must read a summary
   back and wait for the user's yes. Never log or return keys.
3. **No personal data** in code, tests, issues or logs: no real names, phone numbers, emails or paths.
4. Run the tests before a PR: `pip install -e .[dev]` then `python -m pytest`. They need no microphone, GPU or internet
   and finish in about 20 seconds. On Windows also run `python selftest.py`; `python stress_test.py` runs all 10,000 phrases through the real model.
5. Keep PRs small and describe how you tested.

Security issues: please email security@zhessor.com instead of opening a public issue.
