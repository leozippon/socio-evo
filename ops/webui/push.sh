#!/usr/bin/env bash
# Atomic, checksum-verified static releases. See README.md; run against a stable local tree.
set -euo pipefail
export LC_ALL=C
if [[ $# -lt 3 || $# -gt 4 || ! $3 =~ ^(cornerhead|socio-evo)$ ]]; then
    echo "usage: $0 HOST SITE {cornerhead|socio-evo} [ROOT]" >&2; exit 2
fi
host=$1
site=$(cd "$2" && pwd)
service=$3
root=$(printf '%q' "${4:-/opt/$service}")
stamp=$(date -u +%Y%m%dT%H%M%SZ)-$$
[[ -f "$site/index.html" ]] || { echo "missing index.html" >&2; exit 2; }
[[ ! -e "$site/.push" ]] || { echo ".push is reserved" >&2; exit 2; }
[[ -z $(find "$site" -mindepth 1 ! -type f ! -type d -print -quit) ]] || {
    echo "only regular files and directories may be published" >&2; exit 2;
}
remote() {
    # SSH options are deliberately word-split; never put secrets in PUSH_SSH.
    # shellcheck disable=SC2086
    ${PUSH_SSH:-ssh} "$host" "$1"
}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/pack/.push"
cat > "$work/list.sh" <<'EOF'
set -eu
root=$1
case "$root" in /opt/cornerhead|/opt/socio-evo)
    [ "$(id -u)" = 0 ] || { echo "production push requires root" >&2; exit 3; }
    install -d -o root -g www-data -m 750 "$root" "$root/releases";;
*) mkdir -p "$root/releases";; esac
if [ -L "$root/site" ]; then
    old=$(readlink -f "$root/site")
    case "$old" in "$root"/releases/*) ;; *) echo "site points outside releases" >&2; exit 3;; esac
    cd "$old"
    find . -type f -exec sha256sum {} +
elif [ -e "$root/site" ]; then
    echo "site must be a symlink" >&2; exit 3
fi
EOF
cat > "$work/pack/.push/apply.sh" <<'EOF'
set -eu
export LC_ALL=C
root=$(cd "$1" && pwd) stamp=$2 stage=$(cd "$3" && pwd)
exec 9>"$root/.push.lock"
flock -w 30 9 || { echo "another push holds the lock" >&2; exit 3; }
new=$root/releases/$stamp
old=
committed=0
trap '[ "$committed" = 1 ] || rm -rf "$new"; rm -rf "$stage"' EXIT
if [ -L "$root/site" ]; then
    old=$(readlink -f "$root/site")
    case "$old" in "$root"/releases/*) ;; *) exit 3;; esac
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
comm -23 "$stage/.push/present" "$stage/.push/wanted" | while IFS= read -r path; do rm -f "$path"; done
find . -mindepth 1 -type d -empty -delete
sha256sum -c --quiet "$stage/.push/release.sha256"
case "$root" in /opt/cornerhead|/opt/socio-evo)
    chown -R root:www-data "$new"
    find "$new" -type d -exec chmod 750 {} +
    find "$new" -type f -exec chmod 640 {} +;; esac
ln -s "releases/$stamp" "$root/.site-$stamp"
mv -T "$root/.site-$stamp" "$root/site"
committed=1
for release in "$root"/releases/*; do
    [ "$release" = "$new" ] || [ "$release" = "$old" ] || rm -rf "$release"
done
EOF
(cd "$site" && find . -type f -exec sha256sum {} +) | sort -k 2 > "$work/pack/.push/release.sha256"
remote "sh -s -- $root" < "$work/list.sh" | sort -k 2 > "$work/current.sha256"
comm -23 <(sort "$work/pack/.push/release.sha256") <(sort "$work/current.sha256") | cut -c 67- > "$work/changed"
comm -13 <(cut -c 67- "$work/pack/.push/release.sha256" | sort) <(cut -c 67- "$work/current.sha256" | sort) > "$work/removed"
if [[ ! -s $work/changed && ! -s $work/removed ]]; then
    echo "the server already has this site"; exit 0
fi
tar -czf - -C "$work/pack" .push -C "$site" -T "$work/changed" | remote \
    "set -eu; umask 077; stage=\$(mktemp -d $root/releases/.incoming.XXXXXX); tar -xzf - -C \"\$stage\" --no-same-owner --no-same-permissions; sh \"\$stage/.push/apply.sh\" $root $stamp \"\$stage\""
bytes=$( (cd "$site" && tr '\n' '\0' < "$work/changed" | xargs -0 -r cat) | wc -c)
echo "$(wc -l < "$work/changed") files uploaded ($bytes bytes), $(wc -l < "$work/removed") removed; site is releases/$stamp"
