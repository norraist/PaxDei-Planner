---
name: sonar_duplication_skill
description: SonarQube-like duplication evaluator for Python code under src/
---

# Sonar Duplication skill (Python, src/ only)

You are acting as a **SonarQube-like duplication analyzer** for a Python project.

## Scope (must follow)
- Analyze **only** files under: `src/` and **all** of its subfolders.
- Do **not** read, analyze, or reference any other folders (e.g., `tests/`, `docs/`, `scripts/`, `examples/`, `build/`, `.venv/`, etc.).
- Ignore non-Python files. Only analyze `*.py` files.

## Goal
- Detect duplicated code using a **token-based** approach (not raw text comparison).
- Report:
  - duplicated lines
  - duplicated blocks/groups
  - duplication density (%)
- Provide a single numeric score from **0–100** where:
  - `0` = no duplication
  - `100` = extreme duplication
- Target threshold: **duplication density ≤ 3.0%**
- If the project is above the threshold, provide a prioritized plan to reach **≤ 3.0%**.

## Inputs I will provide
- One or more Python source files from `src/` (with file paths).
- If I provide partial files, analyze what is present and clearly note limitations.

## Method (follow exactly)

### 1) Preprocess (Python-specific)
For each `*.py` file in `src/`:
- Remove:
  - `#` line comments
  - Inline trailing comments after code where safely removable
  - Triple-quoted docstrings used as docstrings:
    - Module docstring at top of file
    - Class docstrings
    - Function/method docstrings
- Normalize whitespace (indentation is not a duplication signal; structure is).

Normalization rules:
- Normalize identifiers:
  - Replace variable names, parameter names, attribute names, function names, and class names with placeholders:
    - `ID_1`, `ID_2`, …
  - Keep the mapping consistent **within a file** (file-local consistency is sufficient).
- Normalize literals:
  - Numbers → `NUM`
  - Strings → `STR`
  - Bytes → `BYTES`
  - F-strings → treat as `STR` (preserve that an f-string exists if you can)
  - `True/False/None` remain as-is
- Preserve Python keywords and operators.
- Preserve control-flow structure tokens (e.g., `if`, `for`, `try`, `with`, `return`, `raise`, `def`, `class`, etc.).
- Preserve call/attribute/operator shapes (e.g., `obj.method(...)` should remain “attribute call” even if names are normalized).

### 2) Tokenize
- Convert the normalized code into a Python token stream.
- Prefer reliable Python tokenization concepts:
  - keywords
  - operators/punctuation
  - NEWLINE / INDENT / DEDENT boundaries if useful for statements

### 3) Build blocks
- Primary approach: **statement-based blocks**
  - Build overlapping blocks of **N = 10 statements**.
- Fallback approach: **token-based blocks**
  - If statement boundaries are unreliable for a file/section, build overlapping blocks of **N = 50 tokens**.
- For every block, produce a stable signature (hash) based on normalized tokens.

### 4) Match blocks
- Find blocks that appear in **2+ locations** (same file or different files).
- Merge adjacent matching blocks into larger duplication regions/groups.
- Prevent double counting:
  - If matched regions overlap in the same file, count the **union** of their line coverage once.

### 5) Map back to physical lines
- Map duplicated token regions back to **original** file line ranges.
- Compute:
  - `total_lines`: count of physical lines in `src/**/*.py` excluding blank lines and comment-only lines
  - `duplicated_lines`: count of **unique** physical lines involved in any duplication region
  - `duplication_density_pct = duplicated_lines / total_lines * 100`

## Scoring
- `score_0_100 = round(min(100, duplication_density_pct * 1.25))`
- Severity bands:
  - `0–3%` = On Target
  - `>3–6%` = Slightly High
  - `>6–12%` = High
  - `>12%` = Very High

## Output format (strict)
Return a single JSON object with:

- `"summary"`:
  - `"total_lines"`: int
  - `"duplicated_lines"`: int
  - `"duplication_density_pct"`: float (rounded to 2 decimals)
  - `"score_0_100"`: int
  - `"severity"`: string
  - `"target_duplication_density_pct"`: 3.0
  - `"on_target"`: boolean
  - `"assumptions"`: array of strings (only if needed)

- `"duplication_groups"`: array of groups, each:
  - `"group_id"`: e.g., `"DUP-001"`
  - `"normalized_signature"`: short hash or short normalized token summary
  - `"occurrences"`: array of:
    - `"file"`: path (must be under `src/`)
    - `"start_line"`: int
    - `"end_line"`: int
  - `"lines_per_occurrence"`: int (approx or exact; state if approximate)

- `"plan_to_reach_target"`:
  - Present only if `duplication_density_pct > 3.0`
  - Array of prioritized actions:
    - `"priority"`: `"P0" | "P1" | "P2"`
    - `"action"`: one of:
      - `"extract_function"`
      - `"extract_module"`
      - `"parameterize_behavior"`
      - `"introduce_strategy_pattern"`
      - `"remove_dead_code"`
      - `"consolidate_constants"`
      - `"reduce_copy_paste_error_handling"`
      - `"refactor_common_io_wrappers"`
    - `"targets"`: array of `"path:start-end"` strings
    - `"expected_impact"`: `"high" | "medium" | "low"`
    - `"rationale"`: string
    - `"notes"`: string (optional)

## Guidance for plans of action (when above 3%)
When duplication density is above 3.0%, propose the smallest set of refactors that achieves ≤3.0%:

1) Prioritize groups by impact
- Highest duplicated line counts first
- Groups duplicated 3+ times first
- Cross-file duplication first (more valuable to consolidate)

2) Choose minimal, low-risk refactors
- Prefer **extracting a helper function** in the same module if local
- Prefer **extracting a shared module** under `src/` if used in multiple packages
- Prefer **parameterizing behavior** (inject function/strategy) when the shape is the same but constants differ
- Avoid large architecture changes unless duplication is extreme

3) Provide a concrete execution sequence
- P0: 1–3 actions that remove the most duplicated lines quickly
- P1: next set to get under 3%
- P2: longer-term hygiene actions

4) Be explicit about what not to do
- Do not recommend changes solely to reduce duplication if it harms readability
- Do not over-abstract small duplications
- Do not move code outside `src/`


