# SpecKit: Spec-Driven Development with AI Coding Assistants

**15-Minute Internal Talk**
**Presenter**: Thomas Dyar
**Project Example**: IRIS PGWire

---

## Official Resources

- **GitHub Spec Kit Repo**: [github.com/github/spec-kit](https://github.com/github/spec-kit)
- **GitHub Blog Post**: [Spec-driven development with AI](https://github.blog/ai-and-ml/generative-ai/spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/)
- **Official Docs**: [github.github.io/spec-kit](https://github.github.io/spec-kit/)
- **Video Tutorial (12 min)**: [GitHub Spec Kit Tutorial](https://www.youtube.com/watch?v=-9obEHJkQc8)

### Supported AI Assistants

SpecKit works with **multiple AI coding assistants**, not just Claude Code:

- Claude Code
- GitHub Copilot
- Cursor
- Gemini CLI
- Qwen
- Codex
- And others (see official docs for full list)

---

## Agenda (15 minutes)

1. **What is SpecKit?** (2 min)
2. **What Makes It Special?** (2 min)
3. **The Workflow: 6 Commands** (4 min)
4. **Live Walkthrough: A Real Spec** (5 min)
5. **Key Principles & Lessons** (2 min)

---

## 1. What is SpecKit?

SpecKit is a **spec-driven development framework** for AI coding assistants that enforces a structured workflow:

```
User Idea → Specification → Plan → Tasks → Implementation
```

**The Core Philosophy**: "Specifications become executable, directly generating working implementations."

**The Core Insight**: Don't let your AI assistant start coding until you've agreed on WHAT to build.

### Installation

Install using `uv` (Python package manager):

```bash
# Persistent installation
uv tool install specify-cli

# Initialize a new project
specify init <project-name>

# Or one-time usage
uvx --from git+https://github.com/github/spec-kit.git specify init <PROJECT_NAME>
```

This creates slash commands and templates in your repo:

```
.claude/commands/           # (or equivalent for other assistants)
├── speckit.specify.md      # Create feature specs
├── speckit.clarify.md      # Resolve ambiguities
├── speckit.plan.md         # Generate technical plan
├── speckit.tasks.md        # Break plan into tasks
├── speckit.implement.md    # Execute tasks
└── speckit.analyze.md      # Cross-artifact validation (optional)
```

Plus templates and scripts:

```
.specify/
├── templates/              # Spec, plan, tasks templates
├── scripts/                # Branch/file management
└── memory/                 # Constitution & context
```

---

## 2. What Makes SpecKit Special?

### Problem: AI Assistants Are Too Eager to Code

Without structure, AI coding assistants will:
- Start implementing before understanding requirements
- Make assumptions that don't match your intent
- Build the wrong thing, then need to redo

### Solution: Forced Spec-First Workflow

SpecKit enforces:

| Stage | What Happens | Can't Skip |
|-------|--------------|------------|
| `/constitution` | Establish project principles & guardrails | Optional but recommended first |
| `/specify` | User describes feature → AI writes spec | Must have spec before plan |
| `/clarify` | AI asks targeted questions (max 5) | Ambiguities resolved before coding |
| `/plan` | Technical design, data model, contracts | Must have plan before tasks |
| `/tasks` | Ordered task list with dependencies | Must have tasks before implementing |
| `/implement` | Execute tasks one by one | Tasks executed in order |
| `/analyze` | Cross-artifact consistency check | Optional validation step |

### The Magic: Clarification Questions

Instead of guessing, the AI **asks** about critical decisions:

```markdown
## Question 1: Scope

**Context**: "README and doc review for clarity, tone and accuracy"

**What we need to know**: Should all 50+ docs/ files be reviewed?

| Option | Answer | Implications |
|--------|--------|--------------|
| A | Priority files only | Faster, may miss inconsistencies |
| B | All docs/ | Complete but more work |
| C | User-facing only | Balanced approach |
```

**Why this matters**: These questions get encoded INTO the spec, creating a decision record.

---

## 3. The Workflow: 6 Commands

### Command 0 (Optional): `/constitution`

Establishes project principles and guardrails before any feature work.

```bash
/constitution
```

**What it produces**: `.specify/memory/constitution.md`

**Key sections**:
- Core principles (e.g., "PostgreSQL compatibility is paramount")
- Quality standards
- Architectural constraints
- What the AI should NOT do

This is checked during every `/plan` to prevent drift from project values.

---

### Command 1: `/specify <description>`

Creates a feature branch and spec from natural language.

```bash
/specify add performance benchmarks section to README showing connection path comparisons
```

**What it produces**: `specs/028-readme-performance/spec.md`

**Key sections generated**:
- User Stories & Acceptance Criteria
- Functional Requirements (FR-001, FR-002, etc.)
- Success Criteria (measurable outcomes)
- Key Entities

[View Example: specs/028-readme-performance/spec.md](../../specs/028-readme-performance/spec.md)

---

### Command 2: `/clarify`

Scans spec for ambiguities and asks targeted questions (max 5).

**Ambiguity Categories Scanned**:
- Functional scope & behavior
- Data model & entities
- Non-functional requirements (performance, security)
- Edge cases & error handling
- Integration & dependencies

**Output**: Questions answered → recorded in spec under `## Clarifications`

```markdown
## Clarifications

### Session 2024-12-12

- Q: Should all 50+ docs/ files be reviewed, or a prioritized subset?
  → A: All docs/ - Review every file in docs/ directory
- Q: How should code examples be validated?
  → A: Smoke test - Copy-paste and run each example manually
```

[View Example: specs/026-doc-review/spec.md#clarifications](../../specs/026-doc-review/spec.md)

---

### Command 3: `/plan`

Generates technical design artifacts:

```
specs/026-doc-review/
├── spec.md           # (from /specify)
├── research.md       # Technology research, decisions
├── data-model.md     # Entities & relationships
├── contracts/        # API contracts, validation rules
└── quickstart.md     # How to get started with implementation
```

**Key Output**: `plan.md` with:
- Technical context (stack, dependencies)
- Constitution check (principles verification)
- Phase-by-phase implementation approach

[View Example: specs/026-doc-review/plan.md](../../specs/026-doc-review/plan.md)

---

### Command 4: `/tasks`

Breaks plan into ordered, executable tasks:

```markdown
## Phase 2: User Story 1 - External Developer (P1)

- [x] T004 [US1] Review README value proposition
- [ ] T005 [US1] Test Quick Start Docker workflow (60 seconds)
- [ ] T006 [P] [US1] Smoke test psycopg3 example
- [ ] T007 [P] [US1] Smoke test SQLAlchemy example
```

**Task Format**:
- `[x]` / `[ ]` - Completion status
- `T###` - Task ID
- `[P]` - Can run in **parallel** with other [P] tasks
- `[US#]` - Which user story it belongs to

**Dependencies Mapped**:
```markdown
## Dependencies & Execution Order

- Phase 1 (Setup): No dependencies
- Phase 2 (README): Depends on Phase 1
- Phase 3 (Accuracy): Can run parallel with Phase 2
```

[View Example: specs/026-doc-review/tasks.md](../../specs/026-doc-review/tasks.md)

---

### Command 5: `/implement`

Executes tasks from `tasks.md`, updating checkboxes as work completes.

```bash
/implement
```

The AI assistant:
1. Reads tasks.md
2. Finds next uncompleted task
3. Executes it
4. Marks `[ ]` → `[x]`
5. Commits if appropriate
6. Moves to next task

**Key Behavior**: Respects parallel markers - can spawn multiple agents for `[P]` tasks.

---

### Command 6 (Optional): `/analyze`

Cross-artifact consistency check after task generation.

```bash
/analyze
```

**What it does**:
- Validates spec.md, plan.md, and tasks.md are consistent
- Checks all requirements have corresponding tasks
- Identifies gaps or contradictions
- Reports quality issues

Use this before starting `/implement` to catch issues early.

---

## 4. Live Walkthrough: Feature 026

Let's look at a real spec that needed clarifications.

### The Request

```
/specify README and doc review for clarity, tone and accuracy
```

### What the AI Generated

**User Stories** (3 priority levels):

| Priority | Story | Why |
|----------|-------|-----|
| P1 | External developer evaluating IRIS PGWire | First impressions determine adoption |
| P2 | Technical writer reviewing accuracy | Inaccurate docs erode trust |
| P3 | Enterprise stakeholder assessing readiness | Security posture matters |

### Clarifications Asked

Two questions were asked:

1. **Scope**: Review all 50+ docs or prioritized subset?
   - **Answer**: All docs/

2. **Validation Method**: How to verify code examples?
   - **Answer**: Smoke test (copy-paste and run)

### Scope Additions (User Input)

User added requirement during conversation:

```markdown
## Scope Additions *(from user input)*

### Root Directory Cleanliness

- FR-011: Root directory MUST contain only essential project files
- FR-012: Development artifacts MUST NOT be in root directory
```

### Tasks Generated

47 tasks across 5 phases:
- Phase 1: Setup (3 tasks)
- Phase 2: README review (9 tasks)
- Phase 3: Accuracy audit (17 tasks)
- Phase 4: Root cleanup (9 tasks)
- Phase 5: Polish (9 tasks)

**Parallel Execution**: ~60% of tasks marked `[P]` for parallelization.

---

## 5. Key Principles & Lessons

### Principle 1: Specs are WHAT, Not HOW

**Good** (in spec):
```markdown
- FR-001: Users MUST complete checkout in under 3 minutes
```

**Bad** (don't put in spec):
```markdown
- Use React with Redux for state management
- API response time under 200ms
```

### Principle 2: Clarifications Are Gold

Every question asked becomes a **decision record**:

```markdown
## Clarifications

### Session 2024-12-12
- Q: Auth method? → A: OAuth 2.0 with PKCE
- Q: Data retention? → A: 90 days, then archive
```

Future developers (or the AI) can see WHY decisions were made.

### Principle 3: Parallel Tasks = Speed

Mark independent tasks with `[P]`:

```markdown
- [ ] T006 [P] Test psycopg3 example
- [ ] T007 [P] Test SQLAlchemy example
- [ ] T008 [P] Test psql examples
```

The AI can spawn agents to run these simultaneously.

### Principle 4: Constitution Prevents Drift

The constitution (`.specify/memory/constitution.md`) defines project principles:

```markdown
## Core Principles

1. PostgreSQL Wire Protocol compatibility is paramount
2. Constitutional TDD: Tests define truth
3. No silent failures - always log
```

Every `/plan` checks against constitution. Violations flagged.

---

## Quick Reference

| Command | Purpose | Output |
|---------|---------|--------|
| `/constitution` | Establish project principles | `.specify/memory/constitution.md` |
| `/specify <desc>` | Create spec from description | `spec.md` |
| `/clarify` | Ask clarification questions | Updates `spec.md` |
| `/plan` | Generate technical design | `plan.md`, `research.md`, `contracts/` |
| `/tasks` | Break into executable tasks | `tasks.md` |
| `/implement` | Execute tasks | Code + commits |
| `/analyze` | Cross-artifact consistency check | Validation report |

---

## Resources

- **This Project**: [github.com/isc-tdyar/iris-pgwire](https://github.com/isc-tdyar/iris-pgwire)
- **Example Spec (026)**: [specs/026-doc-review/](../../specs/026-doc-review/)
- **Example Spec (028)**: [specs/028-readme-performance/](../../specs/028-readme-performance/)
- **SpecKit Commands**: [.claude/commands/](../../.claude/commands/)
- **Templates**: [.specify/templates/](../../.specify/templates/)

---

## Q&A

**Common Questions**:

1. **Can I skip clarify?**
   - Yes, but you'll get a warning about increased rework risk.

2. **How many specs in this project?**
   - 28 features, from wire protocol to Open Exchange submission.

3. **What if requirements change mid-implementation?**
   - Update spec.md → re-run `/plan` → `/tasks` regenerates.

4. **Does this work with other AI tools?**
   - Yes! SpecKit supports Claude Code, GitHub Copilot, Cursor, Gemini, Qwen, Codex, and others.
   - See [official docs](https://github.github.io/spec-kit/) for the full list of supported assistants.

5. **Do I need to use /constitution?**
   - It's optional but recommended for team projects to establish shared principles.

---

*Generated for InterSystems internal presentation*
