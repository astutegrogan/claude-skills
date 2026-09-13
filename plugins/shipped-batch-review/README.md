# Shipped-Batch Review

A Claude Code skill for a specific gap that per-commit review leaves open: several commits, each individually reviewed and fine on its own, that land over a session or a day without anyone ever reviewing the *cumulative* result as one unit — and without independently checking any commit that was self-verified with no critic at all.

Written 2026-09-13 the same day the gap it fixes was discovered: five real commits shipped, each piece-reviewed separately by a builder→critic→judge chain, but the last one (a small lint cleanup) was self-verified by the same agent that wrote it, and nobody had looked at all five together. The independent review that followed found a real production issue none of the per-commit reviews caught — a fix that was correct, tested, and merged, but never actually installed on the live system because of a `CREATE ... IF NOT EXISTS` migration gap.

## What's here

A Claude Code plugin (`.claude-plugin/plugin.json`) wrapping one skill (`skills/shipped-batch-review/SKILL.md`), distributed via this repo's marketplace.

## Install

In Claude Code:

```
/plugin marketplace add astutegrogan/claude-skills
/plugin install shipped-batch-review@claude-skills
```

## Use it when

A batch of commits landed on a shared branch without ever being reviewed as a whole, or any commit in the batch had no independent critic. Skip it for a single commit that already went through [`gauntlet-loop`](../gauntlet-loop)'s own judge step — that's already independent review at the right scope.

Not for in-flight or uncommitted work — that's gauntlet-loop's judge, before anything merges. This is for after.
