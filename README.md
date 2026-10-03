# hermes-self-audit

A Hermes skill that audits a Hermes install **offline, with zero external tools**:

- which **skills** are dead weight (indexed every turn, never used)
- which **tools / toolsets / MCP / plugins** you pay schema tax for but never call
- where **tokens** actually go — fixed per-turn tax vs. historical traffic

## One-liner: install + run, straight to results

**Any terminal (no agent needed):**

```bash
hermes skills install https://raw.githubusercontent.com/kurumi1ksllq/hermes-self-audit/main/SKILL.md --yes && python "$HOME/AppData/Local/hermes/skills/hermes-self-audit/scripts/hermes_selfaudit.py"
```

On Linux / macOS swap the path for `~/.hermes/skills/hermes-self-audit/scripts/hermes_selfaudit.py`.

**Cross-platform (auto-locates the script, no hardcoded path):**

```bash
hermes skills install https://raw.githubusercontent.com/kurumi1ksllq/hermes-self-audit/main/SKILL.md --yes \
  && python "$(python -c "import glob,os;print([p for b in (os.path.expanduser('~/.hermes'),os.path.join(os.environ.get('LOCALAPPDATA',''),'hermes')) for p in glob.glob(os.path.join(b,'skills/hermes-self-audit/scripts/hermes_selfaudit.py'))][0])")"
```

**Or just say this to your Hermes:**

```
装 https://raw.githubusercontent.com/kurumi1ksllq/hermes-self-audit/main/SKILL.md 然后立刻用 hermes-self-audit 跑一遍全量审计
```

Hermes installs it, loads it, runs it, and hands back the three SKILLS / TOOLS / TOKENS tables.

## Install only

```bash
hermes skills install https://raw.githubusercontent.com/kurumi1ksllq/hermes-self-audit/main/SKILL.md
```

Then just ask your Hermes: *"用 hermes-self-audit 查一下哪些 skill 冗余、token 花哪了"*.

## Files

- `SKILL.md` — the skill (triggers, method, pitfalls)
- `scripts/hermes_selfaudit.py` — pure-stdlib, read-only audit script

## Run the script directly

```bash
python scripts/hermes_selfaudit.py
python scripts/hermes_selfaudit.py --section skills --json
```
