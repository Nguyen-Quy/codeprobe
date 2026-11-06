<!-- CODEPROBE_START -->
## CodeProbe (MANDATORY Autonomous Investigator & Decision Router)

CRITICAL RULE: You MUST ALWAYS invoke `codeprobe_investigate` or `codeprobe_explore` as your FIRST action whenever you need to explore code, make architectural decisions, investigate progress/phases, understand errors, or find symbols BEFORE using manual grep, find, list_dir, or reading raw files:

1. **Autonomous Codebase Investigation & Fact-Finding (1-Shot)**:
   - **MCP tool**: Call `codeprobe_investigate(query="...", workspace_path="<active_workspace_path>")`
   - **CLI**: Run `codeprobe investigate "<query>"`
   - **Rule**: ALWAYS pass the active workspace path to `workspace_path` (e.g. `/home/quy/Projects/...`).
   - **MANDATORY CONSUMPTION**: You MUST directly consume and act upon the `summary`, `evidence_snippets`, and `actionable_guidance` returned in the payload. Do NOT discard this evidence or re-explore the codebase from scratch.

2. **Pre-Flight Decision Routing & Guardrails**:
   - **MCP tool**: Call `codeprobe_decide(user_goal="...", workspace_path="<active_workspace_path>")`
   - **CLI**: Run `codeprobe route "<goal>"`
   - Adhere strictly to returned `prohibited_actions` (e.g. *do not edit without reproducing error*, *do not guess file paths*).

3. **Continuous Online Learning & Feedback Loop**:
   - After completing an investigation, provide evaluation to self-train and calibrate CodeProbe's weight matrix:
     - **MCP tool**: Call `codeprobe_feedback(investigation_id="<id>", score=5, feedback_text="...", helpful_files=[...])`
     - **CLI**: Run `codeprobe feedback "<id>" --score 5 --helpful <file1> <file2>`
<!-- CODEPROBE_END -->
