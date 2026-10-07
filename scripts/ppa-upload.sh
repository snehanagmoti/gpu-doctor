#!/bin/sh
# Build signed source packages for each Ubuntu series and upload them to the
# Launchpad PPA with dput. Launchpad builds the binary .debs itself.
#
#   ./scripts/ppa-upload.sh [PPA_REVISION] [SERIES...]
#   ./scripts/ppa-upload.sh 1 jammy noble        (the default)
#
# One-time setup (see docs/packaging.md): a Launchpad account, a GPG key
# uploaded to keyserver.ubuntu.com and added to Launchpad, and a PPA called
# "gpu-doctor" created at https://launchpad.net/~snehanagmoti/+activate-ppa
set -eu

PPA=${PPA:-ppa:snehanagmoti/gpu-doctor}
revision=${1:-1}
[ $# -gt 0 ] && shift
series=${*:-jammy noble}

cd "$(dirname "$0")/.."
out=$(realpath -m ../ppa-build)
first=1
for s in $series; do
    # Only the first upload of a new upstream version carries the orig
    # tarball (-sa); later ones reference the copy Launchpad already has.
    opts="-S -d"
    [ "$first" = 1 ] && opts="-S -sa -d"
    first=0
    SIGN=1 PPA_SERIES="$s" PPA_REVISION="$revision" DPKG_BUILDPACKAGE_OPTS="$opts" \
        ./scripts/build-deb.sh "$out"
    changes=$(ls -t "$out"/gpu-doctor_*~"$s"*_source.changes 2>/dev/null | head -n 1 || true)
    [ -n "$changes" ] || changes=$(ls -t "$out"/gpu-doctor_*_source.changes | head -n 1)
    echo "== dput $PPA $changes"
    dput "$PPA" "$changes"
done
