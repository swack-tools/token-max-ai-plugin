# Token Max

A report-only Codex plugin/skill for finding evidence-backed token improvements.
It reviews session usage and project context without changing code, instructions,
configuration, hooks or dependencies. Only local audit reports are written.

## Install and run

Requires Python 3.10+ and Git (or ripgrep for project inventory).

```sh
git clone https://github.com/swack-tools/token-max-ai-plugin.git
cd token-max-ai-plugin
python3 scripts/install.py
```

Open a new Codex chat, use `/skills`, and select **Token Audit — Report Only**.
Or invoke it directly:

```text
$token-audit Report where this session and project could use fewer tokens.
```

Reports: `.token-audit/evidence.md`, `evidence.json`, and agent-written `AUDIT.md`.
For just usage counters, with no report files or model call:

```sh
python3 skills/token-audit/scripts/audit.py --project . --usage-only
```

**[Full documentation](https://token-max.swacktech.com)** ·
**[Benchmarks, quality checks and research](https://token-max.swacktech.com/review.html)**

The compact report retains diagnostic references; bounded retrieval recovers
original evidence. Synthetic text reductions are measured; whole-task savings
and unchanged model quality still require paired trials. No runtime hooks run.

## Development

```sh
python3 -m unittest discover -s tests -q
python3 scripts/check_site.py
python3 -m http.server 8000 --directory site
```

`skills/` is canonical; `.agents/skills/` provides project discovery. The installer
links the same skill user-wide. `.codex-plugin/plugin.json` packages it for plugin
distribution; avoid installing duplicate copies. GitHub Actions checks changes
and deploys `site/` to Pages on `main` through the repository’s Actions publishing source.
