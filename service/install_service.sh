#!/usr/bin/env bash
# Instala e ativa o serviço de inicialização e encerramento automático do JBL Headphones
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

echo "==> Configurando inicialização e encerramento automático para JBL Headphones..."

# 1. Configurar Systemd User Service
mkdir -p ~/.config/systemd/user
cp "$SCRIPT_DIR/jbl-headphones-listener.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now jbl-headphones-listener.service

# 2. Configurar Autostart XDG
mkdir -p ~/.config/autostart
cp "$SCRIPT_DIR/jbl-headphones-listener.desktop" ~/.config/autostart/

echo "==> Concluído com sucesso!"
echo "O monitor agora está ativo em segundo plano."
echo "Quando os fones JBL se conectarem, o app abrirá direto na barra superior."
echo "Quando os fones forem desligados, o app encerrará automaticamente."
