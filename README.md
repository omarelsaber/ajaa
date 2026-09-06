# AJAA — Autonomous Job Application Agent

> **Local-first · Open-source · Single-candidate · No telemetry**

AJAA automates the mechanical work of a job search. It discovers job listings through public APIs, scores them against your profile, and submits applications through deterministic browser automation — all running entirely on your machine.

## What it does

- **Discovers** jobs from public ATS APIs (Greenhouse, Lever, Ashby) and manual paste-in
- **Matches** them against your skill profile with explainable scores
- **Applies** through deterministic connectors (Greenhouse first; others in v0.2)
- **Asks you** when it hits anything uncertain — never fabricates or guesses
- **Audits** every action: full replay, fact citations, cost tracking

## What it never does

- Automate LinkedIn (ToS violation — use paste-in instead)
- Fabricate answers or generate behavioral anecdotes
- Accept terms of service on your behalf
- Send telemetry anywhere
- Store secrets outside your OS keychain

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/ajaa
cd ajaa
uv sync
uv run playwright install chromium
uv run ajaa init
uv run ajaa doctor
uv run ajaa serve
```

## Status

**v0.1 — Architecture validation.** Not yet released.

See [docs/IMPLEMENTATION-PLAN.md](docs/IMPLEMENTATION-PLAN.md) for the full architecture and implementation plan.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Key rule: any job source adapter must include a `compliance` block — the application refuses to load sources without one.

## License

TBD — see Q-BLOCK-05 in the implementation plan.
