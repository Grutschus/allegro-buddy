//! Rich `ReprHighlighter` (Rich 15.0.0 `rich/highlighter.py`). Owned by P2-A.
//!
//! `Console.print("some str")` highlights by default (Console(highlight=True)): numbers,
//! strings in quotes, paths, URLs, UUIDs, ipv4/ipv6/eui48 ... get `repr.*` styles from
//! Rich's default theme. Python bab prints a few plain `str`s this way, e.g.
//! `CONSOLE.print(f'Canceled {ids}.')` (job ids are numbers) and the `--watch` header
//! `every 10s · 12:34:56 · Ctrl-C to quit` (`12:34:56` matches the ipv6 pattern, `10`
//! does not because of `\b`...: verify!). Port the regex list verbatim (order matters:
//! later matches restyle earlier ones, as `Text.highlight_regex` adds spans in order).

use super::text::Text;

/// Apply `ReprHighlighter` to `text` in place (Rich `Highlighter.__call__` -> `highlight`).
pub fn highlight_repr(text: &mut Text) {
    todo!()
}
