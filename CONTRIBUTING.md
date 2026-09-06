# Contributing to AJAA

Thank you for your interest in contributing.

## Ground Rules

1. **No personal data in the repository.** No real CVs, profiles, application histories, API keys, or session cookies. The CI job `test_no_personal_strings_in_source` enforces a denylist.

2. **Every job source adapter must include a `compliance` block.** AJAA refuses to load a source at runtime without one. The compliance block must state why automating the source is acceptable, when it was verified, and when it must be rechecked. Sources for LinkedIn, Indeed, Wuzzuf, Bayt, and sites with `Disallow: /` in `robots.txt` will not be accepted.

3. **Never automate LinkedIn.** This is an architectural decision, not a preference. PRs that add LinkedIn automation will be closed without review.

4. **The genericity suite must pass.** Any change to the matching, answering, or application pipeline must pass the 4-candidate CI suite. A feature that works for one occupation but not others is not ready.

5. **Secrets go in the OS keychain.** No `.env` files, no config files with values, no plaintext credentials anywhere in the codebase or test fixtures.

6. **The data directory must stay outside the repo.** `ajaa doctor` warns if it resolves inside the working tree. PRs that move data into the repo will not be accepted.

## Development Setup

```bash
git clone https://github.com/YOUR_USERNAME/ajaa
cd ajaa
uv sync --all-extras
uv run playwright install chromium
pre-commit install
uv run ajaa init
uv run ajaa doctor
```

## Running Tests

```bash
uv run pytest tests/unit          # unit tests
uv run pytest tests/adversarial   # injection corpus (always runs in CI)
uv run pytest tests/genericity    # 4-candidate suite (CI-blocking)
uv run pytest tests/integration   # mocked LLM
```

## Compliance Policy for Source Contributions

When adding a new job source:

1. Read the source site'\''s `robots.txt` and Terms of Service.
2. Fill in the `compliance` block in `configs/sources.example.yaml`.
3. Add a test that asserts the compliance block is present and not stale.
4. If the source prohibits automated access, submit a paste-in adapter instead.
