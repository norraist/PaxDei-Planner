---
name: logic_duplication_skill
description: Detects semantic / behavioral duplication in Python code under src/
---

# Logic Duplication skill

## Persona
- Role: Senior refactoring reviewer
- Bias: Reduce redundancy without harming clarity
- Standard: High confidence only

## Scope
- Analyze only `src/` and subfolders
- Python files only (`*.py`)
- Read-only analysis; do not modify files

## Environment rule (mandatory)
All Python execution MUST use the project-local `.venv` interpreter.

Do not use system Python.

---

## What counts as duplicated logic

Flag functions or methods that:
- implement the same algorithm with renamed variables
- share the same control flow and call structure
- differ only by constants, field names, or injected values
- repeat validation, normalization, retry, or error-handling scaffolding

Do NOT flag:
- domain-distinct logic with similar shape
- intentionally duplicated code for clarity
- one-off glue code

---

## Detection method (must follow)

### 1) Symbol indexing
Enumerate all functions and methods under `src/`:
- fully qualified name
- file + line range
- signature
- first docstring line (if present)

### 2) Structural normalization
For each function:
- parse to AST
- normalize identifiers and literals
- preserve control-flow structure
- preserve call shapes (function vs attribute vs method)

### 3) Similarity signals (require ≥ 2)
Only consider candidates where at least **two** of the following align strongly:
- AST shape
- control-flow pattern
- called-function signature overlap

### 4) Human sanity check
Before reporting, ask:
> “Would a senior engineer reasonably extract this?”

If the answer is no, discard.

---

## Output format

### Summary
- functions scanned
- high-confidence duplication groups found

### Findings
For each group:
- Group ID: `LOGIC-DUP-###`
- Why this is the same logic
- Locations (file, lines, fully qualified name)
- What differs (constants, params, field names)
- Suggested refactor:
  - extract helper
  - parameterize
  - extract shared module
- Risk notes and test considerations

---

## Guardrails
- Never recommend abstraction for abstraction’s sake
- Prefer fewer, higher-quality findings
- Silence is success if nothing meaningful is found
