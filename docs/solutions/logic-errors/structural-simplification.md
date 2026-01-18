# Solution: Structural Simplification and Decoupling

**Category:** Logic Errors / Anti-patterns
**Date:** 2026-01-17
**Status:** Solved (Structural Improvement)

## Problem Symptom
1. `IRISExecutor` contained a massive (350+ line) `if/elif` chain for intercepting and stubbing PostgreSQL system queries (e.g., `SHOW`, `VERSION()`). This violated the Single Responsibility Principle.
2. SQL transformations were fragmented across `protocol.py`, `vector_optimizer.py`, and `sql_translator/`, leading to redundant logic and "double-patching" bugs.
3. Ad-hoc regex fixes like `fix_order_by_aliases` were duplicated and inconsistently applied.

## Investigation Steps
1. Performed a code-smell analysis using the `explore` agent.
2. Identified high cyclomatic complexity in `execute_query` and protocol handshake.
3. Traced redundant `_fix_order_by_aliases` implementations.

## Root Cause
Iterative feature additions led to "God Object" patterns in `IRISExecutor` and `PGWireProtocol`. Lack of a centralized transformation pipeline resulted in logic drift between protocol handling and execution phases.

## Working Solution
1. **Decoupled Interception**: Created `SQLInterceptor` in `src/iris_pgwire/sql_translator/interceptor.py`. It uses a registry pattern to map SQL patterns to handler functions, removing the procedural block from `IRISExecutor`.
2. **Centralized Pipeline**: Created `SQLPipeline` in `src/iris_pgwire/sql_translator/pipeline.py`. It orchestrates all stages (filtering, normalization, refinement, optimization) in a single, consistent pass.
3. **Unified Refinement**: Created `SQLRefiner` in `src/iris_pgwire/sql_translator/refiner.py` to host IRIS-specific SQL tweaks like the `ORDER BY` alias fix, ensuring they are applied once and only when needed.

## Prevention Strategies
- **Favor Registry over Procedure**: Use registry patterns for command dispatching to keep core classes small.
- **Single-Pass Architecture**: Ensure data (SQL) flows through a single, well-defined pipeline rather than being modified at multiple layer boundaries.
- **Modularize Ad-hoc Fixes**: Move special-case SQL transformations into a dedicated "Refiner" or "Optimizer" rather than embedding them in protocol handlers.

## Cross-References
- [interceptor.py](../../src/iris_pgwire/sql_translator/interceptor.py)
- [pipeline.py](../../src/iris_pgwire/sql_translator/pipeline.py)
- [refiner.py](../../src/iris_pgwire/sql_translator/refiner.py)
- [iris_executor.py](../../src/iris_pgwire/iris_executor.py)
