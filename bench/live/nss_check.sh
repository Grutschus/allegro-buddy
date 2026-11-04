#!/bin/sh
# NSS check on the cluster: bab's user/groups (examples/nss_groups, same code as bab)
# vs Python's allegro_buddy.core.current_groups() vs `id -Gn`. Exit 1 on a mismatch.
#   nss_check.sh VENV/bin/python BIN/nss_groups
set -eu
unset BAB_TEST_GROUPS BAB_TEST_HOSTNAME  # examples link the test-hooks build (dev-dependency)
py=$1 nss=$2
id -Gn | tr ' ' '\n' | sort >id.groups.$$
"$py" -c 'from allegro_buddy.core import current_groups, current_user
print("user", current_user())
for g in sorted(current_groups()): print("group", g)' >py.groups.$$
"$nss" >bab.groups.$$
status=0
if cmp -s py.groups.$$ bab.groups.$$; then echo "bab == python: $(grep -c ^group bab.groups.$$) groups"
else echo "bab != python:"; diff py.groups.$$ bab.groups.$$ || true; status=1; fi
if sed -n 's/^group //p' py.groups.$$ | cmp -s - id.groups.$$; then echo "python == id -Gn"
else echo "python != id -Gn:"; sed -n 's/^group //p' py.groups.$$ | diff - id.groups.$$ || true; fi
rm -f id.groups.$$ py.groups.$$ bab.groups.$$
exit $status
