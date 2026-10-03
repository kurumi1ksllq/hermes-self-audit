# hermes-self-audit

A Hermes skill that audits a Hermes install **offline, with zero external tools**:

- which **skills** are dead weight (indexed every turn, never used)
- which **tools / toolsets / MCP / plugins** you pay schema tax for but never call
- where **tokens** actually go — fixed per-turn tax vs. historical traffic

## Install

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
