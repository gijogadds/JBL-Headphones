#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APPLICATIONS_DIR="$HOME/.local/share/applications"
ICON_ROOT="$HOME/.local/share/icons/hicolor"
LAUNCHER="$BIN_DIR/jbl-headphones"

mkdir -p "$BIN_DIR" "$APPLICATIONS_DIR"
printf '#!/usr/bin/env bash\nexec /usr/bin/python3 %q "$@"\n' \
    "$APP_DIR/main.py" > "$LAUNCHER"
chmod 755 "$LAUNCHER"

python3 "$APP_DIR/scripts/render_desktop_entry.py" \
    "$APP_DIR/io.github.jbl.headphones.linux.desktop" \
    "$APPLICATIONS_DIR/io.github.jbl.headphones.linux.desktop" "$LAUNCHER"

for size in 48x48 64x64 128x128 256x256 scalable; do
    icon_dir="$ICON_ROOT/$size/apps"
    mkdir -p "$icon_dir"
    cp "$APP_DIR/data/icon.png" "$icon_dir/io.github.jbl.headphones.linux.png"
done

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_DIR"
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$ICON_ROOT"
fi

echo "Lançador JBL Headphones instalado em $APPLICATIONS_DIR."
