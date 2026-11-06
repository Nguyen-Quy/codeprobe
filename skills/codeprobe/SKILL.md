---
name: codeprobe
description: Autonomous codebase investigator, pre-flight scanner, and decision router. MUST ALWAYS be invoked before broad text grep, file listing, or multi-file reading loops when exploring unfamiliar code, finding symbols, understanding architectures, checking phases/progress, or making code modifications.
---

# CodeProbe: Autonomous Investigator, Behavioral Search & Decision Router

CodeProbe is an intelligent codebase navigation and decision-routing engine designed specifically for AI coding agents. It replaces expensive, blind grep loops, recursive file crawls, and speculative code edits with targeted, 1-shot evidence synthesis and policy guardrails.

---

## 🚨 MANDATORY AGENT DIRECTIVES (CRITICAL)

1. **FIRST ACTION RULE**: You MUST invoke `codeprobe_investigate` (MCP) or `codeprobe investigate` (CLI) as your **FIRST** action whenever you need to:
   - Understand how a feature, subsystem, or architecture works.
   - Find symbols, declarations, classes, interfaces, or functions.
   - Locate where specific behavior or business logic lives.
   - Investigate error traces, exceptions, or failure points.
   - Check phase progress, roadmap items, or milestone status in `.planning/`.
   - Decide what files to edit before starting modifications.

2. **PROHIBITED ANTIPATTERNS**:
   - ❌ **DO NOT** perform broad text grep (`grep -r`, `rg`, `grep_search`) across the entire repository before consulting CodeProbe.
   - ❌ **DO NOT** execute multi-file reading loops (`view_file` or `cat` on 5+ files) to hunt down behavior.
   - ❌ **DO NOT** guess file paths or assume project conventions without checking `codeprobe files` or `codeprobe investigate`.
   - ❌ **DO NOT** edit code before verifying guardrails and policy constraints via `codeprobe route` / `codeprobe_decide`.

3. **MANDATORY CONSUMPTION**: You MUST directly consume and act upon the `summary`, `evidence_snippets`, `key_declarations`, and `actionable_guidance` returned in the payload. Do NOT discard this evidence or re-explore the codebase from scratch.

---

## Core Capabilities

### 1. Pre-Flight Workspace Inventory (`codeprobe files`)
*Zero-token, instantaneous workspace profiling.*
- Instantly analyzes total files, total code volume (KB/MB), directory distributions, and language breakdown without invoking LLM tokens.
- Prunes noisy directories and respects navigation budgets (default 250 KB ceiling).

**CLI**:
```sh
codeprobe files .
codeprobe files ./src --json
codeprobe files --exclude "*.min.js" --exclude "dist/*" .
```
**MCP**:
```json
{"name": "codeprobe_files", "arguments": {"workspace_path": "<workspace_path>", "root_dir": "."}}
```

### 2. Autonomous Multi-Hop Reconnaissance & Context Sufficiency Engine
*Autonomous multi-hop ReAct loop (up to 6 hops) backed by a 4-pillar Context Sufficiency score.*
- **4 Context Pillars**: Target File (0.30) + Verbatim Code Anchor (0.30) + Callers/Dependents (0.20) + Configs & Env Bindings (0.20). Early-exits when sufficiency reaches >= 80%.
- **Dual Anchor Detection for New Features / Scaffolding**: Automatically detects the **Mounting Point** (router/urls/__init__) and the **Exemplar Donor Template** (similar file in domain conventions).
- **Tier 1: File Leads**: Ranked, relevant source and planning documents.
- **Tier 2: Verbatim Declaration Units**: Extracts exact AST blocks (classes, methods, functions, structs, traits) with start-end lines, docstrings, and outbound function calls across Python, TypeScript/JavaScript, Go, and Rust.
- **Tier 3: Cross-File Call Relationships & False-Positive Pruning**: Resolves caller-callee links across files and automatically retracts irrelevant files.

**CLI**:
```sh
codeprobe investigate "Where is user authentication and session token verification handled?"
codeprobe investigate "How are database connections pooled and retry logic implemented?"
codeprobe investigate "Kiểm tra tiến độ phase hiện tại trong .planning và roadmap"
```
**MCP**:
```json
{"name": "codeprobe_investigate", "arguments": {"query": "<query>", "workspace_path": "<workspace_path>"}}
```

### 3. Pre-Flight Decision Routing & Policy Guardrails
*Evaluates task category, confidence thresholds, blast radius, and security policies.*
- Detects task type (`INVESTIGATION`, `DEBUGGING`, `CODE_EDIT`, `REFACTORING`, `TESTING`).
- Enforces guardrails: forbidden secret files (`.env*`, `*.pem`), read-only lockfiles (`package-lock.json`, `poetry.lock`), and mandatory test execution before code modification.
- Returns explicit `prohibited_actions` that the agent MUST respect.

**CLI**:
```sh
codeprobe route "Refactor authentication middleware to use JWT bearer tokens"
codeprobe route "Fix race condition in background queue worker"
```
**MCP**:
```json
{"name": "codeprobe_decide", "arguments": {"user_goal": "<user_goal>", "workspace_path": "<workspace_path>"}}
```

### 4. Continuous Online Learning & Calibration
*Help CodeProbe self-tune its retrieval weights based on actual agent utility.*
- Provide rating (1-5) and indicate helpful / noisy files.

**CLI**:
```sh
codeprobe feedback "<investigation_id>" --score 5 --helpful "src/auth/jwt.py" --unhelpful "src/auth/legacy.py"
```
**MCP**:
```json
{"name": "codeprobe_feedback", "arguments": {"investigation_id": "<id>", "score": 5, "helpful_files": ["src/auth/jwt.py"]}}
```

### 5. Ready-to-Code Output Payload (Flexible Advisory)
*Concrete multi-target file anchors and unified diff previews ready for immediate modification.*
When `ready_to_code` is returned in the investigation payload:
- **Exact Line Ranges & Verbatim Anchors**: Contains `targets: List[CodeTarget]` where each target specifies `file_path`, `start_line`, `end_line`, `target_content`, `replacement_content`, and `diff_preview`.
- **Dual Format**:
  - `target_content` & `replacement_content`: Accurately indented strings ready to be passed directly into editing tools (`replace_file_content` / `multi_replace_file_content`).
  - `diff_preview`: Fenced markdown diff block for visual inspection.
- **Flexible Advisory Guideline**:
  - Agents are strongly recommended to leverage the exact line ranges and `target_content` to make immediate edits without running extra search or grep loops.
  - Agents retain the flexibility to verify file context with `view_file` (reading only the specified lines, e.g. `start_line` to `end_line`) if they determine additional context is warranted.

---

## Agent Decision Matrix & Workflow

| Agent Intent / Situation | First Tool To Invoke | Fallback / Next Step |
| :--- | :--- | :--- |
| **Entering new/unfamiliar workspace** | `codeprobe files .` | Understand project structure & volume |
| **"Where is X?", "Find symbol Y", "How does Z work?"** | `codeprobe_investigate(query="...")` | Read specific lines from cited Declaration Units |
| **"Check status / progress of phase / milestone"** | `codeprobe_investigate(query="phase status in .planning")` | Review synthesized phase findings & git logs |
| **Investigation returns `ready_to_code` targets** | Use `target_content` / `replacement_content` directly with `replace_file_content` | Apply changes and run tests |
| **About to refactor or edit sensitive code** | `codeprobe_decide(user_goal="...")` | Adhere strictly to `prohibited_actions` |
| **Need to locate test suite or coverage** | `codeprobe_investigate(query="tests for <module>")` | Run tests before making edits |
| **Finished task / verified fix** | `codeprobe_feedback(investigation_id="...", score=5)` | Close feedback loop |
