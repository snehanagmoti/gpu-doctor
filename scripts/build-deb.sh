#!/bin/sh
# Build the Debian source and binary packages from the committed tree, then
# run lintian on the result.
#
#   ./scripts/build-deb.sh [OUTPUT_DIR]            (default: ../build-area)
#
# Environment:
#   DPKG_BUILDPACKAGE_OPTS  extra options, e.g. "-S -sa" for a source-only
#                           upload that includes the orig tarball
#   SIGN=1                  sign with your GPG key (needed for Launchpad)
#   PPA_SERIES=jammy        rewrite the version and distribution for a PPA
#   PPA_REVISION=1          upload: 0.1.0-1~ppa1~22.04 (see
#                           docs/packaging.md for why it looks like that)
#
# The package uses the "3.0 (quilt)" source format, so it needs an upstream
# tarball (gpu-doctor_<version>.orig.tar.gz) that does not contain debian/.
# It is generated with `git archive`, which only includes committed files:
# commit your changes first.
set -eu

cd "$(dirname "$0")/.."
version=$(dpkg-parsechangelog -S Version)
upstream=${version%-*}
out=$(realpath -m "${1:-../build-area}")
src="$out/gpu-doctor-$upstream"

mkdir -p "$out"
rm -rf "$src"

# Upstream tarball: everything except the packaging. Keep an existing one:
# every upload of the same upstream version must use byte-identical tarballs.
orig="$out/gpu-doctor_$upstream.orig.tar.gz"
if [ ! -f "$orig" ]; then
    git archive --format=tar --prefix="gpu-doctor-$upstream/" HEAD -- . ':(exclude)debian' \
        | gzip -n -9 > "$orig"
fi
tar -xzf "$orig" -C "$out"
git archive --format=tar HEAD debian | tar -x -C "$src"

if [ -n "${PPA_SERIES:-}" ]; then
    case "$PPA_SERIES" in
        jammy) release=22.04 ;;
        noble) release=24.04 ;;
        *) echo "unsupported series: $PPA_SERIES" >&2; exit 3 ;;
    esac
    # 0.1.0-1~ppa1~22.04: "~" sorts before everything, so a PPA build is
    # older than the same version from the archive, and the 22.04 build is
    # older than the 24.04 one, so release upgrades also upgrade the package.
    # (No "ubuntu" in the version: that marks uploads by Ubuntu developers.
    # No second dot in the revision: lintian would read it as a binNMU.)
    version="$version~ppa${PPA_REVISION:-1}~$release"
    (cd "$src" && dch --force-bad-version --maintmaint --force-distribution \
        --distribution "$PPA_SERIES" --newversion "$version" \
        "PPA build for Ubuntu $release ($PPA_SERIES).")
fi

sign="-us -uc"
[ "${SIGN:-0}" = 1 ] && sign=""
# shellcheck disable=SC2086  # options are meant to be word-split
(cd "$src" && dpkg-buildpackage $sign ${DPKG_BUILDPACKAGE_OPTS:-})

changes=$(ls -t "$out"/gpu-doctor_"${version}"_*.changes | head -n 1)
echo "== lintian $changes"
lintian --info --display-info --pedantic --fail-on error,warning "$changes"
echo "== built $changes"
