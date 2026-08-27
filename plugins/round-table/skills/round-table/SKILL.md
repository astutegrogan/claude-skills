---
name: round-table
description: >-
  Use when the user asks for a "round table," a "meeting," or wants several specialist agents to weigh in on one judgment call — not a per-piece pass/fail loop. Bounded, turn-based multi-specialist deliberation for decisions where distinct perspectives (e.g. security, UX, compliance) might genuinely disagree and that disagreement is itself the information being bought. For "is this piece correct, loop until it passes," use the separate `gauntlet-loop` skill instead — the two share Workflow-script conventions (structured verdicts, explicit model:'sonnet', live log() cadence) but answer different questions. The primitive is reverse-engineered from Cursor's Grok Bot group-meeting orchestrator (rotating-start-speaker and mentions-restriction union semantics come from that research).
---

# Round-table

## Is this decision even worth a round-table?

Gauntlet-loop answers "is this piece correct?" — one critic, pass/fail, loop. A round-table answers "what should we do?" — a judgment call where several *distinct* specialist perspectives each need a real say and might legitimately disagree (ship-readiness with security + UX + compliance stakes; pick-between-architectures; kill-or-continue). If one well-briefed judge could answer it, use one judge — a round-table is up to `maxRounds × maxMembers` agent calls (18 at the defaults below: 3 rounds × 6 members, since each member's single call per round can return up to 2 messages), not 1. If it's per-piece verification, that's gauntlet-loop's critic, not a meeting. Reach for a round-table only when the disagreement between perspectives is itself the information you're buying.

**State that worst-case call count to the user before launching**, same as gauntlet-loop's spawn-count check-in — it scales fast with room size and round count. Note the actual cost curve: a room that goes quiet in round 1 (all-pass) is the *cheapest* case — one round of calls, then early close. The expensive case is a room that stays *active but unrestricted* for the full `maxRounds` — every eligible member gets a full agent call each of those rounds whether they end up speaking or passing, since a pass still costs the call.

The primitive is reverse-engineered from Cursor's Grok Bot group-meeting orchestrator: rooms of ≤6, ≤3 rounds, ≤10 total messages, ≤2 messages per member per round, 24-message history window, rotating start speaker, silent passes, early close on an all-pass round. Meetings are turn-based and synchronous by design — the source system's priority-interrupt explicitly does not apply to groups — which is why it maps cleanly onto Workflow-script's synchronous `agent()` calls with no interrupt machinery needed (there is no interrupt primitive in Workflow-script either, and the source design never needed one for meetings).

## Before running

- The Workflow tool requires explicit multi-agent-orchestration opt-in before it will run at all — the user asking for a "round table" or "meeting" by name (the trigger for this skill) already satisfies that requirement, the same way asking for a "gauntlet loop" by name satisfies it for that skill. You don't need a separate confirmation step for the opt-in itself; you DO still need to state the worst-case call count as part of launching (see above), since the opt-in being satisfied doesn't make the cost visible.
- **Runtime note:** `agent()`, `parallel()`, `pipeline()`, `phase()`, and `log()` are ambient functions provided by the Workflow-script runtime itself — not something to import or define. `agent(promptString, {label, phase, schema, model})` resolves to the schema-validated parsed object on success, or `null` on an unrecoverable failure (never throws under normal operation — see failure mode 7 and the try/catch hardening in the template below for what to do if that contract is ever violated).
- This primitive has now run live twice (a 2-member convergence case and a 3-member/3-round case that produced genuine dissent) plus a scripted harness covering every control-flow path (all-pass close, error handling, member cap, history-window truncation, mention restriction). Still worth treating a first run in a new context as a validation pass, but the mechanics themselves are no longer unproven.

## Template

```js
const RT_DEFAULTS = { maxMembers: 6, maxRounds: 3, maxMessages: 10, maxPerMemberPerRound: 2, historyWindow: 24 }

// Message length is bounded by the turnPrompt instruction ("~150 words") AND, as a code-enforced
// backstop, by MAX_MESSAGE_CHARS below — the prompt bound is advisory (an LLM can ignore it, and
// adversarial/injected content in a transcript message wouldn't respect it either), so anything
// pushed into the transcript gets hard-truncated regardless of what the prompt asked for.
const MAX_MESSAGE_CHARS = 1200
const TRUNCATION_SUFFIX = ' […truncated, exceeded code-enforced cap]'   // sliced INTO the cap, not appended after it — a naive append could exceed MAX_MESSAGE_CHARS by the suffix's own length

// Member shape (required by turnPrompt and the mention-matching logic below, used verbatim with
// no validation): { id: string, name: string, roleDescription: string }. A missing or misnamed
// field (e.g. "role" instead of "roleDescription") degrades silently — undefined gets interpolated
// into prompts, mentions silently fail to match — rather than erroring, so get this shape right.

// TURN_SCHEMA.messages.maxItems is built from cfg.maxPerMemberPerRound inside runRoundTable (not
// hardcoded here) specifically so overriding maxPerMemberPerRound in opts can't silently drift out
// of sync with the schema that's supposed to enforce it — an earlier version hardcoded maxItems: 2
// as a second, manually-mirrored copy of the same number; found and fixed during review of this
// skill's own logic.
function buildTurnSchema(maxPerMemberPerRound) {
  return {
    type: 'object',
    properties: {
      messages: { type: 'array', items: { type: 'string' }, maxItems: maxPerMemberPerRound },  // 0 messages = pass; nothing here is ever posted if empty
      mentions: { type: 'array', items: { type: 'string' } },  // member ids; restricts who may respond next round
    },
    required: ['messages'],
  }
}

function turnPrompt(topic, member, allMembers, windowed, round, maxRounds, maxPerMemberPerRound) {
  const roster = allMembers.map(m => `- ${m.id}: ${m.name} — ${m.roleDescription}`).join('\n')
  const transcript = windowed.length
    ? windowed.map(t => `[round ${t.round}] ${t.member}: ${t.message}`).join('\n')
    : '(no messages yet — you may be opening the discussion)'
  return `You are ${member.name} (${member.id}) in a bounded round-table. Your role: ${member.roleDescription}
Topic under deliberation: ${topic}
Members:\n${roster}
Round ${round}/${maxRounds}. Recent transcript (windowed):\n${transcript}
Speak ONLY from your specialty and ONLY if you add something not already on the table — repeating an agreement or restating another member's point is a pass, not a message. Return an empty messages array to pass (nothing you write in a pass is ever posted). You may return up to ${maxPerMemberPerRound} messages this round if you genuinely have that many distinct points — most turns should be 0 or 1. Keep each message under ~150 words; this is a bounded meeting, not an essay exchange.
Use mentions:[ids] only if a specific member must answer you next round — mentioning restricts the ENTIRE next round to only the members named by ANYONE this round (not just the members you personally name — if another member also mentions someone this round, next round is the union of everyone's mentions), silencing everyone else (including you, unless you or someone else also mentions you). Use it sparingly.`
}

async function runRoundTable(topic, members, opts = {}) {
  const cfg = { ...RT_DEFAULTS, ...opts }
  if (members.length > cfg.maxMembers) throw new Error(`Room cap is ${cfg.maxMembers} members; got ${members.length}`)
  const turnSchema = buildTurnSchema(cfg.maxPerMemberPerRound)   // built once per run from cfg, never hardcoded
  phase(`Round-table: ${topic.slice(0, 60)}`)
  const transcript = []   // {round, member, message}
  let total = 0
  let restrictTo = null   // ids mentioned last round, or null = everyone
  let roundsRun = 0
  let endedEarly = false
  let errorCount = 0
  let hitMessageCap = false   // true if the room ran out of message budget before every eligible member got asked — distinct from a genuine all-pass/completed close

  for (let round = 1; round <= cfg.maxRounds && total < cfg.maxMessages; round++) {
    roundsRun = round
    // Rotating start speaker: round 1 starts at member[0], round 2 at member[1], ...
    // NOTE on "round" semantics: this is a sequential go-around within a round, not simultaneous
    // turns — `windowed` is recomputed inside the per-member loop below, so a member later in this
    // round's rotation sees messages already posted earlier in this SAME round, not just prior
    // rounds. "Rotating start" varies who leads, but doesn't equalize this within-round
    // informational advantage. That's the intended design (matches the source's one-turn-per-
    // member-per-round shape), not a bug — but "round" here means "one call budget per member,"
    // not "everyone reacts only to what existed before this round started."
    const order = members.map((_, i) => members[(i + round - 1) % members.length])
    const eligible = restrictTo ? order.filter(m => restrictTo.includes(m.id)) : order
    const mentionsThisRound = new Set()
    let spokeThisRound = 0
    let erroredThisRound = 0

    // One call per member per round — NOT a double sweep. A member returns up to
    // maxPerMemberPerRound messages from that single call. (An earlier version of this
    // skill called each member twice per round to fill the per-member cap, which silently
    // doubled worst-case cost and drifted from the source design's one-turn-per-member-per-round
    // shape. Found and fixed during review of this skill's own logic.)
    for (const member of eligible) {
      // If the message budget is already exhausted, every remaining eligible member this round is
      // silently skipped — never even asked. Log it: without this, the caller has no way to tell
      // "the meeting ran to natural completion" from "3 members never got a turn because the room
      // filled up," and the return value alone doesn't distinguish these either.
      if (total >= cfg.maxMessages) {
        hitMessageCap = true
        const skippedCount = eligible.length - eligible.indexOf(member)
        log(`r${round} ${member.id}: SKIPPED, along with ${skippedCount - 1} other eligible member(s) this round (message budget ${cfg.maxMessages}/${cfg.maxMessages} already exhausted)`)
        break
      }
      const windowed = transcript.slice(-cfg.historyWindow)   // capped window, never the full history
      // try/catch around the agent() call itself, not just a null-check on its result: the whole
      // error-handling design (errorCount, distinct logging, early-close detection) rests on the
      // assumption that agent() ALWAYS resolves to null on failure and never throws. That's an
      // unenforced upstream contract — if it's ever violated (a schema-validation error, a network
      // exception not normalized to null, a harness bug), an uncaught throw propagates straight out
      // of runRoundTable and the CALLER gets nothing back: not the transcript already gathered, not
      // partial roundsRun/errorCount, nothing — a meeting several rounds deep with real dissent on
      // record simply vanishes. A caught exception is treated identically to a null return (found
      // and fixed during review of this skill's own logic).
      let turn = null
      let thrownMessage = null
      try {
        turn = await agent(
          turnPrompt(topic, member, members, windowed, round, cfg.maxRounds, cfg.maxPerMemberPerRound),
          { label: `rt:${member.id}:r${round}`, phase: `Round-table round ${round}`, schema: turnSchema, model: 'sonnet' }
        )
      } catch (err) {
        thrownMessage = err?.message || String(err)
      }
      // An errored/unrecoverable agent call resolves to null (Workflow-script's documented
      // behavior) — this is NOT a voluntary pass and must be logged/counted distinctly, or an
      // outage on every member this round looks identical to a genuine all-pass early close. A
      // caught exception is treated identically to a null return, one unified log/count path.
      if (turn == null) {
        errorCount++; erroredThisRound++
        log(`r${round} ${member.id}: ERROR (${thrownMessage ? `agent call threw: ${thrownMessage}` : 'agent call returned null'}) — treated as silent, NOT a pass`)
        continue
      }
      const messages = (turn.messages || []).filter(Boolean).slice(0, cfg.maxPerMemberPerRound)
        .map(m => m.length > MAX_MESSAGE_CHARS ? m.slice(0, MAX_MESSAGE_CHARS - TRUNCATION_SUFFIX.length) + TRUNCATION_SUFFIX : m)
      if (!messages.length) { log(`r${round} ${member.id}: pass`); continue }
      for (const message of messages) {
        if (total >= cfg.maxMessages) {
          // This member had another message queued but the room filled up mid-turn — log it so
          // "budget exhausted with content still pending" is visible, not indistinguishable from
          // a clean stop.
          hitMessageCap = true
          log(`r${round} ${member.id}: remaining message(s) this turn DROPPED (message budget ${cfg.maxMessages}/${cfg.maxMessages} exhausted mid-turn)`)
          break
        }
        transcript.push({ round, member: member.id, message })
        spokeThisRound++; total++
        log(`r${round} ${member.id} [${total}/${cfg.maxMessages}]: ${message.slice(0, 160)}`)
      }
      // Self-mentions are allowed, matching the prompt's promise above ("...including you, unless
      // you or someone else also mentions you") — a mention of X from ANYONE this round, not just
      // from X, keeps X eligible next round; a member can also deliberately mention themselves to
      // restrict the next round to just themselves (e.g. to finish an escalating point
      // uninterrupted). An earlier version filtered self-mentions out silently, contradicting the
      // prompt; found and fixed during review of this skill's own logic.
      for (const id of turn.mentions || []) if (members.some(m => m.id === id)) mentionsThisRound.add(id)
    }
    if (spokeThisRound === 0) {
      endedEarly = true
      // IMPORTANT: `restrictTo` here still reflects whether THIS round was mention-restricted (it's
      // not reassigned until after this block). A restricted round going quiet is NOT the same
      // signal as full-room consensus — the members silenced by the restriction never got asked at
      // all this round, so their silence proves nothing about whether they'd have dissented. Found
      // during review of this skill's own logic: a real gap where a restricted round's pass
      // was logged identically to a genuine all-pass, even though most of the room was silenced by
      // protocol, not by agreement. Distinguish it explicitly rather than restructure the close
      // behavior — the meeting still ends here either way, but the log must not overstate consensus.
      const restrictedNote = restrictTo ? ` (RESTRICTED round — only ${eligible.length}/${members.length} member(s) were eligible to speak; this is NOT full-room consensus)` : ''
      if (erroredThisRound === eligible.length) {
        log(`Round ${round}: ALL ${erroredThisRound} member(s) errored (not a genuine pass) — meeting closed early${restrictedNote}. Treat the transcript as unreliable, do not synthesize from it without checking why.`)
      } else if (erroredThisRound > 0) {
        // A MIX of errors and voluntary passes must not read as a clean consensus signal either —
        // only report "all passed" when every eligible member genuinely passed, zero errors.
        log(`Round ${round}: closed early with ${erroredThisRound} member error(s) mixed in with passes — not a fully clean all-pass, inspect before trusting${restrictedNote}.`)
      } else {
        log(`Round ${round}: all passed — meeting closed early${restrictedNote}`)
      }
      break
    }
    restrictTo = mentionsThisRound.size ? [...mentionsThisRound] : null
    // Only log the next-round restriction if there IS a next round — the loop has TWO exit
    // conditions (round <= cfg.maxRounds AND total < cfg.maxMessages, in the for-loop header above), and a restriction
    // set logs a phantom "Round N+1 restricted to..." if EITHER one ends the meeting before that
    // round runs, not just the maxRounds one. An earlier fix only guarded the maxRounds exit and
    // missed the maxMessages exit — same bug class, second exit path. Found and fixed during review
    // of this skill's own logic.
    if (restrictTo && round < cfg.maxRounds && total < cfg.maxMessages) log(`Round ${round + 1} restricted to: ${restrictTo.join(', ')}`)
  }
  log(`Round-table closed: ${total} messages over ${roundsRun} round(s)${endedEarly ? ' (early)' : ''}${errorCount ? `, ${errorCount} member error(s) — inspect before trusting the transcript` : ''}${hitMessageCap ? `, message budget was hit (${cfg.maxMessages}/${cfg.maxMessages}) — some eligible members/messages were skipped, this is not a natural completion` : ''}`)
  return { transcript, rounds: roundsRun, messages: total, endedEarly, errorCount, hitMessageCap }
}
```

## Optional synthesis — a layer on top, never a seat at the table

The source orchestrator has **no hard-coded manager role**; the room is a complete primitive on its own. If you need a single decision out of the transcript, run one synthesis agent *once, after the room closes* — it is not a member, never speaks in-room, and is entirely optional (sometimes the transcript itself is the deliverable to hand the user).

**Guard against synthesizing from nothing.** If every member errored or passed with zero messages recorded, `result.transcript` is empty — do not run the synthesis call in that case, it will confidently invent a decision from no evidence. Check `result.errorCount` and `result.transcript.length` first.

```js
// Root cause of a real failure, RCA'd in full: the model's synthesis is naturally one
// continuous piece of reasoning, but the old schema offered two adjacent, undescribed string fields
// (decision/rationale) and the prompt below only ever asked for "ONE decision" + dissents — it never
// mentioned "rationale" at all. With no signal to split its own prose, the model dumped everything
// into `decision`, failed schema validation (missing required `rationale`) four times in a row, and
// on the fifth attempt capitulated with a minimal placeholder just to pass validation — a real,
// substantive synthesis existed in its own reasoning the whole time, it just never made it into the
// return value. Fixed by: (a) description strings on both fields so the model knows what goes where,
// (b) the prompt explicitly asking for both parts by name, matching the schema exactly.
const SYNTH_SCHEMA = {
  type: 'object',
  properties: {
    decision: { type: 'string', description: 'The single synthesized decision/recommendation, stated directly — not the reasoning behind it.' },
    rationale: { type: 'string', description: 'Why — the reasoning connecting the transcript to the decision above. Distinct from decision: this is the "because," not a restatement of the "what."' },
    dissents: { type: 'array', items: { type: 'string' } },
  },
  required: ['decision', 'rationale'],
}
const result = await runRoundTable(topic, members)
let verdict = null
if (!result.transcript.length) {
  log(`Round-table produced zero messages${result.errorCount ? ` (${result.errorCount} member error(s))` : ' (genuine all-pass)'} — skipping synthesis, nothing to synthesize from.`)
} else {
  verdict = await agent(
    `You did not attend this meeting. Read the transcript and synthesize ONE decision on: ${topic}\n` +
    `Give BOTH parts explicitly: "decision" (the recommendation itself, stated directly) AND "rationale" (why — the reasoning connecting the transcript to that decision). These are two distinct fields, not one field split in half.\n` +
    `Record real dissents as dissents — do not paper over disagreement.\nTranscript:\n` +
    result.transcript.map(t => `[r${t.round}] ${t.member}: ${t.message}`).join('\n'),
    { label: 'rt:synthesis', phase: 'Round-table synthesis', schema: SYNTH_SCHEMA, model: 'sonnet' }
  )
  // The verdict MUST be consumed here — logged and/or returned — not left as a local variable
  // that silently vanishes. An earlier version of this doc's example did exactly that: computed
  // verdict, never logged or returned it, so a caller copying the snippet verbatim would pay for
  // the synthesis call and then lose the result. Found and fixed during review of this skill's own
  // logic.
  log(`Synthesis: ${verdict?.decision}\nRationale: ${verdict?.rationale}${verdict?.dissents?.length ? `\nDissents: ${verdict.dissents.join('; ')}` : ''}`)
}
// Whatever script calls this, its own top-level return (or whatever downstream step consumes the
// result) needs `verdict` in it too, e.g.: return { result, verdict }
```

## Anticipated failure modes to guard against (ported from the source system's verified constraints, and confirmed against two live runs plus a scripted harness — see "Before running" above)

1. **Never pass the full transcript into a turn — always `slice(-historyWindow)`.** An unbounded transcript defeats the point of bounding rounds and messages: the caps hold the message count flat while the real token cost per turn keeps growing anyway. The source system windows at 24 for exactly this reason.
2. **Enforce the member cap with a hard throw, not a warning.** Every member is up to `maxRounds` agent calls; a 10-member "room" is a cost bug wearing a feature's clothes. The source caps rooms at 6. Note this throw is intentionally overridable — `runRoundTable(topic, members, {maxMembers: 8})` will run 8 members without complaint, since `cfg.maxMembers` (not the hardcoded 6) is what's checked. That's a deliberate escape hatch for a caller who's made a conscious call to exceed the source default, not a bug — but it means the cap only protects you if you don't also raise it in `opts`.
3. **Discard pass content unconditionally.** A member that returns an empty `messages` array must not leak anything into the transcript — silent passes are what make the all-pass early-close signal trustworthy. If passes half-post, the room can never go quiet and always burns all 3 rounds.
4. **Do not add a moderator as a room member.** A manager inside the room eats message budget, biases the rotating start order, and re-creates the hard-coded-manager design the source system deliberately avoided. Synthesis runs once, after close, from outside.
5. **Do not bolt on interrupts or async side-channels between members.** The source system explicitly excludes priority-interrupt from groups; turn-based synchronous is the design, not a limitation — and it's the only shape Workflow-script's sequential `agent()` calls can honestly deliver anyway.
6. **Instruct members that agreement is a pass.** Without the "restating another member's point is a pass" line in the prompt, LLM members politely echo each other, the room never produces an all-pass round, and early termination — the mechanism that makes short meetings cheap — never fires.
7. **Never conflate an errored agent call with a voluntary pass.** `agent()` resolves to `null` on an unrecoverable error, not to a pass-shaped object — if this gets treated the same as `messages: []`, an API outage on every member in one round looks exactly like a genuine all-pass close, and synthesis will then run on (or be skipped from) a transcript for the wrong reason. Log and count errors distinctly (see `errorCount` in the template above), and treat an all-error round's early close as suspect, not as a real consensus signal.
8. **Bound message length, not just message count.** The 24-entry history window caps how many past messages a turn sees, but nothing stops any single message from being 800 words — which reintroduces the per-turn token-growth problem the window was meant to solve. The `turnPrompt` template above includes an explicit "~150 words" instruction for this reason, and `MAX_MESSAGE_CHARS` code-enforces a hard backstop (advisory prompt bound + code-enforced cap, not either alone).
9. **No per-call timeout exists, and there is no clean workaround — this is a real, accepted limitation, not something worked around here.** Confirmed against official docs: `agent()` has no `timeout`/`timeoutMs` option, and there's no workflow-level timeout either. A stalled call (network stall, provider-side hang) blocks the synchronous round-based loop indefinitely. `Promise.race()` against a timeout promise is NOT a real fix if you're tempted to add one — it stops the *script* from waiting, but doesn't cancel the underlying `agent()` call, which keeps running (and costing) orphaned in the background; you'd trade "the loop hangs" for "the loop moves on while an untracked call still runs somewhere." If a hang is a real operational risk for a given use, the mitigation is external (watch `/workflows`, be ready to stop it manually) — there's no in-script fix to write.
10. **No circuit breaker on systemic failure — the loop pays the full worst-case cost to discover a meeting had zero chance.** If `agent()` is failing systemically (bad credentials, model outage), nothing here fails fast: every remaining member of every remaining round is still called, each resolving to `null` (or a caught exception, per the try/catch above), before the final summary log reveals it was all errors. That's up to the full `maxRounds × maxMembers` call budget spent finding out the meeting never had a chance — directly undercutting the "state the worst-case cost up front" discipline this skill otherwise holds itself to. **Deliberately left unfixed, with a recorded dissent** (from a round-table run using this skill on its own logic): the synthesized recommendation was to defer circuit-breaker/retry policy to the `agent()`/Workflow-script primitive itself rather than duplicate it inside every skill that calls `agent()` — but the safety-reviewer perspective in that same meeting dissented, arguing a primitive that calls itself "bounded" shouldn't lean on an unstated upstream guarantee for the one dimension (failure cascade) it doesn't actually bound. Unresolved; it's the user's call if it ever matters in practice.
11. **A schema with undescribed, ambiguous fields lets a model quietly capitulate to a placeholder rather than fail loudly.** RCA'd from a real incident: the synthesis schema's `decision`/`rationale` fields had no `description`, and the prompt only ever asked for a "decision," never mentioning "rationale" by name. The model's genuine, substantive synthesis had no field to put half of itself in, failed validation four times, and on the fifth attempt returned a minimal placeholder (`{"decision":"test decision","rationale":"test rationale"}`) just to satisfy the validator — a real answer existed in the model's own reasoning the entire time, only the returned value was lost. Two general lessons, not just a synthesis-specific fix: (a) every schema field needs a `description` distinguishing it from its siblings, and the prompt needs to name every required field explicitly, not just describe the task in prose; (b) never trust a schema-valid response as *content*-valid without a sanity check — a suspiciously short or generic-sounding payload after multiple retries is a signal to log and flag, not to silently accept and move on.
12. **A restricted round going quiet is not the same signal as full-room consensus.** Found during review of this skill's own logic: if a mention restricts round N+1 to a subset of members, and that subset passes, the code correctly closes the meeting (per the source's "no-message-round ends it" rule) — but the log and the early-close signal don't distinguish "everyone eligible this round passed" from "most of the room was silenced by protocol and never got asked." The members excluded by the restriction may have had real, unspoken dissent; their silence proves nothing. The fix is to log this distinction explicitly (see `restrictedNote` in the template), not to change the close behavior itself — a restricted round ending the meeting is correct per the source design, it just needs honest labeling.

## Worked example

```js
const members = [
  { id: 'sec',  name: 'Security reviewer',   roleDescription: 'attack surface, secrets handling, authz — speak only on security-relevant risk' },
  { id: 'ux',   name: 'UX reviewer',         roleDescription: 'user-facing friction, error states, first-run experience' },
  { id: 'comp', name: 'Compliance reviewer', roleDescription: 'data-retention, GDPR exposure, audit-trail obligations' },
]
const room = await runRoundTable(
  'The relay-webhook feature branch is code-complete and gauntlet-passed piece-by-piece. Are we ready to ship it to production today, or does something block?',
  members,
  { maxRounds: 3 }   // defaults otherwise: 6 members / 10 messages / 2 per member per round / 24-window
)
// then optionally: the guarded SYNTH_SCHEMA call above to collapse room.transcript into one decision + dissents
```

## Relationship to gauntlet-loop

The two are siblings, not one-inside-the-other: gauntlet-loop decomposes a goal into independently-gradable pieces and loops each until a critic passes it; round-table takes a single question to several specialists at once and surfaces where they disagree. A real task can use both in sequence — gauntlet-loop builds and verifies the pieces, round-table makes the final ship/no-ship call on the assembled result — but neither requires the other, and round-table is equally valid invoked on its own for a pure judgment call with no build involved.
