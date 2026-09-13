---
name: batch-review
description: Independently re-review a batch of already-shipped/merged commits as one cumulative unit, fresh-context, trusting no prior self-report or per-commit review. Use after a day (or session) of individually-reviewed commits landed without ever being checked together, or after any change that had no independent critic at the time. Not for reviewing in-flight/uncommitted work — use gauntlet-loop's judge step for that, before anything merges.
---

# Batch Review

Gauntlet-loop's judge reviews a *loop's own pieces* against *that loop's own baseline*, before landing. This skill exists for the gap that leaves: several commits, each individually fine, that landed over a session or a day without anyone ever reviewing the *cumulative* result as one unit — and without anyone independently checking a piece that was self-verified with no critic at all (a "just this once, it's small" commit). Found and fixed 2026-09-13, the same day it happened: five real commits shipped, each piece-reviewed separately, but the last one (a lint cleanup) was self-verified by the same agent that wrote it, and nobody had looked at all five together.

## Is this worth running?

Yes whenever: a batch of commits landed on `main`/a shared branch without ever being reviewed as a whole; any commit in the batch had no independent critic (self-verified only); or enough time/commits have passed that "did any of this interact badly" is a live question, not a hypothetical. Skip it for a single commit that already went through gauntlet-loop's own judge — that's already independent review of the right scope; re-running this on top adds nothing.

State the scope before starting: the commit range (a tag or SHA to `HEAD`), and whether this is being run against the actual shared branch (read-only checks only, be careful) or a disposable copy.

## What this authorizes

Independent verification only — reading the diff, running tests, running read-only queries/checks. It does not authorize new commits, reverts, force-pushes, or any write to the reviewed branch. If a finding warrants a fix, that's a separate, explicitly-authorized follow-up (a direct fix, or a gauntlet-loop run) — this skill's job ends at a report.

## Required shape

A single independent reviewer agent, fresh context, given the commit range and nothing else — no prior commit messages' claims, no "here's what each piece said." Trust nothing already asserted; verify by doing.

```js
const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    testSuiteResult: { type: 'string', description: 'exact command run and its raw pass/fail/count output' },
    interactionFindings: { type: 'array', items: { type: 'string' }, description: 'any place two or more commits in this range touch related code/behavior in a way that was not obviously checked together' },
    unreviewedCommits: { type: 'array', items: { type: 'string' }, description: 'any commit in range that appears to have been self-verified with no independent critic (no evidence of a fresh-context review) -- name it explicitly' },
    integrationCheck: { type: 'string', description: 'at least one check beyond the unit-test suite -- e.g. exercising a fixed code path against a real (scratch-copy) database/service, not just a mock' },
    verdict: { type: 'string', enum: ['PROMOTE', 'FINDINGS'] },
    findings: { type: 'array', items: { type: 'string' }, description: 'each finding needs file:line or command output as evidence -- no vague impressions' },
  },
  required: ['testSuiteResult', 'interactionFindings', 'unreviewedCommits', 'verdict', 'findings'],
}

const reviewResult = await agent(
  `Independent QA review, fresh context. Do not trust any commit message or prior review's claim -- verify everything yourself by running it.
Repo: ${repoPath}. Range to review: ${baselineRef}..${headRef} (${commitList.join(', ')}).
1. Read the full cumulative diff for this range as one unit, not commit by commit.
2. Run the full test suite yourself: ${testCmd}. Report the raw result.
3. Check for interaction effects BETWEEN commits in this range -- does anything one commit changed depend on, conflict with, or get silently affected by another commit in the same range? This is the main thing per-commit review cannot catch.
4. Identify which commits (if any) show no evidence of an independent fresh-context review at the time -- self-verified-only commits are the highest-risk items in the batch.
5. Do at least one integration-level check beyond the unit-test suite for the highest-risk change in this range -- a real (scratch/disposable copy, never the live system) exercise of the actual behavior, not just a mocked test.
6. Verdict PROMOTE only if the suite is green, no interaction findings, and every commit had real independent review at some point (including now, for any that didn't before). Otherwise FINDINGS, itemized with evidence.`,
  { label: 'batch-review', phase: 'Batch review', schema: REVIEW_SCHEMA, model: 'sonnet' }
)
```

## After running

Report the verdict plainly — PROMOTE, or the itemized findings with evidence. A FINDINGS verdict on already-shipped code is not an emergency by default (it already shipped; assess actual risk), but don't let "it's already live" become a reason to skip acting on a real finding. If a finding needs a code change, that's a separate, explicitly-scoped follow-up — this skill's report is the deliverable, not a fix.
