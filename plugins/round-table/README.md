# Round-table

A Claude Code skill implementing bounded, turn-based multi-specialist deliberation — reverse-engineered from Cursor's "Grok Bot" group-meeting orchestrator and ported onto Claude Code's `Workflow` tool.

Use it for a judgment call where several *distinct* specialist perspectives each need a real say and might legitimately disagree (ship-readiness with security + UX + compliance stakes, pick-between-architectures, kill-or-continue). If one well-briefed judge could answer it, use one judge instead — a round-table costs up to `maxRounds × maxMembers` agent calls, not one. If the question is "is this piece correct, loop until it passes," that's a different pattern — see the sibling [`gauntlet-loop`](../gauntlet-loop) skill in this repo.

## What's here

A Claude Code plugin (`.claude-plugin/plugin.json`) wrapping one skill (`skills/round-table/SKILL.md`), distributed via this repo's marketplace.

**Requires Claude Code's `Workflow` tool** (multi-agent orchestration — `agent()`/`parallel()`/`phase()`/`log()`). If your Claude Code setup doesn't have it, this skill has nothing to run.

## Install

In Claude Code:

```
/plugin marketplace add astutegrogan/claude-skills
/plugin install round-table@claude-skills
```

No git, no terminal commands outside Claude Code itself. Once installed, Claude Code will invoke it automatically when you ask for a "round table" or a "meeting," or you can call it explicitly.

## The primitive

Rooms of ≤6 members, ≤3 rounds, ≤10 total messages, ≤2 messages per member per round, a bounded history window. Rotating start speaker each round. Silent passes are allowed and expected. A round where everyone passes closes the meeting early. Mentioning another member restricts the *entire next round* to the union of everyone mentioned that round — not just the member doing the mentioning, and not just the members that one speaker named. An optional synthesis pass can run once, after the room closes, to turn the transcript into a single decision — it's never a member and never speaks in-room.

## What's baked in beyond the basic recipe

The rules in `SKILL.md` aren't a paraphrase of the source design — each is traced to a specific bug found and fixed while running this pattern for real, including:

- A phantom "restricted next round" log that needs to check *both* of the loop's exit conditions, not just one — the same bug class can hide behind either exit path.
- A restricted round going quiet (because most members were silenced by a mention-restriction, not by agreement) must not be logged identically to genuine full-room consensus — the two look the same at the log line unless you deliberately distinguish them.
- Mid-round message drops (budget exhausted before every eligible member got a turn, or partway through a member's own turn) need to be tracked and surfaced in the return value, not just silently absorbed — otherwise a truncated meeting is indistinguishable from one that ran to natural completion.
- The mentions-restriction prompt text has to describe the *actual* union-across-all-speakers code behavior, not a narrower "restricts to who I named" reading that a member could reasonably infer instead.
- Truncating an over-length message to a hard character cap has to account for the suffix you're appending — slicing to the full cap and then adding a suffix silently blows past it.

Full rule-by-rule commentary, including a recorded architectural dissent from this skill's own self-review (on whether a circuit-breaker for systemic `agent()` failure belongs in this skill or in the `Workflow` primitive itself — left unresolved on purpose), is in the skill file.

## Attribution

Reverse-engineered from Cursor's Grok Bot group-meeting orchestrator. This implementation and its hardening rules are not official Cursor material — they're a working port of the observed pattern onto Claude Code's `Workflow` tool, refined against real usage.

## Rights

© Delegated Trust. All rights reserved. You're welcome to install and use this skill, and adapt it for your own work. Not offered under an open-source license — please don't republish or redistribute it as your own. (The underlying *pattern* itself isn't something anyone owns — this notice covers this specific written implementation, not the idea.)
