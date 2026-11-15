---
last-verified: 2026-08-10
---

# Design guides — how WE do things

House conventions. The question this file answers is **"what is a review topic?"** — a
violation here is a conversation, not a bug (hard "cannot/must not" rules live in
`package-constraints.md`). Remaining planned sections (naming, architecture, code-review
expectations, decision format, commits) are outlined in `CONTENT-TODO.md` §3 and need the
team's real rules — do not invent them.

## One source per procedure

Procedures live in skills; agents and prompts are thin and point at the skill, never
restating its content in their own words. Any other skill or agent that needs a rule links
to the skill that owns it instead of re-deriving it inline.

Why it is a rule: the same inline copy of one set of rules was found drifted in five
places during a 2026-08 audit — every copy is a place a future rule change
silently misses. When a review finds a skill or agent restating another skill's
procedure, the fix is a pointer, not a better copy.
