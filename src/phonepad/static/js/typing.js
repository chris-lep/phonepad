// Live typing (ADR-0007): the text field is diffed against what was already sent, and the
// difference goes out as "press Backspace n times, then type this". Pure, unit-tested in
// tests/js/typing.test.js.

/** Invisible marker in front of the text, so Backspace on an empty field is detectable. */
export const SENTINEL = "​";

const segmenter =
  typeof Intl !== "undefined" && Intl.Segmenter
    ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
    : null;

/** User-perceived characters (grapheme clusters); code points as a fallback. */
export function graphemes(text) {
  if (segmenter) return Array.from(segmenter.segment(text), (s) => s.segment);
  return Array.from(text);
}

/** The edit that turns `before` into `after`, keeping their common prefix. */
export function diff(before, after) {
  const a = graphemes(before);
  const b = graphemes(after);
  let common = 0;
  while (common < a.length && common < b.length && a[common] === b[common]) common += 1;
  return { backspace: a.length - common, insert: b.slice(common).join("") };
}

/** Tracks the text already typed on the laptop for one text field. */
export class TypingBuffer {
  constructor() {
    this.sent = "";
  }

  /** The value the field should show for an empty buffer. */
  get emptyField() {
    return SENTINEL;
  }

  /**
   * The field changed to `value`.
   * Returns `edit` (null if nothing to send) and `field` (a value to put back into the field,
   * or null to leave it).
   */
  input(value) {
    let text = value;
    let field = null;
    let extraBackspace = 0;
    if (text.startsWith(SENTINEL)) {
      text = text.slice(SENTINEL.length);
    } else {
      // The marker was deleted. With nothing typed, that is Backspace on an empty field.
      if (text === "" && this.sent === "") extraBackspace = 1;
      text = text.replaceAll(SENTINEL, "");
      field = SENTINEL + text;
    }
    const change = diff(this.sent, text);
    change.backspace += extraBackspace;
    this.sent = text;
    const edit = change.backspace || change.insert ? change : null;
    return { edit, field };
  }

  /** Forget the text (the laptop's text cursor may have moved). */
  reset() {
    this.sent = "";
  }
}
