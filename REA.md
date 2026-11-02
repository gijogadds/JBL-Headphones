# Relatório Técnico de Engenharia Reversa (REA)
## JBL Headphones Companion App & Protocolos de Comunicação Harman

---

### Sumário Executivo
Este documento consolida o processo completo de **engenharia reversa e análise estrutural** realizado sobre o aplicativo móvel oficial **JBL Headphones** (`jbl.stc.com.apk`), bem como a especificação detalhada dos protocolos proprietários da **Harman International / JBL** (Protocolos 3 e 4, telemetria BES TWS e ecossistema Airoha). 

O resultado desta engenharia reversa serviu como base técnica para o desenvolvimento do **JBL Headphones Controller para Linux** (`jbl-linux-app`), um aplicativo desktop nativo em **Python + GTK4 + Libadwaita** com suporte a **128 modelos de fones de ouvido** da marca.

---

## 1. Identificação do Artefato Binário

A análise foi conduzida estaticamente sobre o arquivo APK oficial e sua árvore de arquivos descompactada:

| Atributo | Valor Observado |
| :--- | :--- |
| **Arquivo Alvo** | `jbl.stc.com.apk` |
| **Tamanho em Disco** | 174.049.796 bytes (~166 MB) |
| **SHA-256 Digest** | `702b2290e06272b9fe57e76e42f5ee78f07203deed2abfdfb5367860d54926a3` |
| **Package Name** | `jbl.stc.com` |
| **Application Name** | `JBL Headphones` |
| **Version Name** | `5.38.2` |
| **Version Code** | `260928180` |
| **Target SDK** | `36` (Android 16) |
| **Min SDK** | `26` (Android 8.0 Oreo) |
| **Esquemas de Assinatura** | APK Signature Scheme v2 (presente), Scheme v3 (presente), v1 JAR (ausente) |
| **Certificado SHA-256** | `de7fe9dd4d2d6415d8834d1886f5186efbfb9833ebb2502e44096a93b4baa53d` |
| **Source Stamp SHA-256** | `3257d599a49d2c961a471ca9843f59d341a405884583fc087df4237b733bbd6d` |
| **Volume de Bytecode** | 4 arquivos DEX (`classes.dex` a `classes4.dex`), totalizando 33,1 MB |
| **Inventário Total** | 5.024 entradas compactadas (14.913 nós analisados pelo REA) |

### 1.1 Permissões Críticas no `AndroidManifest.xml`
A análise do manifesto decodificado revelou os seguintes pontos de entrada no hardware Bluetooth:
- `android.permission.BLUETOOTH` & `BLUETOOTH_ADMIN`: Comunicação e gerenciamento de rádio Bluetooth Classic.
- `android.permission.BLUETOOTH_SCAN`: Varredura BLE para fones no Android 12+.
- `android.permission.BLUETOOTH_CONNECT`: Acesso aos canais GATT e RFCOMM.
- `android.permission.ACCESS_FINE_LOCATION` & `COARSE_LOCATION`: Necessárias para localização e scanning em versões anteriores.

---

## 2. Camada de Transporte e Bluetooth Stack

A investigação dos pacotes decompilados (`com.harman.bluetooth.*`, `com.airoha.liblinker.physical.*`) revelou uma arquitetura **Dual-Mode** altamente sofisticada:

```
+-------------------------------------------------------------------+
|                     Dispositivo JBL / Harman                      |
+---------------------------------+---------------------------------+
|      Bluetooth Classic (BR/EDR) |    Bluetooth Low Energy (BLE)   |
|     Canal RFCOMM SPP (Porta 17) |      Serviço GATT Excelpoint    |
+---------------------------------+---------------------------------+
                 |                                  |
                 v                                  v
+---------------------------------+---------------------------------+
|   BES TWS Telemetry & Status    |    Controle Acústico Prioritário|
| (Bateria Case/L/R, Pareamento)  |   (ANC, Ambient, TalkThru, EQ)  |
+---------------------------------+---------------------------------+
```

### 2.1 Serviço BLE Proprietário Harman / Excelpoint
Para operações de áudio prioritárias (cancelamento de ruído, som ambiente, equalizador paramétrico e detecção de toques físicos), os fones JBL utilizam o serviço BLE GATT:

- **Service UUID**: `65786365-6c70-6f69-6e74-2e636f6d0000` (ASCII: `excelpoint.com\0\0`)
- **Characteristic NOTIFY / INDICATE**: `65786365-6c70-6f69-6e74-2e636f6d0001`
  - Utilizada pelo microcontrolador do fone para emitir eventos espontâneos de toques no auricular (Tap/Double-Tap), alterações de modo ANC e telemetria de status.
- **Characteristic WRITE WITHOUT RESPONSE**: `65786365-6c70-6f69-6e74-2e636f6d0002`
  - Utilizada pela aplicação controladora para despachar comandos imediatos sem roundtrip de ACK Bluetooth.
- **Characteristic AUX**: `65786365-6C70-6F69-6E74-2E636F6D0003`
- **Serviço de Atualização OTA (Firmware)**: `65786365-6c70-6f69-6e74-2e636f820000`

### 2.2 Canal Bluetooth Classic (RFCOMM SPP)
- **UUID SPP Padrão**: `00001101-0000-1000-8000-00805F9B34FB` (Serial Port Profile)
- **Canais Identificados**:
  - **Canal 17**: Canal primário utilizado por quase toda a linha Tune, Live e Wave.
  - **Canal 12 / Canal 1**: Portas de contingência para modelos legados.

---

## 3. Protocolos de Controle Harman (Reverse Engineered)

A análise aprofundada dos arquivos DEX revelou a coexistência de duas gerações principais de protocolo desenvolvidas pela Harman:

### 3.1 Protocolo 3 (Harman Classic & BES TWS)
Implementado no pacote `com.harman.cmdctrl.imp.control.u3.protocol3`:

#### Estrutura Geral do Quadro (Header `0xAA`):
```
+--------------+---------------+--------------+----------------------+
| Header (1B)  | CommandID(1B) | Length (1B)  | Payload (N bytes)    |
|     0xAA     |     0x??      |    0x??      | ...                  |
+--------------+---------------+--------------+----------------------+
```

#### Comandos Críticos Mapeados:
1. **Identificação do Dispositivo (`0x11` / `0x12`)**:
   - Requisição: `AA 11 01 00`
   - Resposta: Retorna o nome textual do fone (16 bytes), o **PID de Hardware** (ex: `21 0C` para Tune Buds 2), status de conexão e nível inicial de bateria.
2. **Telemetria de Bateria Dedicada (`0x25`)**:
   - Requisição: `AA 25 01 00`
   - Resposta: Bytes independentes para fone esquerdo, direito e estojo.
3. **Controle de Modos Acústicos (`0x91`)**:
   - Transmissão (`CmdGen.genSetANCModes` / `SubId.SET = 0x10`):
     - **Ativar Cancelamento Ativo de Ruído (ANC)**:
       `AA 91 07 10 01 01 02 00 03 00` (Tipo 1=ANC:1, Tipo 2=AA:0, Tipo 3=TT:0)
     - **Ativar Som Ambiente (Ambient Aware)**:
       `AA 91 07 10 01 00 02 01 03 00` (Tipo 1=ANC:0, Tipo 2=AA:1, Tipo 3=TT:0)
     - **Ativar Modo Conversa (TalkThru)**:
       `AA 91 07 10 01 00 02 00 03 01` (Tipo 1=ANC:0, Tipo 2=AA:0, Tipo 3=TT:1)
     - **Desligar Todos os Modos (Normal / Off)**:
       `AA 91 01 13` (`SubId.OFF = 0x13`)
   - Recepção / Notificações (`HandleParse.parseData` / `SubId.RET = 0x12`):
     - O pacote de telemetria possui cabeçalho `[0xAA, 0x91, Len, 0x12]` seguido de `(Len - 1) / 2` pares dinâmicos `[Type, Value]`.
     - `Type = 1`: ANC (`Value != 0` -> ANC ativo).
     - `Type = 2`: Ambient Aware (`Value != 0` -> Ambient Aware ativo).
     - `Type = 3`: TalkThru (`Value != 0` -> TalkThru ativo).
     - *Nota técnica*: O parser oficial inspeciona iterativamente os pares `(Type, Value)` em vez de assumir índices fixos, garantindo compatibilidade quando o fone reporta pares em ordens alternadas.
4. **Equalizador Oficial Pré-definido (`0x40`)**:
   - Formato: `AA 40 01 [CategoryID]`
   - Categorias oficiais Harman BES (extraídas de `assets/standard_preset_eq.json`):
     - `1`: Jazz
     - `2`: Vocal
     - `3`: Bass
     - `9`: Extreme Bass
     - `6`: Club
     - `7`: Studio
     - `13`: Pop
     - `0`: Personalizado (Custom)
5. **Equalizador Paramétrico de Alta Fidelidade `EQSettings2` (`0xA2`)**:
   - Decompilado de `com.harman.commands.EQCmd.sendCmd`, `assets/standard_preset_eq.json` e `com.harman.utils.HexArray.float2bytes`.
   - Framing estendido: `AA A2 [Len_LSB] [Len_MSB] ...payload (116 bytes)`.
   - Cabeçalho do payload (16 bytes fixos):
     - Byte 0: `subSetCmd10` (`0x03` indicando escala de Q multiplicada por 10)
     - Byte 1: `category` (`0x00` para curva personalizada ou CategoryID oficial 1 a 13)
     - Bytes 2..5: `calibration` (float 32-bit Little-Endian `<f`, `0.0f`)
     - Byte 6: `sampleRate` (1 byte, `0x00`)
     - Bytes 7..10: `leftGain` (float 32-bit Little-Endian `<f`, `0.0f`)
     - Bytes 11..14: `rightGain` (float 32-bit Little-Endian `<f`, `0.0f`)
     - Byte 15: `bandCount` (1 byte, `0x0A` para 10 bandas)
   - 10 bandas de frequência consecutivas (10 bytes cada, totalizando 100 bytes):
     - Offset + 0: `bandType` (1 byte, `0x01` = Filtro Peaking Paramétrico ativo; `0x00` = bypass/desativado)
     - Offset + 1..4: `gainValue` (float 32-bit Little-Endian `<f`, ex: `-10.0f` a `+10.0f`)
     - Offset + 5..8: `frequency` (float 32-bit Little-Endian `<f`, ex: `32.0f`, `64.0f`, etc.)
     - Offset + 9: `qValue * 10` (1 byte unsigned, `10` para fator Q = 1.0)
   - As 10 frequências centrais oficiais extraídas dos assets são:
     `32 Hz, 64 Hz, 125 Hz, 250 Hz, 500 Hz, 1.000 Hz, 2.000 Hz, 4.000 Hz, 8.000 Hz, 16.000 Hz`.
6. **VoiceAware / Sidetone (`0x98`)**:
   - Formato: `AA 98 01 [Level]` (0: Off, 1: Low, 2: Mid, 3: High).
7. **Localizar Meus Fones (`0x36`)**:
   - Formato: `AA 36 01 [Bitmask]` (Bit 0: Esquerdo, Bit 1: Direito).

#### Telemetria BES TWS (Prefixo `0x03`):
Fones equipados com microcontroladores da Bestechnic transmitem pacotes com prefixo `0x03`:
```
+-------------+---------------+---------------+--------------------+
| Prefixo(1B) | CommandID(1B) | Length (2B BE)| Payload (N bytes)  |
|    0x03     |     0x??      | [MSB] [LSB]   | ...                |
+-------------+---------------+---------------+--------------------+
```
- **CommandID `0x03` (Baterias em Tempo Real)**:
  - Tamanho: Exatamente 3 bytes `[Left, Right, Case]`.
  - Bit 7 (`0x80`): Flag de carregamento ativo (`True` se em recarga).
  - Bits 0-6 (`val & 0x7F`): Porcentagem de bateria de 0% a 100%.
- **CommandID `0x09` (Firmware)**: String ASCII com a versão (ex: "4.9.0.0").
- **CommandID `0x01` (Status TWS)**: Estado de pareamento dos auriculares.

---

### 3.2 Protocolo 4 (Next-Gen Harman BLE Protocol)
Identificado no pacote `com.harman.protocol4.*` e mapeado em `assets/protocol4_commands.json`. É o padrão utilizado em modelos topo de linha recentes (ex: JBL Tour Pro 2/3, Live 3 Series com Smart Case):

#### Estrutura do Quadro (`AssembleCmd4`):
```
+-------------------+-------------------+-------------+--------------+------------------+------------------+
| Identifier (2B LE)|  CommandID (2B LE)| PktCount(1B)| PktIndex(1B) | PayloadSize(2BLE)| Payload (TLV)    |
|   0xF0 0xDC       |      0x?? 0x??    |    0x01     |     0x00     |    0x?? 0x??     | Feature ID + Data|
+-------------------+-------------------+-------------+--------------+------------------+------------------+
```
- **Identifier**: `0xDCF0` (Transmitido como `[0xF0, 0xDC]` em Little-Endian).
- **CommandIDs Mapeados**:
  - `0x0001`: `GET_DEVICE_INFO_0001` (Consulta de propriedades)
  - `0x0002`: `SET_DEVICE_INFO_0002` (Escrita de comandos)
  - `0x0003`: `NOTIFICATION_TO_APP_0003` (Eventos assíncronos)
  - `0x0004`: `NOTIFICATION_TO_DEVICE_0004`
  - `0x00FF`: `RESET_TO_FACTORY_00FF`
- **Features Chave Mapeadas (Total de 171 features catalogadas)**:
  - `0x0001`: `MTU`
  - `0x0002`: `Heartbeat`
  - `0x0004`: `ProductID`
  - `0x0006`: `DeviceName`
  - `0x000A`: `MACAddress`
  - `0x000C`: `FirmwareVersion`
  - `0x000D`: `LeftDeviceBatteryStatus`
  - `0x000E`: `RightDeviceBatteryStatus`
  - `0x0018`: `ANC` (0: Off, 1: On)
  - `0x0019`: `AmbientAware` (0: Off, 1: On)
  - `0x001A`: `TalkThru` (0: Off, 1: On)
  - `0x0021`: `SpatialSoundMode` (Áudio Espacial)
  - `0x0023`: `Sidetone` (VoiceAware)
  - `0x0027`: `AudioLimiter`

---

## 4. Ecossistema de Hardware e Chipsets

A análise de strings e classes revelou que a JBL projeta seus dispositivos utilizando duas plataformas principais de silício:

1. **Bestechnic (BES)**:
   - Utilizado em fones compactos TWS (séries Tune Buds, Tune Beam, Wave Buds, Vibe Flex).
   - Utiliza a stack proprietária BES com canal SPP e framing `0x03` / `0xAA`.
2. **MediaTek / Airoha**:
   - Encontrado nas famílias Live, Everest e Club (ex: AB1562, AB1565).
   - Implementado no pacote `com.airoha.adapter.harman`.
   - Gerencia algoritmos proprietários de PersoniFi 2.0 (teste audiométrico, compensação de curva auditiva por usuário).
3. **Smart Charging Case**:
   - Modelos como *JBL Tour Pro 2*, *Tour Pro 3* e *Live Buds 3* integram uma tela sensível ao toque colorida no estojo de recarga.
   - O aplicativo gerencia papéis de parede, atalhos rápidos e widgets através do `SmartCaseActivity` e comandos `CasePageConfigFeature`.

---

## 5. Implementação no Aplicativo Linux (`jbl-linux-app`)

Todos os conhecimentos adquiridos na engenharia reversa foram transpostos diretamente para o código-fonte do cliente Linux:

- **Detecção Automática BlueZ (`core/bluetooth_backend.py`)**: Interroga a árvore de objetos D-Bus do BlueZ (`org.bluez.Device1`) para descobrir fones JBL pareados pelo nome e pelo Vendor ID Harman (`0ECB`).
- **Controlador BLE Assíncrono (`core/ble_controller.py`)**: Implementado com a biblioteca `bleak`, mantendo um loop assíncrono dedicado (`asyncio`) para conectar às características GATT `65786365-6c70-6f69-6e74-2e636f6d0001` (Notify) e `0002` (Write).
- **Tratamento de Protocolos Dual (`core/protocol.py`)**:
  - `Protocol3Handler`: Monta pacotes Harman `0xAA`, implementa o equalizador `EQSettings2` com empacotamento IEEE 754 float e decodifica a telemetria BES `0x03`.
  - `Protocol4Handler`: Monta e decodifica quadros `0xDCF0`, suportando troca de comandos com modelos da nova geração.
- **Registro de Dispositivos (`core/device_registry.py`)**:
  - Contém o banco de dados completo de **128 modelos** extraídos do APK original.
  - Carrega dinamicamente os recursos (`uiFeatures`) para exibir apenas os botões e controles suportados por aquele fone físico específico.
- **Interface Gráfica (`ui/main_window.py`)**:
  - Desenvolvida em **GTK4 + Libadwaita**, perfeitamente integrada aos ambientes GNOME e Linux modernos (modo claro/escuro automático).
  - Inclui sliders verticais para as 10 bandas do equalizador oficial da JBL e seletor rápido de modelos para fins de teste e simulação.

---

## 6. Conclusão

A engenharia reversa demonstrou que a Harman/JBL possui uma pilha de protocolos muito bem estruturada, combinando canais BLE GATT e RFCOMM para oferecer alta velocidade de resposta sem comprometer a estabilidade do fluxo de áudio estéreo (A2DP). 

O código e os dados extraídos fornecem paridade de recursos entre a plataforma móvel oficial e o sistema operacional Linux, viabilizando controle integral de cancelamento de ruído, equalização acústica de estúdio e monitoramento contínuo de baterias.
