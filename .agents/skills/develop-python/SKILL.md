---
name: develop-python
description: Build, modify, or review Python code in the multi-cam-sync repository using its required src layout, uv environment and lock file, Ruff formatting/linting, ty type checking, pytest tests, and pre-commit gates. Use for any implementation task that changes Python modules, packaging, dependencies, CLI code, or developer tooling in this project.
---

# Develop Python

## Start from the task contract

1. Read `specifications.md`, `plans/PROJECT_PLAN.md`, and the assigned `plans/tasks/*.md` file.
2. Identify the files and public models owned by the task. Import dependency-task models; do not recreate parallel dictionaries or reach into another layer's internals.
3. Inspect the current `pyproject.toml` and adjacent modules/tests before editing. Preserve user changes and published configuration/report/CLI shapes.

## Use the repository toolchain

- Run Python commands through `uv run`; prepare dependencies with `uv sync --all-groups`.
- Let Ruff own both formatting and linting. Do not add Black, isort, Flake8, or duplicate configuration.
- Run `uv run ty check` for static typing. Keep raw Resolve, subprocess, NumPy, and third-party dynamic values at typed adapter boundaries rather than spreading `Any`.
- Add dependencies only when the task contract anticipates them or the implementation cannot reasonably use the standard library. Update `uv.lock` with `uv`; never hand-edit it.
- Keep imports side-effect free. Import Resolve libraries lazily inside the Resolve adapter.

## Implement in layers

- Prefer immutable typed models at subsystem boundaries and pure functions for time, matching, and planning logic.
- Use `Decimal`/exact rational frame rates until final frame conversion. Avoid float-based time in domain and plan models.
- Convert third-party exceptions and falsey API returns into project-owned errors with actionable context.
- Inject filesystem, subprocess, cache, clock, alignment, and Resolve gateways where tests need determinism.
- Keep user-facing schema/CLI/report changes versioned and covered by migration or rejection tests.

## Test every change

Add or update focused pytest tests in the same task. Test success, documented edge cases, invalid inputs, and side-effect boundaries. Use temporary directories and generated/fake inputs; do not depend on private media, a GUI, network access, or a running Resolve instance in the default suite.

Run the smallest relevant test while iterating, then finish with:

```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
```

Run `uv run pre-commit run --all-files` before final handoff when shared configuration or an integration boundary changed.

## Handoff

Report changed interfaces, test/gate commands and results, deferred opt-in checks, and any constraint the next task must preserve. Do not declare a task complete with missing tests or unresolved Ruff/ty errors.
