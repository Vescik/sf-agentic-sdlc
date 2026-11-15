# sf-agentic-sdlc — instructions for Claude Code

@AGENTS.md

- Goal and current plan: `docs/handoff-2026-11-15.md` (base = sf-extension-harness, donor = W8-SDLC patterns; first step = Copilot CLI spike).
- Target runtime is **GitHub Copilot CLI**, not VS Code. The inherited agent/hook files still use the VS Code shape until the port is done.
- Local setup on the owner's Mac: Python venv at `.venv` (Python 3.11), `npm ci --ignore-scripts`, commit-message hook installed. Verification gates: SETUP.md § 4.
- Synthetic data only. Do not copy `W8_*` programme files here; copy patterns (contracts, schemas) instead.
