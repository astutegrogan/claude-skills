---
name: gauntlet-loop
description: Use when the user asks for a "gauntlet loop," a "builder and critic loop," or asks to build/fix something with independent verification per piece rather than one bundled build-then-check pass. Matt Shumer's pattern — decompose into independently-gradable pieces, each with a dedicated builder + fresh-context blind critic, looped until the critic passes or a bounded attempt cap is hit.
---

# Gauntlet Loop

**Requires the `Workflow` tool.** This skill is a script shape for Claude Code's `Workflow` tool (`agent()`, `parallel()`, `phase()`, `log()`). If that tool isn't available in this environment, this skill can't run as written — say so rather than improvising a substitute.

Run a `Workflow` script shaped like this, not a bundled spec→build→verify pass. Decompose the goal into independently-gradable pieces before writing any prompt. This skill exists because the naive version (one build pass covering several findings, one verify pass at the end) misses two things: a single weak piece can hide behind several strong ones when everything is verified together, and there's no automatic revise-and-reloop step when something falls short — a gap has to be caught and fixed manually instead of the critic sending it straight back to the builder.

## Is this task even worth a Gauntlet Loop?

Not everything is. A single, well-scoped fix with an obvious verification step (already-diagnosed bug, one function, clear fix) is a direct build-and-verify pass, not a loop. Reach for the full pattern when there are genuinely multiple independently-gradable pieces, or when a single piece is subtle/sensitive enough that a blind second opinion is worth the round-trip.

Before launching, **state the worst-case spawn count to the user**: roughly `N_pieces × MAX_ATTEMPTS × 2 + N_waves (commit agents) + 2 (judge + integrate)`. This can add up fast — a real run with 8 pieces and a `MAX_ATTEMPTS` of 3 hit 50+ agent spawns. Know the number before committing to it, not after.

**Model:** every `agent()` call in the script should pass `opts.model` explicitly (e.g. `'sonnet'`, or `'haiku'` for trivial checks). `Workflow`'s `agent()` inherits the session model when `model` is omitted — on a higher-tier session that means every builder and critic silently runs at that tier's rates. This applies to builders, critics, wave-commit agents, and the judge alike.

## Required shape

```js
const MAX_ATTEMPTS = 3   // validated default — across several real runs of this pattern, roughly 80%
                          // of pieces passed on attempt 1; exhaustion has never once been fixed by
                          // raising this number, see rule 2b below

const VERDICT_SCHEMA = {
  type: 'object',
  properties: { pass: {type:'boolean'}, summary: {type:'string'}, failures: {type:'array', items:{type:'string'}} },
  required: ['pass', 'summary'],
}

async function buildPart(part, waveTitle) {
  let feedback = ''
  let lastVerdict = null
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    log(`${part.id} attempt ${attempt}/${MAX_ATTEMPTS}`)   // the user checks these against what they watched live — don't drop them
    await agent(builderPrompt(part, feedback), {label: `build:${part.id}`, phase: waveTitle, model: 'sonnet'})
    const verdict = await agent(criticPrompt(part), {label: `critic:${part.id}`, phase: waveTitle, schema: VERDICT_SCHEMA, model: 'sonnet'})
    lastVerdict = verdict
    if (verdict?.pass) {
      log(`${part.id} PASSED on attempt ${attempt}/${MAX_ATTEMPTS}`)
      return {id: part.id, name: part.name, pass: true, attempts: attempt, lastFailures: [], lastSummary: ''}
    }
    // GUARD: a critic agent that errors returns null/undefined here — do not skip this check.
    // An unguarded verdict.summary on a null verdict throws and kills the ENTIRE workflow mid-wave,
    // taking every in-flight sibling piece down with it.
    feedback = verdict
      ? `${verdict.summary}\nFailures:\n- ${(verdict.failures||[]).join('\n- ')}`
      : 'Critic agent did not return a verdict (possible error) — re-verify against the quality bar from scratch.'
    log(`${part.id} failed attempt ${attempt}/${MAX_ATTEMPTS}: ${feedback.slice(0, 200)}`)
  }
  log(`${part.id} FAILED after ${MAX_ATTEMPTS} attempts — will be committed anyway per policy, flagged incomplete`)
  // Real failure — report it, don't paper over it. CARRY THE ACTUAL LAST VERDICT OUT, not just pass:false —
  // a bare {pass:false} loses the itemized failure list, and whatever reads this result (a wave-commit
  // agent, the punchlist) then has nothing concrete to log. Return shape must stay UNIFORM with the
  // pass-path above — this whole object gets JSON.stringify'd into later prompts.
  return {
    id: part.id, name: part.name, pass: false, attempts: MAX_ATTEMPTS,
    lastSummary: lastVerdict ? lastVerdict.summary : 'Critic never returned a verdict.',
    lastFailures: lastVerdict ? (lastVerdict.failures || []) : [],
  }
}
```

### Wave-commit and judge agents — condensed prompt requirements

These two agent types have no reusable code template (every piece's builder/critic prompt is task-specific, but these two aren't) — write them fresh each time, but every one **must** include:

**Wave-commit agent**, run once per wave after all that wave's `buildPart` calls resolve:
- Pass each piece's full result object (including `lastFailures`/`lastSummary`) into the prompt and instruct: *"use these verbatim, do not summarize them away."*
- `git add -A && git commit` **everything from the wave in one commit**, regardless of pass/fail (rule 3) — never `git checkout --` to discard a failed piece.
- If any piece failed: update the punchlist (seeded before the loop started — see "Before running") with the verbatim failure detail, not a summary.
- Explicit instruction: **do NOT push to a shared/remote branch** — that decision belongs to the user, every time, regardless of how clean the run looked.

**Judge agent**, run once at the very end, independent of every per-piece critic:
- Re-verify the full diff against the pre-loop baseline tag (rule 9) with fresh live testing — not by reading the critics' self-reports.
- Specifically hunt for: a piece a critic passed that isn't actually better than baseline, and a defect shared by old and new code that no piece's clauses happened to check for.
- Recommend promote-or-revert per piece, with reasoning grounded in what the judge itself observed.

## Non-negotiable rules

1. **Decompose with explicit file ownership BEFORE writing any prompt.** Each piece's prompt states exactly which files it owns and that it must not touch anything else — this is what makes parallelism safe, not tooling. **Enforce it in the critic prompt too**: every critic must check "did this piece stay inside its declared ownership (grep the diff against files outside its listed scope)?" and "did it accidentally revert or damage anything already merged from an earlier wave?" — ownership stated with no enforcement mechanism is just a hope.

2. **`MAX_ATTEMPTS = 3`, and a `pass: false` after exhaustion is a real, reported failure — never silently accepted or shipped as done.** Don't cap a piece short of the loop's own designed ceiling and accept whatever the critic says as final — that produces genuine regressions shipping as if they were fine.

   **2b. Exhaustion is a signal to diagnose the piece, not to raise the cap.** Every observed `MAX_ATTEMPTS` exhaustion so far has been structural — an unpassable clause (rule 7), a stale worktree (rule 6), or a false failure from a lost-detail bug (rule 3) that turned out to be working code all along — never a case where more rounds would have helped. Raising the cap to 7 has, twice, produced a pass on attempt 1/7. What actually fixes a stuck piece is relaunching it *solo* after fixing whatever was structurally wrong (clearer ownership, dependencies now merged, a corrected spec) — never just more attempts at the same prompt. If a piece exhausts its attempts, stop and diagnose the setup rather than reaching for a bigger number.

3. **On exhaustion, commit the failed state with an "(incomplete — needs manual follow-up)" flag. Never discard it.** Compute is spent regardless of pass/fail; reverting a failed attempt throws away paid-for work for no safety benefit. Gate what merges to a shared branch or deploys, not what gets committed to the working branch. **Pass the failed piece's `lastSummary`/`lastFailures` verbatim into the wave-commit agent's prompt and any punchlist entry** — a bare fail flag with no itemized detail is nearly useless to whoever follows up.

   **3b. If a piece is relaunched after a failed/exhausted attempt, its builder prompt must say so explicitly** — the owned files may already contain committed-but-unverified partial work from the earlier run (rule 3 commits it rather than discarding), and cleaning that up or completing it correctly is in scope for the retry.

4. **Critic clauses must be explicit and checkable ("run X, grep Y, curl Z, confirm result"), not a vague comparison ("as good as some reference app").** Write numbered clauses that can be independently re-verified, not a subjective quality bar. Every critic prompt should also say: *"do not pass because a self-report claims it works"* — verify by doing, not by reading what the builder said it did. On a **retry** critic specifically, ask for maximum specificity in any failure: name the exact clause, file/line, and observed-vs-expected — a vague failure on a retry is how diagnostic detail gets lost twice.

5. **`isolation: 'worktree'` is effectively deprecated in favor of true `parallel()` on disjoint files — default to disjoint-file parallelism, not worktree isolation, whenever the files genuinely don't overlap.** It has no equivalent failure mode. Where pieces genuinely share files and must run concurrently, worktree isolation is the fallback, but see rule 6 for its real cost before reaching for it — serializing shared-file pieces on a plain checkout is usually the simpler, safer choice over isolating them.

6. **`isolation: 'worktree'` can silently root a new worktree on a stale, unrelated commit — this has cost a full piece's work in real usage.** The staleness can hit worktrees allocated **later in a run** (after an earlier wave's merge), not just the first one allocated — a single first-agent check is not sufficient. If worktree isolation is used at all (see rule 5), **every** builder and critic in that call must verify its own base ref against the calling branch's current tip as step zero of its own prompt, every attempt, not just once per wave.

7. **A "must work from a clean checkout / fresh clone" clause cannot be checked inside the standard per-attempt critic loop**, because builders don't commit — a wave-level agent commits once, after the loop already returns. Checking clean-clone state mid-loop will always fail regardless of code quality, no matter how many attempts. Route any such clause to a separate post-wave-commit verification step, or let that specific piece's builder commit its own work before its critic runs.

8. **Builders never commit mid-loop.** A separate, centralized agent commits once per wave, after all that wave's build/critique loops resolve (respecting rules 3 and 7).

9. **A final judge agent, independent of the per-piece critics, re-verifies the diff against a preserved pre-loop baseline** (`git tag` the state before starting) before recommending promote-or-revert per piece. This catches things per-piece loops structurally can't — e.g. a critic-approved piece that isn't actually better than baseline, or a defect shared by both the old and new code that no piece's clauses happened to check.

## Before running

- Confirm with the user whether this qualifies as their environment's opt-in for multi-agent orchestration (some Claude Code setups require explicit confirmation before launching many agents) — state the worst-case spawn count as part of that check-in.
- Tag the pre-loop state (`git tag <descriptive-name>`) so the final judge has a real baseline to compare against.
- **Create a punchlist file before writing the first `agent()` call, seeded with every piece as pending** — as an actual `Write` step early in the script, not a prose reminder to do it "later." A workflow that crashes mid-run before any commit agent runs is exactly the scenario this guards against, and the file has to exist before that risk window opens. Where to put it is up to the user's own conventions (a durable notes/reviews location if they have one, or a plain file in the project) — ask if unclear.

## After running

- Report per-piece pass/fail and attempt counts, not just a summary — the user checks these numbers against what they watched live.
- If anything failed after `MAX_ATTEMPTS`, say so plainly and what's still needed — don't fold it into a "done" summary.
- Update the punchlist with real results — check off passed pieces, keep failed ones open with the verbatim failure detail. Only mark it fully resolved once every piece is genuinely done (including any follow-up retries).
