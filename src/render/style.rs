//! Rich `Style` subset: parsing style definitions, combining, and SGR rendering.
//!
//! # What bab needs
//!
//! Definitions used by allegro-buddy: `bold`, `dim`, `bold red`, `bold yellow`,
//! `bold green`, `bold blue`, `bold cyan`, `green`, `yellow`, `blue`, `red`, `cyan`,
//! `magenta`, `white`, plus whatever the rich-click `modern` theme and the
//! `ReprHighlighter` theme (`repr.number` = `bold cyan` not italic..., check Rich's
//! `DEFAULT_STYLES`) use. Implement Rich's full grammar anyway (`not bold`, `on <color>`,
//! `#rrggbb`, `rgb(r,g,b)`, `color(n)`, `bright_*`, `link`-less), since rich-click themes
//! and `RICH_CLICK_THEME` can bring any of it.
//!
//! # Exact Rich semantics to replicate
//!
//! * Attributes are a bitmask with a "set" mask (Rich `_attributes` / `_set_attributes`), so
//!   `not bold` can switch bold off when combining. Bit order (Rich `_style_map`):
//!   bold=1, dim=2, italic=3, underline=4, blink=5, blink2=6, reverse=7, conceal=8,
//!   strike=9, underline2=21, frame=51, encircle=52, overline=53. SGR codes are emitted in
//!   that order, then the foreground colour, then the background colour, joined by `;`.
//! * Standard colours 0-7: fg `30+n`, bg `40+n`; bright 8-15: fg `82+n` (90..97), bg
//!   `92+n`; 8-bit: `38;5;n` / `48;5;n`; truecolor: `38;2;r;g;b`. Downgrade by colour
//!   system as Rich `Color.downgrade` does (only relevant with `COLORTERM`/256-colour TERM).
//! * `Style.render(text)` = `ESC[{codes}m{text}ESC[0m`; a style with no codes renders
//!   the text unchanged. With `NO_COLOR` set, colours are stripped but attributes kept
//!   (Rich `Style.without_color` applied by the console).
//! * `a + b` (Rich `Style.__add__`, here [`Style::combine`]): `b`'s set attributes and
//!   colours override `a`'s.

/// Rich `ColorSystem` (Console.color_system). `None` at the console level = no colour.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ColorSystem {
    Standard,
    EightBit,
    TrueColor,
}

/// Rich `Color` subset.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Color {
    /// `default` (SGR 39/49).
    Default,
    /// Standard + bright colours, 0..=15 (`red` = 1, `bright_red` = 9).
    Standard(u8),
    /// `color(n)` / named 256-palette colours, 16..=255.
    EightBit(u8),
    /// `#rrggbb` / `rgb(r,g,b)`.
    TrueColor(u8, u8, u8),
}

/// An immutable, `Copy` style (Rich `Style` without links/meta).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
pub struct Style {
    /// Attribute bits (see module docs for the bit numbering).
    pub attributes: u16,
    /// Which attribute bits are set (on or explicitly off).
    pub set_attributes: u16,
    pub color: Option<Color>,
    pub bgcolor: Option<Color>,
}

/// Error for an invalid style definition (Rich `StyleSyntaxError`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StyleSyntaxError(pub String);

impl Style {
    /// The null style (renders text unchanged).
    pub const NULL: Style = Style {
        attributes: 0,
        set_attributes: 0,
        color: None,
        bgcolor: None,
    };

    /// Parse a Rich style definition such as `"bold red"`, `"dim"`, `"on blue"`,
    /// `"not italic #ff0000"`. Empty string / `"none"` -> [`Style::NULL`].
    pub fn parse(definition: &str) -> Result<Style, StyleSyntaxError> {
        todo!()
    }

    /// Parse a definition that is a compile-time constant in bab; panics on bad syntax.
    /// Implementations may memoize (styles are parsed in hot loops for table cells).
    pub fn of(definition: &str) -> Style {
        Style::parse(definition).unwrap_or_else(|e| panic!("bad style {definition:?}: {e:?}"))
    }

    pub fn is_null(&self) -> bool {
        *self == Style::NULL
    }

    /// Rich `self + other`: `other` wins where it sets something.
    pub fn combine(&self, other: &Style) -> Style {
        todo!()
    }

    /// Rich `Style.without_color` (for `NO_COLOR`).
    pub fn without_color(&self) -> Style {
        todo!()
    }

    /// SGR parameter string (`"1;31"`) for the given colour system; empty if nothing to emit.
    pub fn sgr_codes(&self, color_system: ColorSystem) -> String {
        todo!()
    }

    /// Rich `Style.render(text, color_system=...)`: `ESC[{codes}mtextESC[0m`, or `text`
    /// when `color_system` is `None` or there are no codes.
    pub fn render(&self, text: &str, color_system: Option<ColorSystem>) -> String {
        todo!()
    }
}
