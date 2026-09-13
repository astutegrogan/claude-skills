---
name: mutation-audit
description: Audit whether a test suite would actually catch a plausible bug, by applying one small mechanical mutation at a time in an isolated worktree and checking whether the tests fail. Use to find weak/hollow regression coverage after a fix or before trusting a suite as a real gate — not to change production code, and not a substitute for running the tests normally.
---

# Mutation Audit

This audits the *tests*, not the implementation. Introduce one small, mechanical, plausible defect into an isolated copy of the code, run the target tests, and ask whether they notice. A surviving mutant is evidence of a coverage gap — it is not permission to change assertions or production code automatically.

Ported from a Codex skill (2026-09-12) and stripped to its transferable core — the original's filesystem-identity/device-inode checks, allocation-registry bookkeeping, and durable SQLite audit trail exist to compensate for Codex's protocol having no equivalent to `Workflow`'s `isolation: 'worktree'` and schema-validated `agent()` retries. None of that is needed here.

## Is this worth running?

Only when you actually doubt a suite's power to catch regressions — after a fix that touched a subtle boundary, before trusting an existing suite as a real release gate, or when a piece passed gauntlet-loop's critic suspiciously easily. Don't run this reflexively on every change; it's a targeted audit, not a routine step.

## The one design constraint that makes this valid — read before writing the script

**Both the baseline test run and the mutation must happen inside the SAME single `agent()` call, with `isolation: 'worktree'`.** Do not split "apply the mutation" and "run the tests" across two separate `agent()` calls, and do not use two different worktrees for baseline vs. mutant. Two reasons, both real:
1. Each `agent({isolation:'worktree'})` call gets its own independently-allocated worktree (verified live, 2026-09-10) — a second call would not see the first call's mutation at all.
2. The mutation must be applied *deterministically*, not by a freely-reasoning agent given open-ended license to "introduce a bug" — a reasoning agent asked to mutate code can, and will, sometimes "helpfully" fix something else, refactor nearby, or apply more than one change, which invalidates the whole audit (you can no longer attribute a `SURVIVED` result to exactly one plausible fault). Choose the exact mutation as a literal, mechanical text substitution *before* dispatching the agent that applies it, and instruct that agent to apply that exact substitution and nothing else — no interpretation, no "while I'm here" fixes.

The clean shape: one agent picks the mutation (reasoning), a second, tightly-constrained turn *inside the same worktree* applies it exactly as specified and reports raw results (mechanical) — or, for a single well-understood mutation, one agent does both in strict sequence within its own turn, explicitly told not to deviate from the literal substitution given.

## Required shape

```js
const MUTANT_SCHEMA = {
  type: 'object',
  properties: {
    baselineClean: { type: 'boolean', description: 'true only if the UNMODIFIED test command passed before any mutation was applied' },
    mutationApplied: { type: 'boolean' },
    diffLineCount: { type: 'number', description: 'lines changed per `git diff --stat`, after the mutation — must be minimal (expect 1-2)' },
    testExitCode: { type: 'number' },
    testOutputSummary: { type: 'string' },
    classification: { type: 'string', enum: ['KILLED', 'KILLED_INVALID', 'SURVIVED', 'INCONCLUSIVE'] },
    reasoning: { type: 'string' },
  },
  required: ['baselineClean', 'mutationApplied', 'diffLineCount', 'testExitCode', 'classification', 'reasoning'],
}

async function runMutant(mutant, testCmd, spawnCeiling) {
  trackSpawn(spawnCeiling)
  return agent(
    `You are auditing test coverage via one controlled mutation. Work inside your own isolated worktree.
1. Run the UNMODIFIED test command exactly as given: ${testCmd}. Confirm it passes cleanly. If it does not, report baselineClean:false and classification:INCONCLUSIVE immediately — do not proceed to mutate a red baseline.
2. Apply EXACTLY this one mechanical change, character for character, nothing else: ${mutant.description}
   File: ${mutant.file}
   Change: ${mutant.oldText}  -->  ${mutant.newText}
   Do not fix, refactor, or touch anything else in this file or any other file. If the exact old text is not found verbatim, report mutationApplied:false and classification:INCONCLUSIVE — do not improvise a similar-looking edit.
3. Run 'git diff --stat' and report the line count — it must be minimal (this mutation should be a 1-2 line change). If it's larger, something went wrong; report honestly.
4. Run the SAME test command again: ${testCmd}. Report the raw exit code and a summary of the output.
5. Classify: KILLED (tests failed for a reason connected to this mutation), KILLED_INVALID (a build/import/syntax error prevented the tests from running meaningfully — this shows the type system caught it, not the tests), SURVIVED (tests passed despite the mutation being live and reachable), INCONCLUSIVE (timeout, missing dependency, ambiguous result, or anything that makes the above unclear).
Do not modify anything outside this one file. Do not commit. Do not push. This worktree is disposable.`,
    { label: `mutant:${mutant.id}`, phase: 'Mutation audit', schema: MUTANT_SCHEMA, model: 'sonnet', isolation: 'worktree' }
  )
}
```

## Choosing mutants — prefer a few explainable ones over a broad score

Pick mutations from real risk boundaries: the piece that was just fixed, a recent bug's exact location, a contract boundary, a resource-cleanup path. A handful of targeted, explainable mutants beats a large automated sweep that produces a score nobody can interpret.

| Behavior under test | Example mutation |
|---|---|
| Guard / feature flag | `if (enabled)` → `if (not enabled)` |
| Boundary condition | `>=` → `>`, `<=` → `<` |
| Success/failure contract | `return True` → `return False` (or the reverse) |
| Required side effect | remove one call that registers/subscribes/records something |
| Cleanup / ownership | omit one required close/release/unsubscribe call |

Never mutate authentication, authorization, billing, destructive operations, or anything touching real credentials or production data — this skill mutates code in a disposable worktree for a test run, never anything that could have a real-world side effect if the mutation somehow executed against a live system.

## Interpreting results

- **KILLED** is only meaningful evidence if the failure is actually connected to the mutation — a mutant that "fails" due to an unrelated flaky test is not evidence the suite caught the fault; treat that as INCONCLUSIVE instead.
- **KILLED_INVALID** shows a compiler/linter/type-checker caught the change, not that behavioral tests did — report it separately, don't fold it into a "tests caught it" count.
- **SURVIVED** is the actual finding: report the exact behavior that changed, the test command that failed to notice, and the smallest missing assertion or scenario that would have caught it. This is a coverage gap report, not a bug report on the mutated code (which never ships).
- Report a mutation "score" only with its denominator (e.g. "3/5 killed, 1 invalid, 1 inconclusive") — never a bare percentage, and never let a survived high-risk mutant hide behind an otherwise-good score.

## After running

Hand every `SURVIVED` result to the user directly, or to a bounded follow-up fix (gauntlet-loop, if the missing test itself is worth building through that pattern) — this skill never adds tests or fixes code itself. Report the full mutant ledger: mutation ID, file/line, exact substitution, classification, and evidence, not just a summary count.
