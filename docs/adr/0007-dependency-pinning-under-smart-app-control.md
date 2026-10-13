# ADR 0007: Pin mature dependency releases that load under Windows Smart App Control

**Status:** accepted · **Date:** 2026-10-13

## Context
The development laptop runs Windows Smart App Control, which blocks unsigned native binaries
without reputation. The newest wheels at the time (numpy 2.5.4, SQLAlchemy 2.1.4) were blocked
("An Application Control policy has blocked this file"), as were uv-created virtualenv launchers.

## Decision
Pin widely distributed releases that loaded cleanly: numpy 2.3.3, pandas 2.3.3, SciPy 1.16.2,
scikit-learn 1.7.2, SQLAlchemy 2.0.44 (all with Python 3.12–3.14 wheels). Create virtualenvs with
`py -m venv`. Frontend tooling (Vite 8, Vitest 5, Tailwind 4) loaded without issues; TypeScript is
pinned to 6.0.3 because typescript-eslint supports < 6.1.

## Consequences
+ Works on locked-down Windows machines without disabling a security feature.
− Not the newest releases; Dependabot proposals must be checked on such a machine before merging.