//! Rich `Text`: a string with style spans. Owned by P2-A.
//!
//! # Semantics to replicate (Rich 15.0.0 `rich/text.py`)
//!
//! * `Text(plain, style=base)`: `style` is the BASE style applied under all spans (kept
//!   separate from spans: it also styles the padding Rich adds when justifying the text,
//!   e.g. inside table cells). Constructing strips control codes (`strip_control_codes`:
//!   BEL, BS, VT, FF, CR are removed).
//! * `append(str, style)` adds a span over the new characters (no span when style is
//!   empty/None). `append_text(text)` copies the other text's base style as a span over
//!   its range, then its spans (Rich `append_text`).
//! * `Text.assemble(*parts)`: parts are `str` (plain), `(str, style)` or `Text`
//!   ([`TextPart`]), appended in order onto an empty Text.
//! * `sep.join(texts)` (`Text(' · ').join(parts)`): like Rich `Text.join`.
//! * `len(text)` is the number of code points of `plain` ([`Text::len`]), NOT cells:
//!   `_render_free_by_node` packs lines by `len()`.
//! * Truthiness (`if line:`) is `len() > 0` ([`Text::is_empty`]).
//! * Rendering (`__rich_console__`): wrap to `options.max_width` with Rich's word wrapping
//!   (`Text.wrap` -> `divide_line`; words split at spaces, long words folded, trailing
//!   whitespace on wrapped lines handled exactly like Rich incl. `rstrip` of the line end),
//!   tabs expanded (tab_size 8), `justify` default = left without padding, then per line the
//!   segments of each style run (base style + all spans covering the run, combined in span
//!   order: Rich `Text.render`), with `end` (`"\n"`) handled by the console.
//!
//! Offsets: spans are in code points, like Rich. The implementation may keep byte offsets
//! internally if the public behaviour is identical.

use super::style::Style;
use super::{Justify, Measurement, RenderOptions, Renderable, Segment};

/// Rich `OverflowMethod`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
pub enum Overflow {
    #[default]
    Fold,
    Crop,
    Ellipsis,
    Ignore,
}

/// A styled range in code points `[start, end)` (Rich `Span`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Span {
    pub start: usize,
    pub end: usize,
    pub style: Style,
}

/// Rich `Text`.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Text {
    plain: String,
    spans: Vec<Span>,
    /// Base style (Rich `Text.style`).
    pub style: Style,
    pub justify: Option<Justify>,
    pub overflow: Option<Overflow>,
    pub no_wrap: Option<bool>,
}

/// One argument of [`Text::assemble`]: `str`, `(str, style)` or `Text`.
#[derive(Debug, Clone, PartialEq)]
pub enum TextPart {
    Plain(String),
    Styled(String, Style),
    Text(Text),
}

impl Text {
    /// `Text(plain)` (control codes stripped).
    pub fn new(plain: impl Into<String>) -> Text {
        todo!()
    }

    /// `Text(plain, style=definition)`; `definition` is a Rich style string.
    pub fn styled(plain: impl Into<String>, definition: &str) -> Text {
        todo!()
    }

    /// `Text(plain, style=style)`.
    pub fn with_style(plain: impl Into<String>, style: Style) -> Text {
        todo!()
    }

    /// `Text.assemble(*parts)`.
    pub fn assemble<I: IntoIterator<Item = TextPart>>(parts: I) -> Text {
        todo!()
    }

    /// `self.join(items)`: items separated by copies of `self`.
    pub fn join<I: IntoIterator<Item = Text>>(&self, items: I) -> Text {
        todo!()
    }

    /// The plain string.
    pub fn plain(&self) -> &str {
        &self.plain
    }

    pub fn spans(&self) -> &[Span] {
        &self.spans
    }

    /// `len(text)`: code points.
    pub fn len(&self) -> usize {
        todo!()
    }

    pub fn is_empty(&self) -> bool {
        self.plain.is_empty()
    }

    /// Terminal cells of the plain text (Rich `Text.cell_len`).
    pub fn cell_len(&self) -> usize {
        super::cells::cell_len(&self.plain)
    }

    /// `append(text, style)` with a style definition (`None`/empty: no span).
    pub fn append(&mut self, text: &str, style: Option<&str>) -> &mut Text {
        todo!()
    }

    /// `append(text, style)` with a parsed style.
    pub fn append_styled(&mut self, text: &str, style: Style) -> &mut Text {
        todo!()
    }

    /// `append_text(other)` / `append(other: Text)`.
    pub fn append_text(&mut self, other: &Text) -> &mut Text {
        todo!()
    }

    /// `stylize(style, start, end)`: add a span (code points, end clamped).
    pub fn stylize(&mut self, style: Style, start: usize, end: Option<usize>) -> &mut Text {
        todo!()
    }

    /// Rich `Text.wrap(console, width, justify, overflow, tab_size=8, no_wrap)` -> lines.
    pub fn wrap(
        &self,
        width: usize,
        justify: Option<Justify>,
        overflow: Option<Overflow>,
        no_wrap: bool,
    ) -> Vec<Text> {
        todo!()
    }

    /// Rich `Text.render(console, end="")` for ONE line: segments per style run.
    pub fn render_segments(&self) -> Vec<Segment> {
        todo!()
    }
}

impl From<&str> for Text {
    fn from(s: &str) -> Text {
        Text::new(s)
    }
}

impl From<String> for Text {
    fn from(s: String) -> Text {
        Text::new(s)
    }
}

impl From<&String> for Text {
    fn from(s: &String) -> Text {
        Text::new(s.as_str())
    }
}

impl From<&str> for TextPart {
    fn from(s: &str) -> TextPart {
        TextPart::Plain(s.to_owned())
    }
}

impl From<String> for TextPart {
    fn from(s: String) -> TextPart {
        TextPart::Plain(s)
    }
}

impl From<Text> for TextPart {
    fn from(t: Text) -> TextPart {
        TextPart::Text(t)
    }
}

/// `("text", "style definition")`.
impl From<(&str, &str)> for TextPart {
    fn from((s, style): (&str, &str)) -> TextPart {
        TextPart::Styled(s.to_owned(), Style::of(style))
    }
}

/// `(f"...", "style definition")`.
impl From<(String, &str)> for TextPart {
    fn from((s, style): (String, &str)) -> TextPart {
        TextPart::Styled(s, Style::of(style))
    }
}

impl Renderable for Text {
    fn render_lines(&self, console: &super::Console, options: &RenderOptions) -> Vec<Vec<Segment>> {
        todo!()
    }

    fn measure(&self, console: &super::Console, options: &RenderOptions) -> Measurement {
        todo!("Rich Text.__rich_measure__: max line cells / longest word")
    }
}
