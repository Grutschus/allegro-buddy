#!/bin/sh
# Final local comparison on the replay (see bench/RESULTS.md): Python allegro-buddy 2.7
# (venv console script from replay/make_ab_venv.sh, BAB_TEST_* hooks via .pth) vs bab
# (release, --features test-hooks), both pinned to the same CPUs.
#
#   sh bench/run_local.sh AB_VENV BAB_HOOKS_BIN BAB_PLAIN_BIN [OUT]
set -eu
venv=${1:?usage: run_local.sh AB_VENV BAB_HOOKS_BIN BAB_PLAIN_BIN [OUT]}
bab=$(realpath "$2")
plain=$(realpath "$3")
here=$(cd "$(dirname "$0")" && pwd)
out=$(realpath -m "${4:-$here/results/local}")
cpus=${CPUS:-4-7}
runs=${RUNS:-6}
rounds=${ROUNDS:-5}
hf=$(command -v hyperfine || echo /srv/public/plainer/rust/cargo/bin/hyperfine)
ab=$venv/bin/ab
mkdir -p "$out"

{
    echo "host=$(hostname)"
    echo "date=$(date -Iseconds)"
    echo "cpu=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | sed 's/^ //')"
    echo "nproc=$(nproc)"
    echo "governor=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)"
    echo "pinned_cpus=$cpus"
    echo "loadavg=$(cut -d' ' -f1-3 /proc/loadavg)"
    echo "kernel=$(uname -r)"
    echo "glibc=$(ldd --version | head -n 1)"
    echo "commit=$(git -C "$here" rev-parse HEAD)"
    echo "rustc=$(rustc --version 2>/dev/null || echo '?')"
    echo "python=$("$venv/bin/python" -V 2>&1)"
    echo "ab=$("$ab" --version)"
    echo "packages=$("$venv/bin/python" -c 'import importlib.metadata as m; print(" ".join(f"{d}=={m.version(d)}" for d in ("allegro-buddy","click","rich","rich-click","pygments","markdown-it-py")))')"
    echo "bab=$("$bab" --version) (test-hooks, sha256 $(sha256sum "$bab" | cut -c1-16))"
    echo "bab_plain=$("$plain" --version) (sha256 $(sha256sum "$plain" | cut -c1-16))"
    echo "hyperfine=$("$hf" --version)"
    echo "runs=$runs rounds=$rounds"
} > "$out/env.txt"
cat "$out/env.txt"

# Hook overhead: the same commands with the BAB_TEST_* hooks active and inactive
# (--version / -h do not depend on clock, groups or host name; both sides go through env).
hooks="BAB_TEST_NOW=2026-11-04T18:52:00 BAB_TEST_GROUPS=a,b BAB_TEST_HOSTNAME=allegro"
mkdir -p "$out/hooks"
for args in --version -h; do
    name=$(echo "$args" | tr -d -)
    taskset -c "$cpus" "$hf" -N -w 5 -r 40 --style none --export-json "$out/hooks/ab-$name.json" \
        -n "ab $args (no hooks)" "env $ab $args" \
        -n "ab $args (hooks)" "env $hooks $ab $args"
    taskset -c "$cpus" "$hf" -N -w 5 -r 40 --style none --export-json "$out/hooks/bab-$name.json" \
        -n "bab $args (plain build)" "env $plain $args" \
        -n "bab $args (test-hooks build, hooks set)" "env $hooks $bab $args"
done

bench() {  # bench NAME [bench.py args...]
    name=$1; shift
    echo "== $name"
    python3 "$here/replay/bench.py" --cpus "$cpus" --bin "bab=$bab" --bin "ab=$ab" \
        --runs "$runs" --rounds "$rounds" --warmup 3 --out "$here/replay/.work/final" \
        --json "$out/$name.json" --export-dir "$out/$name.raw" "$@"
}
bench nodelay
bench realtime --realtime
bench info-cold-nodelay --cold-cache -k '^info$'
bench info-cold-realtime --cold-cache --realtime -k '^info$'
user=$here/data/allegro/as-user-a
bench as-user-a-nodelay --data "$user"
bench as-user-a-realtime --data "$user" --realtime
echo "date_end=$(date -Iseconds)" >> "$out/env.txt"
