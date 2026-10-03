---
name: hermes-self-audit
description: Use when 想知道 Hermes 自己的 skill/MCP/插件是否冗余、哪些该优化、token 花在哪、以及别的自省信息。纯本地零依赖：跑 hermes prompt-size、读 skills/.usage.json 与 state.db，拼出「谁在吃灰 / 谁在吃固定税 / 钱花在哪」。
---

# Hermes 自省审计 (self-audit)

离线回答「我自己的 Hermes 装了一大堆东西，哪些是冗余、该砍哪、token 花哪了」。
**不联网、不装包、不依赖任何外部工具**——只用 Python 标准库，加本机的 `hermes` CLI（可选）。

## 什么时候用

- 三姐问「哪些 skill/MCP/插件是冗余的 / 该优化什么 / token 消耗分布 / 还有什么自省信息」
- 技能库或工具集膨胀后，想决定砍谁
- 想搞清 token 到底花在「固定税」还是「历史流量」上

## 核心认知（先记住，别答错）

1. **没有一条命令直接吐「冗余报告」**——必须从三处数据拼：`hermes prompt-size`（固定税）、`skills/.usage.json`（用过没用过）、`state.db`（历史流量）。
2. **冗余 ≠ 条数**。判据是「装了但没被调用」，不是「装得多」。
3. **MCP 的每轮 token 税几乎恒定**：装了任意 MCP/插件就激活 Tool Search，MCP 工具 schema **不注入**系统提示，只注入 3 个桥工具 + 一份目录清单。所以装 1 个和装 20 个的固定开销差不多——**MCP 冗余与否不看条数**。
4. **token 必须分两层看**：固定税（每轮必付）vs 历史流量（决定该压哪层）。只看总量没用。
5. 日志（`agent.log`）会轮转、只覆盖约两周，**用它下「从没用过」的结论会严重低估**；真值在 `state.db` 的 `messages.tool_name`。

## 一条命令拿到全部分析

把 `scripts/hermes_selfaudit.py` 跑起来即可（纯标准库，只读）：

```bash
python scripts/hermes_selfaudit.py
# 只要某一节 / 要机器可读：
python scripts/hermes_selfaudit.py --section skills
python scripts/hermes_selfaudit.py --json
# Hermes home 不在默认位置时：
python scripts/hermes_selfaudit.py --home /path/to/hermes
```

脚本自动定位 Hermes home（Windows: `%LOCALAPPDATA%\hermes`；Linux/macOS: `~/.hermes`），
读取 `skills/.usage.json`、`state.db`（只读打开），并调用 `hermes prompt-size --json`。
输出三节：**SKILLS**（索引税 vs 实际使用）、**TOOLS**（每 toolset 的 schema 税 + 历史调用）、
**TOKENS**（固定税 + 历史流量）。

## 手工等价的命令（不想跑脚本时）

| 想知道 | 命令 / 入口 |
|---|---|
| 每轮固定税（系统提示/技能索引/记忆/工具 schema） | `hermes prompt-size --json` |
| 每个技能的调用/查看次数与状态 | `hermes curator usage`（读 `skills/.usage.json`） |
| 技能清单与启用状态（唯一真值源） | `hermes skills list` |
| 装过但没用的技能 → 归档 / 删除 | `hermes curator archive <name>` / `hermes skills uninstall <name> --yes` |
| MCP 连接与工具数 | `hermes mcp list` / `hermes mcp test <name>` |
| 插件启用、能力、运行时契约 | `hermes plugins list` / `capabilities` / `doctor` |
| 已启用工具与 toolset | `hermes tools list` |
| 聚合的 token/成本/活动视图 | `hermes insights`、`hermes dashboard` 的 Analytics 页 |
| 会话/消息/工具调用总数 | `hermes sessions stats` |
| 账户额度窗口（限流） | `hermes usage --json` |
| 技能与记忆的习得时间线 | `hermes journey`（别名 `learning` / `memory-graph`） |
| 每个技能的调用排名 | `hermes curator usage` |
| 完整环境快照（排障） | `hermes dump` |
| 依赖健康 | `hermes doctor`、`hermes pm status` |

## 冗余判断：技能 / MCP / 插件

**技能** —— 两处数据 join：
1. `hermes curator usage`（或 `.usage.json`）→ 每个技能的 `use_count` / `view_count` /
   `patch_count` / `last_used_at` / `state` / `pinned` / `archived_at`
2. `hermes prompt-size --json` 的 `skills_breakdown` → 每个技能的 `index_line_bytes`
   （索引行是**常驻成本**，正文是懒加载，只有被 `skill_view` 时才进上下文）
3. 筛 `use_count=0 且 view_count=0 且 在索引里` = 吃灰常驻税；再交叉核对它有没有被别的
   在用技能、MEMORY/USER/AGENTS.md 引用（避免归档出坏引用）
4. 处置：`hermes curator archive <name>`（只去索引行、可逆）或
   `hermes skills uninstall <name> --yes`（真删）。curator 只管 agent 创建的技能。

**MCP** —— 先分清两笔账：
- token 账几乎恒定（见上「核心认知 3」），**别按条数砍**。
- 真冗余 = 装了但没调用：`hermes mcp list` 看连接与工具数；再用 `state.db` 查这些工具名
  有没有出现在 `messages.tool_name` 里（脚本的 TOOLS 节已列）。
- `lazy: true` **只省进程/连接，不省 token**，别拿它当优化手段。

**插件** —— `hermes plugins list`（启用状态）、`capabilities`（声明 vs 实际授予）、
`doctor`（真实运行时契约）。三者对不上就是该查的点。

**工具 / toolset**（常驻税大头）—— `hermes tools list` 看启用了哪些；
`hermes prompt-size` 的 `toolsets_breakdown` 按 toolset 排 schema 体积。
关掉没用的 toolset 是省固定税最狠的一刀。

## Token 消耗：两层拆解

**第 1 层 · 固定税**：`hermes prompt-size --json` 提供
`system_prompt` / `skills_index` / `memory` / `user_profile` / `tools.json_bytes` /
`sections[]`。这是「不管聊什么都要交的税」，优化点都在这。

**第 2 层 · 历史流量**：读 `state.db`——
```sql
-- 输入:输出 比例 = 输出侧压缩方案的天花板
select count(*), sum(input_tokens), sum(output_tokens),
       sum(cache_read_tokens), sum(reasoning_tokens)
  from sessions where input_tokens is not null;

-- 按工具看谁最占上下文
select tool_name, count(*), sum(length(content))
  from messages where role='tool' or tool_name is not null
  group by tool_name order by 3 desc limit 12;

-- 按模型拆
select model, sum(input_tokens), sum(output_tokens), sum(cache_read_tokens),
       sum(estimated_cost_usd)
  from session_model_usage group by model order by 2 desc;
```
读法：输入:输出 通常约 4~5:1 → 输出只占 ~18~23%，任何「让 agent 少说话」的方案上限就在这；
工具结果常占上下文 90%+ → 压工具输出的杠杆远大于压回话；`cache_read` 常是裸输入几十倍 →
**任何改写历史/碎缓存的压缩方案，都要先把省下的按全价重算**（缓存读约 10% 价，碎了反而更贵）。

## 坑

- 直链 URL 安装 skill 时，**只拉取 SKILL.md 正文里显式链接的** `references/`、`scripts/`、
  `templates/`、`assets/` 文件。所以配套脚本必须在 SKILL.md 里用相对路径写出来，否则装完缺文件。
- `state.db` 的 `messages` 里，工具调用结果的行用 `tool_name` 标注（不是 `role='tool'`）；
  用 `role='tool'` 过滤会漏。
- `hermes prompt-size` 的 `skills_breakdown` 只含**当前在索引里**的技能；
  `skills/.usage.json` 含历史与已归档的。两边取并集才是完整视图。
- 工具/toolset 的名字和提示里的不一致（如 `process` vs `process_manage`），
  以 `state.db` 里真实出现的为准。

## 参考文件

- [`scripts/hermes_selfaudit.py`](scripts/hermes_selfaudit.py) — 上述三节的完整实现，纯标准库、只读、可直接跑。
