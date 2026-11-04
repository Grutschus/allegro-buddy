//! Rich `RegexHighlighter` / `ReprHighlighter` (rich/highlighter.py).
//!
//! `Console.print("some str")` highlights by default (Console(highlight=True)): numbers,
//! quoted strings, paths, URLs, UUIDs, ipv4/ipv6/eui48 ... get `repr.*` styles from Rich's
//! default theme. Table cells are not highlighted (Table(highlight=False)). The patterns
//! below are Rich 15's, verbatim except for escaping `[`/`]` inside character classes
//! (Rust regex syntax); `fancy_regex` provides the lookbehinds.

use super::text::Text;
use super::theme::Theme;
use fancy_regex::Regex;
use std::sync::{LazyLock, OnceLock};

/// One highlight pattern, compiled on first use (Rich's patterns are expensive to compile
/// and most strings bab prints need only some of them).
#[derive(Debug)]
struct Pattern {
    source: String,
    compiled: OnceLock<Regex>,
    /// Cheap test that the pattern cannot match when false.
    may_match: fn(&str) -> bool,
    /// (group name, max code points): emulates `[\w_]{1,50}` without its compile cost.
    trim_group: Option<(&'static str, usize)>,
}

fn always(_: &str) -> bool {
    true
}

/// Rich `RegexHighlighter`: each regex adds `base_style + group name` spans, in order.
#[derive(Debug)]
pub struct RegexHighlighter {
    patterns: Vec<Pattern>,
    pub base_style: String,
}

impl RegexHighlighter {
    /// Compile `patterns` (Python `re` syntax that `fancy_regex` understands).
    pub fn new(
        base_style: &str,
        patterns: &[&str],
    ) -> Result<RegexHighlighter, fancy_regex::Error> {
        let mut out = Vec::with_capacity(patterns.len());
        for p in patterns {
            let compiled = OnceLock::new();
            let _ = compiled.set(Regex::new(p)?);
            out.push(Pattern {
                source: (*p).to_owned(),
                compiled,
                may_match: always,
                trim_group: None,
            });
        }
        Ok(RegexHighlighter {
            patterns: out,
            base_style: base_style.to_owned(),
        })
    }

    /// Rich `RegexHighlighter.highlight(text)` (in place).
    pub fn highlight(&self, text: &mut Text, theme: &Theme) {
        for pattern in &self.patterns {
            if !(pattern.may_match)(text.plain()) {
                continue;
            }
            let re = pattern
                .compiled
                .get_or_init(|| Regex::new(&pattern.source).expect("highlight pattern"));
            let before = text.spans().len();
            text.highlight_regex(re, &self.base_style, theme);
            if let Some((group, max)) = pattern.trim_group {
                let style = theme.get_style_or_null(&format!("{}{group}", self.base_style));
                for span in &mut text.spans_mut()[before..] {
                    if span.style == style && span.end - span.start > max {
                        span.start = span.end - max;
                    }
                }
            }
        }
    }
}

fn has_any(text: &str, chars: &[char]) -> bool {
    text.contains(chars)
}

static REPR: LazyLock<RegexHighlighter> = LazyLock::new(|| {
    let combined = [
        r"(?P<ipv4>[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})",
        r"(?P<ipv6>([A-Fa-f0-9]{1,4}::?){1,7}[A-Fa-f0-9]{1,4})",
        r"(?P<eui64>(?:[0-9A-Fa-f]{1,2}-){7}[0-9A-Fa-f]{1,2}|(?:[0-9A-Fa-f]{1,2}:){7}[0-9A-Fa-f]{1,2}|(?:[0-9A-Fa-f]{4}\.){3}[0-9A-Fa-f]{4})",
        r"(?P<eui48>(?:[0-9A-Fa-f]{1,2}-){5}[0-9A-Fa-f]{1,2}|(?:[0-9A-Fa-f]{1,2}:){5}[0-9A-Fa-f]{1,2}|(?:[0-9A-Fa-f]{4}\.){2}[0-9A-Fa-f]{4})",
        r"(?P<uuid>[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})",
        r"(?P<call>[\w.]*?)\(",
        r"\b(?P<bool_true>True)\b|\b(?P<bool_false>False)\b|\b(?P<none>None)\b",
        r"(?P<ellipsis>\.\.\.)",
        r"(?P<number_complex>(?<!\w)(?:\-?[0-9]+\.?[0-9]*(?:e[-+]?\d+?)?)(?:[-+](?:[0-9]+\.?[0-9]*(?:e[-+]?\d+)?))?j)",
        r"(?P<number>(?<!\w)\-?[0-9]+\.?[0-9]*(e[-+]?\d+?)?\b|0x[0-9a-fA-F]*)",
        r"(?P<path>\B(/[-\w._+]+)*\/)(?P<filename>[-\w._+]*)?",
        r#"(?<![\\\w])(?P<str>b?'''.*?(?<!\\)'''|b?'.*?(?<!\\)'|b?""".*?(?<!\\)"""|b?".*?(?<!\\)")"#,
        r"(?P<url>(file|https|http|ws|wss)://[-0-9a-zA-Z$_+!`(),.?/;:&=%#~@]*)",
    ]
    .join("|");
    let pattern = |source: &str, may_match: fn(&str) -> bool, trim_group| Pattern {
        source: source.to_owned(),
        compiled: OnceLock::new(),
        may_match,
        trim_group,
    };
    RegexHighlighter {
        base_style: "repr.".to_owned(),
        patterns: vec![
            pattern(
                r"(?P<tag_start><)(?P<tag_name>[-\w.:|]*)(?P<tag_contents>[\w\W]*)(?P<tag_end>>)",
                |t| t.contains('<') && t.contains('>'),
                None,
            ),
            // Rich: `(?P<attrib_name>[\w_]{1,50})=...`; a longer run of word characters
            // before `=` matches only its last 50 (the span is trimmed accordingly).
            pattern(
                r#"(?P<attrib_name>[\w_]+)=(?P<attrib_value>"?[\w_]+"?)?"#,
                |t| t.contains('='),
                Some(("attrib_name", 50)),
            ),
            pattern(
                r"(?P<brace>[\]\[{}()])",
                |t| has_any(t, &['[', ']', '{', '}', '(', ')']),
                None,
            ),
            pattern(&combined, combined_may_match, None),
        ],
    }
});

/// False only when no alternative of Rich's combined repr regex can match.
fn combined_may_match(t: &str) -> bool {
    t.bytes()
        .any(|b| b.is_ascii_digit() || matches!(b, b'(' | b':' | b'/' | b'\'' | b'"'))
        || t.matches('-').count() >= 4
        || t.matches('.').count() >= 2
        || t.contains("True")
        || t.contains("False")
        || t.contains("None")
}

/// Rich `ReprHighlighter`.
pub fn repr_highlighter() -> &'static RegexHighlighter {
    &REPR
}

/// Apply `ReprHighlighter` to `text` in place (Rich `Highlighter.__call__` -> `highlight`).
pub fn highlight_repr(text: &mut Text) {
    REPR.highlight(text, &Theme::default());
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::render::style::Style;

    fn styled(s: &str) -> Vec<(String, Style)> {
        let mut t = Text::new(s);
        highlight_repr(&mut t);
        t.spans()
            .iter()
            .map(|sp| {
                (
                    s.chars().skip(sp.start).take(sp.end - sp.start).collect(),
                    sp.style,
                )
            })
            .collect()
    }

    #[test]
    fn numbers_and_clock() {
        let number = Style::of("bold cyan not italic");
        let spans = styled("Canceled 123, 456_7.");
        assert_eq!(spans[0], ("123".to_owned(), number));
        let spans = styled("every 10s · 12:34:56 · Ctrl-C to quit");
        assert!(spans.iter().any(|(s, _)| s == "12:34:56"));
        assert!(!spans.iter().any(|(s, _)| s == "10"));
    }

    #[test]
    fn strings_and_paths() {
        let spans = styled("see '/tmp/x.txt' now");
        assert!(spans.iter().any(|(s, _)| s == "'/tmp/x.txt'"));
        assert_eq!(spans.len(), 1);
    }
}
