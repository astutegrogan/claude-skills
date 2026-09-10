---
name: gauntlet-loop
description: Use when the user asks for a "gauntlet loop," a "builder and critic loop," or asks to build/fix something with independent verification per piece rather than one bundled build-then-check pass. Matt Shumer's pattern — decompose into independently-gradable pieces, each with a dedicated builder + fresh-context blind critic, looped until the critic passes or a bounded attempt cap is hit.
---

# Gauntlet Loop

**Requires the `Workflow` tool.** This skill is a script shape for Claude Code's `Workflow` tool (`agent()`, `parallel()`, `phase()`, `log()`). If that tool isn't available in this environment, this skill can't run as written — say so rather than improvising a substitute.

Run a `Workflow` script shaped like this, not a bundled spec→build→verify pass. Decompose the goal into independently-gradable pieces before writing any prompt. This skill exists because the naive version (one build pass covering several findings, one verify pass at the end) misses two things: a single weak piece can hide behind several strong ones when everything is verified together, and there's no automatic revise-and-reloop step when something falls short — a gap has to be caught and fixed manually instead of the critic sending it straight back to the builder.

## Is this task even worth a Gauntlet Loop?

**Scope of authorization:** asking for a gauntlet loop authorizes the specialist collaboration needed to run it — decomposing the task, spawning builder/critic/wave-commit/judge agents, and committing to a local review branch as this pattern requires. It does not authorize unrelated changes, commits to a shared/remote branch, deployment, or any other external mutation beyond what's needed to run the pattern locally. Anything past that (pushing, merging to a shared/default branch, deploying, reverting a piece) is a separate decision the user makes explicitly, every time — see rule 3, rule 9, and the wave-commit prompt requirements below for the specific "do NOT push" instance of this general boundary.

Not everything is. A single, well-scoped fix with an obvious verification step (already-diagnosed bug, one function, clear fix) is a direct build-and-verify pass, not a loop. Reach for the full pattern when there are genuinely multiple independently-gradable pieces, or when a single piece is subtle/sensitive enough that a blind second opinion is worth the round-trip.

Before launching, **state the worst-case spawn count to the user**: roughly `N_pieces × MAX_ATTEMPTS × 2 + N_waves (commit agents) + 1 (judge)`. Only two agent types run outside the per-piece build/critic loop — the wave-commit agent (one per wave) and the judge (one, at the very end); there is no separate "integrate" agent anywhere in this pattern, so don't budget spawns for one. A real run hit 50+ agent spawns on that formula — know the number before committing to it, not after. Rule 10's worktree-teardown and per-piece-commit refinements (below) fold into the wave-commit agent's and critic's existing turns — they add no new agent type and do not change this formula.

**Model:** every `agent()` call in the script should pass `opts.model` explicitly (e.g. `'sonnet'`, or `'haiku'` for trivial checks). `Workflow`'s `agent()` inherits the session model when `model` is omitted — on a higher-tier session that means every builder and critic silently runs at that tier's rates. This applies to builders, critics, wave-commit agents, and the judge alike.

## Required shape

```js
const MAX_ATTEMPTS = 3   // validated default — across several real runs of this pattern, roughly 80%
                          // of pieces passed on attempt 1; exhaustion has never once been fixed by
                          // raising this number, see rule 2b below

// SPAWN CEILING (rule 11): the worst-case formula stated to the user before launch
// (N_pieces × MAX_ATTEMPTS × 2 + N_waves + 1) is advisory unless something in the script actually
// checks against it. Build the ceiling from the SAME MAX_ATTEMPTS constant above, never a
// second hand-typed copy of it (rule 14) — a drifted mirror is exactly the bug rule 14 exists to
// prevent, and it would silently understate the real ceiling.
const SPAWN_CEILING_MULTIPLIER = 2   // abort once actual spawns exceed 2x the pre-stated worst case
let spawnCount = 0
function trackSpawn(ceiling) {
  spawnCount++
  if (spawnCount > ceiling) {
    log(`SPAWN CEILING EXCEEDED: ${spawnCount} agent() calls made, ceiling was ${ceiling} (${SPAWN_CEILING_MULTIPLIER}x the worst-case estimate stated before launch). Aborting run rather than continuing to spend silently — see rule 11.`)
    throw new Error(`gauntlet-loop spawn ceiling exceeded (${spawnCount} > ${ceiling})`)
  }
}
// Computed once, from the pieces/waves actually decomposed for this run — not hand-typed:
// const WORST_CASE_SPAWNS = N_PIECES * MAX_ATTEMPTS * 2 + N_WAVES + 1
// const SPAWN_CEILING = WORST_CASE_SPAWNS * SPAWN_CEILING_MULTIPLIER
// ...then pass SPAWN_CEILING into every buildPart() call below.

const BUILD_SCHEMA = {
  type: 'object',
  properties: { diffHash: {type:'string'}, summary: {type:'string'} },
  required: ['diffHash', 'summary'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: { pass: {type:'boolean'}, summary: {type:'string'}, failures: {type:'array', items:{type:'string'}} },
  required: ['pass', 'summary'],
}

async function buildPart(part, waveTitle, spawnCeiling) {
  let feedback = ''
  let lastVerdict = null
  let lastDiffHash = null   // rule 13: no-progress detection across retries
  let wastedAttempts = 0
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    log(`${part.id} attempt ${attempt}/${MAX_ATTEMPTS}`)   // the user checks these against what they watched live — don't drop them
    trackSpawn(spawnCeiling)
    const buildResult = await agent(builderPrompt(part, feedback), {label: `build:${part.id}`, phase: waveTitle, model: 'sonnet', schema: BUILD_SCHEMA})
    // GUARD, closing the asymmetry with the critic guard below: a builder agent that errors
    // returns null/undefined here too — do not fall through and run the critic against whatever
    // the tree happens to contain. Log it distinctly from a critic failure, and count this as a
    // failed attempt in the retry accounting, not a silent no-op.
    if (buildResult == null) {
      feedback = 'Builder agent did not return a result (possible error) — retry the build from scratch.'
      log(`${part.id} attempt ${attempt}/${MAX_ATTEMPTS}: BUILDER returned null/errored — treated as a failed attempt, critic NOT run this attempt`)
      continue
    }

    // NO-PROGRESS CHECK (rule 13): `Workflow` scripts have NO filesystem/child_process access at
    // all (require() throws — confirmed live) — this script cannot shell out to hash a diff itself,
    // and for a worktree-isolated piece it cannot reach that worktree's filesystem at all anyway.
    // So the BUILDER computes the hash itself, in its own Bash call — from inside its own worktree
    // when the piece is worktree-isolated — via `git diff <part.baseRef> -- <part.ownedPaths> | sha1sum`
    // (part.baseRef is the actual base tag/ref this run started from) and reports it back as
    // `diffHash` in BUILD_SCHEMA above. This is a plain JS string comparison, no hashDiff() call.
    const diffHash = buildResult.diffHash ? buildResult.diffHash.trim() : ''
    if (diffHash === lastDiffHash || !diffHash) {
      wastedAttempts++
      log(`${part.id} attempt ${attempt}/${MAX_ATTEMPTS}: NO PROGRESS — diff hash unchanged from the previous attempt (or empty). Wasted spawn (${wastedAttempts} so far), skipping straight to exhausted path instead of burning remaining attempts.`)
      break
    }
    lastDiffHash = diffHash

    trackSpawn(spawnCeiling)
    const verdict = await agent(criticPrompt(part), {label: `critic:${part.id}`, phase: waveTitle, schema: VERDICT_SCHEMA, model: 'sonnet'})
    lastVerdict = verdict
    if (verdict?.pass) {
      log(`${part.id} PASSED on attempt ${attempt}/${MAX_ATTEMPTS}`)
      return {id: part.id, name: part.name, pass: true, attempts: attempt, lastFailures: [], lastSummary: '', wastedAttempts}
    }
    // GUARD: a critic agent that errors returns null/undefined here — do not skip this check.
    // An unguarded verdict.summary on a null verdict throws and kills the ENTIRE workflow mid-wave,
    // taking every in-flight sibling piece down with it.
    feedback = verdict
      ? `${verdict.summary}\nFailures:\n- ${(verdict.failures||[]).join('\n- ')}`
      : 'Critic agent did not return a verdict (possible error) — re-verify against the quality bar from scratch.'
    log(`${part.id} failed attempt ${attempt}/${MAX_ATTEMPTS}: ${feedback.slice(0, 200)}`)
  }
  log(`${part.id} FAILED after ${MAX_ATTEMPTS} attempts (${wastedAttempts} of them wasted/no-progress) — will be committed anyway per policy, flagged incomplete`)
  // Real failure — report it, don't paper over it. CARRY THE ACTUAL LAST VERDICT OUT, not just pass:false —
  // a bare {pass:false} loses the itemized failure list, and whatever reads this result (a wave-commit
  // agent, the punchlist) then has nothing concrete to log. Cost a full piece's worth of lost diagnostic
  // detail in the 2026-08-23 Bran pedagogy-fixes run before this was caught. Return shape must stay
  // UNIFORM with the pass-path above — this whole object gets JSON.stringify'd into later prompts.
  return {
    id: part.id, name: part.name, pass: false, attempts: MAX_ATTEMPTS, wastedAttempts,
    lastSummary: lastVerdict ? lastVerdict.summary : 'Critic never returned a verdict.',
    lastFailures: lastVerdict ? (lastVerdict.failures || []) : [],
  }
}
```

### Wave-commit and judge agents — condensed prompt requirements

These two agent types have no reusable code template (every piece's builder/critic prompt is task-specific, but these two aren't) — write them fresh each time, but every one **must** include:

**Wave-commit agent**, run once per wave after all that wave's `buildPart` calls resolve:
- Pass each piece's full result object (including `lastFailures`/`lastSummary`) into the prompt and instruct: *"use these verbatim, do not summarize them away"* — this is the exact hand-off where a real payload bug once dropped that detail.
- **State explicitly in this agent's prompt which row of the "Landing modes at a glance" table (below) applies to this wave** — worktree-default, shared-checkout fallback, or serial shared-checkout. That table is the single source of truth for who commits, when, scoping, and which branch the work lands on; do not restate that logic here beyond naming the applicable row.
- **Before committing, run `git status --porcelain` and check it against the wave's declared file ownership (rule 1)**, scoped to the pieces landing in this wave. Since rule 1 requires every piece's owned files to be known up front, stage and commit **only the files each piece is known to have created/modified** (`git add <owned files>`, not a blind `git add -A`) — this is what makes it safe to say (per the table below) that nothing from this run's own pieces is mid-flight at wave-commit time; it does not license skipping the ownership check. If for some reason ownership can't be reliably determined for what `git status --porcelain` shows, do not guess: abort the wave-commit and surface a clear message that the tree had unexplained changes and nothing was auto-committed.
- Commit **everything from the wave's owned files in one commit**, regardless of pass/fail (rule 3) — never `git checkout --` to discard a failed piece.
- **Once a worktree-isolated piece's work has landed** (merged/cherry-picked into the review branch), in this same turn run `git worktree remove <path>` for it, then — only after confirming the merge/cherry-pick actually landed, never before — `git branch -D <branch>` for that piece's branch. Fold both steps into the wave-commit agent's existing job, not a new per-piece cleanup agent (keeps the spawn-count formula unchanged — see "Is this task even worth a Gauntlet Loop?"). This is the same class of debt rule 6's staleness incident already warns about, just for branches instead of worktrees: confirmed live, orphan `worktree-agent-*`-style branches have accumulated in a real repo from real runs where only the worktree directory was removed.
- If any piece failed: update the punchlist (seeded before the loop started — see "Before running") with the verbatim failure detail, not a summary.
- Explicit instruction: **do NOT push to a shared/remote branch** — that decision belongs to the user, every time, regardless of how clean the run looked.

**Judge agent**, run once at the very end, independent of every per-piece critic:
- Re-verify the full diff against the pre-loop baseline tag (rule 9) with fresh live testing — not by reading the critics' self-reports.
- Specifically hunt for: a piece a critic passed that isn't actually better than baseline, and a defect shared by old and new code that no piece's clauses happened to check for (both have actually happened).
- Recommend promote-or-revert per piece, with reasoning grounded in what the judge itself observed — **or promote-with-caveats**, when a piece correctly passed its own narrow clause but the judge still found a real residual gap (e.g. a fix that doesn't cover every input case it should). A caveat is not a failure and doesn't block promotion, but it must be reported, not silently dropped — see "After running" for where it goes (the punchlist, as a new follow-up item). **This is a recommendation only** — the judge never reverts anything itself; any revert requires explicit user approval (consistent with rule 3's "never discarded" — see below).

## Non-negotiable rules

### Landing modes at a glance

This table is the **single authoritative statement** of who commits, when, from where, and which branch the work lands on — rules 7, 8, and 10 hold the reasoning and incident history behind these mechanics, not a restatement of them. If a rule's prose and this table ever seem to disagree, the table wins; fix the prose.

| Mode | Who commits | When | Scoping | Lands on | Who tears down |
|---|---|---|---|---|---|
| Worktree-default (rule 10) | The **critic**, inline | Every verdict it issues — PASS and FAIL, including the final `MAX_ATTEMPTS`-exhausted FAIL | The piece's own worktree; `git add -A` is safe by construction (nothing else can be mid-flight there) | A dedicated **review branch**, cut from the pre-loop baseline tag (rule 9) — **never a shared/default branch directly**. Wave-commit merges/cherry-picks the piece's branch there. | Wave-commit agent runs `git worktree remove <path>`, then (only after confirming the merge/cherry-pick landed) `git branch -D <branch>`, both in the same turn |
| Shared-checkout fallback (rule 10's fallback — worktree tooling unavailable) | The **critic**, inline | Every verdict it issues — PASS and FAIL, including the final `MAX_ATTEMPTS`-exhausted FAIL | Scoped strictly to the piece's declared owned paths — **never** `git add -A` | A dedicated **review branch**, created and checked out from the pre-loop baseline tag *before the build loop starts* (see "Before running") — **never a shared/default branch directly**. Because the critic commits inline with no wave-commit merge step to redirect it, HEAD must already be on the review branch before the first builder/critic call, by construction | No worktree to remove; the wave-commit agent below still runs once, covering FAILed pieces and the punchlist |
| **Serial shared-checkout** (rule 5 — deliberately chosen for a serial run, not a tooling-unavailable fallback) | The **critic**, inline — same mechanics as the fallback row above | Every verdict it issues — PASS and FAIL, including the final `MAX_ATTEMPTS`-exhausted FAIL | Same as the fallback row above | Same as the fallback row above — a dedicated **review branch**, checked out before the build loop starts. The only real difference from the fallback row is *why* worktree isolation isn't in use (tooling unavailable there vs. deliberately choosing serial here), not the landing mechanism | No worktree to remove; wave-commit still runs once, covering FAILed pieces and the punchlist |
| Wave-commit, either mode (rule 8) | The **wave-commit agent** | Once per wave, after every piece in that wave has resolved | Files owned by the wave's pieces (verified via `git status --porcelain` against declared ownership before staging, never a blind `git add -A` — see the wave-commit prompt requirements above); safe to determine because nothing from this run's own pieces is mid-flight at that point (contrast the fallback row above) | The review branch (the same one named in whichever row above applies) — wave-commit itself never targets a shared/default branch | N/A — this agent is the landing step, not a teardown step (except the worktree-remove/branch-delete noted above) |

Builders never appear in this table — rule 8 holds with no exception; every commit-actor path routes through the critic or the wave-commit agent.

1. **Decompose with explicit file ownership BEFORE writing any prompt.** Each piece's prompt states exactly which files it owns and that it must not touch anything else — this is what makes parallelism safe, not tooling. **Enforce it in the critic prompt too**: every critic must check "did this piece stay inside its declared ownership (grep the diff against files outside its listed scope)?" and "did it accidentally revert or damage anything already merged from an earlier wave?" — ownership stated with no enforcement mechanism is just a hope.

2. **`MAX_ATTEMPTS = 3`, and a `pass: false` after exhaustion is a real, reported failure — never silently accepted or shipped as done.** Don't cap a piece short of the loop's own designed ceiling and accept whatever the critic says as final — that produces genuine regressions shipping as if they were fine.

   **2b. Exhaustion is a signal to diagnose the piece, not to raise the cap.** Every observed `MAX_ATTEMPTS` exhaustion so far has been structural — an unpassable clause (rule 7), a stale worktree (rule 6), or a false failure from a lost-detail bug (rule 3) that turned out to be working code all along — never a case where more rounds would have helped. Raising the cap to 7 has, twice, produced a pass on attempt 1/7. What actually fixes a stuck piece is relaunching it *solo* after fixing whatever was structurally wrong (clearer ownership, dependencies now merged, a corrected spec) — never just more attempts at the same prompt. If a piece exhausts its attempts, stop and diagnose the setup rather than reaching for a bigger number.

   **2c. The concrete decision procedure for a piece that exhausts `MAX_ATTEMPTS`, replacing vague "flag it and move on" narrative advice:** (1) **Log** — the full per-attempt history for that piece: every attempt's `lastSummary`/`lastFailures` (not just the final one), the wasted-vs-genuine attempt breakdown from rule 13's no-progress check, and whether the failure pattern looks structural per 2b (same clause failing every time) or varied (different failures each attempt, suggesting a flaky critic or a moving spec). (2) **State the piece is left in** — committed per rule 3 (see the "Landing modes at a glance" table for which branch/commit that lands on), untouched further by this run; do not relaunch it again within the same wave once `MAX_ATTEMPTS` is hit, and do not let the wave-commit agent quietly merge it as if it passed. (3) **What the calling agent does next** — surface the piece, its full attempt history, and every critic verdict **to the user directly**, in the after-run report (see "After running"), with the diagnostic question from 2b already asked ("what about this piece's setup makes it unpassable") and, where the log makes it obvious, a candidate answer. Do **not** silently retry further in the same run, do not guess at a fix and re-launch without that surfacing step, and do not fold it into a "done" summary — an exhausted piece is the user's call to make, not this workflow's to paper over.

3. **On exhaustion, commit the failed state with an "(incomplete — needs manual follow-up)" flag. Never discard it.** Compute is spent regardless of pass/fail; reverting a failed attempt throws away paid-for work for no safety benefit. Gate what merges to a shared branch or deploys, not what gets committed to the working branch. **Pass the failed piece's `lastSummary`/`lastFailures` verbatim into the wave-commit agent's prompt and any punchlist entry** — a bare fail flag with no itemized detail is nearly useless to whoever follows up.

   **3b. If a piece is relaunched after a failed/exhausted attempt, its builder prompt must say so explicitly** — the owned files may already contain committed-but-unverified partial work from the earlier run (rule 3 commits it rather than discarding), and cleaning that up or completing it correctly is in scope for the retry.

4. **Critic clauses must be explicit and checkable ("run X, grep Y, curl Z, confirm result"), not a vague comparison ("as good as some reference app").** Write numbered clauses that can be independently re-verified, not a subjective quality bar. Every critic prompt should also say: *"do not pass because a self-report claims it works"* — verify by doing, not by reading what the builder said it did. On a **retry** critic specifically, ask for maximum specificity in any failure: name the exact clause, file/line, and observed-vs-expected — a vague failure on a retry is how diagnostic detail gets lost twice.

   **4b. Where a clause is naturally parametrizable (property-based/parametric tests with a variant generator), prefer a randomized/capped-pass-rate test variant over a fixed, memorizable one — re-drawing the random seed on every retry attempt, never freezing it once at gate-in.** (Round-table, 2026-09-10.) A frozen seed lets the builder hill-climb the oracle across gauntlet-loop's own bounded retries — fail variant A on attempt 1, patch specifically for A, see variant B on attempt 2, and so on — decaying the guarantee to near-zero by attempt 3-5. This is **not** a blanket default: most pieces are one-off fixes with hand-authored clauses ("grep Y, curl Z") with no distribution to sample from, and forcing a variant generator onto those adds nothing.

5. **True `parallel()` only across pieces with zero file overlap.** Where pieces share files, either serialize (simplest — see the "Serial shared-checkout" row of the "Landing modes at a glance" table above for which commit-actor rules apply) or use `opts.isolation: 'worktree'` — but see rule 6 before reaching for it, and see rule 10 for why "zero file overlap" is no longer sufficient on its own to call this failure-mode-free.

6. **`isolation: 'worktree'` can silently root a new worktree on a stale, unrelated commit — this has cost a full piece's work in real usage.** The staleness can hit worktrees allocated **later in a run** (after an earlier wave's merge), not just the first one allocated — a single first-agent check is not sufficient. **Every** builder and critic in a worktree-isolated call must verify its own base ref against the calling branch's current tip as step zero of its own prompt, every attempt, not just once per wave. **Same step zero must also assert the agent is actually operating inside the worktree**: print `pwd` and `git rev-parse --show-toplevel` and confirm the result matches the EXPECTED worktree path, not the original shared checkout — worktree isolation only prevents the rule-10 incident if the agent's shell is actually running inside it, and nothing before this checked that. See rule 10 for why "the files genuinely don't overlap" is no longer sufficient on its own to skip isolation.

   **6b. On a retry within a piece's own `MAX_ATTEMPTS` loop, reuse the same worktree and resync it to the latest base ref (per this rule) — do not tear down and recreate a fresh worktree each attempt.** This is the explicit default: cheaper than a fresh worktree per attempt, and consistent with rule 3b's model that a relaunch builds on committed-but-broken partial work rather than starting fresh. State this explicitly in the retry builder prompt, alongside rule 3b's own required note. **"Resync to the latest base ref" means merge or rebase the current base ref INTO the piece's existing worktree branch, preserving that branch's own commits/changes — never `git reset --hard <base>` or any other operation that resets/discards the worktree branch itself.** A hard reset would destroy the exact committed-but-broken partial work rule 3b says to preserve and build on; state this explicitly in the retry builder prompt so a naive agent doesn't read "resync" as "reset."

7. **A "must work from a clean checkout / fresh clone" clause cannot be checked inside the standard per-attempt critic loop, because it needs a real commit to check against, and mid-loop the only thing on disk is uncommitted builder state.** By default that commit is made by the **critic**, inline, on every verdict it issues (see the "Landing modes at a glance" table's worktree-default row) — builders themselves never commit (rule 8). So the clean-clone check still can't run mid-attempt, before that verdict's own commit lands — checking against uncommitted state will always fail regardless of code quality, no matter how many attempts. Route any such clause to a separate post-verdict verification step, checked against whichever landing-modes-table row actually applies to this run: worktree-default — check against that piece's own worktree branch as soon as a commit lands (PASS or the exhausted FAIL, both committed inline per the table above); shared-checkout fallback (or serial shared-checkout) — check against the critic's scoped commit on the review branch, PASS or the exhausted FAIL alike. The point in every mode is the same: check against a real commit, never mid-loop uncommitted builder state. Don't invent a third "let the builder commit" path — rule 8 has no such exception.

8. **Builders never commit mid-loop.** A separate, centralized agent commits once per wave, after all that wave's build/critique loops resolve (respecting rule 3 and rule 7) — see the "Landing modes at a glance" table above for the per-verdict commit-actor exceptions (worktree-default, shared-checkout fallback, serial shared-checkout). All of them route through the critic, never the builder.

9. **A final judge agent, independent of the per-piece critics, re-verifies the diff against a preserved pre-loop baseline** (`git tag` the state before starting) before recommending promote-or-revert per piece. This catches things per-piece loops structurally can't — e.g. a critic-approved piece that isn't actually better than baseline, or a defect shared by both the old and new code that no piece's clauses happened to check. **This does not contradict rule 3's "never discarded":** the judge only *recommends* promote-or-revert — it never executes a revert itself, and neither does the loop. Any actual revert requires explicit user approval.

10. **A builder's own scope-hygiene check is a loaded gun under shared concurrency — this supersedes rule 5's "file-disjoint pieces are safe for true `parallel()`" for any piece whose builder runs a `git status`/`git diff` self-check against the whole tree** (which correct ownership-verification practice requires). Every builder should verify it hasn't strayed outside its owned paths — that's correct practice, and the skill's own critic-prompt requirement (rule 1) asks for exactly this kind of check. But under `parallel()` against one shared checkout, that verification necessarily surfaces every sibling piece's legitimate concurrent changes too, and a bare `git status` cannot distinguish "my own accidental spillover" from "a sibling's real, in-progress work." A builder that responds to "unexpected changes" by running `git checkout --` or `rm -rf` will silently destroy a sibling's real, tested, already-critic-verified work — with no error, no warning, and no trace in git history once wave-commit runs, because the deleted files were never committed. This already happened (2026-08-29, "A Spell for You" Wave 1a): two file-disjoint pieces, each already critic-verified with real passing Unity test runs, were each `rm -rf`'d by a *different* sibling's builder mid-run, each believing the other's real files were its own mistake to clean up. The wave-commit then landed whatever coincidentally survived, making genuinely-good work look like a critic failure to any observer relying on the final repo state alone. **Fix — default, no exception:** every piece in a `parallel()` block gets `isolation: 'worktree'`, with no exception for "this piece is file-disjoint by ownership map" — file-disjoint-by-intent does not protect against a scope-check step that reads the *whole* tree. For exactly who commits, when, from where, and which branch it lands on under this default (and under the shared-checkout fallback and serial shared-checkout modes) — see the "Landing modes at a glance" table above; that table is authoritative, this rule is the incident that motivated it.

**Worktree-default commit actor (closes the gap left by "builders never commit"):** without a named actor here, an exhausted piece's uncommitted worktree would either be destroyed by teardown (violating rule 3) or leaked as a stale uncommitted worktree (re-arming rule 6's staleness bug). See the "Landing modes at a glance" table's worktree-default row for who commits, when, and the scoping — the critic, inline, on every verdict including the exhausted FAIL, so rule 3's "commit failed work, never discard" is honored inside the worktree too, not just at the wave-commit/shared-checkout layer.

**Worktree allocation granularity — VERIFIED LIVE 2026-09-10** (single-piece canary against a real repository, `wf_8a7f8903-511`): `Workflow`'s `agent({isolation:'worktree'})` gives every call its own independently-allocated worktree — confirmed, there is no parameter to force two calls to share one. What actually matters is **reachability via git refs, not a shared filesystem path**. A builder's commit in its own isolated worktree (e.g. `<repo>/.claude/worktrees/wf_<id>-1` on branch `worktree-wf_<id>-1`) is fully visible from ANY other location in the same repo — a separate worktree, or the main checkout — via ordinary `git log <branch>`, `git show <branch>:<path>`, `git diff <branch>`, etc., because worktrees of one repo share the same object database and refs. **The actual requirement: pass the builder's exact branch name into the critic's prompt** (read it back from the builder's own `agent()` result, e.g. `git branch --show-current` reported in a schema field) so the critic can reference it by name — the critic does NOT need `opts.isolation:'worktree'` pointed at the same path, and in practice runs fine unisolated in whatever the current working context is. Also confirmed: a worktree with a real commit is NOT auto-removed ("auto-removed if unchanged" means exactly that — unchanged only) and persists until an explicit `git worktree remove <path>` (read the exact path from a fresh `git worktree list`, don't guess) — and the branch behind it persists too, orphaned, until a separate `git branch -D <branch>`; folding both into the wave-commit agent's existing job (per the "Landing modes at a glance" table) is confirmed sufficient. Landing on a dedicated review branch cut from the pre-loop baseline tag, never merging into the run's starting branch directly, was also verified to leave that starting branch's HEAD byte-for-byte unchanged.

**Fallback — use only when worktree tooling is unavailable in this environment, not as an equal alternative "in order of preference":** see the "Landing modes at a glance" table's shared-checkout-fallback row for who commits, when, and the scoping. An unscoped `-A` on a shared checkout stages whatever *any* sibling piece currently has mid-flight in the tree, reproducing this exact hazard one step later, at commit time instead of at delete time — which is why that row scopes commits strictly to the piece's own declared owned paths, never `git add -A`.

Deletion under this failure mode is categorically unrecoverable via git — this is why "report, don't delete" is the *only* correct response to unexpected changes, not a conservative alternative to some recoverable option a builder might otherwise assume exists: an untracked file removed by `rm -rf` was never in the object database (no blob, no reflog, no `git fsck --lost-found` path), and a tracked-but-uncommitted change clobbered by `git checkout --` is equally gone unless it happened to be stashed first. Bake into every builder prompt as standing instruction, not a reactive patch: **never delete or revert a file you did not create in the current session; if `git status` shows unexpected changes outside your ownership map, stop and report it as an anomaly for the wave-commit/judge to sort out — do not `rm -rf` or `git checkout --` it away.**

**Exception, so this doesn't get read as blocking rule 3b's own retry model:** this prohibition is scoped to files **outside** the piece's declared ownership map — the prohibition is about not touching another piece's files, not about a fresh-context agent being unable to touch its own piece's prior work. Within the piece's own owned paths (in its own worktree per the default, or under the fallback's scoping), a retry builder may freely clean up, build on, or replace prior-attempt work, per rule 3b — a relaunched piece is expected to modify its own committed-but-broken partial work, that's the whole point of rule 3b's "the retry is in scope to complete or fix it."

11. **The worst-case spawn count is advisory unless the script actually enforces it — track spawns in-script and abort on a hard ceiling, don't just state the number and hope.** State the worst-case formula to the user before launch (see "Is this task even worth a Gauntlet Loop?"), then build a real ceiling from it in the script — e.g. `SPAWN_CEILING_MULTIPLIER` × that worst-case estimate (see the `SPAWN_CEILING` block in "Required shape" for the canonical implementation) — and increment/check a counter on every single `agent()` call via a shared `trackSpawn()` helper, not just at a few call sites. Build that ceiling from the same `MAX_ATTEMPTS`/`N_PIECES`/`N_WAVES` constants used to state the estimate, never a second hand-typed copy (rule 14) — a drifted mirror would silently understate the real ceiling. Abort the run the moment actual spawns exceed the ceiling, rather than continuing to spend silently past a number the user was told was the worst case.

12. **`agent()` has no in-script timeout — same accepted limitation as round-table's failure mode 9, inherited from the same primitive, and there is nothing to fix here.** See round-table's failure mode 9 for the full reasoning (no subprocess of gauntlet-loop's own to reap, and `Promise.race()` doesn't cancel the underlying `agent()` call); the mitigation for a stalled run is external, same as round-table's — watch `/workflows`, be ready to stop it manually. The one actionable bit specific to gauntlet-loop: if a piece's own builder shells out to a real long-running subprocess (not just `agent()`), that subprocess needs `setsid`/process-group handling so it can actually be killed on timeout, rather than leaving orphans behind.

13. **Detect no-progress across retries via a builder-reported diff hash, not just tracking pass/fail.** `Workflow` scripts have no filesystem or subprocess access at all (`require()` throws) — the orchestrating script cannot shell out to hash a diff itself, and for a worktree-isolated piece it couldn't reach that worktree's filesystem from outside anyway. So the **builder** computes the hash itself, in its own Bash call (from inside its own worktree when the piece is worktree-isolated), via `git diff <part.baseRef> -- <part.ownedPaths> | sha1sum` — targeting the actual base tag/ref this run started from — and reports the trimmed result back as `diffHash` in `BUILD_SCHEMA` (see the `buildPart` template above). The script then does a plain string comparison against the previous attempt's reported hash — there is no `hashDiff()` call anywhere in the script. An unchanged (or empty) hash means that attempt's builder+critic spawn pair produced no actual change to review; log it explicitly as a wasted attempt, distinct from a genuine attempt that changed something and still failed, and skip straight to the exhausted path rather than spending the rest of `MAX_ATTEMPTS` on a builder that has already shown it won't diverge from the same feedback.

14. **Never hardcode a second, mirrored copy of `MAX_ATTEMPTS` (or any other config value) into a generated prompt or schema.** Same lesson round-table already learned the hard way with `TURN_SCHEMA.messages.maxItems` (fixed 2026-08-26, after an earlier version hand-typed `maxItems: 2` as a second copy of `maxPerMemberPerRound` that could silently drift out of sync): if a builder/critic prompt or a verdict schema needs to state the attempt count, wave count, or spawn ceiling, build that string/value from the single `MAX_ATTEMPTS`/`N_PIECES`/`N_WAVES` constants at the top of the script — `` `attempt ${attempt}/${MAX_ATTEMPTS}` ``, not a prompt template with `3` typed in literally. The `SPAWN_CEILING` block in "Required shape" is the canonical worked example of this rule applied to the spawn ceiling itself — see the comment there.

15. **For any run with more than a couple of pieces, or any run that could plausibly need to survive a restart, write a manifest to disk before the build loop starts, and checkpoint per piece as results land.** (External review, 2026-09-10, RCA'd finding: gauntlet-loop's `Workflow` script cannot itself be a durable unattended supervisor — no state persists across a crash, and there's no OS-level process control to resume one — but it *can* cheaply checkpoint to disk, which is worth doing on its own merits even for a run the user is watching live.)
    - **Before the build loop starts**, `Write` a manifest object alongside the punchlist file (see "Before running") — a machine-readable sibling of it, not a replacement: pieces, `baseRef`, spawn ceiling, `MAX_ATTEMPTS`, and which landing mode this run is using (worktree-default / shared-checkout fallback / serial shared-checkout, per the "Landing modes at a glance" table) — a human or future system reading this on resume needs to know which commit mechanics and which branch apply, same reason everything else here is recorded.
    - **After each piece's `buildPart` call resolves** (pass or fail), write/update that piece's checkpoint entry to disk — could be the same manifest file, updated in place — recording pass/fail, attempts used, `wastedAttempts`. This is what lets a caller tell, after an interruption, which pieces are already done without re-running them.
    - **This checkpoint has no automatic resume-from-checkpoint logic in gauntlet-loop's own script** — building that would require the OS-level supervisor this skill explicitly doesn't attempt to be (see rule 12). The manifest is written for a human or a future automated system to read on manual resume, not for gauntlet-loop to consume itself mid-run.

## Before running

- **Verify a git repo and a dedicated working branch before any tagging or committing happens.** Confirm cwd is inside a git repo (e.g. `git rev-parse --is-inside-work-tree`), and confirm there's a dedicated working branch for this run. If it's not a git repo, or the current branch is a shared/default branch the user hasn't explicitly confirmed for this run, stop and ask — don't proceed into tagging or wave commits.
- Confirm with the user whether this qualifies as their environment's opt-in for multi-agent orchestration (some Claude Code setups require explicit confirmation before launching many agents) — state the worst-case spawn count as part of that check-in.
- **Before launching, tell the user explicitly what committing will look like**, something like: *"This run will create up to N commits on the review branch (see the "Landing modes at a glance" table), including any failed pieces (committed with an 'incomplete' flag, never reverted)."* Compute N from the spawn-count formula above (roughly `N_waves` commits, one per wave, each possibly containing incomplete pieces). This is the "never revert, commit incomplete pieces flagged incomplete" policy (rule 3) — say it up front, don't just leave it documented in this file.
- Tag the pre-loop state (`git tag <descriptive-name>`) so the final judge has a real baseline to compare against.
- **If this run is using the shared-checkout fallback or serial shared-checkout mode (see the "Landing modes at a glance" table), create and checkout a dedicated review branch from that same pre-loop baseline tag BEFORE the build loop starts** — e.g. `git checkout -b review/<descriptive-name> <baseline-tag>` — and do this before the first builder/critic `agent()` call, not as something wave-commit fixes up afterward. Under these two modes the critic commits inline with no separate piece branch and no wave-commit merge step to redirect commits after the fact: whatever branch HEAD is on when the critic runs `git commit` is where that commit lands, permanently. This is exactly the mechanism behind a real incident where a live run was invoked while sitting on the default branch and the critic's inline commits landed directly there. Worktree-default mode doesn't need this step — its review branch is populated by the wave-commit agent's merge/cherry-pick, not by inline commits landing wherever HEAD happens to be.
- **Create a punchlist file before writing the first `agent()` call, seeded with every piece as pending** — as an actual `Write` step early in the script, not a prose reminder to do it "later." A workflow that crashes mid-run before any commit agent runs is exactly the scenario this guards against, and the file has to exist before that risk window opens. Where to put it is up to the user's own conventions (a durable notes/reviews location if they have one, or a plain file in the project) — ask if unclear.
- **Also write the rule 15 manifest to disk before the build loop starts** — pieces, `baseRef`, spawn ceiling, `MAX_ATTEMPTS`, and this run's landing mode — alongside the punchlist file, as its own `Write` step (see rule 15).
- Worktree-isolated pieces (rule 10's default) were shaken down live 2026-09-10 in a real single-piece canary run — see rule 10's "Worktree allocation granularity" note for the verified findings. If running against a genuinely new repo/context (different filesystem, different git remote setup, a monorepo with submodules, etc.), a fresh single-piece canary is still cheap insurance — the mechanism is verified, not every possible environment.

## After running

- Report per-piece pass/fail and attempt counts, not just a summary — the user checks these numbers against what they watched live.
- If anything failed after `MAX_ATTEMPTS`, say so plainly and what's still needed — don't fold it into a "done" summary.
- Update the punchlist with real results — check off passed pieces, keep failed ones open with the verbatim failure detail. Only mark it fully resolved once every piece is genuinely done (including any follow-up retries).
- **A judge's promote-with-caveats finding — a piece promoted but with a judge-flagged residual gap (not a failure; it passed its own narrow clause but the judge caught something the clause didn't cover) — also goes into the punchlist, as a new open item.** Check off the original piece as done, but record the judge's specific caveat as its own follow-up entry — don't let a technically-passed piece cause a real residual gap to get silently dropped.
</content>
