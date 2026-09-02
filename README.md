# claude-skills

Claude Code skills built by [Delegated Trust](https://github.com/astutegrogan) — each one a self-contained procedure that loads as forced instructions when it's invoked, rather than something to remember and re-derive every time. Distributed as a Claude Code plugin marketplace, so installing one doesn't require git or any shell literacy.

**Start here: [gauntlet-loop](./plugins/gauntlet-loop/)** — makes Claude Code decompose a build/fix into independently-gradable pieces and grade each one with a fresh-context blind critic before calling it done, instead of one bundled build-then-check pass where a weak piece can hide behind strong ones.

© Delegated Trust. All rights reserved. You're welcome to install and use these skills, and adapt them for your own work. Not offered under an open-source license — please don't republish or redistribute them as your own.

## Skills

- **[gauntlet-loop](./plugins/gauntlet-loop/)** — Matt Shumer's builder/critic sub-agent pattern, ported to Claude Code's `Workflow` tool and hardened against real usage. Requires the `Workflow` tool.
- **[round-table](./plugins/round-table/)** — bounded, turn-based multi-specialist deliberation for judgment calls where distinct perspectives might genuinely disagree, reverse-engineered from Cursor's Grok Bot group-meeting orchestrator. Requires the `Workflow` tool.

## Install

In Claude Code:

```
/plugin marketplace add astutegrogan/claude-skills
/plugin install gauntlet-loop@claude-skills
/plugin install round-table@claude-skills
```

That's it — no git, no terminal commands outside Claude Code itself. The skill becomes available as `/gauntlet-loop:gauntlet-loop`, or just ask for what it does in plain language and Claude Code will invoke it. See each skill's own `README.md` for prerequisites.

To update later: `/plugin marketplace update claude-skills`, then reinstall.

## Adding a skill

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the directory shape and quality bar, and [AUTHORING.md](./AUTHORING.md) for how skills in this repo are written.

## Bugs / feedback

Open a [GitHub issue](https://github.com/astutegrogan/claude-skills/issues) on this repo.
