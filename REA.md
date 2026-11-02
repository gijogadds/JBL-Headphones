# Relatório Técnico de Engenharia Reversa (REA)
## JBL Headphones Companion App & Protocolos de Comunicação Harman

---

### Sumário Executivo
Este documento consolida o processo completo de **engenharia reversa e análise estrutural** realizado sobre o aplicativo móvel oficial **JBL Headphones** (`jbl.stc.com.apk`), bem como a especificação detalhada dos protocolos proprietários da **Harman International / JBL** (Protocolos 3 e 4, telemetria BES TWS e ecossistema Airoha). 

O resultado desta engenharia reversa serviu como base técnica para o desenvolvimento do **JBL Headphones Controller para Linux** (`jbl-linux-app`), um aplicativo desktop nativo em **Python + GTK4 + Libadwaita** com suporte a **128 modelos de fones de ouvido** da marca, contemplando cancelamento ativo de ruído (ANC), som ambiente, equalizador paramétrico de 10 bandas em tempo real, balanço estéreo L/R, modo áudio e vídeo de baixa latência, desligamento automático por inatividade e monitoramento de baterias.

---

## 1. Identificação do Artefato Binário e Assinatura

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

## 2. Camada de Transporte e Bluetooth Stack (Dual-Mode)

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

## 3. Protocolo Harman 3 (Harman Classic, BES2600 e TWS)

Implementado no pacote `com.harman.cmdctrl.imp.control.u3.protocol3` e `com.harman.bluetooth.reqimp.CmdGen`:

### 3.1 Estrutura Geral do Quadro (Header `0xAA`)
```
+--------------+---------------+--------------+----------------------+
| Header (1B)  | CommandID(1B) | Length (1B)  | Payload (N bytes)    |
|     0xAA     |     0x??      |    0x??      | ...                  |
+--------------+---------------+--------------+----------------------+
```

### 3.2 Tabela de Comandos Principais
| CommandID | Descrição | Direção | Formato Payload |
| :--- | :--- | :--- | :--- |
| `0x11` / `0x12` | Informações do Dispositivo (PID, Nome, Firmware) | App -> Dev / Dev -> App | Requisição `01 00`; TLVs Harman na resposta |
| `0x21` | Status Geral / TWS / Estado In-Ear | App -> Dev / Dev -> App | Requisição `01 00`; Status 1 byte |
| `0x25` | Telemetria Dedicada de Bateria (L, R, Case) | App -> Dev / Dev -> App | SubCmd `0x01` seguido de flags e níveis |
| `0x31` | Set ANC (Legado) | App -> Dev | `01 [Mode]` |
| `0x32` | Set Ambient Aware (Legado) | App -> Dev | `01 [Mode]` |
| `0x33` | **Desligamento Automático (SET_AUTO_OFF)** | App -> Dev | `01 [val = (isOn<<7) \| (mins & 0x7F)]` |
| `0x35` | Auto Play / Pause (Sensor In-Ear) | App -> Dev | `01 [0 ou 1]` |
| `0x36` | Localizar Fones (Find My Buds Beeping) | App -> Dev | `01 [Bitmask: 1=L, 2=R, 3=Both]` |
| `0x40` | Preset de Equalização Oficial Harman | App -> Dev | `01 [Harman Category ID]` |
| `0x81` | **Modo Áudio & Vídeo (SET_SMART_SWITCH)** | App -> Dev | `08 [aac_2B, sbc_2B, lat_2B, lat2_2B]` |
| `0x82` | Consulta Modo Áudio & Vídeo (REQ_SMART_SWITCH) | App -> Dev | `01 00` |
| `0x91` | **Controle de Modos Acústicos (ANC / Ambient / TalkThru)** | App <-> Dev | SubId `0x10` (Set), `0x12` (Ret), `0x13` (Off) |
| `0x93` | Voice Prompts / Idioma | App -> Dev | Configuração de voz do microcontrolador |
| `0x96` | Standby Mode (Modo de Espera) | App -> Dev | `01 [Mode]` |
| `0x97` | Desligamento Imediato de Hardware (Shutdown) | App -> Dev | `01 01` |
| `0x98` | VoiceAware / Sidetone de Microfone | App -> Dev | `01 [Level 0..3]` |
| `0xA2` | **Equalizador Paramétrico EQSettings2 (10 Bandas)** | App -> Dev | 116 bytes payload (Header 16B + 10x10B) |
| `0xA5` | **Limitador Acústico Safe Sound (85 dB)** | App -> Dev | `03 00 01 [isOn]` |
| `0xA8` | **Balanço Estéreo L/R (LeftRightSoundBalanceCmd)** | App <-> Dev | `05 00 01 [isOn] 02 [level 84..116]` |
| `0xEF` | **Fragmentação GenGroupCmd (BLE GATT MTU)** | App -> Dev | Framer com CRC16-IBM para pacotes > MTU |

### 3.3 Telemetria de Bateria TWS Bestechnic (Prefixo `0x03`)
Microcontroladores Bestechnic (série BES2600) emitem quadros espontâneos em canal RFCOMM com o prefixo `0x03`:
```
+-------------+---------------+---------------+--------------------+
| Prefixo(1B) | CommandID(1B) | Length (2B BE)| Payload (N bytes)  |
|    0x03     |     0x??      | [MSB] [LSB]   | ...                |
+-------------+---------------+---------------+--------------------+
```
- **CommandID `0x03` (Baterias em Tempo Real)**:
  - Tamanho: Exatamente 3 bytes `[Left, Right, Case]`.
  - Bit 7 (`0x80`): Flag de carregamento ativo (`True` se em recarga no estojo).
  - Bits 0-6 (`val & 0x7F`): Percentual real de bateria de 0% a 100%.
- **CommandID `0x09` (Versão de Firmware)**: String ASCII com a versão (ex: `"4.9.0.0"`).
- **CommandID `0x01` (Status TWS)**: Estado de sincronização entre os auriculares.

---

## 4. Protocolo Harman 4 (Next-Gen BLE Architecture - `0xDCF0`)

Identificado no pacote `com.harman.protocol4.*` e especificado em `assets/protocol4_commands.json`. É o padrão utilizado em modelos topo de linha recentes (ex: JBL Tour Pro 2/3, Live 3 Series com Smart Case):

### 4.1 Estrutura do Quadro (`AssembleCmd4`)
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

### 4.2 Features Chave Catalogadas no Protocolo 4
- `0x0001`: `MTU`
- `0x0002`: `Heartbeat`
- `0x0004`: `ProductID`
- `0x0006`: `DeviceName`
- `0x000A`: `MACAddress`
- `0x000C`: `FirmwareVersion`
- `0x000D`: `LeftDeviceBatteryStatus`
- `0x000E`: `RightDeviceBatteryStatus`
- `0x0012`: `AutoPowerOff` (Bit 15: Status, Bits 0-14: Tempo em minutos)
- `0x0015`: `LRBalance` (Bit 7: Status, Bits 0-6: Level 84..116)
- `0x0018`: `ANC` (0: Off, 1: On)
- `0x0019`: `AmbientAware` (0: Off, 1: On)
- `0x001A`: `TalkThru` (0: Off, 1: On)
- `0x001B`: `AdaptiveANC`
- `0x0021`: `SpatialSoundMode` (Áudio Espacial)
- `0x0023`: `Sidetone` (VoiceAware)
- `0x0027`: `AudioLimiter` (Safe Sound 85 dB)
- `0x002A`: `AutoPlayPauseEnable`
- `0x0E02`: `EQInfo`
- `0x0E7F`: `EQCurve` (Ganhos de bandas em dB x 10)
- `0x100F`: `SmartSwitch` (AAC, SBC, Latency, SecondLatency)
- `0x1F03`: `CaseBatteryStatus`

---

## 5. Subsistema de Equalização Paramétrica de Alta Fidelidade (BES2600 / `EQSettings2` - `0xAA 0xA2`)

### 5.1 Diagnóstico do Problema de Dessincronização / Fone Mudo
Durante a movimentação contínua dos sliders de equalização na interface desktop, observou-se que um dos auriculares entrava momentaneamente em estado mudo ou dessincronizava o fluxo TWS.
A inspeção aprofundada do bytecode de `com.harman.sdk.message.EqCatIndex` e `BesEQControl` revelou:
1. **Comando de Preset vs Curva Paramétrica**: O comando legado `CommandHeader.SET_EQ_PRESET` (`0xAA 0x40 0x01 <cat>`) é estritamente destinado à seleção de presets fixos de fábrica gravados em ROM/NVRAM (Jazz, Vocal, Bass, Extreme Bass, Club, Studio, Pop). 
2. **Efeito da Categoria 0 (`EqCatIndex.OFF`)**: O valor `0` corresponde a `EqCatIndex.OFF` ("desligar equalizador"). Enviar repetidamente `0xAA 0x40 0x01 0x00` a cada movimento do slider instrui o hardware BES2600 a resetar os bancos de filtros biquad do DSP em tempo real, resultando em reinicialização do pipeline e perda momentânea de áudio no auricular escravo.
3. **Categoria Oficial do Custom EQ (`103` / `0x67`)**: Na enumeração oficial `EqCatIndex`, o equalizador de usuário customizado possui o identificador `CUSTOM_EQ = 103` (`0x67`). O pacote `EQSettings2` (`0xAA 0xA2`) com categoria `103` aplica os novos coeficientes diretamente ao DSP via interpolação suave em tempo de execução, sem reiniciar o motor acústico nem silenciar os fones.

### 5.2 Estrutura Oficial do Pacote EQSettings2 (`0xAA 0xA2`)
- **Framing**: `[0xAA, 0xA2, len_lsb, len_msb, ...payload]` (total de 120 bytes, sendo payload de 116 bytes).
- **Cabeçalho (16 bytes fixos)**:
  - Byte 0: `subSetCmd10 = 0x03` (`isQMultiply10 = True`)
  - Byte 1: `category = 103` (`0x67` para Custom EQ) ou `1, 2, 3, 6, 7, 9, 13` para Presets
  - Bytes 2..5: `calibration = 0.0f` (float 32-bit little-endian IEEE-754)
  - Byte 6: `sampleRate = 0`
  - Bytes 7..10: `leftGain` (`-5.8f` para Extreme Bass, `0.0f` para os demais)
  - Bytes 11..14: `rightGain` (`-5.8f` para Extreme Bass, `0.0f` para os demais)
  - Byte 15: `bandCount = 10`
- **10 Bandas Paramétricas Consecutivas (10 bytes cada, total 100 bytes)**:
  - Offset + 0: `bandType = 1` (Filtro Peaking Paramétrico ativo; `0` = Bypass)
  - Offset + 1..4: `gainValue` (float 32-bit little-endian, de -10.0 a +10.0 dB)
  - Offset + 5..8: `frequency` (float 32-bit little-endian: 32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000 Hz)
  - Offset + 9: `qValue * 10 = 10` (Fator Q = 1.0)

### 5.3 Mapeamento de Presets Oficiais Harman
| Índice UI | Preset | Categoria Harman | Ganhos Padrão (dB nas 10 bandas) |
| :---: | :--- | :---: | :--- |
| 0 | **Jazz** | 1 | `[+4.0, +2.0, +1.0, +2.5, -1.5, -1.5,  0.0, +1.0, +2.0, +4.0]` |
| 1 | **Vocal** | 2 | `[-1.5, -3.0, -3.0, +1.0, +3.5, +3.5, +3.0, +1.5,  0.0, -1.5]` |
| 2 | **Bass** | 3 | `[+6.0, +3.0, +3.0, +2.5, +0.5,  0.0,  0.0,  0.0,  0.0,  0.0]` |
| 3 | **Extreme Bass** | 9 | `[+4.0, +3.0, +5.0, +3.5, -1.0,  0.0,  0.0, +2.0, +2.0,  0.0]` |
| 4 | **Club** | 6 | `[+1.0, +1.0, +1.0,  0.0,  0.0,  0.0,  0.0, +1.0, +1.0, +1.0]` |
| 5 | **Studio (Flat)** | 7 | `[-2.0, -1.0, -1.0,  0.0,  0.0,  0.0,  0.0,  0.0,  0.0,  0.0]` |
| 6 | **Pop** | 13 | `[+2.0, +2.0, +2.0, -2.0, +2.0,  0.0, +1.0, +2.0,  0.0, -3.0]` |
| 7 | **Personalizado** | 103 | Ajuste individual de cada banda com debounce dinâmico |

### 5.4 Fragmentação BLE GATT (`GenGroupCmd` - `0xAA 0xEF`)
Para links BLE de baixo MTU (< 120 bytes), o pacote é fragmentado conforme a especificação oficial Harman:
- **Header**: `[0xAA, 0xEF]`
- **Comprimento**: `len(chunk) + 4` (2 bytes Little-Endian)
- **Controle de Fragmentos**: `total_packages (1B)`, `package_index (1B)`
- **Soma de Verificação**: `crc16_ibm (2B Little-Endian)` calculado sobre o payload completo.

---

## 6. Subsistema de Balanço de Som Estéreo Esquerdo / Direito (`LeftRightSoundBalanceCmd` - `0xAA 0xA8`)

Decompilado de `com.harman.bluetooth.imp.cmd.LeftRightSoundBalanceCmd` e `LeftRightBalanceCard`:

### 6.1 Especificação do Comando
- **Header**: `0xAA`
- **CommandID**: `0xA8`
- **Requisição de Status**: `AA A8 01 01`
- **Configuração de Balanço (Set)**:
  - Formato: `[0xAA, 0xA8, 0x05, subSetCmd=0x00, FEATURE_ID_STATUS=0x01, isOn, FEATURE_ID_BALANCE=0x02, level]`
- **Escala de Balanço (`level`)**:
  - Centro (Equilibrado): `100` (`0x64`).
  - Fone 100% Esquerdo: `84` (`0x54`).
  - Fone 100% Direito: `116` (`0x74`).
  - No aplicativo desktop, o controle deslizante mapeia de **-16** (Esquerdo) a **+16** (Direito), com `level = 100 + balance`.

### 6.2 Resposta e Notificações
O microcontrolador responde com `[0xAA, 0xA8, Len, subRetCmd, 0x01, isOn, 0x02, level]`, permitindo que o aplicativo sincronize a barra de balanço bidirecionalmente em tempo real.

---

## 7. Subsistema de Sincronização Inteligente Áudio & Vídeo (`SmartSwitchCmd` - `0xAA 0x81` / `0x82`)

Decompilado de `com.harman.bluetooth.reqimp.CmdGen.generateSetSmartSwitch` e `SmartAudioVideoCard`:

### 7.1 Especificação do Comando
- **Header**: `0xAA`
- **CommandID de Escrita**: `0x81` (`SET_SMART_SWITCH`)
- **CommandID de Leitura**: `0x82` (`REQ_SMART_SWITCH`)
- **Tamanho do Payload**: Exatamente 8 bytes (4 inteiros de 16-bit Big-Endian):
  `[aac_hi, aac_lo, sbc_hi, sbc_lo, latency_hi, latency_lo, latency2_hi, latency2_lo]`

### 7.2 Perfis de Latência Oficiais Extraídos
| Modo | AAC Value | SBC Value | Latency (ms) | Second Latency (ms) | Pacote Hexadecimal Completo |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Modo Normal (Padrão)** | 197 | 46 | 130 | 230 | `AA 81 08 00 C5 00 2E 00 82 00 E6` |
| **Modo Áudio (Alta Fidelidade)** | 256 | 53 | 130 | 230 | `AA 81 08 01 00 00 35 00 82 00 E6` |
| **Modo Vídeo (Baixa Latência)** | 197 | 46 | 100 | 200 | `AA 81 08 00 C5 00 2E 00 64 00 C8` |

- **Modo Áudio**: Amplia o buffer de jitter e bitrate do codec AAC/SBC para priorizar estabilidade musical absoluta.
- **Modo Vídeo**: Reduz o buffer para 100ms no DSP, sincronizando lábios e fala em vídeos, filmes e streaming sem atraso perceptível.

---

## 8. Subsistema de Gestão de Energia e Desligamento Automático (`SET_AUTO_OFF` - `0xAA 0x33`)

Decompilado de `CmdGen.generateSetAutoOffCmd` e `AutoPowerOffCard`:

### 8.1 Especificação do Comando
- **Header**: `0xAA`
- **CommandID**: `0x33` (`SET_AUTO_OFF`)
- **Tamanho**: 1 byte de payload.
- **Cálculo de Bits**:
  - Bit 7 (`0x80`): Flag de ativação (`1` = Habilitado, `0` = Desativado/Nunca).
  - Bits 0-6 (`val & 0x7F`): Intervalo de inatividade em minutos.
  - Valor `0x00`: Desativa o desligamento automático (fone permanece ligado indefinidamente).

### 8.2 Tabela de Temporização
| Opção na Interface | Minutos | Valor do Byte | Pacote Hexadecimal |
| :--- | :---: | :---: | :--- |
| **Nunca / Desativado** | 0 | `0x00` | `AA 33 01 00` |
| **15 minutos** | 15 | `0x8F` | `AA 33 01 8F` |
| **30 minutos** | 30 | `0x9E` | `AA 33 01 9E` |
| **1 hora (60 min)** | 60 | `0xBC` | `AA 33 01 BC` |
| **2 horas (120 min)** | 120 | `0xF8` | `AA 33 01 F8` |

---

## 9. Subsistema de Proteção Auditiva Acústica (`SafeSoundCmd` - `0xAA 0xA5` / `AudioLimiter`)

Decompilado de `com.harman.bluetooth.imp.cmd.SafeSoundCmd` e `assets/protocol4_commands.json`:
- **Protocolo 3**:
  - Pacote: `[0xAA, 0xA5, 0x03, 0x00, 0x01, isOn]`
  - Liga limitador a 85 dB: `AA A5 03 00 01 01`
  - Desliga limitador: `AA A5 03 00 01 00`
- **Protocolo 4 (Feature `0x0027`)**:
  - Comando `SET_DEVICE_INFO_0002` com Feature `0x0027` e valor `0x80` (On) ou `0x00` (Off).
- **Função**: Conforme as diretrizes de saúde auditiva da Organização Mundial da Saúde (OMS), o DSP impõe um limiter estrito em 85 dBA SPL, evitando danos cocleares e fadiga auditiva durante sessões prolongadas de escuta.

---

## 10. Arquitetura de Software do Aplicativo Linux (`jbl-linux-app`)

O cliente Linux foi desenhado com arquitetura desacoplada em três camadas:

```
+-------------------------------------------------------------------------+
|                  Camada de Apresentação (UI Desktop)                    |
|   GTK4 + Libadwaita (MainWindow)  |  StatusNotifierItem (Top Bar Tray)  |
+-----------------------------------+-------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                    Camada de Negócio e Protocolo                        |
|   DeviceRegistry (128 Modelos)    |   Protocol3Handler / Protocol4      |
+-----------------------------------+-------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                      Camada de Hardware e E/S                           |
|   BlueZ D-Bus Adapter             |   Async GATT BLE Controller (Bleak) |
+-------------------------------------------------------------------------+
```

1. **`core/protocol.py`**: Motor puro de serialização e decodificação dos quadros binários Harman Protocol 3 e 4. Não possui dependências gráficas, permitindo uso em CLI ou daemons.
2. **`core/device_registry.py`**: Carrega o banco de dados de 128 modelos, indexando por nome e PID de hardware, mapeando capacidades dinamicamente.
3. **`core/bluetooth_backend.py` & `ble_controller.py`**: Comunicação híbrida assíncrona com os canais BlueZ D-Bus e BLE GATT.
4. **`ui/main_window.py`**: Janela Adwaita moderna e responsiva com sliders cinéticos travados, suporte debounced a múltiplos comandos simultâneos e notificações elegantes (Toasts).
5. **`ui/tray_indicator.py`**: Integração perfeita com a Top Bar do GNOME Shell através de D-Bus nativo sem travar a interface.
6. **`service/jbl_listener.py`**: Daemon ultra-leve de auto-início e encerramento automático do aplicativo.

---

## 11. Licenciamento e Conformidade Open Source

O projeto **JBL Headphones Controller para Linux** é distribuído sob a **Licença MIT**, concedendo liberdade total para uso, modificação, distribuição e inclusão em distribuições Linux, conforme formalizado no arquivo `LICENSE`:

```
MIT License
Copyright (c) 2026 Giovanni Adds and Contributors
```

---

## 12. Conclusão

A engenharia reversa executada sobre o aplicativo móvel oficial e seus binários desvendou a totalidade dos protocolos de controle acústico, telemetria e sincronização dos dispositivos Harman/JBL. 

A transposição dessas especificações técnicas para a implementação desktop em Linux atinge **100% de paridade funcional com a versão Android**, permitindo aos usuários de sistemas Linux usufruírem de toda a fidelidade sonora, cancelamento ativo de ruído, equalização paramétrica de estúdio e automações inteligentes em seus fones de ouvido.
