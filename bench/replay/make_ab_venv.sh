#!/bin/sh
# The benchmark reference: a plain venv with allegro-buddy 2.7 (pinned like compat/),
# timed through its own console script `VENV/bin/ab`, plus the BAB_TEST_* hooks
# (ab_bench_hooks.py, active only when BAB_TEST_NOW is set).
#
#   sh bench/replay/make_ab_venv.sh VENV [PYTHON]      (default PYTHON: 3.12)
set -eu
venv=${1:?usage: make_ab_venv.sh VENV [PYTHON]}
python=${2:-3.12}
here=$(cd "$(dirname "$0")" && pwd)
uv venv -q --python "$python" "$venv"
uv pip install -q --python "$venv/bin/python" allegro-buddy==2.7 click==8.3.2 rich==15.0.0 \
    rich-click==1.9.9 markdown-it-py==4.0.0 mdurl==0.1.2 pygments==2.20.0 typing-extensions==4.15.0
site=$("$venv/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
cp "$here/ab_bench_hooks.py" "$site/"
echo "import os; os.environ.get('BAB_TEST_NOW') and __import__('ab_bench_hooks').install()" \
    > "$site/ab_bench_hooks.pth"
# byte-compile once, like a normal install, so no run pays for it
"$venv/bin/python" -m compileall -q "$site"
"$venv/bin/ab" --version
