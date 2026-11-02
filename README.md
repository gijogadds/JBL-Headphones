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

4. **Recursos de Chamadas e Utilidades:**
   - **VoiceAware:** Retorno da sua própria voz durante reuniões e chamadas (Desligado, Baixo, Médio, Alto).
   - **Smart Audio & Video:** Alternância entre alta fidelidade e modo de baixa latência para vídeos e jogos.
   - **Buscar Meus Fones (Find My Buds):** Disparo de sinal sonoro independente no fone Esquerdo ou Direito.

5. **Arquitetura Dinâmica Universal:**
   - Possui catálogo interno de **128 modelos da JBL** (linhas *Tune, Live, Tour, Wave, Vibe, Club, Everest, Endurance, Quantum*, etc.).
   - A interface oculta ou exibe os cards automaticamente com base nos recursos que o fone suporta.
   - Inclui seletor/simulador de modelos para inspecionar a interface de outros fones.

6. **Camada de Comunicação Dual-Transport:**
   - **BLE GATT**: Conecta ao serviço proprietário Harman (`65786365-6c70-6f69-6e74-2e636f6d0000`) para comandos prioritários e notificações em tempo real de toques físicos.
   - **RFCOMM SPP (Porta 17)**: Suporte a dispositivos legados e telemetria contínua.
   - **Suporte a Protocolo 3 e Protocolo 4**: Compatível com toda a linha tradicional BES e com a nova linha Harman (Tour Pro 2/3, Live 3).

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

### Instalar Lançador no Menu do Sistema:
Copie o arquivo `.desktop` para sua pasta de aplicativos locais:
```bash
cp jbl-headphones.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/
```
Agora basta abrir o menu do sistema e buscar por **JBL Headphones**!

---

## 📖 Documentação de Engenharia Reversa
Para especificações detalhadas sobre os quadros binários, opcodes, UUIDs, chipsets e algoritmos, leia o arquivo [REA.md](REA.md).
