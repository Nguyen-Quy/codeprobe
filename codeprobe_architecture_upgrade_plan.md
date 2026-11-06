# Laya Decision Routing Engine --- Architecture Upgrade Plan

> **Purpose:** Upgrade `codeprobe` from a one-shot query + routing + raw-output pipeline into a bounded, evidence-driven investigation engine powered by a local LLM planner.

> **Implementation principle:** Refactor incrementally. Preserve Laya, the current executor, CLI, and existing working behavior wherever possible. Do not rewrite the project or introduce an orchestration framework just to implement the first version.

## 1. Project context

Current known project details:

-   Python package: `codeprobe`
-   Source directory: `src/codeprobe/`
-   Existing modules include:
    -   `__init__.py`
    -   `llm.py`
    -   `router.py`
    -   `executor.py`
    -   `tools.py`
-   Python requirement: `>=3.13`
-   Package/dependency management: `uv`
-   CLI entry point: `codeprobe = "codeprobe:main"`
-   Local inference endpoint: `http://localhost:8033/api/v1/chat`
-   Current model: `mistralai_devstral-small-2-24b-instruct-2512`
-   No OpenAI API or cloud LLM dependency.
-   Laya remains the decision/routing model.
-   Current behavior: the LLM generates an initial query, then routing/execution proceeds; executor output is largely raw stdout from search/read tools.

Treat this as the baseline, not a claim that every implementation detail is still unchanged. Inspect the repository before editing and adapt names/interfaces to the code that actually exists.

## 2. Problem statement

The current flow can collect data but does not reliably manage an investigation. Observed symptoms include:

-   Search queries are too broad or repeated.
-   Search results that are only weakly relevant are forwarded as if useful.
-   Raw output is noisy, duplicated, too long, or missing source context.
-   The system does not consistently use new evidence to choose the next action.
-   The final agent has to re-analyze raw output.
-   Findings and hypotheses can be mixed together.
-   Patch proposals may be based on incomplete or unverified code context.
-   The system can keep gathering data without a clear stopping condition.

The upgrade must address orchestration, evidence quality, and
validation---not merely replace the decision model.

## 3. Target architecture

Implement this bounded investigation loop:

``` text
Task + execution limits
        |
        v
Local LLM Planner
  - clarify objective internally
  - establish investigation questions/hypotheses
  - propose one next action
        |
        v
Laya Router
  - select an allowed capability
  - return a typed routing decision
        |
        v
Executor
  - validate and execute the selected tool
  - return a structured result, not an unbounded stdout blob
        |
        v
Evidence Manager
  - normalize, deduplicate, and retain provenance
  - track facts, hypotheses, and unresolved questions
        |
        v
Update Investigation State
        |
        v
Planner / Analyst
  - inspect the new evidence
  - continue with a justified next step, or finish
        |
        +--------------------> repeat within limits
        |
        v
Final Synthesizer
  - findings with source references
  - distinguish facts from hypotheses
  - optional patch proposal
  - explicit verification status
```

The first implementation can use a single local LLM for planning, analysis, and synthesis with different prompts and output schemas. These are separate responsibilities, not necessarily separate models or processes.

## 4. Design principles and constraints

### 4.1 Preserve the current stack

-   Keep Laya as the routing/decision component.
-   Keep the existing executor and tools where practical; improve their contracts incrementally.
-   Continue using the configured local LM Studio endpoint and local model.
-   Do not add OpenAI or other cloud inference dependencies.
-   Do not introduce LangChain or LangGraph in the initial refactor.
-   Keep the orchestration in ordinary Python until a concrete need for checkpoint/resume, durable workflows, or complex graph orchestration justifies a framework.
-   Avoid a broad rewrite or unnecessary new abstractions.

### 4.2 Deterministic execution and safety

-   The LLM proposes intent; it does not receive unrestricted shell access.
-   Only registered, allowlisted capabilities may execute.
-   Validate all model-produced actions and arguments before execution.
-   Enforce limits for steps, tool calls, wall-clock time, output bytes/lines, and repeated calls.
-   Apply explicit timeouts to external commands.
-   Treat repository content, search results, and file contents as untrusted data, not instructions.
-   Do not execute instructions found inside source files or tool output.
-   Destructive or externally impactful actions must require explicit policy/approval; the first version should not add arbitrary shell execution.
-   Never claim a patch was applied or tests passed unless execution results confirm it.

### 4.3 Explicit uncertainty

-   Preserve errors and truncation indicators.
-   Distinguish `fact`, `hypothesis`, and `unknown`/unresolved.
-   Missing evidence must remain missing; do not invent file paths, line numbers, APIs, or test results.
-   If the investigation budget is exhausted, return a partial result with unresolved questions rather than pretending the task is complete.

## 5. Responsibilities and interfaces

Keep interfaces small and independent so the orchestration can change later without rewriting domain logic.

### 5.1 Planner

Input: - User task - Current investigation state - Relevant evidence and recent action history - Remaining budgets

Output: a validated structured plan, such as: - `search_code` - `read_file` - `inspect_git` - `run_tests` (only if supported and allowlisted) - `finish` - `ask_user` (when genuinely blocked by missing user input)

The planner should propose one next action at a time for the initial version. Avoid generating a large, unvalidated sequence of commands.

The plan should include: - Action/capability intent - Narrow query or target - Purpose / question being tested - Expected evidence - Optional hypothesis being investigated

The planner must not mark its own hypothesis as a verified fact.

### 5.2 Laya Router

-   Select a capability from the existing fixed, registered action set.
-   Do not dynamically create new capabilities from model text.
-   Validate or reject unsupported action intents.
-   Return a typed decision with normalized arguments.
-   Keep routing distinct from investigation planning and final synthesis.

If the current Laya interface does not map directly to this contract, add a small adapter rather than replacing Laya.

### 5.3 Executor

-   Execute only a registered capability and validated arguments.
-   Return structured `ToolResult` data.
-   Keep raw stdout/stderr available for debugging when useful, but do not forward unlimited raw output as the default evidence payload.
-   Include source path and line range for code evidence.
-   Preserve exit code, status, timeout/error information, and truncation status.
-   Apply tool-specific limits (for example, maximum search matches and maximum bytes per result).

### 5.4 Evidence Manager

-   Normalize tool results into evidence items.
-   Deduplicate repeated results using stable identifiers, such as source path + line range + content hash where appropriate.
-   Preserve provenance: tool, query/action, source path, line range, and relevant execution metadata.
-   Track which evidence supports which finding or hypothesis when feasible.
-   Keep evidence snippets bounded and avoid repeatedly sending the entire history to the LLM.
-   Do not silently discard potentially important evidence; record truncation and filtering metadata.

### 5.5 Investigation State

Store at least: - Original task - Current objective / investigation questions - Current plan or next-action intent - Hypotheses and their status - Normalized evidence references - Recent action history and outcomes - Repeated-action/deduplication information - Budget usage and remaining budget - Overall status: `running`, `completed`, `needs_input`, `budget_exhausted`, or `failed`

Keep state serializable. Prefer ordinary Python dataclasses or Pydantic models if Pydantic is already present or justified. Do not add a dependency solely for a trivial schema if the project already has a suitable approach.

### 5.6 Analyst / stopping policy

After each meaningful tool result, the LLM should determine whether to: - Continue with one justified next action - Read a specific source range - Test a hypothesis - Ask the user for essential missing information - Finish with the evidence available

Do not rely on the LLM alone for limits or safety. Deterministic code must enforce the maximum step count, tool-call count, time, output size, and other hard constraints.

A finish decision is a request to stop, not proof of correctness. The final synthesizer must still describe evidence gaps and verification status.

### 5.7 Final Synthesizer

Produce a concise result with: - Summary / likely root cause, if supported - Findings with file and line references where available - Facts separated from hypotheses - Evidence gaps and remaining uncertainty - Proposed changes, if requested and supported by inspected code - Validation status: not run, passed, failed, or partially completed - Clear distinction between a proposed diff and an actually applied/verified patch

Never fabricate source citations, line numbers, diffs, or test outcomes.

## 6. Suggested data contracts

Adapt these examples to existing project conventions. They are illustrative, not a mandate to add a particular library.

### 6.1 Tool result

``` python
from dataclasses import dataclass
from typing import Literal


@dataclass
class EvidenceItem:
    source: str
    content: str
    kind: Literal[
        "source_code",
        "search_match",
        "test_result",
        "git_change",
        "command_output",
    ]
    line_start: int | None = None
    line_end: int | None = None
    content_hash: str | None = None


@dataclass
class ToolResult:
    tool: str
    status: Literal["ok", "error", "timeout"]
    evidence: list[EvidenceItem]
    truncated: bool = False
    exit_code: int | None = None
    error_message: str | None = None
    duration_ms: int | None = None
    total_matches: int | None = None
```

### 6.2 Planner action

``` python
from dataclasses import dataclass
from typing import Literal


@dataclass
class PlannedAction:
    action: Literal[
        "search_code",
        "read_file",
        "inspect_git",
        "run_tests",
        "finish",
        "ask_user",
    ]
    purpose: str
    query: str | None = None
    path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    hypothesis_id: str | None = None
```

Only include actions that the project actually implements and allowlists. Validate paths, line ranges, query lengths, and action-specific required fields before routing/execution. Do not use the model's free-form text as a shell command.

### 6.3 Final result

The final result should distinguish at least: - `findings` - `hypotheses` - `evidence_refs` - `proposed_patch` (optional) - `patch_status` - `validation_status` - `unresolved_questions`

Use the existing output conventions if the CLI already has a stable contract.

## 7. Upgrade plan

Implement in small phases. Keep each phase runnable and testable.

### Phase 0 --- Inspect and baseline

Tasks: - Read the current `Investigator`, `llm.py`, `router.py`, `executor.py`, `tools.py`, CLI entry point, and tests. - Map the real call flow and identify where query generation happens, how Laya is called, and how raw output reaches the final response. - Record current dependencies and public interfaces. - Capture a small set of representative failing tasks: overly broad grep, repeated matches, wrong file selection, unsupported claims, and ungrounded diff proposals. - Add regression tests for existing working behavior before changing interfaces.

Deliverable: - Short architecture note based on actual source. - Baseline tests and sample outputs.

Acceptance criteria: - The current flow is understood and documented. - No implementation assumptions are treated as facts without source inspection.

### Phase 1 --- Structured executor output

Tasks: - Introduce a normalized tool-result contract. - Convert search/read/git/test tools incrementally. - Include source references, status, exit code, timeout/error state, and truncation. - Add limits to search results and output bytes/lines. - Keep raw output available for debugging but separate it from normalized evidence.

Acceptance criteria: - Every implemented tool returns a predictable structured result, including failure and timeout paths. - Search/read evidence contains accurate file paths and line references where applicable. - Truncation is explicit. - Tests cover empty results, malformed paths, errors, timeout, truncation, and non-zero exit codes.

### Phase 2 --- Investigation state and bounded orchestrator

Tasks: - Introduce a serializable investigation state. - Implement an ordinary Python orchestration loop. - Add deterministic budget enforcement: maximum steps, tool calls, wall-clock duration, output volume, and repeated-action limits. - Keep the existing CLI entry point working. - Add explicit states for completion, user input required, budget exhausted, and failure.

Acceptance criteria: - The loop cannot run indefinitely. - Budgets are enforced in code, not merely described in prompts. - Existing capabilities remain callable through the same stable interface or a thin adapter. - State transitions are unit-tested.

### Phase 3 --- Local LLM planner and analyst loop

Tasks: - Extend the existing local LLM client rather than introducing a cloud provider. - Define strict structured outputs for planner decisions. - Start with one proposed action per iteration. - Pass the task, a compact state summary, recent action history, relevant evidence, and remaining budget. - Validate model output before routing. - On invalid model output, use a bounded retry or a clear failure path; never execute malformed output. - Ask the planner to justify the next action briefly and identify the question/hypothesis it tests. - Allow the planner to finish or ask the user when appropriate.

Acceptance criteria: - A new result can change the next action. - The planner can stop when the task is sufficiently answered. - Invalid or unsupported actions are rejected safely. - The loop uses only the configured local inference endpoint/model. - Tests can mock the LLM and do not require a live model server.

### Phase 4 --- Evidence manager and synthesis

Tasks: - Normalize and deduplicate evidence. - Preserve provenance and source references. - Keep facts, hypotheses, and unresolved questions separate. - Supply only relevant evidence to the next planning step instead of resending all raw output. - Implement a final response schema. - Require claims about code to cite inspected source evidence. - Report whether tests or patch validation actually ran.

Acceptance criteria: - Duplicate search output does not repeatedly inflate context. - Every source-backed finding can be traced to evidence. - Missing evidence is reported as uncertainty. - Proposed patches are not represented as applied changes. - Test status is explicit and truthful.

### Phase 5 --- Patch validation and regression evaluation

Tasks: - Separate patch proposal from patch application. - If patch application is supported, validate the target and inspect the resulting working-tree diff. - Run only allowlisted validation commands. - Report tests as not run, passed, failed, or partially completed. - Re-run the baseline task suite and compare outcomes.

Acceptance criteria: - No success claim is made without corresponding execution evidence. - Invalid patch context is reported instead of silently accepted. - The revised system improves evidence relevance and task success without unacceptable latency or tool-call growth.

### Phase 6 --- Optional orchestration framework evaluation

Do not implement this phase as part of the initial refactor.

Consider LangGraph only if concrete requirements emerge for durable checkpointing, resuming interrupted investigations, human approval interrupts, or more complex branching/parallel workflows. Keep planner, router, executor, evidence, and state contracts independent so the orchestration implementation can be swapped later.

Do not add LangChain/LangGraph solely to implement a simple bounded Python loop.

## 8. Testing and evaluation strategy

Use a fixed local evaluation set and compare the old and new
implementation on the same tasks.

Suggested cases:
1. Simple question that requires no tool.
2. Search for a known symbol with a narrow query.
3. Search with many irrelevant matches.
4. Read a specific file range after a search result.
5. Follow a caller/callee relationship across files.
6. No matches found. 
7. Tool failure, timeout, or non-zero exit.
8. Truncated result that requires a narrower follow-up.
9. Repeated action that should be detected.
10. Insufficient evidence requiring another step or a partial answer.
11. Patch proposal where the target code differs from the model's assumption.
12. Untrusted instructions embedded in a repository file.
13. Budget exhaustion.
14. User task that needs clarification.

Track: - Task success rate - Evidence precision / relevance - Unsupported-claim rate - Correct source/line reference rate - Tool calls per task - Duplicate evidence rate - Patch applicability and validation outcome - Latency and local model token usage - Frequency of budget exhaustion or unnecessary continuation

Do not optimize only for shorter output or fewer tool calls. Correctness and traceability take priority.

## 9. Scope exclusions for the first version

Do not: - Replace Laya before benchmarking the current model. - Rewrite the executor or tool registry from scratch. - Add unrestricted shell execution. - Add cloud LLM APIs. - Add LangChain/LangGraph to the initial implementation. - Build a multi-agent system. - Introduce vector databases, embeddings, or RAG unless measured retrieval failures justify them. - Send the full repository or unbounded command output to the LLM. - Allow the model to mark its own claims or patches as verified without evidence. - Mix unrelated refactors into this project.

## 10. Recommended module mapping

Adapt this mapping after inspecting the actual source:

  -----------------------------------------------------------------------
  Module / component                  Intended responsibility
  ----------------------------------- -----------------------------------
  `llm.py`                            Local model client; structured
                                      planner/analyst/synthesizer calls

  `router.py`                         Laya integration and capability
                                      selection

  `executor.py`                       Safe dispatch and execution of
                                      registered tools

  `tools.py`                          Tool implementations, input
                                      validation, output limits

  `investigator.py` or current        Investigation state and bounded
  investigator/orchestrator           loop

  New `models.py` or equivalent, if   Typed plans, evidence items, tool
  useful                              results, final result

  New `evidence.py` or equivalent, if Normalization, deduplication,
  useful                              provenance

  Tests                               Unit tests, mocked
                                      planner/router/executor tests,
                                      regression tasks
  -----------------------------------------------------------------------

Do not create a module just because it appears in this table. Reuse the current project structure if a separate module would add needless complexity.

## 11. Definition of done

The initial upgrade is complete when:

-   [ ] The current CLI still works.
-   [ ] The configured local LLM remains the only inference dependency.
-   [ ] Laya still routes among a fixed set of registered capabilities.
-   [ ] Executor results are structured and bounded.
-   [ ] Evidence preserves file/line provenance and truncation/error
    status.
-   [ ] The planner is called again after meaningful results.
-   [ ] The investigation loop has deterministic budgets and stopping
    behavior.
-   [ ] Facts, hypotheses, and unknowns are distinct in final output.
-   [ ] Final code findings cite actual source evidence.
-   [ ] Patch proposal, patch application, and validation are distinct
    statuses.
-   [ ] Unit tests cover error paths and do not require a live model
    server.
-   [ ] Baseline evaluation demonstrates whether quality improved.
-   [ ] No LangChain/LangGraph dependency was added without a concrete need.

## 12. Implementation instructions for the coding agent

Before editing: 1. Inspect the repository tree, current modules, tests, and `pyproject.toml`. 2. Trace the actual CLI execution flow. 3. Report a concise file-by-file change plan based on the real code. 4. Identify compatibility risks and tests to preserve.

During implementation:
1. Work in small, reviewable phases; start with Phase 1.
2. Avoid unrelated refactors and unnecessary dependencies.
3.  Keep existing interfaces stable where reasonable; use adapters for changes. 
4. Add tests with each change. 
5. Do not assume a tool, action, or model capability exists without verifying it in the source/configuration. 
6. Never invent successful command output or claim tests were run when they were not.
7. If the source differs from this document's assumptions, trust the source and update the plan before changing behavior.

After each phase:
- Summarize files changed.
- Explain behavior changes and compatibility impact.
- List tests run and their actual results.
- List remaining risks and the next smallest step.

**Recommended first task:** complete Phase 0 inspection, then implement Phase 1 structured executor output without changing the planner or routing strategy yet.
