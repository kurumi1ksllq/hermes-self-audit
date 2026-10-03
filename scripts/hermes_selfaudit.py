#!/usr/bin/env python3
"""hermes_selfaudit.py — offline self-audit for a Hermes install.

Answers three questions WITHOUT any external tool or network call:

  skills  Which skills are dead weight, and what does the always-on skill
          index actually cost every turn?
  tools   Which tools/toolsets (incl. MCP-bridged tools) do you pay schema
          tax for, and which of them you have never actually called?
  tokens  Where do tokens actually go — fixed per-turn tax vs historical
          traffic — so you know which layer is worth optimizing.

Everything is local: it shells out to `hermes prompt-size --json`, reads
skills/.usage.json, and opens state.db read-only. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict

# --------------------------------------------------------------------------- #
# Locating the Hermes home (Windows: %LOCALAPPDATA%\hermes ; posix: ~/.hermes)
# --------------------------------------------------------------------------- #


def default_hermes_home() -> str:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
        return os.path.join(base, "hermes")
    return os.path.join(os.path.expanduser("~"), ".hermes")


def resolve_home(arg: str | None) -> str:
    home = arg or default_hermes_home()
    home = os.path.abspath(os.path.expanduser(home))
    if not os.path.isdir(home):
        sys.exit(f"[selfaudit] hermes home not found: {home}\n"
                 f"           pass --home /path/to/hermes")
    return home


# --------------------------------------------------------------------------- #
# prompt-size: the always-on per-turn tax (authoritative, from Hermes itself)
# --------------------------------------------------------------------------- #


def run_prompt_size(hermes_bin: str) -> dict | None:
    exe = shutil.which(hermes_bin) or hermes_bin
    try:
        out = subprocess.run(
            [exe, "prompt-size", "--json"],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"[selfaudit] could not run '{hermes_bin} prompt-size --json': {e}",
              file=sys.stderr)
        return None
    if out.returncode != 0:
        print(f"[selfaudit] prompt-size exited {out.returncode}: {out.stderr.strip()[:200]}",
              file=sys.stderr)
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        print("[selfaudit] prompt-size did not return JSON", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# skills: usage.json (who was ever used) joined with the index cost (what it costs)
# --------------------------------------------------------------------------- #


def load_usage(home: str) -> dict:
    path = os.path.join(home, "skills", ".usage.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def load_config_text(home: str) -> str:
    for name in ("config.yaml", "config.yml", "config.json"):
        path = os.path.join(home, name)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            except OSError:
                return ""
    return ""


def report_skills(home: str, ps: dict | None, usage: dict, as_json: bool) -> dict:
    """Join index cost (what each skill costs every turn) with usage (was it ever
    used). Returns a dict; prints a human table unless as_json."""
    cost_by_name: dict[str, dict] = {}
    if ps:
        for row in ps.get("skills_breakdown", []) or []:
            cost_by_name[row.get("name", "")] = row

    # Union of names seen in usage.json and in the live index.
    names = set(usage) | set(cost_by_name)

    rows = []
    for name in names:
        u = usage.get(name, {})
        c = cost_by_name.get(name, {})
        index_bytes = int(c.get("index_line_bytes") or 0)
        body_bytes = int(c.get("skill_md_bytes") or 0)
        archived = bool(u.get("archived_at"))
        state = u.get("state") or "?"  # active / idle / archived / ...
        use_count = int(u.get("use_count") or 0)
        view_count = int(u.get("view_count") or 0)
        last_used = u.get("last_used_at")
        in_index = name in cost_by_name
        rows.append({
            "name": name,
            "state": state,
            "archived": archived,
            "use_count": use_count,
            "view_count": view_count,
            "last_used_at": last_used,
            "index_bytes": index_bytes,
            "skill_md_bytes": body_bytes,
            "in_index": in_index,
        })

    # "Dead weight": indexed (so it taxes every turn) but never used or viewed.
    indexed_never_used = [
        r for r in rows if r["in_index"] and r["use_count"] == 0 and r["view_count"] == 0
    ]
    indexed_never_used.sort(key=lambda r: -r["index_bytes"])
    dead_bytes = sum(r["index_bytes"] for r in indexed_never_used)

    total_index = sum(r["index_bytes"] for r in rows if r["in_index"])
    summary = {
        "indexed_skills": sum(1 for r in rows if r["in_index"]),
        "known_skills": len(rows),
        "archived": sum(1 for r in rows if r["archived"]),
        "index_total_bytes": total_index,
        "never_used_indexed": len(indexed_never_used),
        "never_used_index_bytes": dead_bytes,
        "never_used": [
            {"name": r["name"], "index_bytes": r["index_bytes"],
             "skill_md_bytes": r["skill_md_bytes"]}
            for r in indexed_never_used
        ],
    }

    if as_json:
        return summary

    print("\n== SKILLS: always-on index cost vs. actual use ==")
    if ps is None:
        print("   (prompt-size unavailable — index costs omitted; usage still shown)")
    print(f"   indexed skills : {summary['indexed_skills']}")
    print(f"   archived       : {summary['archived']}")
    if ps:
        idx = ps.get("skills_index", {})
        print(f"   index size     : {idx.get('bytes', '?')} bytes "
              f"(~{round((idx.get('bytes') or 0)/4)} tok) — paid EVERY turn")
        print(f"   index total    : {total_index} bytes across indexed skills")
    print(f"   indexed but never used/viewed: {len(indexed_never_used)} "
          f"({dead_bytes} bytes of index)")
    if indexed_never_used:
        print("\n   top dead weight (indexed, 0 uses, 0 views):")
        print(f"   {'skill':<40} {'idx B':>7} {'body B':>9}")
        for r in indexed_never_used[:20]:
            print(f"   {r['name'][:40]:<40} {r['index_bytes']:>7} {r['skill_md_bytes']:>9}")
        print("\n   -> 'hermes curator archive <name>' drops the index line (reversible),")
        print("      or 'hermes skills uninstall <name> --yes' removes it for good.")
    return summary


# --------------------------------------------------------------------------- #
# tools: schema tax per toolset + which tools were actually called historically
# --------------------------------------------------------------------------- #


def db_connect(home: str) -> sqlite3.Connection | None:
    path = os.path.join(home, "state.db")
    if not os.path.exists(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def tool_call_counts(con: sqlite3.Connection) -> dict[str, dict]:
    """Per-tool call count + bytes from the messages table.

    A tool result is a role='tool' row whose tool_name is set. Counting those rows
    (and their content length) is a proxy for how much each tool shapes context.
    """
    cols = table_columns(con, "messages")
    if not {"tool_name", "content"} <= cols:
        return {}
    counts: Counter[str] = Counter()
    bytes_by: Counter[str] = Counter()
    try:
        for row in con.execute(
            "select tool_name, content from messages where tool_name is not null"
        ):
            name = row[0] or "?"
            counts[name] += 1
            bytes_by[name] += len(row[1] or "")
    except sqlite3.Error:
        return {}
    return {n: {"calls": counts[n], "bytes": bytes_by[n]} for n in counts}


def report_tools(home: str, ps: dict | None, con: sqlite3.Connection | None,
                 as_json: bool) -> dict:
    tax_rows = []
    if ps:
        for row in ps.get("toolsets_breakdown", []) or []:
            tax_rows.append({
                "toolset": row.get("toolset", "?"),
                "tool_count": int(row.get("tool_count") or 0),
                "json_bytes": int(row.get("json_bytes") or 0),
            })
    tax_rows.sort(key=lambda r: -r["json_bytes"])
    total_tool_bytes = (ps or {}).get("tools", {}).get("json_bytes")

    calls = tool_call_counts(con) if con is not None else {}
    called_names = set(calls)

    # Tools that carry schema tax but were never invoked. Map toolset -> tool names
    # is not exposed by prompt-size (only counts), so we report calls by name and
    # let the user match them against the toolsets they enabled.
    never = []
    for name, c in calls.items():
        if c["calls"] == 0:
            never.append(name)

    summary = {
        "tools_total": (ps or {}).get("tools", {}).get("count"),
        "tools_json_bytes": total_tool_bytes,
        "toolsets": tax_rows,
        "called_tools": sorted(called_names),
        "top_tools_by_calls": sorted(
            ({"tool": n, **c} for n, c in calls.items()),
            key=lambda r: -r["calls"],
        )[:15],
    }

    if as_json:
        return summary

    print("\n== TOOLS: schema tax (always-on) per toolset ==")
    if tax_rows:
        print(f"   {'toolset':<16} {'tools':>5} {'schema B':>9}")
        for r in tax_rows:
            print(f"   {r['toolset']:<16} {r['tool_count']:>5} {r['json_bytes']:>9}")
        if total_tool_bytes is not None:
            print(f"   {'TOTAL':<16} {(ps or {}).get('tools', {}).get('count', '?'):>5} "
                  f"{total_tool_bytes:>9}")
        print("\n   -> disable toolsets you never use (biggest ones first). MCP tool")
        print("      schemas are NOT injected — only a directory listing + 3 bridge")
        print("      tools are — so MCP's per-turn tax is ~constant regardless of count.")
    else:
        print("   (prompt-size unavailable)")

    if calls:
        print("\n== TOOLS: historical usage (from state.db messages) ==")
        print(f"   distinct tool names seen in history: {len(calls)}")
        print(f"   {'tool':<28} {'calls':>8} {'bytes':>12}")
        for r in sorted(calls.items(), key=lambda kv: -kv[1]["calls"])[:15]:
            print(f"   {r[0][:28]:<28} {r[1]['calls']:>8} {r[1]['bytes']:>12}")
    else:
        print("\n   (no tool history in state.db, or table unavailable)")
    return summary


# --------------------------------------------------------------------------- #
# tokens: fixed tax vs historical traffic
# --------------------------------------------------------------------------- #


def summarize_tokens(con: sqlite3.Connection | None) -> dict:
    out: dict = {}
    if con is None:
        return out
    cols = table_columns(con, "sessions")
    want = {"input_tokens", "output_tokens", "cache_read_tokens",
            "cache_write_tokens", "reasoning_tokens"}
    if want <= cols:
        try:
            row = con.execute(
                "select count(*), sum(input_tokens), sum(output_tokens), "
                "sum(cache_read_tokens), sum(cache_write_tokens), sum(reasoning_tokens) "
                "from sessions where input_tokens is not null"
            ).fetchone()
            out["sessions_counted"] = row[0]
            out["input_tokens"] = row[1] or 0
            out["output_tokens"] = row[2] or 0
            out["cache_read_tokens"] = row[3] or 0
            out["cache_write_tokens"] = row[4] or 0
            out["reasoning_tokens"] = row[5] or 0
        except sqlite3.Error:
            pass

    # Per-model rollup if the table exists.
    cols = table_columns(con, "session_model_usage")
    if cols:
        try:
            rows = con.execute(
                "select model, sum(input_tokens), sum(output_tokens), "
                "sum(cache_read_tokens), sum(estimated_cost_usd) "
                "from session_model_usage group by model "
                "order by sum(input_tokens) desc"
            ).fetchall()
            out["by_model"] = [
                {"model": r[0] or "?", "input_tokens": r[1] or 0,
                 "output_tokens": r[2] or 0, "cache_read_tokens": r[3] or 0,
                 "estimated_cost_usd": r[4] or 0}
                for r in rows
            ]
        except sqlite3.Error:
            pass
    return out


def report_tokens(ps: dict | None, con: sqlite3.Connection | None, as_json: bool) -> dict:
    fixed = {}
    if ps:
        fixed = {
            "system_prompt_chars": ps.get("system_prompt", {}).get("chars"),
            "system_prompt_bytes": ps.get("system_prompt", {}).get("bytes"),
            "skills_index_bytes": ps.get("skills_index", {}).get("bytes"),
            "memory_bytes": ps.get("memory", {}).get("bytes"),
            "user_profile_bytes": ps.get("user_profile", {}).get("bytes"),
            "tools_json_bytes": ps.get("tools", {}).get("json_bytes"),
            "sections": ps.get("sections"),
        }
    traffic = summarize_tokens(con)

    summary = {"fixed_tax_per_turn": fixed, "historical_traffic": traffic}

    if as_json:
        return summary

    print("\n== TOKENS layer 1: fixed per-turn tax (prompt-size) ==")
    if fixed:
        for k in ("system_prompt_bytes", "skills_index_bytes", "memory_bytes",
                  "user_profile_bytes", "tools_json_bytes"):
            v = fixed.get(k)
            if v is not None:
                print(f"   {k:<22} {v:>8} bytes  (~{round(v/4)} tok)")
        if fixed.get("sections"):
            print("   sections (chars, bytes):")
            for s in fixed["sections"]:
                print(f"     {str(s[0]):<44} {s[1]:>7} {s[2]:>8}")
    else:
        print("   (prompt-size unavailable)")

    print("\n== TOKENS layer 2: historical traffic (state.db) ==")
    if traffic.get("sessions_counted"):
        i = traffic["input_tokens"]; o = traffic["output_tokens"]
        cr = traffic["cache_read_tokens"]
        tot = i + o
        print(f"   sessions counted : {traffic['sessions_counted']}")
        print(f"   input tokens     : {i:,}")
        print(f"   output tokens    : {o:,}  ({round(100*o/tot,1) if tot else 0}% of in+out)")
        print(f"   cache_read       : {cr:,}")
        if traffic.get("reasoning_tokens"):
            print(f"   reasoning        : {traffic['reasoning_tokens']:,}")
        if cr:
            print(f"   cache_read / input ratio: {round(cr/i,2) if i else '?'}x")
            print("   -> if you rewrite history, re-price the savings at full price;")
        print("      cached reads are ~10% cost, so busting cache can cost MORE.")
        print(f"   -> output is only {round(100*o/tot,1) if tot else 0}% of traffic; any")
        print("      'make the agent talk less' scheme is capped at that fraction.")
    else:
        print("   (no token totals in state.db)")

    if traffic.get("by_model"):
        print("\n   per-model (input / output / cache_read / est. cost USD):")
        for r in traffic["by_model"]:
            print(f"     {r['model'][:30]:<30} {r['input_tokens']:>12,} "
                  f"{r['output_tokens']:>11,} {r['cache_read_tokens']:>13,} "
                  f"{r['estimated_cost_usd']:>9.4f}")
    return summary


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Offline self-audit for a Hermes install (skills / tools / tokens).")
    ap.add_argument("--home", help="Hermes home (default: %%LOCALAPPDATA%%\\hermes or ~/.hermes)")
    ap.add_argument("--hermes", default="hermes", help="path to the hermes CLI")
    ap.add_argument("--section", choices=["skills", "tools", "tokens", "all"],
                    default="all")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--no-prompt-size", action="store_true",
                    help="skip calling 'hermes prompt-size' (usage/db only)")
    args = ap.parse_args()

    home = resolve_home(args.home)
    ps = None if args.no_prompt_size else run_prompt_size(args.hermes)
    usage = load_usage(home)
    con = db_connect(home)

    if not args.json:
        print(f"[selfaudit] hermes home: {home}")
        print(f"[selfaudit] hermes CLI : {shutil.which(args.hermes) or args.hermes}")
        print(f"[selfaudit] state.db   : {'ok' if con else 'missing/closed'}")

    result: dict = {"home": home}
    if args.section in ("skills", "all"):
        result["skills"] = report_skills(home, ps, usage, args.json)
    if args.section in ("tools", "all"):
        result["tools"] = report_tools(home, ps, con, args.json)
    if args.section in ("tokens", "all"):
        result["tokens"] = report_tokens(ps, con, args.json)

    if con is not None:
        con.close()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
