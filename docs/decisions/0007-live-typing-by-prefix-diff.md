---
status: accepted
date: 2026-11-20
decision-makers: project owner
---

# Live typing as "backspaces + insert" from a prefix diff

## Context and Problem Statement

The owner wants characters to appear on the laptop while typing. Phone keyboards change text
after it was typed (autocorrect, predictions, dictation, composition on Android), and key
events from software keyboards are unreliable (Android often reports "Unidentified").

## Considered Options

- Diff the text field against the last sent value: common prefix, then n backspaces + insert
- Forward key events
- Compose on the phone, then send

## Decision Outcome

Chosen option: "prefix diff", counted in grapheme clusters (`Intl.Segmenter`), because the
laptop then always ends with the field's text, whatever the keyboard did. An invisible marker in front of
the text detects Backspace on an empty field. The field is cleared when the laptop's text cursor
may have moved (clicks, Enter, special keys).

### Consequences

- Bad, because an autocorrection near the start of a long word or sentence resends the rest of
  it; clearing on Enter keeps that short.
