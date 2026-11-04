//! Rich `Segment`: a run of text with one style, plus the line helpers tables need
//! (`Segment.split_and_crop_lines`, `Segment.adjust_line_length`, `Segment.set_shape`,
//! `Segment.divide`, `Segment.simplify` where Rich uses them). Owned by P2-A.

use super::style::Style;

/// Text with an optional style. Rich segments with a null style render as plain text.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Segment {
    pub text: String,
    pub style: Option<Style>,
}

impl Segment {
    pub fn plain(text: impl Into<String>) -> Self {
        Segment {
            text: text.into(),
            style: None,
        }
    }

    pub fn styled(text: impl Into<String>, style: Style) -> Self {
        Segment {
            text: text.into(),
            style: Some(style),
        }
    }

    /// Terminal cells this segment occupies.
    pub fn cell_len(&self) -> usize {
        super::cells::cell_len(&self.text)
    }
}

/// Rich `Segment.adjust_line_length(line, length, style, pad=True)`: crop or pad (with
/// spaces in `pad_style`) a line to exactly `length` cells.
pub fn adjust_line_length(
    line: Vec<Segment>,
    length: usize,
    pad_style: Option<Style>,
    pad: bool,
) -> Vec<Segment> {
    todo!()
}

/// Total cells of a line.
pub fn line_cell_len(line: &[Segment]) -> usize {
    line.iter().map(Segment::cell_len).sum()
}
