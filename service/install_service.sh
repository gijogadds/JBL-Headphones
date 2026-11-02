#!/usr/bin/env bash
# Instala e ativa o serviço de inicialização e encerramento automático do JBL Headphones
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
BIN_DIR="$HOME/.local/bin"
SERVICE_DIR="$HOME/.config/systemd/user"

mkdir -p "$BIN_DIR" "$SERVICE_DIR"
printf '#!/usr/bin/env bash\nexec /usr/bin/python3 %q "$@"\n' \
    "$SCRIPT_DIR/jbl_listener.py" > "$BIN_DIR/jbl-headphones-listener"
chmod 755 "$BIN_DIR/jbl-headphones-listener"

echo "==> Configurando inicialização e encerramento automático para JBL Headphones..."

# 1. Configurar Systemd User Service
cp "$SCRIPT_DIR/jbl-headphones-listener.service" "$SERVICE_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now jbl-headphones-listener.service

# 2. Configurar Autostart XDG
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
python3 "$APP_DIR/scripts/render_desktop_entry.py" \
    "$SCRIPT_DIR/jbl-headphones-listener.desktop" \
    "$AUTOSTART_DIR/jbl-headphones-listener.desktop" \
    "$BIN_DIR/jbl-headphones-listener"

echo "==> Concluído com sucesso!"
echo "O monitor agora está ativo em segundo plano."
echo "Quando os fones JBL se conectarem, o app abrirá direto na barra superior."
echo "Quando os fones forem desligados, o app encerrará automaticamente."
