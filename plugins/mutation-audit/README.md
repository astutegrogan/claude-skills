# Mutation Audit

A Claude Code skill that audits *tests*, not implementation: apply one small, mechanical, plausible mutation to code inside an isolated worktree, run the target tests, and check whether they notice. A surviving mutant is evidence of a coverage gap.

Ported and stripped from a Codex skill (2026-09-12) — the original spent roughly half its length on filesystem-identity checks and an allocation-registry that exist only to compensate for Codex's protocol having no equivalent to Claude Code's `agent({isolation:'worktree'})` and schema-validated `agent()` retries. None of that carried over; only the actual mutation-testing mechanism did.

Complementary to (not overlapping with) capped-pass-rate/randomized-test techniques: those stop an agent from overfitting a fixed test suite; this measures whether the suite itself has any teeth at all. A change can pass a capped-rate check with a hollow suite behind it — mutation-audit is what catches that.

## What's here

A Claude Code plugin (`.claude-plugin/plugin.json`) wrapping one skill (`skills/mutation-audit/SKILL.md`), distributed via this repo's marketplace.

**Requires Claude Code's `Workflow` tool** (`agent()` with `isolation: 'worktree'` specifically — the mutation must be applied and tested inside one single isolated-worktree agent turn, deterministically, not by a freely-reasoning builder given open license to "introduce a bug").

## Install

In Claude Code:

```
/plugin marketplace add astutegrogan/claude-skills
/plugin install mutation-audit@claude-skills
```

## Use it when

You doubt a test suite's power to catch regressions — after a fix touched a subtle boundary, before trusting an existing suite as a real release gate, or when a piece passed a builder/critic loop suspiciously easily. Not a routine step; a targeted audit.

See the sibling [`gauntlet-loop`](../gauntlet-loop) skill for the builder+critic pattern this complements, and [`shipped-batch-review`](../shipped-batch-review) for independently reviewing a batch of already-shipped commits.
