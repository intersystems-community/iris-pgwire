# Yes, Bot! How I Learned to Stop Worrying and Love the AI (Responsibly)

*A Holiday Gift from DevRel: IRIS PGWire and the Art of Structured Creativity*

**By Thomas Dyar, Sr. Manager AI Platform and Ecosystem, InterSystems**

---

## The Rut

I'll be honest: I was sick of coding.

After years of software development, the tedium had worn me down. The endless cycle of boilerplate, debugging, and context-switching left me creatively depleted. Like Jim Carrey's character in *Yes Man*, I found myself saying "no" to projects before they even started. Safe, but unfulfilled.

Then AI coding assistants arrived. And I became a "Yes Man" for bots.

---

## Act I: Exuberance ("Yes to Everything!")

When I first started using Claude Code, it felt like magic. Natural language → working code. I said "yes" to every suggestion, every refactor, every wild idea.

*"Write me a PostgreSQL wire protocol server!"* Yes!
*"Add OAuth 2.0 authentication!"* Yes!
*"Support pgvector operators!"* Yes!

The results were impressive. In days, I had a working prototype that let any PostgreSQL client connect to InterSystems IRIS. The creative energy was back.

But there was a problem.

---

## Act II: The Trough of Reality

Like Jim Carrey learning that saying "yes" to everything creates chaos, I discovered the downsides:

- **Hallucinations**: The bot confidently generated code for APIs that didn't exist
- **Context drift**: Long sessions lost track of architectural decisions
- **Quality variance**: Some outputs were brilliant; others needed complete rewrites
- **The "Yes, and don't..." dance**: Every prompt became "Yes, add this feature... and don't break authentication... and don't forget the tests... and don't change the public API..."

I was spending more time managing the bot than coding. The exuberance phase had ended.

---

## Act III: Enter specify-kit ("Taming the Beast")

The turning point came when I realized: **I needed a system, not just a bot.**

That's when I discovered [specify-kit](https://github.com/ProfSynapse/specify-kit) - a Claude Code workflow that transforms how I interact with AI assistants. (AWS's [Kiro](https://kiro.dev) is another flavor of spec-driven AI-assisted development - the pattern is emerging across the industry.) Instead of freeform "yes," I now have structured specifications:

### The Workflow

```
/specify → /clarify → /plan → /tasks → /implement
```

Each step produces artifacts that survive context windows:

| Command | Output | Purpose |
|---------|--------|---------|
| `/specify` | `spec.md` | User stories, requirements, acceptance criteria |
| `/clarify` | Updated spec | Resolve ambiguities before coding |
| `/plan` | `plan.md` | Implementation strategy, architecture decisions |
| `/tasks` | `tasks.md` | Ordered task list with dependencies |
| `/implement` | Code + tests | Actual implementation |

### What Changed

**Before specify-kit:**
> "Add Open Exchange support... no wait, don't auto-start the server... actually, check if module.xml exists first... and make sure the tests pass..."

**After specify-kit:**
> `/specify make this an Open Exchange package`

The system asks clarifying questions, documents decisions, and generates implementation plans. When I picked "manual start" vs "auto-start" during `/clarify`, that decision was encoded into the spec and carried through to implementation.

---

## The Proof: IRIS PGWire

IRIS PGWire is my Christmas gift to the InterSystems developer community. It's a PostgreSQL wire protocol server that lets you connect **any** PostgreSQL client to IRIS:

- **psql, DBeaver, Superset, Metabase, Grafana** - zero configuration
- **psycopg3, asyncpg, SQLAlchemy, pandas** - all your Python favorites
- **pgvector syntax** - use `<=>` for cosine similarity, `<#>` for dot product

```bash
# Quick Start
git clone https://github.com/isc-tdyar/iris-pgwire.git
cd iris-pgwire
docker-compose up -d

# Connect with any PostgreSQL client
psql -h localhost -p 5432 -U _SYSTEM -d USER -c "SELECT 'Hello from IRIS!'"
```

### Built with Structured AI Collaboration

What makes this project interesting isn't just the code - it's how it was built. The `specs/` directory contains the full specification history:

```
specs/
├── 026-doc-review/          # Documentation quality review
│   ├── spec.md              # User stories for clarity, tone, accuracy
│   ├── plan.md              # Review strategy
│   └── tasks.md             # Actionable checklist
└── 027-open-exchange/       # Open Exchange publication
    ├── spec.md              # Package requirements
    ├── research.md          # Market research
    ├── plan.md              # Publication strategy
    └── tasks.md             # Implementation steps
```

Each feature started as a natural language description and became a structured specification. When the bot implemented the code, it had clear requirements to follow. When I reviewed the output, I had acceptance criteria to verify against.

**The result:** 171 tests passing across 8 programming languages. Production-ready.

---

## What I Learned

### 1. Specifications are Force Multipliers

A 30-minute investment in `/specify` and `/clarify` saves hours of debugging and rework. The bot doesn't have to guess your intent when it's documented.

### 2. Clarification Questions Reveal Gaps

When specify-kit asked "Should the server auto-start after ZPM installation?", I realized I hadn't decided. That one question prevented a design mistake that would have affected every user.

### 3. The Spec is the Source of Truth

When context windows overflow or sessions restart, the spec survives. The bot can read `spec.md` and get back to work without re-explaining everything.

### 4. Test-First Still Matters

Every user story in the spec maps to acceptance criteria. Every acceptance criterion maps to a test. The bot doesn't "forget" to write tests because they're required by the spec.

---

## Try It Yourself

### IRIS PGWire
- **GitHub**: https://github.com/isc-tdyar/iris-pgwire
- **Open Exchange**: Coming soon!
- **Quick Start**: 60 seconds with Docker

### specify-kit
- **GitHub**: https://github.com/ProfSynapse/specify-kit
- **Usage**: Add to your Claude Code project and run `/specify`
- **Alternative**: [Kiro by AWS](https://kiro.dev) - similar spec-driven approach

---

## The Balance

I'm no longer a "Yes Man" for bots. I'm not saying "no" either.

I'm saying: **"Yes, with structure."**

The creative energy is back. The tedium is managed by the bot. But the specifications ensure we're building the right thing, the right way.

Happy Holidays from InterSystems DevRel. May your prompts be clear and your tests be green.

---

*Thomas Dyar is Sr. Manager of AI Platform and Ecosystem at InterSystems, where he works on developer enablement, AI tooling, and making databases accessible to everyone. When he's not taming AI bots, he's probably watching Kubrick films and thinking about human-machine collaboration.*

---

## Resources

- [IRIS PGWire GitHub Repository](https://github.com/isc-tdyar/iris-pgwire)
- [specify-kit Claude Code Workflow](https://github.com/ProfSynapse/specify-kit)
- [Kiro - AWS Spec-Driven Development](https://kiro.dev)
- [Claude Code Documentation](https://docs.anthropic.com/claude-code)
- [InterSystems Open Exchange](https://openexchange.intersystems.com)
