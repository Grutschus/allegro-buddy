#!/bin/sh
# Live wall-time benchmark, Python allegro-buddy 2.7 vs bab, ON the cluster (one ssh session).
#
#   sh bench_live.sh OUTDIR          (in ~/.local/share/bab-bench, see bench/RESULTS.md)
#
# Read-only commands only (the allowlist of bench/live/commands.txt): never dev
# start/stop/login, l, --watch, --fix, completion --install. The reference is the
# private venv's console script, NEVER /usr/bin/ab (Apache Bench). Per command: one
# hyperfine call timing both tools, 1 warmup + 10 runs each, tool order alternating
# from command to command, >= 5 s pause between commands, a timeout per call.
set -eu
B=$HOME/.local/share/bab-bench
AB=$B/venv/bin/allegro-buddy
BAB=$B/bin/bab
HF=$B/bin/hyperfine
out=${1:?usage: bench_live.sh OUTDIR}
runs=${RUNS:-10}
pause=${PAUSE:-5}
mkdir -p "$out"

case $("$BAB" --version) in 'bab, version 2.7') ;; *) echo "unexpected bab" >&2; exit 1 ;; esac
case $("$AB" --version) in 'allegro-buddy, version 2.7') ;; *) echo "unexpected ab" >&2; exit 1 ;; esac

cache=${XDG_CACHE_HOME:-$HOME/.cache}/allegro-buddy/cluster-name.$(hostname)
pending=$(squeue -h -t PD -o '%i' | grep -v '[_[]' | head -n 1 || true)
nodes=$(sinfo -h -N -o '%N' | sort -u)
node=$(echo "$nodes" | grep -x gpu062 || echo "$nodes" | grep '^gpu' | head -n 1 || true)

{
    echo "host=$(hostname)"
    echo "date_start=$(date -Iseconds)"
    echo "loadavg_start=$(cut -d' ' -f1-3 /proc/loadavg)"
    echo "users_logged_in=$(who | cut -d' ' -f1 | sort -u | wc -l)"
    echo "jobs_total=$(squeue -h | wc -l)"
    echo "jobs_pending=$(squeue -h -t PD | wc -l)"
    echo "nodes=$(echo "$nodes" | wc -l)"
    echo "slurm=$(sinfo --version)"
    echo "cpu=$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | sed 's/^ //')"
    echo "nproc=$(nproc)"
    echo "kernel=$(uname -r)"
    echo "python=$("$B/venv/bin/python" -V 2>&1)"
    echo "ab=$("$AB" --version)"
    echo "bab=$("$BAB" --version)"
    echo "bab_sha256=$(sha256sum "$BAB" | cut -d' ' -f1)"
    echo "hyperfine=$("$HF" --version)"
    echo "pending_job=$pending"
    echo "node=$node"
    echo "runs=$runs"
} > "$out/env.txt"
cat "$out/env.txt"

i=0
bench() {  # bench NAME [--prepare CMD] -- ARGS...
    name=$1; shift
    prep=
    if [ "$1" = --prepare ]; then prep=$2; shift 2; fi
    shift  # --
    a="$AB $*"; b="$BAB $*"
    if [ $((i % 2)) -eq 0 ]; then first="-n ab"; c1=$a; second="-n bab"; c2=$b
    else first="-n bab"; c1=$b; second="-n ab"; c2=$a; fi
    i=$((i + 1))
    echo "== $name ($(date +%T))"
    # shellcheck disable=SC2086
    COLUMNS=160 timeout 180 "$HF" -N -w 1 -r "$runs" -i --style basic \
        ${prep:+--prepare "$prep"} --export-json "$out/$name.json" \
        $first "$c1" $second "$c2" 2>&1 | grep -E 'Time|±|faster|Benchmark' || true
    sleep "$pause"
}

bench version -- --version
bench help -- -h
bench info -- info
bench info-cold --prepare "rm -f $cache" -- info
bench free -- free
bench free-nodes -- free --nodes
bench q -- q
bench q-all -- q --all
bench why -- why
[ -n "$pending" ] && bench why-pending -- why "$pending"
[ -n "$node" ] && bench node -- node "$node"
bench job-history -- job history
bench config-show -- config show

{
    echo "date_end=$(date -Iseconds)"
    echo "loadavg_end=$(cut -d' ' -f1-3 /proc/loadavg)"
} >> "$out/env.txt"
echo done
