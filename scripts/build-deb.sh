#!/usr/bin/env bash
# Build an amd64 .deb from the current tree (stdlib + system GTK).
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])" 2>/dev/null \
  || python3 -c "from pathlib import Path; import re; print(re.search(r'version\s*=\s*\"([^\"]+)\"', Path('pyproject.toml').read_text()).group(1))")"
ARCH="${ARCH:-amd64}"
PKG_NAME="seshka-linux"
ROOT="build/deb/${PKG_NAME}_${VERSION}_${ARCH}"
DIST="dist"

rm -rf "build/deb"
mkdir -p "$ROOT/DEBIAN" "$ROOT/usr/bin" "$ROOT/usr/lib/seshka-linux" \
  "$ROOT/usr/share/applications" "$ROOT/usr/share/doc/${PKG_NAME}"

# Install package files into /usr/lib/seshka-linux
python3 -m pip install --target "$ROOT/usr/lib/seshka-linux" --no-deps --no-compile .
cp -a packaging/seshka.desktop "$ROOT/usr/share/applications/seshka.desktop"
# Point desktop entry at wrapper
sed -i 's|^Exec=.*|Exec=seshka-gui|' "$ROOT/usr/share/applications/seshka.desktop"

install -m 0644 LICENSE NOTICE THIRD_PARTY.md README.md "$ROOT/usr/share/doc/${PKG_NAME}/"
cat > "$ROOT/usr/share/doc/${PKG_NAME}/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: seshka-linux
Source: https://github.com/php4umagento/seshka-linux

Files: *
Copyright: 2026 PHP4U
License: MIT

Files: usr/lib/seshka-linux/seshka/gui/icons/*
Copyright: 2026 JigJoy
License: MIT
Comment: See THIRD_PARTY.md / NOTICE
EOF

# Wrappers so PATH works without PYTHONPATH
cat > "$ROOT/usr/bin/seshka" <<'EOF'
#!/bin/sh
export PYTHONPATH="/usr/lib/seshka-linux${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m seshka "$@"
EOF
cat > "$ROOT/usr/bin/seshka-gui" <<'EOF'
#!/bin/sh
export PYTHONPATH="/usr/lib/seshka-linux${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -c 'from seshka.gui.app import main; raise SystemExit(main())' "$@"
EOF
chmod 0755 "$ROOT/usr/bin/seshka" "$ROOT/usr/bin/seshka-gui"

INSTALLED_SIZE="$(du -sk "$ROOT" | awk '{print $1}')"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Installed-Size: ${INSTALLED_SIZE}
Maintainer: PHP4U <https://github.com/php4umagento>
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-3.0, gir1.2-gdk-3.0, gir1.2-ayatanaappindicator3-0.1 | gir1.2-appindicator3-0.1
Recommends: gir1.2-ayatanaappindicator3-0.1
Homepage: https://github.com/php4umagento/seshka-linux
Description: Kill leftover processes from Claude Code sessions
 seshka-linux finds processes stamped by Claude Code (CLAUDECODE=1)
 after a session closes, and lets you kill them from a tray GUI or CLI.
EOF

mkdir -p "$DIST"
DEB="${DIST}/${PKG_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$DEB"
echo "Built $DEB"
dpkg-deb -I "$DEB"
ls -lh "$DEB"
