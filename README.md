# codeprobe

> **Universal Decision Router and Policy Engine for AI Coding Agents** (Antigravity, Claude Code, Codex, Cursor, Aider).

`codeprobe` sits between your coding agent and raw tool execution. Before an LLM performs expensive or risky actions (broad search, deep file reads, complex refactoring, executing arbitrary code), it queries `codeprobe` to receive:
- **Optimal Action Strategy**: Recommended actions with priority and rationale.
- **Guardrails & Prohibited Actions**: Strict constraints (e.g. *do not edit without reproducing error*, *do not modify read-only lockfiles*, *do not guess file paths*).
- **Pre-Flight Workspace Inventory (`codeprobe files`)**: Zero-token directory and language volume profiling.
- **Autonomous Behavioral Code Search (`codeprobe investigate`)**: 1-shot 3-tier evidence synthesis (File Leads, Verbatim Declaration Units with line numbers, and Cross-File Relationships).
- **Model Tier Guidance**: Model routing advice (e.g. `fast_infer` vs `reasoning_heavy`).
- **Continuous Learning Loop**: Feedback-driven matrix calibration that trains on agent outcomes.

---

## 📦 Installation & Setup

### 1. Production Installation (Sử dụng chính thức)

Cài đặt thông qua `pip` hoặc `uv`:

```bash
# Cài đặt qua pip
pip install codeprobe

# Hoặc cài đặt qua uv tool (khuyến nghị)
uv tool install codeprobe

# Nếu bạn đang phát triển CodeProbe thì cài đặt editable mode
uv tool install --editable /home/quy/Projects/codeprobe --force
```

#### Cài đặt Agent Skill (Dành cho AI Coding Agents)

Cài đặt `SKILL.md` để hướng dẫn AI Agent (Antigravity, Claude Code, Cursor) tự động kích hoạt CodeProbe:

```bash
# Cài đặt cục bộ vào thư mục project hiện tại (.agents/skills/codeprobe/)
codeprobe skill

# Hoặc cài đặt toàn cục cho mọi dự án (~/.gemini/config/, ~/.claude/, ~/.agents/)
codeprobe skill --global
```

#### Khởi tạo Guardrails & Policy cho dự án:

```bash
codeprobe init
```
Lệnh này sẽ tạo `.codeprobe/rules.toml` chứa các quy tắc bảo vệ file bí mật (`.env*`, `*.pem`), file chỉ đọc (`package-lock.json`, `uv.lock`), và giới hạn bán kính sửa đổi (blast radius).

---

### 2. Development Setup (Dành cho phát triển mã nguồn CodeProbe)

Nếu bạn clone repository để phát triển hoặc đóng góp tính năng mới:

```bash
# Clone repository
git clone https://github.com/dzhng/codeprobe.git
cd codeprobe

# Cài đặt môi trường ảo và dependencies với uv
uv sync

# Hoặc cài đặt editable mode
uv pip install -e .
```

#### Cài đặt Agent Skill trong môi trường Dev:

```bash
# Cài skill vào workspace hiện tại
uv run codeprobe skill

# Cài đặt toàn cục cho hệ thống
uv run codeprobe skill --global
```

#### Chạy Test Suite:

```bash
# Chạy toàn bộ 70+ unit tests
uv run pytest

# Chạy benchmark ma trận quyết định
uv run codeprobe test-matrix
```

---

## 🤖 Cách hoạt động với AI Coding Agent

Khi cài đặt `codeprobe skill` hoặc cấu hình MCP Server:
1. **Tự động gọi làm bước đầu tiên (FIRST ACTION RULE)**: Thay vì đoán mò đường dẫn hoặc chạy `grep -rn` quét toàn bộ ổ đĩa tốn hàng trăm ngàn tokens, Agent sẽ gọi `codeprobe_investigate` (MCP) hoặc `codeprobe investigate` (CLI).
2. **Pre-flight Inventory**: Agent chạy `codeprobe files` để nắm cấu trúc thư mục và kích thước mã nguồn với chi phí **0 token LLM**.
3. **Tuân thủ Guardrails**: Agent gọi `codeprobe_decide` trước khi refactor hoặc sửa code để kiểm tra các cấm kỵ (`prohibited_actions`).
4. **Tự động phản hồi (Feedback Loop)**: Sau mỗi lượt điều tra, Agent gọi `codeprobe_feedback` để chấm điểm và cung cấp danh sách file hữu ích / gây nhiễu, giúp CodeProbe tự động huấn luyện lại ma trận trọng số.

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

Kết nối `codeprobe` trực tiếp với Claude Code, Antigravity IDE, Cursor, hoặc Codex:

```bash
# Chạy MCP server qua stdio (mặc định)
codeprobe serve

# Chạy MCP server qua SSE transport
codeprobe serve --sse --port 8000

# Chạy REST HTTP server (FastAPI)
codeprobe serve --http --port 8000
```

#### Cấu hình MCP (`mcp_config.json`):

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

#### Các công cụ MCP được cung cấp:
- `codeprobe_files`: Quét thống kê file và dung lượng dự án (Zero-token inventory).
- `codeprobe_investigate` / `codeprobe_explore`: **1-Shot Autonomous Investigation Engine**. Trích xuất từ khóa, quét mã nguồn, trích xuất AST Declaration Units kèm số dòng, liên kết đồ thị gọi hàm cross-file và loại bỏ false-positives.
- `codeprobe_decide`: Đánh giá trạng thái và trả về chiến lược, hành động khuyến nghị, model tier và danh sách `prohibited_actions`.
- `codeprobe_feedback`: Gửi đánh giá và học online để tinh chỉnh trọng số retrieval.
- `codeprobe_recommend_strategy`: Triage nhanh chiến lược thực thi và tier mô hình.
- `codeprobe_evaluate_evidence`: Kiểm tra mức độ đầy đủ của bằng chứng (Sufficiency check).
- `codeprobe_explain_decision`: Giải thích chi tiết xác suất của ma trận quyết định.

---

## 💻 CLI Commands

```bash
# 1. Pre-flight workspace inventory
codeprobe files .
codeprobe files ./src --json
codeprobe files --exclude "*.min.js" .

# 2. Điều tra hành vi mã nguồn 1-shot
codeprobe investigate "Where is user authentication token verified?"
codeprobe investigate "Kiểm tra tiến độ phase hiện tại trong .planning"

# 3. Định tuyến quyết định và kiểm tra guardrails
codeprobe route "Refactor database query caching"

# 4. Cài đặt Agent Skill
codeprobe skill
codeprobe skill --global
codeprobe skill --print

# 5. Khởi tạo và kiểm tra cấu hình guardrails
codeprobe init
codeprobe config

# 6. Gửi feedback huấn luyện trọng số
codeprobe feedback "inv_123456" --score 5 --helpful "src/auth.py"

# 7. Chạy benchmark ma trận
codeprobe test-matrix
```

---

## ⚙️ Project Configuration & Guardrails (`.codeprobe/rules.toml`)

```toml
[guardrails]
# Files cấm đọc hoặc chỉnh sửa
forbidden_files = [
    ".env*",
    "*.pem",
    "*.key",
    "credentials.json",
    "secrets/*",
]

# Files chỉ được đọc, không được sửa đổi
read_only_files = [
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    "uv.lock",
    "*.min.js",
]

[policy]
# Yêu cầu bằng chứng chạy test trước khi cho phép sửa code
require_tests_before_edit = true

# Giới hạn số file tối đa trong một đợt chỉnh sửa
blast_radius_limit = 5

# Giới hạn số dòng tối đa khi đọc lát cắt file (slice read)
max_file_slice_lines = 150

# Giới hạn dung lượng đọc duyệt mã nguồn (navigation budget)
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
                            │ DecisionRequest / Investigation
┌───────────────────────────▼────────────────────────────┐
│                    codeprobe Engine                    │
├────────────────────────────────────────────────────────┤
│ 1. Pre-flight Inventory & Budgeted Explorer            │
│ 2. Multi-language AST Declaration Units (Py/TS/Go/Rust)│
│ 3. Cross-file Relationship Linker & Pruning            │
│ 4. Laya Probabilistic Decision Router                  │
│ 5. Guardrails Policy Engine (Secret / Lockfile bounds) │
│ 6. Online Feedback Calibration Weight Matrix           │
└───────────────────────────┬────────────────────────────┘
                            │ DecisionResponse / 3-Tier Evidence
┌───────────────────────────▼────────────────────────────┐
│      Agent Executes Safe, Grounded & Targeted Action   │
└────────────────────────────────────────────────────────┘
```
