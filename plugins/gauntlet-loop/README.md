# Gauntlet Loop

A Claude Code skill implementing Matt Shumer's ["Gauntlet Loop"](https://x.com/mattshumer_/status/2081830214384886228) agentic-engineering pattern: decompose a goal into independently-gradable pieces, give each piece a dedicated **builder** sub-agent paired with a fresh-context **blind critic**, and loop revisions until the critic passes or a bounded attempt cap is hit.

> "The agent (not you!!) breaks the goal into parts, gives each part a specialist builder and a ruthless blind critic sub-agent, with a mandate to only pass if the generated artifact is better than some real-world equivalent." — Matt Shumer

## What's here

A Claude Code plugin (`.claude-plugin/plugin.json`) wrapping one skill (`skills/gauntlet-loop/SKILL.md`), distributed via this repo's marketplace.

**Requires Claude Code's `Workflow` tool** (multi-agent orchestration — `agent()`/`parallel()`). If your Claude Code setup doesn't have it, this skill has nothing to run.

## Install

In Claude Code:

```
/plugin marketplace add astutegrogan/claude-skills
/plugin install gauntlet-loop@claude-skills
```

No git, no terminal commands outside Claude Code itself. Once installed, it's available as `/gauntlet-loop:gauntlet-loop`, or Claude Code will invoke it automatically when you ask for a "gauntlet loop" or "builder and critic loop."

## Why it's more than "generate then verify"

Two things distinguish a real Gauntlet Loop from generic adversarial-verify:

1. **Decomposition happens up front**, into pieces that can each be independently graded — not one big build pass with one verify step at the end, where a single weak piece can hide behind several strong ones.
2. **The critic runs in a fresh, isolated context** and is judged against explicit, checkable clauses ("run X, verify Y") — not the builder's own self-report, and not a vague "does this feel good enough" comparison.

## What's baked into the skill beyond the basic recipe

This isn't a paraphrase of the original tweet thread — the rules in `SKILL.md` are each traced to a specific real failure mode discovered running this pattern for real (via Claude Code's `Workflow` tool) across several actual builds, including:

- A crash bug in the naive `buildPart` loop template (an unguarded `null` critic verdict kills the whole workflow mid-run).
- `MAX_ATTEMPTS` exhaustion is (empirically, every time so far) a signal that something about the piece's setup is structurally wrong — not a reason to raise the cap. Two real cases where the attempt limit was raised from 3 to 7 both passed on attempt 1 anyway; what actually fixed a stuck piece was relaunching it solo with a corrected spec.
- A subtle git-worktree isolation footgun (`opts.isolation: 'worktree'` can silently root a new worktree on a stale, unrelated commit).
- Why a "must build/pass from a clean checkout" verification clause is structurally unpassable inside the standard per-attempt critic loop, and how to route around it.
- Why failed pieces should be committed with an "incomplete" flag and never discarded (the compute is already spent either way).

Full research, attribution chain, and case-study evidence: see the skill file's own rule-by-rule commentary — each rule names the specific incident it came from.

## Attribution

Pattern named and popularized by Matt Shumer ([@mattshumer_](https://x.com/mattshumer_)), HyperWrite/OthersideAI, August 2026 ("Claude of Duty" — an AAA-quality FPS built end-to-end via a fleet of builder/critic sub-agent pairs in Claude Code). This implementation and its hardening rules are not official Shumer material — they're a working port of the pattern onto Claude Code's `Workflow` tool, refined against real usage.

## Rights

© Delegated Trust. All rights reserved. You're welcome to install and use this skill, and adapt it for your own work. Not offered under an open-source license — please don't republish or redistribute it as your own. (The underlying *pattern* itself, as described in Shumer's public thread above, isn't something anyone owns — this notice covers this specific written implementation, not the idea.)
