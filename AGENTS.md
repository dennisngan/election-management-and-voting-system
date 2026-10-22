# Project agent instructions

## Subagent delegation

For large tasks, the main agent may delegate small, independent, clearly
bounded work to `luna_worker`.

Suitable work includes:

- Small bug fixes
- Focused refactoring
- Tests
- Documentation
- Log analysis
- Configuration-file changes

The main agent must retain architectural decisions, wait for the worker,
review its changes, and independently verify the result.

## Agent skills

### Issue tracker

Track specs and tickets as local Markdown under `.scratch/`. For publication, numbering, and updates, read `docs/agents/issue-tracker.md`.

### Triage labels

Use the configured triage vocabulary when setting issue status. Read `docs/agents/triage-labels.md` for role-to-label mappings.

### Domain docs

Use the existing single-context glossary and ADRs. Before domain exploration or implementation, read `docs/agents/domain.md`.
