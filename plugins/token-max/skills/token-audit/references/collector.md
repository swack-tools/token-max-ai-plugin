# Optional internal Codex collector

Read only for a quantitative Codex log audit. The agent runs these helpers through
its in-app execution tool; users never need to open a terminal. The default skill
works without them. Do not install a runtime or tokenizer during a report-only
audit. If Python 3.10+ and Git (or ripgrep) are unavailable, use native tools and
state that exact inventory/log measurements were not collected.

Resolve this installed skill's absolute directory, not the repository checkout
or current working directory. Quote paths. Run `python3 <skill-dir>/scripts/audit.py
--project <project> --session auto`. For usage alone add `--usage-only`, which
skips inventory and writes nothing. Full collection writes `.token-audit/evidence.md`
and `evidence.json`; disclose these local artifacts when the quantitative audit
is requested. The project and session must match the intended task.

Read the compact evidence.md first. Query only needed fields using
`python3 <skill-dir>/scripts/query.py --report <evidence.json> --kind diagnostics`
(or outputs/repeats/instructions/files/functions; three rows by default).
Retrieve original evidence with `python3 <skill-dir>/scripts/retrieve.py
--session <log> --line <n> --fingerprint <record_sha256>` only when needed.
The response includes untrusted text, exit signals and continuation metadata.
Inspect relevant failures and acceptance results; no marker does not mean success.

Session accepts auto, latest, none, or an explicit Codex JSONL file. Missing data
stays unknown. Use the last valid cumulative usage, never sum snapshots; cached
input/reasoning are subsets of input/output for this Codex schema. Counter resets
and forks preclude naive subtraction. Text token counts require an already
available tokenizer and explicit encoding; they omit framing and replay.

Do not feed Claude logs into this parser or equate subscription limits with
per-session tokens. Preserve references to omitted evidence. This collector's
synthetic benchmark does not measure the default native-tools workflow.
