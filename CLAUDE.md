@AGENTS.md

## Claude Code specifics

- Never inject real input into the developer's desktop from tests or experiments (it could type into
  the terminal). Use `--record-input`, the recording backend, or `make xtest` (nested Xephyr).
- Independent reviews (when the owner asks): `fable-reviewer` subagent; record the outcome
  and what was fixed in `docs/worklog.md`.
