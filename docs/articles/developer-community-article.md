# Yes, Bot! How I Learned to Stop Worrying and Love the AI (Responsibly)

*A Holiday Gift from DevRel: IRIS PGWire and the Art of Structured Creativity*

**By Thomas Dyar, Sr. Manager AI Platform and Ecosystem, InterSystems**

---

## The Rut

I'll be honest: Up to a year agoI was not doing much coding -- I was sick of it.

I had been a hands-on software engineer and data scientist After years, but a few years before starting at InterSystems I had gotten worn down by the tedium  of software development. The endless cycle of boilerplate, debugging, and context-switching left me creatively depleted. Like Jim Carrey's character in *Yes Man*, I found myself saying "no" and "not *again*" -- so much so that I switched jobs! But I must say that I missed the creative aspects of coding.

Then AI coding assistants arrived. And I became a "Yes Man" for bots.

---

## Act I: Exuberance ("Yes to Everything!")

When I first started using AI coding assistants (Windsurf, then Cline, then Roo Code, now Claude Code), it felt like magic. Natural language → working code. I said "yes" to every suggestion, every refactor, every wild idea.

My first major AI-assisted project was an internal project I started a few months ago - a vector search and "RAG templates" collection for IRIS. I was so excited I let the bot run wild:


*"Implement semantic search!"* Yes!
*"Build a full RAG pipeline!"* Yes!
*"Make it extensible!"* Yes!
*"Add MCP support!"* Yes!

The creative energy was back. Code was flowing. I felt productive again.

Then my intern - a software engineering major - looked over the codebase.

He was **NOT impressed**.

Though I had implemented about 6 complete RAG methods based on academic papers, only 2 of them "really worked" -- the pytests were passing, but they had a lot of mocks that were being used instead of real database queries. In many cases "fast iteration" was admittedly "AI slop" - inconsistent patterns, duplicated logic, questionable architectural decisions. The bot had said "yes" to everything I asked, but nobody was saying "no" to bad ideas or "wait, let's think about this first."

---

## Act II: The Trough of Reality

That intern review was a wake-up call. Like Jim Carrey learning that saying "yes" to everything creates chaos, I had to face the downsides:

- **Hallucinations**: The bot confidently generated code for APIs that didn't exist -- easy to spot, but annoyingly frequent and time-consuming to debug.
- **Context drift**: Long sessions lost track of architectural decisions
- **Quality variance**: Some outputs were brilliant; others needed complete rewrites
- **The "Yes, and don't..." dance**: Every prompt became "Yes, add this feature... and don't break what we did yesterday... and don't forget that thing I mentioned three hours ago...", and many many exclamation points and ALL CAPS as I tried to communicate the severity of the issue ;)

I had to admit that I was spending more time managing the bot than it was worth. The exuberance phase had ended, and I wasn't alone in being disillusioned. I needed a different approach, a course correction.

---

## Act III: Enter specify-kit ("Taming the Beast")

I came to realize: **I needed a system, not just a bot.**

That's when I discovered [spec-kit](https://speckit.org/) - a code assistant-agnostic workflow that transforms interaction with AI assistants. (AWS's [Kiro](https://kiro.dev) is another flavor of spec-driven AI-assisted development - the pattern is emerging across the industry.) Instead of freeform "yes," I now have structured specifications:

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
git clone https://github.com/intersystems-community/iris-pgwire.git
cd iris-pgwire
docker-compose up -d

# Connect with any PostgreSQL client

### Quick Demo: From Zero to Analytics

Once your container is up, you’re not just connected to a database—you’re connected to an ecosystem.

**1. The Classic Handshake (psql)**
```bash
psql -h localhost -p 5432 -U _SYSTEM -d USER
```

**2. Standard SQL, IRIS Power**
```sql
-- This runs on IRIS, but feels like Postgres
SELECT COUNT(*) FROM MyPatients WHERE category = "Follow-up";
```

**3. The "Killer Feature": pgvector Syntax on IRIS**
This is where it gets interesting. You can use standard `pgvector` distance operators, and IRIS PGWire translates them into native IRIS vector functions on the fly:

```sql
-- Semantic search using the pgvector <=> (cosine distance) operator
SELECT id, content 
FROM medical_notes 
ORDER BY embedding <=> TO_VECTOR("[0.1, 0.2, 0.3...]", DOUBLE) 
LIMIT 5;
```
psql -h localhost -p 5432 -U _SYSTEM -d USER -c "SELECT 'Hello from IRIS!'"
```

### The "Impossible" Connection: No IRIS Driver? No Problem.

This isn’t just about making things *easier*—it’s about making things *possible*.

Take **Metabase Cloud** or **Prisma ORM**.

- **Metabase Cloud** is a beautiful, managed BI tool. You can’t upload an IRIS JDBC driver to their cloud servers. You are limited to their pre-installed list.
- **Prisma** is the standard ORM for modern TypeScript developers. It uses a custom engine that doesn’t (yet) speak IRIS.

Without a wire protocol adapter, these tools are locked out of your IRIS data. With **IRIS PGWire**, they just see a high-performance PostgreSQL database.

**Demo: Prisma with InterSystems IRIS**
Just point your `schema.prisma` at the PGWire port:

```prisma
datasource db {
  provider = "postgresql"
  url      = "postgresql://_SYSTEM:SYS@localhost:5432/USER"
}
```

Now you can use Prisma’s world-class CLI and type-safety:
```bash
npx prisma db pull
npx prisma generate
```

### Built with Structured AI Collaboration

What makes this project interesting isn't just the code - it's how it was built. The `specs/` directory contains **27 feature specifications** documenting the entire development journey:

```
specs/
├── 001-postgresql-wire-protocol/    # Where it all began
├── 002-sql-query-processing/        # Query translation layer
├── 003-iris-integration-layer/      # IRIS backend connection
├── 006-vector-operations-pgvector/  # AI/ML vector support
├── 008-copy-protocol-bulk-operations/
├── 010-security-production-readiness/
├── 012-client-compatibility-testing/ # 8-language test matrix
├── 019-async-sqlalchemy-based/      # FastAPI integration
├── 025-comprehensive-code-and/      # Quality validation
├── 026-doc-review/                  # Documentation audit
└── 027-open-exchange/               # This publication!
    ├── spec.md                      # Package requirements
    ├── research.md                  # Market analysis
    ├── plan.md                      # Publication strategy
    └── tasks.md                     # Implementation steps
```

Each feature started as a natural language description like:

> *"PostgreSQL Wire Protocol Foundation - SSL/TLS handshake, authentication, session management, and basic protocol compliance"*

And became a structured specification with user stories, acceptance criteria, and `[NEEDS CLARIFICATION]` markers for decisions that required human judgment.

**The Evolution:**
- **Spec 001**: "Can we make PostgreSQL clients talk to IRIS?"
- **Spec 006**: "What about vector search and AI workloads?"
- **Spec 019**: "FastAPI developers need async support"
- **Spec 027**: "Let's share this with the world"

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
- **GitHub**: https://github.com/intersystems-community/iris-pgwire
- **Open Exchange**: Coming soon!
- **Quick Start**: 60 seconds with Docker

### specify-kit
- **GitHub**: https://github.com/github/spec-kit
- **Usage**: Add to your Claude Code project at the command line with `specify init --here`and then in Claude Code run `/specify <what you want to build>`
- **Alternative**: [Kiro by AWS](https://kiro.dev) - similar spec-driven approach in a full IDE

---

## The Balance

I'm no longer a "Yes Man" for bots. I'm not saying "no" either.

I'm saying: **"Yes, with structure."**

The creative energy is back. The tedium is managed by the bot. But the specifications ensure we're building the right thing, the right way.

Happy Holidays from InterSystems. May your prompts be clear and your tests be green.

---

*Thomas Dyar is Sr. Manager of AI Platform and Ecosystem at InterSystems, where he works on developer enablement, AI tooling, and making databases accessible to everyone. When he's not taming AI bots, he's probably watching Kubrick films and thinking about human-machine collaboration.*

---

## Resources

- [IRIS PGWire GitHub Repository](https://github.com/intersystems-community/iris-pgwire) - The "after" (27 specs, 171 tests)
- [Internal project started a few months ago](https://github.com/isc-tdyar/iris-vector-rag) - The "before" (no specs, AI slop)
- [specify-kit Claude Code Workflow](https://github.com/ProfSynapse/specify-kit)
- [Kiro - AWS Spec-Driven Development](https://kiro.dev)
- [Claude Code Documentation](https://docs.anthropic.com/claude-code)
- [InterSystems Open Exchange](https://openexchange.intersystems.com)
