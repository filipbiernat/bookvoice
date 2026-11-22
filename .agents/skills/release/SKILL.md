---
name: release
description: >-
  Fast, standardized release workflow for the bookvoice repository (version bump,
  CI lint/format/test checks, git commit, annotated v* tag, and push to trigger
  GitHub Actions Release). Activate whenever the user asks to cut, publish, tag,
  or push a new release of bookvoice.
---

# Bookvoice Release Workflow

Use this checklist directly — no need to inspect `pyproject.toml`, `.github/workflows/`, or git conventions first.

## Repository Facts

- **Single source of truth for version:** `src/bookvoice/__init__.py` (`__version__ = "X.Y.Z"`, dynamically loaded by Hatch in `pyproject.toml`).
- **Default branch & remote:** `main` -> `origin` (`https://github.com/filipbiernat/bookvoice`).
- **Virtualenv (Windows):** `.venv\Scripts\python.exe` (macOS/Linux: `.venv/bin/python`).
- **CI checks (`.github/workflows/ci.yml`):** `ruff check .`, `ruff format --check .`, and `pytest`.
- **GitHub Release automation (`.github/workflows/release.yml`):** pushing any tag matching `v*` automatically runs `gh release create "$TAG" --title "Release $TAG" --generate-notes`. Do **not** manually create a GitHub Release unless the workflow fails.
- **Windows PowerShell 5.1 note:** do not chain commands with `&&`; use `;` with `if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }`.

## Step-by-Step Procedure

### 1. Inspect Current Version & Pending Changes
Read `src/bookvoice/__init__.py` and run:
```powershell
git status --short; git log -n 3 --oneline --decorate
```
Determine the next SemVer version (unless the user explicitly specified one):
- **Patch (`X.Y.(Z+1)`):** bug fixes, parser/pipeline tweaks, small polish.
- **Minor (`X.(Y+1).0`):** notable new features, CLI commands, GUI additions.

### 2. Bump Version
Update `__version__` in `src/bookvoice/__init__.py` to `"X.Y.Z"`.

### 3. Run Full CI Verification
Run lint, format check, and test suite:
```powershell
.venv\Scripts\python.exe -m ruff check .; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; .venv\Scripts\python.exe -m ruff format --check .; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; .venv\Scripts\python.exe -m pytest -q
```
- If `ruff format --check .` reports unformatted modified files, run `.venv\Scripts\python.exe -m ruff format <files>` and re-run `pytest -q`.
- Do **not** proceed to commit/tag if any check fails.

### 4. Stage, Commit, Tag, and Push
- Stage **only** the intentional release files (never `git add -A` or `git add .` blindly — ignore generated audiobook folders, `.work/`, or unrelated dirty files; verify with `git diff` if unsure):
  ```powershell
  git add src/bookvoice/__init__.py <other_changed_files>
  ```
- Commit, create an annotated tag, and push both `main` and the tag:
  ```powershell
  git commit -m "Release vX.Y.Z: <concise English summary of changes>"; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; git tag -a vX.Y.Z -m "Release vX.Y.Z"; git push origin main vX.Y.Z
  ```

### 5. Report to the User
Confirm briefly with:
- Version (`X.Y.Z`) and commit hash
- Tag (`vX.Y.Z`) and GitHub Release URL: `https://github.com/filipbiernat/bookvoice/releases/tag/vX.Y.Z`
- Verification summary (`pytest` count, `ruff check`, `ruff format`)
