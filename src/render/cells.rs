//! Terminal cell widths (Rich `rich.cells`). Owned by P2-A.
//!
//! Rich 15 computes `cell_len` from its own table (`rich._cell_widths`, wcwidth-like:
//! 0 for combining/zero-width, 2 for East Asian wide/fullwidth, 1 otherwise; ambiguous
//! width counts as 1). Use `unicode-width` (`UnicodeWidthChar::width`, NOT `width_cjk`)
//! and check every non-ASCII character bab prints against Rich's table: `ⓘ` `·` `…` `→`
//! `≤` `─` (box) and the spinner frames. Control characters count 0 in Rich.

/// Rich `cell_len(text)`.
pub fn cell_len(text: &str) -> usize {
    todo!()
}

/// Rich `get_character_cell_size(ch)`.
pub fn char_width(ch: char) -> usize {
    todo!()
}

/// Rich `set_cell_size(text, total)`: crop (never splitting a wide char; pad with a space
/// if needed) or pad with spaces to exactly `total` cells.
pub fn set_cell_size(text: &str, total: usize) -> String {
    todo!()
}

/// Rich `chop_cells(text, width)`: split into pieces of at most `width` cells (used by
/// `fold` overflow when a single word is longer than the line).
pub fn chop_cells(text: &str, width: usize) -> Vec<String> {
    todo!()
}
