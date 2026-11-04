//! Differential test of the click/rich-click layer: replays tests/cli_ref/cases.json
//! (recorded from the Python reference by tests/cli_ref/gen.py) against the `bab` binary
//! with stubbed handlers (`BAB_TEST_STUB_HANDLERS=1`, a `test-hooks` feature hook that
//! `cargo test` turns on through the self dev-dependency in Cargo.toml).
//!
//! * `BAB_CLI_REF_PYTHON=/path/to/venv/bin/python cargo test --test cli_ref` regenerates
//!   the fixtures first (venv with allegro-buddy==2.7, click==8.3.2, rich==15.0.0,
//!   rich-click==1.9.9).
//! * `BAB_CLI_REF_FILTER=<substring>` runs only matching cases.

use serde_json::Value;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

/// Length of the per-case root directory (as in gen.py), so wrapped paths match.
const ROOT_LEN: usize = 64;

fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/cli_ref")
}

fn regenerate() {
    let Some(python) = std::env::var_os("BAB_CLI_REF_PYTHON") else {
        return;
    };
    let tmp = Path::new(env!("CARGO_TARGET_TMPDIR")).join("cli-ref-gen");
    std::fs::create_dir_all(&tmp).unwrap();
    let status = Command::new(&python)
        .arg(fixtures().join("gen.py"))
        .env("BAB_REF_PYTHON", &python)
        .env("BAB_GEN_TMP", &tmp)
        .status()
        .expect("run gen.py");
    assert!(status.success(), "gen.py failed");
}

struct Outcome {
    stdout: String,
    stderr: String,
    code: i32,
    files: Vec<(String, Option<String>)>,
}

fn run_case(case: &Value, index: usize) -> Outcome {
    let base = format!("{}/cli-ref/{index}", env!("CARGO_TARGET_TMPDIR"));
    assert!(
        base.len() < ROOT_LEN,
        "target dir path too long for the fixtures"
    );
    let root = PathBuf::from(format!("{base}{}", "_".repeat(ROOT_LEN - base.len())));
    let _ = std::fs::remove_dir_all(&root);
    std::fs::create_dir_all(root.join("home")).unwrap();
    let root_str = root.to_str().unwrap().to_owned();
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_bab"));
    cmd.env_clear()
        .current_dir(&root)
        .env("PATH", "/usr/bin:/bin")
        .env("HOME", root.join("home"))
        .env("XDG_CONFIG_HOME", root.join("config"))
        .env("XDG_CACHE_HOME", root.join("cache"))
        .env("AB_SITE_CONFIG", root.join("site/config.ini"))
        .env("AB_CLUSTER", "allegro")
        .env("USER", "alice")
        .env("LOGNAME", "alice")
        .env("LANG", "C.UTF-8")
        .env("TZ", "UTC");
    if case["stub"].as_bool().unwrap() {
        cmd.env("BAB_TEST_STUB_HANDLERS", "1");
    }
    for (key, value) in case["env"].as_object().unwrap() {
        let value = value.as_str().unwrap().replace("$ROOT", &root_str);
        if key == "BAB_GEN_RC" {
            std::fs::write(root.join("home/.bashrc"), value).unwrap();
        } else {
            cmd.env(key, value);
        }
    }
    if let Some(config) = case["config"].as_str() {
        let path = root.join("config/allegro-buddy/config.ini");
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, config).unwrap();
    }
    let argv: Vec<&str> = case["argv"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| a.as_str().unwrap())
        .collect();
    let mut child = cmd
        .args(&argv)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn bab");
    {
        use std::io::Write;
        let mut stdin = child.stdin.take().unwrap();
        let _ = stdin.write_all(case["stdin"].as_str().unwrap().as_bytes());
    }
    let out = child.wait_with_output().unwrap();
    let clean = |bytes: &[u8]| String::from_utf8_lossy(bytes).replace(&root_str, "$ROOT");
    let files = case["files"]
        .as_object()
        .unwrap()
        .keys()
        .map(|rel| {
            let content = std::fs::read_to_string(root.join(rel))
                .ok()
                .map(|c| clean(c.as_bytes()));
            (rel.clone(), content)
        })
        .collect();
    let _ = std::fs::remove_dir_all(&root);
    Outcome {
        stdout: clean(&out.stdout),
        stderr: clean(&out.stderr),
        code: out.status.code().unwrap_or(-1),
        files,
    }
}

#[test]
fn cli_matches_python_reference() {
    regenerate();
    let text = std::fs::read_to_string(fixtures().join("cases.json")).unwrap();
    let cases: Vec<Value> = serde_json::from_str(&text).unwrap();
    let filter = std::env::var("BAB_CLI_REF_FILTER").unwrap_or_default();
    let mut failures = Vec::new();
    let mut ran = 0;
    for (index, case) in cases.iter().enumerate() {
        let name = case["name"].as_str().unwrap();
        if !name.contains(&filter) {
            continue;
        }
        ran += 1;
        let got = run_case(case, index);
        let mut problems = Vec::new();
        if got.code != case["code"].as_i64().unwrap() as i32 {
            problems.push(format!("exit code {} != {}", got.code, case["code"]));
        }
        for (label, actual, expected) in [
            ("stdout", &got.stdout, case["stdout"].as_str().unwrap()),
            ("stderr", &got.stderr, case["stderr"].as_str().unwrap()),
        ] {
            if actual != expected {
                problems.push(format!(
                    "{label}:\n--- expected\n{expected:?}\n+++ got\n{actual:?}"
                ));
            }
        }
        for (rel, content) in &got.files {
            let expected = case["files"][rel].as_str();
            if content.as_deref() != expected {
                problems.push(format!(
                    "file {rel}: expected {expected:?}, got {content:?}"
                ));
            }
        }
        if !problems.is_empty() {
            failures.push(format!(
                "[{name}] argv={}\n{}",
                case["argv"],
                problems.join("\n")
            ));
        }
    }
    if !failures.is_empty() {
        let names: Vec<&str> = failures
            .iter()
            .map(|f| f.lines().next().unwrap_or_default())
            .collect();
        let shown: Vec<&str> = failures.iter().take(8).map(String::as_str).collect();
        panic!(
            "{} of {ran} cases differ:\n{}\n\n{}",
            failures.len(),
            names.join("\n"),
            shown.join("\n\n")
        );
    }
}
