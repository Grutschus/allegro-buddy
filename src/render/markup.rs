//! Rich console markup (`rich.markup.render`). Owned by P2-A.
//!
//! Plain `str` values printed with `Console.print(str)` or used as `Table` cells go
//! through `Console.render_str(text, markup=True, highlight=...)` in Rich: markup tags like
//! `[bold]x[/bold]` become styles, `\[` escapes a bracket, and text that is not a tag
//! (`[0-3]`, `[123]`) stays literal. Tag regex (Rich 15): `((\\*)\[([a-z#/@][^[]*?)])`.
//! A closing tag without an open one raises `MarkupError` in Rich (bab mirrors the message
//! if a reachable input can trigger it; e.g. a job name `[/x]` in a str table cell).
//!
//! bab passes `str` (not `Text`) exactly where Python does, so job names, node lists etc.
//! that Python renders through markup are rendered through markup here too.

use super::style::Style;
use super::text::Text;

/// Rich `MarkupError` message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MarkupError(pub String);

/// Rich `render(markup, style=base_style, emoji=False)` -> `Text`.
pub fn render(markup: &str, base_style: Style) -> Result<Text, MarkupError> {
    todo!()
}
