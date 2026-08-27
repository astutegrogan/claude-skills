# Authoring a skill

How skills in this repo are written and packaged — for reference, whether you're adapting an existing one or (per [CONTRIBUTING.md](./CONTRIBUTING.md)) reporting something that should become a new rule.

## Shape

This repo is a Claude Code plugin marketplace. Each skill is packaged as its own plugin:

```
plugins/<plugin-name>/
  .claude-plugin/
    plugin.json          # required — name, description, version, author
  skills/
    <skill-name>/
      SKILL.md            # required — YAML frontmatter (name, description) + the procedure
  README.md               # required — what it does, why, and how to install it
```

`plugin.json`'s `name` must match its directory name under `plugins/`. `SKILL.md`'s frontmatter `name` must match its directory name under `skills/`. The root `.claude-plugin/marketplace.json` must list every plugin that exists under `plugins/` (and nothing that doesn't) — `scripts/validate_plugins.py` checks all of this in CI on every push.

Look at `plugins/gauntlet-loop/` for the reference example: a `SKILL.md` written as forced instructions for Claude Code to follow, a `README.md` written for a human deciding whether to install it. Keep the two in sync — the README shouldn't claim behavior the skill doesn't actually enforce.

## Adding a new plugin to the marketplace

1. Create the directory structure above under `plugins/<name>/`.
2. Add an entry to `.claude-plugin/marketplace.json`'s `plugins` array (`name`, `source: "./plugins/<name>"`, `description`, `version`, `author`).
3. Run `python3 scripts/validate_plugins.py` locally, and `claude plugin validate ./plugins/<name>` if you have the CLI, before pushing.

## Bar for a rule inside a skill

- **Grounded in real usage, not a paraphrase of a good idea.** If a rule exists, it should trace back to something that actually happened — a real failure mode, a real fix. See how `gauntlet-loop`'s rules each cite the specific incident behind them (dates, counts, what actually broke).
- **Specific and enforceable, not general advice.** "Write good tests" is not a rule; "run X, check Y, fail if Z" is. A rule a fresh agent could disagree with or interpret three different ways isn't done yet.
- **De-personalized.** A skill published here has to run correctly for anyone who installs it — no references to a specific person, a specific machine's file paths, or a specific project's private history as if they're universal. Case-study evidence (dates, counts, what broke) stays; the private names and paths that only make sense on one machine don't.
