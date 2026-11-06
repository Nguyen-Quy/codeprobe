# codeprobe

> **Universal Decision Router, Autonomous Reconnaissance, and Policy Engine for AI Coding Agents** (Antigravity, Claude Code, Codex, Cursor, Aider).

`codeprobe` sits between your coding agent and raw tool execution. Before an LLM performs expensive or risky actions (broad search, deep file reads, complex refactoring, executing arbitrary code), it queries `codeprobe` to receive:
- **Pre-Flight Query Analyzer (Step 0)**: Evaluates query ambiguity with local Qwen 3B, providing interactive clarification prompts on CLI or structured `NEEDS_CLARIFICATION` contracts over MCP before wasting token budgets.
- **Optimal Action Strategy**: Recommended actions with priority and rationale.
- **Guardrails & Prohibited Actions**: Strict constraints (e.g. *do not edit without reproducing error*, *do not modify read-only lockfiles*, *do not guess file paths*).
- **Pre-Flight Workspace Inventory (`codeprobe files`)**: Zero-token directory and language volume profiling.
- **Autonomous Behavioral Code Recon (`codeprobe investigate`)**: 1-shot multi-hop evidence synthesis (File Leads, Verbatim AST Declaration Units with exact line numbers, and Cross-File Call Relationships).
- **Hop-by-Hop Mid-Flight Analyst**: Local LLM reasoning guides multi-hop traversal jumps based on verified `FACT`s and missing `GAP`s in the `EvidenceManager`.
- **Git Commit-Aware Semantic Cache**: 0ms instant response when querying unchanged repository commits (`git rev-parse HEAD`).
- **1-Click Patch Applicator (`codeprobe apply`)**: Validates AST syntax, generates automatic backups (`.bak`), provides dry-run diff previews, and supports instant rollback.
- **Continuous Learning Loop**: Feedback-driven matrix calibration that trains on agent outcomes.

---

## 📦 Installation & Setup

### 1. Production Installation

Install via `pip` or `uv`:

```bash
# Install via pip
pip install codeprobe

# Or install via uv tool (recommended)
uv tool install codeprobe

# If you are developing codeprobe locally, install in editable mode
uv tool install --editable /path/to/codeprobe --force
```

#### Install Agent Skill (For AI Coding Agents)

Install `SKILL.md` to instruct AI Agents (Antigravity, Claude Code, Cursor) to automatically activate CodeProbe:

```bash
# Install locally in current project workspace (.agents/skills/codeprobe/)
codeprobe skill

# Or install globally across all workspaces (~/.gemini/config/, ~/.claude/, ~/.agents/)
codeprobe skill --global
```

#### Initialize Guardrails & Policy for your project:

```bash
codeprobe init
```
This generates `.codeprobe/rules.toml` with protections for secret files (`.env*`, `*.pem`), read-only lockfiles (`package-lock.json`, `uv.lock`), and blast radius boundaries.

---

### 2. Development Setup

If you clone the repository to contribute or develop features:

```bash
# Clone repository
git clone https://github.com/dzhng/codeprobe.git
cd codeprobe

# Install virtual environment and dependencies with uv
uv sync

# Or install in editable mode
uv pip install -e .
```

#### Install Agent Skill in Dev Environment:

```bash
# Install skill in current workspace
uv run codeprobe skill

# Install skill globally
uv run codeprobe skill --global
```

#### Run Test Suite:

```bash
# Run full test suite (135+ tests)
uv run pytest

# Run decision matrix benchmark
uv run codeprobe test-matrix
```

---

## 🤖 How it Works with AI Coding Agents

When `codeprobe skill` is installed or the MCP Server is registered:
1. **FIRST ACTION RULE**: Instead of hallucinating file paths or running `grep -rn` across the entire disk burning hundreds of thousands of tokens, the agent calls `codeprobe_investigate` (MCP) or `codeprobe investigate` (CLI).
2. **Step 0 Query Clarification**: If a query is too vague (e.g. *"fix this"*, *"check code"*), CodeProbe pauses early and asks targeted clarification questions before consuming traversal budgets.
3. **Pre-flight Inventory**: The agent runs `codeprobe files` to survey project structure and code volume at **zero LLM token cost**.
4. **Guardrail Enforcement**: The agent calls `codeprobe_decide` before refactoring or editing to check forbidden actions (`prohibited_actions`).
5. **1-Click Patch Application**: For code modifications, the agent uses `ReadyToCodePayload` or runs `codeprobe apply` to execute verified changes safely.
6. **Continuous Feedback Loop**: After each task, the agent calls `codeprobe_feedback` to score findings and submit helpful/unhelpful files, calibrating CodeProbe's retrieval matrix.

---

## 🚀 Quick Usage

### Python SDK

```python
from codeprobe import (
    DecisionRequest,
    LayaDecisionRouter,
    TaskCategory,
)

router = LayaDecisionRouter()

request = DecisionRequest(
    user_goal="Diagnose and fix authentication timeout error",
    task_category=TaskCategory.DEBUGGING,
    last_error="TimeoutError: database connection acquired after 30.0s",
    known_files=["src/auth/session.py"],
)

decision = router.route(request)

print(f"Strategy: {decision.strategy}")
print(f"Suggested Model Tier: {decision.suggested_model_tier}")
print(f"Prohibited: {decision.prohibited_actions}")

for action in decision.recommended_actions:
    print(f"-> Action: {action.action} | Params: {action.params} | Reason: {action.rationale}")
```

### Model Context Protocol (MCP) Server

Connect `codeprobe` directly with Claude Code, Antigravity IDE, Cursor, or Codex:

```bash
# Run MCP server via stdio transport (default)
codeprobe serve

# Run MCP server via SSE transport
codeprobe serve --sse --port 8000

# Run REST HTTP server (FastAPI)
codeprobe serve --http --port 8000
```

#### MCP Client Configuration (`mcp_config.json`):

```json
{
  "mcpServers": {
    "codeprobe": {
      "command": "codeprobe",
      "args": ["serve"]
    }
  }
}
```

#### Available MCP Tools:
- `codeprobe_files`: Fast workspace structure and language breakdown (Zero-token inventory).
- `codeprobe_investigate` / `codeprobe_explore`: **Autonomous Hybrid Investigation Engine**. Extracts keywords, traverses code, parses multi-language AST units with line ranges, links cross-file call graphs, prunes noise, and produces ready-to-code diffs.
- `codeprobe_decide`: Evaluates agent context and returns execution strategies, recommended actions, model tiers, and `prohibited_actions`.
- `codeprobe_feedback`: Submits quality scores and helpful file lists to self-calibrate retrieval weights.
- `codeprobe_recommend_strategy`: Fast triage of execution strategies and model tiers.
- `codeprobe_evaluate_evidence`: Checks whether gathered evidence meets context sufficiency thresholds.
- `codeprobe_explain_decision`: Returns detailed probability calculations and decision matrix rationale.

---

## 💻 CLI Commands

```bash
# 1. Pre-flight workspace inventory
codeprobe files .
codeprobe files ./src --json
codeprobe files --exclude "*.min.js" .

# 2. Autonomous behavioral code investigation
codeprobe investigate "Where is user authentication token verified?"
codeprobe investigate "Compare deploy scripts and main application runner" --mode compare
codeprobe investigate "Fix SQL injection vulnerability in search endpoint" --mode code

# 3. 1-Click patch application and rollback
codeprobe apply --dry-run
codeprobe apply
codeprobe apply --rollback src/auth/session.py

# 4. Local LLM Server daemon management (Qwen 2.5 Coder 3B)
codeprobe llm-server status
codeprobe llm-server start --gpu-layers 16
codeprobe llm-server restart
codeprobe llm-server stop

# 5. Decision routing & guardrails check
codeprobe route "Refactor database query caching"

# 6. Install Agent Skill
codeprobe skill
codeprobe skill --global
codeprobe skill --print

# 7. Initialize & inspect guardrail configuration
codeprobe init
codeprobe config

# 8. Submit feedback for retrieval calibration
codeprobe feedback "inv_123456" --score 5 --helpful "src/auth.py"

# 9. Run decision matrix benchmark
codeprobe test-matrix
```

---

## ⚙️ Project Configuration & Guardrails (`.codeprobe/rules.toml`)

```toml
[guardrails]
# Files forbidden from reading or modifying
forbidden_files = [
    ".env*",
    "*.pem",
    "*.key",
    "credentials.json",
    "secrets/*",
]

# Read-only files (agents cannot edit or delete)
read_only_files = [
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    "uv.lock",
    "*.min.js",
]

[policy]
# Require test execution evidence before allowing code modifications
require_tests_before_edit = true

# Maximum number of files permitted in a single modification set
blast_radius_limit = 5

# Maximum line count when reading file slices
max_file_slice_lines = 150

# Maximum navigation byte budget
navigation_budget_bytes = 256000

[thresholds]
default = 0.70
investigation = 0.70
debugging = 0.75
refactoring = 0.80
testing = 0.70

[model_tiers]
investigation = "fast_infer"
debugging = "reasoning"
refactoring = "reasoning"
testing = "standard"
```

---

## 🧩 Architecture

```
┌────────────────────────────────────────────────────────┐
│      Coding Agents (Antigravity, Claude Code, Cursor)  │
└───────────────────────────┬────────────────────────────┘
                            │ DecisionRequest / Investigation Query
┌───────────────────────────▼────────────────────────────┐
│                    codeprobe Engine                    │
├────────────────────────────────────────────────────────┤
│ 0. Pre-Flight Query Analyzer (Step 0 Ambiguity Gate)   │
│ 1. Git Commit-Aware Semantic Cache (0ms Instant Return)│
│ 2. Pre-flight Inventory & Budgeted Explorer            │
│ 3. Multi-language AST Units (Python, JS/TS, Go, Rust)  │
│ 4. Hop-by-Hop Multi-Hop Recon + Mid-Flight Analyst     │
│ 5. Cross-file Relationship Linker & Noise Pruning      │
│ 6. Laya Probabilistic Decision Router & Guardrails     │
│ 7. Ready-to-Code Synthesizer & 1-Click Patch Patcher   │
│ 8. Online Feedback Calibration Matrix                  │
└───────────────────────────┬────────────────────────────┘
                            │ DecisionResponse / ReadyToCodePayload
┌───────────────────────────▼────────────────────────────┐
│      Agent Executes Safe, Grounded & Targeted Action   │
└────────────────────────────────────────────────────────┘
```
