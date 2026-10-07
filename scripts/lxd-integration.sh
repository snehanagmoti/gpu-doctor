#!/bin/sh
# Install a built gpu-doctor .deb into a fresh Ubuntu LXD container and check
# that it runs cleanly on a machine without a GPU.
#
#   ./scripts/lxd-integration.sh 24.04 ../build-area/gpu-doctor_0.1.0-1_all.deb
#
# LXD basics used here:
#   lxc launch ubuntu:24.04 NAME   create and start a system container
#   lxc file push FILE NAME/PATH   copy a file into it
#   lxc exec NAME -- CMD           run a command inside it (as root)
#   lxc delete --force NAME        stop and remove it
# A container shares the host kernel but has its own userspace, so it is a
# cheap, disposable "clean Ubuntu install" for testing packages.
set -eu

release=$1
deb=$2
name="gpu-doctor-test-$(echo "$release" | tr . -)-$$"

cleanup() { lxc delete --force "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT

lxc launch "ubuntu:$release" "$name"
# Wait until the container has booted and has network.
lxc exec "$name" -- cloud-init status --wait >/dev/null || true

lxc file push "$deb" "$name/tmp/gpu-doctor.deb"
# shellcheck disable=SC2016  # the script is meant to expand inside the container
lxc exec "$name" -- sh -eu -c '
    apt-get update -q
    apt-get install -y -q /tmp/gpu-doctor.deb
    gpu-doctor --version
    rc=0
    gpu-doctor --json > /tmp/out.json || rc=$?
    echo "exit status: $rc"
    python3 - <<EOF
import json
doc = json.load(open("/tmp/out.json"))
statuses = {c["id"]: c["status"] for c in doc["checks"]}
print(statuses)
assert not any(c["internal_error"] for c in doc["checks"]), "a check crashed"
# No GPU in a container: gpu_present fails and the GPU checks are skipped.
assert statuses["gpu_present"] == "fail", statuses
assert doc["exit_code"] == 2, doc["exit_code"]
EOF
    gpu-doctor --color never || true
'
echo "lxd-integration ($release): OK"
