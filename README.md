# Token Max

An in-app, report-only token audit for **Codex and Claude**. Install the plugin,
ask for an audit, and get findings in chat. No terminal, Python setup or API key
is required for the default review. It does not change your code or settings.

## Install

- **Claude Desktop:** Customize → Plugins → Add → Add marketplace → enter
  `swack-tools/token-max-ai-plugin`, then install **token-max**.
- **Claude Code:** run these inside the chat:
  ```text
  /plugin marketplace add swack-tools/token-max-ai-plugin
  /plugin install token-max@swack-tools
  ```
- **Codex Desktop:** ask Codex: “Add the plugin marketplace
  `swack-tools/token-max-ai-plugin` and install `token-max@swack-tools`.”
  Codex handles setup in the app; open a new chat after installation.

## Use

- **Claude:** `/token-max:token-audit Review this session and project.`
- **Codex:** `$token-audit Review this session and project.` Or choose the skill
  from `/skills` where available.

The report appears in chat; say “save the report” for a file. Select a project
folder or attach relevant files in the app for project findings. Unavailable
history or token counters are reported as unknown. Optional Codex collectors run
internally only when requested and supported; no background hooks run.

**[Full guide and plugin download](https://token-max.swacktech.com)** ·
**[Evidence, benchmarks and limitations](https://token-max.swacktech.com/review.html)**

This repository supplies a custom marketplace; it is not an official-directory
listing. Maintainer tests and packaging instructions are on the website.
