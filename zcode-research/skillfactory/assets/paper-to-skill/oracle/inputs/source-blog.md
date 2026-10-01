<!--
来源: https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
      （Anthropic 工程博客 "Equipping agents for the real world with Agent Skills"，作者 Barry Zhang / Keith Lazuka / Mahesh Murag）
获取方式: WebFetch 抓取于 2026-09-29；另用 Python urllib 直连同 URL 验证页面存在
（HTTP 200，173679 字节，含特征串 "onboarding"、"progressive disclosure"）。
说明: 以下为 WebFetch 对原文的结构化提取稿（保留原文章节结构与要点），非逐字全文。
-->

# Equipping agents for the real world with Agent Skills (summary)

*Published Oct 16, 2025 — Anthropic Engineering blog. Updated Dec 18, 2025: Agent Skills is now an open standard for cross-platform portability.*

## What Skills are

Skills are "organized folders of instructions, scripts, and resources that agents can discover and load dynamically to perform better at specific tasks." Anthropic compares building one to writing an onboarding guide for a new hire — rather than building bespoke agents per use case, anyone can capture procedural knowledge and share it as composable capabilities.

## Structure of a skill

- A skill is a directory containing a **SKILL.md** file.
- SKILL.md must begin with **YAML frontmatter** holding required metadata: `name` and `description`. At startup, only this metadata for each installed skill is pre-loaded into the system prompt.
- **Progressive disclosure** (the core design principle) works in levels:
  1. Metadata (name/description) in the system prompt — just enough to know when to use a skill.
  2. The full SKILL.md body, loaded only if Claude deems it relevant.
  3. Additional bundled files (e.g., `reference.md`, `forms.md`), read only as needed.

Because agents with filesystem and code-execution tools never need to load an entire skill, the bundled context is effectively unbounded.

### How it plays out in the context window

1. Context starts with the system prompt, skill metadata, and the user's message.
2. Claude triggers the PDF skill by running a Bash command to read `pdf/SKILL.md`.
3. Claude reads bundled `forms.md` when relevant.
4. Claude proceeds with the task, now carrying only the needed instructions.

## Skills and code execution

Skills can bundle executable code. The example PDF skill ships with a Python script that "reads a PDF and extracts all form fields" — Claude can run it without loading the script or PDF into context. Code is also preferred for operations where determinism matters (e.g., sorting is cheaper as an algorithm than via token generation).

## Best practices for authoring and evaluating

- **Start with evaluation:** run agents on representative tasks, find where they struggle, and build skills incrementally to fill those gaps.
- **Structure for scale:** split large SKILL.md files into referenced files; keep rarely co-used contexts separate to cut token usage; make it clear whether scripts should be executed or read as reference.
- **Think from Claude's perspective:** monitor real usage and iterate; the name and description matter most since Claude uses them to decide when to trigger a skill.
- **Iterate with Claude:** ask Claude to codify successful approaches and mistakes into reusable skill content, and to self-reflect when it goes off track.

## Security considerations

Skills carry instructions and code, so malicious skills could introduce vulnerabilities or direct data exfiltration. Recommendations: install only from trusted sources, audit skills from less-trusted sources (files, code dependencies, bundled images/scripts), and watch for instructions to connect to untrusted external network sources.

## Availability and roadmap

Skills are supported across Claude.ai, Claude Code, the Claude Agent SDK, and the Claude Developer Platform. Future plans include lifecycle tooling (creating, editing, discovering, sharing), complementing MCP servers with complex workflow knowledge, and enabling agents to create, edit, and evaluate their own Skills.

*Written by Barry Zhang, Keith Lazuka, and Mahesh Murag.*
