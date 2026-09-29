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
- **ChatGPT desktop app / Codex Desktop:** add the marketplace in the app:
  1. Open **Settings → Plugins → Marketplace**.
  2. Select **Add → Add plugin marketplace**.
  3. For **Source**, enter `https://github.com/swack-tools/token-max-ai-plugin`.
     The UI also accepts a Git URL or a local folder.
  4. Leave **Sparse paths** empty. This repository keeps its Codex marketplace
     manifest at `.agents/plugins/marketplace.json` in the repo root, so the
     marketplace directory is the root.
  5. Leave **Git ref** empty to use the default branch, or enter `main`.
  6. Add the marketplace, then select **Token Max** from the marketplace and
     install it. Start a new chat and invoke it with
     `$token-audit Review this session and project.`

  Adding a marketplace through these settings is a user-facing desktop UI flow.
  A chat agent's model-facing plugin tools do not necessarily expose marketplace
  registration or installation, so asking the agent to do those setup steps is
  not a substitute for using Settings.

- **Codex CLI (optional):** register the Git-backed marketplace separately:
  ```sh
  codex plugin marketplace add https://github.com/swack-tools/token-max-ai-plugin.git --ref main
  ```
  Codex CLI documents `codex plugin marketplace add` for Git-backed sources.
  The command registers the marketplace; use the desktop Plugins UI to install
  and test the plugin when working in the ChatGPT desktop app.

## Use

- **Claude:** `/token-max:token-audit Review this session and project.`
- **Codex:** `$token-audit Review this session and project.` Or choose the skill
  from `/skills` where available.

The report includes a copyable fix prompt per actionable finding. Ask “give me one
combined fix prompt” to cover them all. Prompts are guidance; the audit never runs
them. [Examples](https://token-max.swacktech.com/#fix-prompts).

The report appears in chat; say “save the report” for a file. Select a project
folder or attach relevant files in the app for project findings. Unavailable
history or token counters are reported as unknown. Optional Codex collectors run
internally only when requested and supported; no background hooks run.

**[Full guide and plugin download](https://token-max.swacktech.com)** ·
**[Evidence, benchmarks and limitations](https://token-max.swacktech.com/review.html)**

This repository supplies a custom marketplace; it is not an official-directory
listing. Maintainer tests and packaging instructions are on the website.
