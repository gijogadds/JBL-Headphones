#!/usr/bin/env bash
# Instala e ativa o serviço de inicialização e encerramento automático do JBL Headphones
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

# O systemd user é o único mecanismo de inicialização para evitar dois listeners.
rm -f "$HOME/.config/autostart/jbl-headphones-listener.desktop"

echo "==> Concluído com sucesso!"
echo "O monitor systemd agora está ativo em segundo plano."
echo "Quando os fones JBL se conectarem, o app abrirá direto na barra superior."
echo "Quando os fones forem desligados, o app encerrará automaticamente."
