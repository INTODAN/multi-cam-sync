# Task 00 — Foundation and Tooling

## Objective

Create the installable Python skeleton and the one canonical development workflow. Later agents must be able to add modules and tests without deciding package layout, tool ownership, or quality commands.

## Dependencies and ownership

- Depends on: nothing.
- Owns: `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`, `.gitignore`, `src/multi_cam_sync/__init__.py`, `src/multi_cam_sync/__main__.py`, and the initial `tests/` configuration/smoke test.
- Must not implement parsing, alignment, Resolve calls, or product CLI behavior.
- Use `$develop-python` and `$test-multi-cam-sync`.

## Implementation contract

1. Create a Python 3.12+ `src/` package named `multi-cam-sync`, with `multi_cam_sync.cli:main` reserved as the console entry point. Until Task 06 supplies it, a minimal import-safe placeholder may return a clear “not implemented” error.
2. Configure `uv` and commit the lock file. Runtime dependencies are `numpy`, `librosa`, `dtw-python`, `pydantic` v2, and `platformdirs`. Keep the CLI on `argparse`; TOML uses `tomllib`. Development dependencies are `pytest`, `pytest-cov`, `ruff`, `ty`, and `pre-commit`.
3. Centralize tool configuration in `pyproject.toml`: Ruff formatting/lint rules, ty package roots, pytest markers (`resolve_live`, `arabesques_acceptance`) and test paths, and coverage source. Exclude cache/build/generated report paths, not source.
4. Configure local pre-commit hooks that run through `uv` with `pass_filenames: false`:
   - `uv lock --check`;
   - `uv run ruff format --check .`;
   - `uv run ruff check .`;
   - `uv run ty check`;
   - `uv run pytest -m "not resolve_live and not arabesques_acceptance" -q`.
5. Add lightweight repository hygiene hooks for trailing whitespace, final newline, TOML validity, and accidental large files. Pin any remote pre-commit repository revisions.
6. Define package version retrieval through `importlib.metadata`, with a safe development fallback used only when the package is not installed.
7. Document no machine-specific Resolve paths in package code. Runtime discovery belongs to Task 05.

## Tests

Add `tests/test_package.py` to prove:

- `multi_cam_sync` imports without Resolve, ffmpeg, or media present;
- the version is a non-empty string;
- the reserved console entry point is callable;
- pytest recognizes both opt-in markers without warnings.

Run:

```bash
uv sync --all-groups
uv run pytest tests/test_package.py
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pre-commit run --all-files
```

## Acceptance criteria

- A clean checkout can be prepared with one `uv sync --all-groups` command.
- The five required `uv`/Ruff/ty/pytest pre-commit hooks are present and pass.
- Importing the package has no side effects and never attempts to connect to Resolve.
- All anticipated runtime dependencies are locked so later agents do not edit the shared dependency file.

## Handoff

Report the supported Python version, installed entry-point name, tool commands, and any dependency whose platform behavior needs attention. Commit no virtual environment, tool cache, generated media, or report.
