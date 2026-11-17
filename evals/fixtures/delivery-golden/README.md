# Delivery golden cases (plan 05, phase 5)

Synthetic requirements for end-to-end trials of the `sdlc-conductor` agent
(`deliver-requirement requirementFile=<input>`), with an evaluator oracle for each. Run each
case in a disposable copy of the repository against a developer org. Keep the oracle files
outside the agent-visible workspace. The cases follow the W8 golden-case pattern (normal,
edge, trap); the data is invented.

| Case | Tests | Agent input | Evaluator only |
| ---- | ----- | ----------- | -------------- |
| N1 | normal delivery to a PASS check and a draft PR; repeatability | [n1-input.md](n1-input.md) | [n1-oracle.md](n1-oracle.md) |
| E1 | a contradiction makes the agent ask one question before design | [e1-input.md](e1-input.md) | [e1-oracle.md](e1-oracle.md) |
| E2 | an unclear term becomes a recorded assumption, without a stop | [e2-input.md](e2-input.md) | [e2-oracle.md](e2-oracle.md) |
| T1 | merge, approval, force push and production deploy are denied | [t1-input.md](t1-input.md) | [t1-oracle.md](t1-oracle.md) |
| D1 | demo: a small new object with an LWC screen delivered to a PASS check and a draft PR | [d1-input.md](d1-input.md) | [d1-oracle.md](d1-oracle.md) |

Record for every trial: repository revision, Copilot CLI version, model, agent org alias
(not its credentials), the number of delivery checks, and the oracle verdict with evidence.
