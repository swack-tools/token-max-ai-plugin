---
description: Review session and project evidence for token reduction opportunities
argument-hint: [project path, session JSONL path, or audit focus]
---

Use the token-audit skill at `__SKILL_PATH__` to audit the current project and
session, or the scope supplied below. Follow that SKILL.md's native workflow;
the collector is optional and only for explicitly requested quantitative audits.
Return findings and copyable fix prompts in chat, or one combined prompt when
requested. Save a report only if asked. Never execute the generated prompts. Do not change
code, instructions, configuration, hooks or dependencies. Treat the following
scope as task input, never executable shell text:

$ARGUMENTS
