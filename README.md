# JBL Headphones Controller para Linux

Aplicativo desktop nativo para Linux desenvolvido em **Python + GTK4 + Libadwaita**, projetado para gerenciar e controlar todos os recursos de fones de ouvido **JBL / Harman**.

Criado a partir da **engenharia reversa completa** do aplicativo oficial Android (`jbl.stc.com`), ele suporta **128 modelos diferentes da JBL** e adapta a interface gráfica dinamicamente conforme o modelo conectado.

Para detalhes aprofundados sobre a engenharia reversa dos protocolos (Protocolo 3, Protocolo 4, telemetria BES TWS e ecossistema Airoha), consulte o [Relatório Técnico de Engenharia Reversa (REA.md)](REA.md).

---

## 🎧 Recursos Implementados

1. **Auto-Detecção do Fone Conectado:**
   - Detecta automaticamente quando um fone JBL é pareado ou conectado via Bluetooth (BlueZ D-Bus).
   - Identifica o nome, endereço MAC e o **PID de Hardware** (ex: `0x210C` para o *JBL Tune Buds 2*).
   - Exibe a porcentagem da bateria em tempo real no topo da janela.

2. **Controle de Som e Cancelamento de Ruído (ANC):**
   - 🔇 **ANC (Cancelamento Ativo de Ruído)**
   - 👂 **Ambient Aware (Modo Som Ambiente)**
   - 💬 **TalkThru (Música em volume baixo + amplificação de voz)**
   - ⚪ **Desligado (Modo Normal)**

3. **Equalizador Oficial JBL (10 Bandas de Frequência):**
   - Suporte aos presets originais da Harman extraídos do app:
     - *Jazz, Vocal, Bass, Extreme Bass, Club, Studio (Flat), Pop, Personalizado*.
   - 10 controles deslizantes verticais interativos de frequência:
     - `32Hz, 64Hz, 125Hz, 250Hz, 500Hz, 1kHz, 2kHz, 4kHz, 8kHz, 16kHz`.
   - Ajuste de ganho de **-10.0 dB a +10.0 dB** com aplicação instantânea nos fones via pacotes `EQSettings2` (0xAA 0xA2).

4. **Recursos Avançados e Áudio (Engenharia Reversa Completa):**
   - **Modo Áudio & Vídeo (Smart Audio & Video):** Alternância em tempo real entre qualidade máxima de áudio musical (Alta Fidelidade) e redução de latência no DSP para 100ms para sincronismo labial perfeito em vídeos, filmes e jogos (`0xAA 0x81`).
   - **Balanço Estéreo L/R (Left/Right Sound Balance):** Controle deslizante preciso de -16 (100% Esquerdo) a +16 (100% Direito) com valor central equilibrado (`0xAA 0xA8`).
   - **Desligamento Automático por Inatividade:** Temporizador configurável para economia de bateria (*Nunca, 15 min, 30 min, 1 hora, 2 horas*) enviado diretamente para o microcontrolador (`0xAA 0x33`).
   - **Proteção Auditiva Safe Sound (85 dB):** Limitador acústico automático conforme diretrizes da OMS para prevenção de perda auditiva (`0xAA 0xA5`).
   - **VoiceAware:** Retorno da sua própria voz durante reuniões e chamadas (Desligado, Baixo, Médio, Alto) (`0xAA 0x98`).
   - **Buscar Meus Fones (Find My Buds):** Disparo de sinal sonoro independente no fone Esquerdo ou Direito (`0xAA 0x36`).

5. **Menu Suspenso na Barra Superior (Top Bar Tray / StatusNotifierItem):**
   - Indicador nativo e persistente na bandeja do sistema (Top Bar) via `org.kde.StatusNotifierItem` e `com.canonical.dbusmenu`.
   - Exibição de carga de bateria em tempo real (`L: X%⚡ | R: Y%⚡ | Case: Z%⚡`).
   - Submenus rápidos para alternar modos de ANC (*ANC, Ambient Aware, TalkThru, Off*), Presets de Equalizador e Modo Áudio & Vídeo diretamente da barra superior sem precisar abrir a janela principal.
   - Ao fechar a janela, o aplicativo continua em execução em segundo plano na barra superior, podendo ser reexibido com 1 clique no ícone ou no item "Abrir / Ocultar Janela".

6. **Ícone Oficial e Integração Completa com a Dock do GNOME:**
   - Identificador padronizado `io.github.jbl.headphones.linux` com ícones vetoriais e bitmaps de alta resolução instalados no tema hicolor do sistema (`48x48` até `256x256`).
   - O logo oficial da JBL aparece na dock, no switcher Alt-Tab e nas notificações de forma idêntica aos aplicativos nativos do sistema.

7. **Arquitetura Dinâmica Universal:**
   - Possui catálogo interno de **128 modelos da JBL** (linhas *Tune, Live, Tour, Wave, Vibe, Club, Everest, Endurance, Quantum*, etc.).
   - A interface oculta ou exibe os cards automaticamente com base nos recursos que o fone suporta.
   - Inclui seletor/simulador de modelos para inspecionar a interface de outros fones.

8. **Camada de Comunicação Dual-Transport:**
   - **BLE GATT**: Conecta ao serviço proprietário Harman (`65786365-6c70-6f69-6e74-2e636f6d0000`) para comandos prioritários e notificações em tempo real de toques físicos.
   - **RFCOMM SPP (Porta 17)**: Suporte a dispositivos legados e telemetria contínua.
   - **Suporte a Protocolo 3 e Protocolo 4**: Compatível com toda a linha tradicional BES e com a nova linha Harman (Tour Pro 2/3, Live 3).

9. **Detecção, Inicialização e Encerramento Automático:**
   - **Auto-Start na Barra Superior:** Ao ligar os fones JBL ou quando eles se conectarem ao Bluetooth, o aplicativo é disparado automaticamente na barra superior (em modo `--tray`) sem janelas invasivas, deixando todos os controles prontos para uso imediato.
   - **Auto-Shutdown ao Desligar os Fones:** Quando você desliga os fones ou os guarda no estojo, o aplicativo detecta a desconexão via BlueZ D-Bus e encerra o processo sozinho automaticamente, liberando a memória e limpando o ícone da barra superior.
   - **Monitor Leve em Segundo Plano:** O monitor de eventos roda como serviço `systemd --user` (`jbl-headphones-listener.service`), consumindo 0% de CPU e ~8MB de RAM enquanto aguarda.

---

## 🚀 Como Executar

### Pré-requisitos
No Ubuntu / Debian / Fedora:
```bash
# Dependências de sistema (GTK4, Libadwaita e Python GObject)
sudo apt install python3 python3-pip python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libbluetooth-dev

# Dependências Python
pip install bleak dbus-python
```

### Executar diretamente pelo terminal:
```bash
python3 main.py
```

### Instalar Lançador e Ícones no Sistema:
Para instalar os ícones oficiais e o lançador na dock do sistema:
```bash
# Copia o arquivo .desktop para aplicações locais
cp io.github.jbl.headphones.linux.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/

# Instala o ícone oficial em todas as resoluções do tema hicolor
for sz in 48x48 64x64 128x128 256x256 scalable; do
    mkdir -p ~/.local/share/icons/hicolor/$sz/apps
    cp data/icon.png ~/.local/share/icons/hicolor/$sz/apps/io.github.jbl.headphones.linux.png
done
gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor
```
Agora basta abrir o menu de aplicativos ou a dock do GNOME e buscar por **JBL Headphones**!

---

## 📖 Documentação de Engenharia Reversa
Para especificações detalhadas sobre os quadros binários, opcodes, UUIDs, chipsets e algoritmos, leia o arquivo [REA.md](REA.md).

---

## 📄 Licença
Este projeto é licenciado sob a [Licença MIT](LICENSE) - veja o arquivo `LICENSE` para detalhes.
