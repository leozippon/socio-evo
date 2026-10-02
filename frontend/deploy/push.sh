#!/usr/bin/env bash
# Upload a published site to a web server with ssh and tar only, and switch it in atomically.
#
#   frontend/deploy/push.sh HOST SITE [ROOT]
#
# HOST is an ssh destination, SITE the directory `python -m frontend.publish` wrote, and ROOT
# the directory on the server that holds the site, /opt/socio-evo by default; the ssh user
# must be able to write there. The server needs a POSIX shell, tar, find, sed and GNU
# coreutils.
#
# On the server ROOT/site is a symbolic link to the current release, ROOT/releases/<stamp>.
# A push reads the checksums of the current release and uploads only the files that differ.
# The new release is assembled beside the current one: unchanged files are hard links to the
# same data and uploaded files are renamed into place, so nothing in the current release is
# ever written to. Once every file of the new release matches the checksums of SITE, the link
# is replaced by a single rename: a browser sees the old site or the new one, never a mix.
# The previous release is kept and older ones are removed. Run one push at a time, and not
# while a publish is writing SITE.
#
# PUSH_SSH (default `ssh`, options allowed) is the command that runs a shell command on HOST;
# a command that runs it locally instead pushes into a local ROOT, which is how it is tested.
set -euo pipefail
export LC_ALL=C

if [ $# -lt 2 ] || [ $# -gt 3 ]; then
    echo "usage: $0 HOST SITE [ROOT]" >&2
    exit 2
fi
host=$1
site=$(cd "$2" && pwd)
root=$(printf '%q' "${3:-/opt/socio-evo}")
stamp=$(date -u +%Y%m%dT%H%M%SZ)-$$
if [ ! -f "$site/index.html" ] || [ ! -f "$site/data/manifest.json" ]; then
    echo "$site is not a published site" >&2
    exit 2
fi

remote() {
    # PUSH_SSH may carry options, so it is split into words on purpose.
    # shellcheck disable=SC2086
    ${PUSH_SSH:-ssh} "$host" "$1"
}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir "$work/pack" "$work/pack/.push"

cat > "$work/list.sh" <<'EOF'
set -eu
root=$1
mkdir -p "$root/releases"
rm -rf "$root"/releases/.incoming.*
if [ -L "$root/site" ]; then
    cd "$root/site/"
    find . -type f -exec sha256sum {} +
elif [ -e "$root/site" ]; then
    echo "$root/site exists and is not a symbolic link; move it away first" >&2
    exit 3
fi
EOF

cat > "$work/pack/.push/apply.sh" <<'EOF'
set -eu
export LC_ALL=C
root=$(cd "$1" && pwd) stamp=$2 stage=$(cd "$3" && pwd)
new=$root/releases/$stamp
old=
if [ -L "$root/site" ]; then
    old=$(readlink -f "$root/site")
    cp -al "$old" "$new"
else
    mkdir "$new"
fi
cd "$stage"
find . -path ./.push -prune -o -type f -print | while IFS= read -r path; do
    mkdir -p "$new/${path%/*}"
    mv -f "$path" "$new/$path"
done
cd "$new"
sed 's/^[0-9a-f]*  //' "$stage/.push/release.sha256" | sort > "$stage/.push/wanted"
find . -type f | sort > "$stage/.push/present"
comm -23 "$stage/.push/present" "$stage/.push/wanted" | while IFS= read -r path; do
    rm -f "$path"
done
find . -mindepth 1 -type d -empty -delete
sha256sum -c --quiet "$stage/.push/release.sha256"
ln -s "releases/$stamp" "$root/.site-$stamp"
mv -T "$root/.site-$stamp" "$root/site"
rm -rf "$stage"
for release in "$root"/releases/*; do
    [ "$release" = "$new" ] || [ "$release" = "$old" ] || rm -rf "$release"
done
EOF

(cd "$site" && find . -type f -exec sha256sum {} +) | sort -k 2 > "$work/pack/.push/release.sha256"
remote "sh -s -- $root" < "$work/list.sh" | sort -k 2 > "$work/current.sha256"
comm -23 <(sort "$work/pack/.push/release.sha256") <(sort "$work/current.sha256") \
    | cut -c 67- > "$work/changed"
comm -13 <(cut -c 67- "$work/pack/.push/release.sha256" | sort) \
    <(cut -c 67- "$work/current.sha256" | sort) > "$work/removed"
if [ ! -s "$work/changed" ] && [ ! -s "$work/removed" ]; then
    echo "the server already has this site"
    exit 0
fi

tar -czf - -C "$work/pack" .push -C "$site" -T "$work/changed" | remote \
    "set -eu; stage=\$(mktemp -d $root/releases/.incoming.XXXXXX); tar -xzf - -C \"\$stage\"; sh \"\$stage/.push/apply.sh\" $root $stamp \"\$stage\""

bytes=$( (cd "$site" && tr '\n' '\0' < "$work/changed" | xargs -0 -r cat) | wc -c)
echo "$(wc -l < "$work/changed") files uploaded ($bytes bytes), $(wc -l < "$work/removed") removed; site is releases/$stamp"
