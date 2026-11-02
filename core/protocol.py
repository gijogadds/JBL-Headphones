"""
Implementação dos Comandos do Protocolo Harman/JBL (Protocol 3 e 4).
Responsável por empacotar e desempacotar comandos binários.
"""

import struct
from enum import IntEnum
from typing import Dict, Any, Optional, List, Tuple

class AncMode(IntEnum):
    OFF = 0
    ANC = 1
    AMBIENT_AWARE = 2
    TALKTHRU = 3

class VoiceAwareLevel(IntEnum):
    OFF = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3

class Protocol3Handler:
    """Gerencia comandos do Protocolo 3 oficial da Harman (Header 0xAA)"""
    MAGIC = 0xAA

    # Comandos de Requisição Oficiais
    REQ_DEV_INFO = bytes([0xAA, 0x11, 0x01, 0x00])
    REQ_DEV_STATUS = bytes([0xAA, 0x21, 0x01, 0x00])
    REQ_BATTERY_INFO = bytes([0xAA, 0x25, 0x01, 0x00])
    REQ_TWS_STATUS = bytes([0xAA, 0x21, 0x01, 0x00])
    REQ_ANC_MODES = bytes([0xAA, 0x91, 0x01, 0x11])
    
    # IDs de comando
    CMD_ANC_MODES = 0x91
    CMD_SET_EQ_PRESET = 0x40
    CMD_SET_CUSTOM_EQ = 0x41
    CMD_SET_EQ2 = 0xA2
    CMD_SET_VOICE_AWARE = 0x98
    CMD_SET_FIND_BUDS = 0x36
    CMD_VOICE_PROMPT = 0x93

    # Frequências padrão do equalizador oficial JBL de 10 bandas
    EQ_FREQUENCIES = [32.0, 64.0, 125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 16000.0]

    @staticmethod
    def build_packet(cmd: int, payload: bytes) -> bytes:
        """Estrutura Harman padrão: [0xAA, cmd, len(payload), ...payload]"""
        return bytes([0xAA, cmd, len(payload)]) + payload

    @classmethod
    def set_anc_mode(cls, mode: AncMode) -> List[bytes]:
        """
        Alterna o modo de isolamento acústico utilizando os comandos oficiais Harman/BES:
        - ANC: Modo 1 = 1, Modo 2 = 0, Modo 3 = 0 (0xAA 0x91 0x07 0x10 0x01 0x01 0x02 0x00 0x03 0x00)
        - AMBIENT_AWARE: Modo 1 = 0, Modo 2 = 1, Modo 3 = 0 (0xAA 0x91 0x07 0x10 0x01 0x00 0x02 0x01 0x03 0x00)
        - TALKTHRU: Modo 1 = 0, Modo 2 = 0, Modo 3 = 1 (0xAA 0x91 0x07 0x10 0x01 0x00 0x02 0x00 0x03 0x01)
        - OFF: Desliga ANC, Som Ambiente e TalkThru (0xAA 0x91 0x01 0x13)
        """
        if mode == AncMode.ANC:
            # Modo 1 = 1 (ANC Ativado)
            return [bytes([0xAA, 0x91, 0x07, 0x10, 0x01, 0x01, 0x02, 0x00, 0x03, 0x00])]
        elif mode == AncMode.AMBIENT_AWARE:
            # Modo 2 = 1 (Ambient Aware Ativado)
            return [bytes([0xAA, 0x91, 0x07, 0x10, 0x01, 0x00, 0x02, 0x01, 0x03, 0x00])]
        elif mode == AncMode.TALKTHRU:
            # Modo 3 = 1 (TalkThru Ativado)
            return [bytes([0xAA, 0x91, 0x07, 0x10, 0x01, 0x00, 0x02, 0x00, 0x03, 0x01])]
        else: # OFF
            return [bytes([0xAA, 0x91, 0x01, 0x13])]

    # Mapeamento oficial Harman de predefinições para categorias do chip BES (standard_preset_eq.json)
    HARMAN_PRESET_MAP = {
        0: 1,   # Jazz -> Categoria 1
        1: 2,   # Vocal -> Categoria 2
        2: 3,   # Bass -> Categoria 3
        3: 9,   # Extreme Bass -> Categoria 9
        4: 6,   # Club -> Categoria 6
        5: 7,   # Studio -> Categoria 7
        6: 13,  # Pop -> Categoria 13
        7: 0,   # Personalizado / Custom -> Categoria 0
    }

    @classmethod
    def set_eq_preset(cls, preset_id: int) -> bytes:
        """
        Define o preset do equalizador oficial JBL de acordo com CommandHeader.SET_EQ_PRESET (0xAA 0x40):
        Categorias Harman BES oficiais:
        0 (Jazz): 1, 1 (Vocal): 2, 2 (Bass): 3, 3 (Extreme Bass): 9, 
        4 (Club): 6, 5 (Studio): 7, 6 (Pop): 13, 7 (Custom): 0
        """
        harman_cat = cls.HARMAN_PRESET_MAP.get(preset_id, preset_id)
        return bytes([0xAA, 0x40, 0x01, harman_cat & 0xFF])

    @classmethod
    def build_eq2_packet(cls, gains: List[float], preset_id: int = 0) -> bytes:
        """
        Monta o pacote oficial do Equalizador EQSettings2 (0xAA 0xA2) de alta fidelidade
        extraído do APK oficial (EQCmd.sendCmd / QMultiply10EQ).
        Utilizado por todos os fones modernos JBL BES (Tune Buds 2, Tune Beam 2, etc.).
        Header de 16 bytes:
          0: subSetCmd10 (0x03)
          1: category (1B, preset_id mapeado para Harman Category)
          2..5: calibration (4B float <f, 0.0)
          6: sampleRate (1B, 0)
          7..10: leftGain (4B float <f, 0.0)
          11..14: rightGain (4B float <f, 0.0)
          15: bandCount (1B, 10)
        Seguido por 10 bandas de 10 bytes cada:
          offset + 0: bandType (1B, 1 = Peaking filter ativo)
          offset + 1..4: gainValue (4B float <f)
          offset + 5..8: frequency (4B float <f)
          offset + 9: qValue * 10 (1B, 10 para Q=1.0)
        """
        harman_cat = cls.HARMAN_PRESET_MAP.get(preset_id, preset_id)
        sub_set_cmd_10 = 0x03  # isQMultiply10 = True
        category = harman_cat & 0xFF
        calibration = 0.0
        sample_rate = 0
        left_gain = 0.0
        right_gain = 0.0
        band_count = min(len(gains), len(cls.EQ_FREQUENCIES))
        
        payload = bytearray(16)
        payload[0] = sub_set_cmd_10
        payload[1] = category
        payload[2:6] = struct.pack("<f", calibration)
        payload[6] = sample_rate
        payload[7:11] = struct.pack("<f", left_gain)
        payload[11:15] = struct.pack("<f", right_gain)
        payload[15] = band_count
        
        for i in range(band_count):
            band_type = 1  # 1 = Peaking filter ativo (standard_preset_eq.json)
            gain_val = float(gains[i])
            freq_val = float(cls.EQ_FREQUENCIES[i])
            q_val = int(round(1.0 * 10))  # Q=1.0 * 10 = 10
            
            payload.append(band_type)
            payload.extend(struct.pack("<f", gain_val))
            payload.extend(struct.pack("<f", freq_val))
            payload.append(q_val & 0xFF)
            
        # combineLen2: [0xAA, 0xA2, len_lsb, len_msb, ...payload]
        length = len(payload)
        pkt = bytearray([0xAA, 0xA2, length & 0xFF, (length >> 8) & 0xFF])
        pkt.extend(payload)
        return bytes(pkt)

    @classmethod
    def set_custom_eq(cls, gains: List[float]) -> bytes:
        """Fallback para comando de equalização legado."""
        return cls.build_eq2_packet(gains)

    @classmethod
    def set_voice_aware(cls, level: VoiceAwareLevel) -> bytes:
        """Define o nível de retorno de voz durante chamadas"""
        return cls.build_packet(cls.CMD_SET_VOICE_AWARE, bytes([int(level)]))

    @classmethod
    def set_find_my_buds(cls, ring_left: bool, ring_right: bool) -> bytes:
        """Emite alerta sonoro para encontrar fones perdidos"""
        val = (1 if ring_left else 0) | ((2 if ring_right else 0))
        return cls.build_packet(cls.CMD_SET_FIND_BUDS, bytes([val]))

    @staticmethod
    def _extract_harman_feature(res: Dict[str, Any], fid: int, fval: bytes):
        """Extrai valores das features TLV padrão Harman/JBL."""
        if fid == 26 and len(fval) >= 2:
            res["charging_left"] = bool(fval[0])
            res["battery_left"] = fval[1]
        elif fid == 27 and len(fval) >= 2:
            res["charging_right"] = bool(fval[0])
            res["battery_right"] = fval[1]
        elif fid == 28 and len(fval) >= 2:
            res["charging_case"] = bool(fval[0])
            res["battery_case"] = fval[1]
        elif fid == 25 and len(fval) >= 2:
            res["charging_overall"] = bool(fval[0])
            res["battery_overall"] = fval[1]
        elif fid == 6 and len(fval) > 0:
            try:
                res["device_name"] = bytes(fval).decode("utf-8", errors="ignore").strip("\x00")
            except Exception:
                pass
        elif fid == 4 and len(fval) >= 2:
            res["pid"] = f"{fval[0]:02X}{fval[1]:02X}"
        elif fid == 12 and len(fval) > 0:
            try:
                res["firmware_version"] = bytes(fval).decode("utf-8", errors="ignore").strip("\x00")
            except Exception:
                pass

    @classmethod
    def parse_packet(cls, data: bytes) -> Dict[str, Any]:
        """Faz a interpretação de pacotes retornados pelo dispositivo (Protocolos BES e Harman)."""
        res: Dict[str, Any] = {}
        if not data or len(data) < 3:
            return res

        # 1. Parser do Protocolo BES TWS (Comandos com prefixo 0x03)
        idx = 0
        while idx + 4 <= len(data):
            prefix = data[idx]
            if prefix == 0x03:
                cmd_id = data[idx+1]
                pkt_len = (data[idx+2] << 8) | data[idx+3]
                if idx + 4 + pkt_len > len(data):
                    break
                payload = data[idx+4 : idx+4+pkt_len]

                # ID 0x03: Telemetria de Bateria TWS em Tempo Real (Left, Right, Case)
                # O pacote de bateria BES TWS possui exatamente 3 bytes: [Esquerdo, Direito, Estojo]
                # Cada byte possui o bit 7 (0x80) para indicar Carregamento, e bits 0-6 para porcentagem (0-100%)
                if cmd_id == 0x03 and pkt_len == 3:
                    raw_l, raw_r, raw_c = payload[0], payload[1], payload[2]
                    lvl_l = raw_l & 0x7F
                    lvl_r = raw_r & 0x7F
                    lvl_c = raw_c & 0x7F
                    if lvl_l <= 100 and lvl_r <= 100 and lvl_c <= 100:
                        res["battery_left"] = lvl_l
                        res["charging_left"] = bool(raw_l & 0x80)
                        res["battery_right"] = lvl_r
                        res["charging_right"] = bool(raw_r & 0x80)
                        res["battery_case"] = lvl_c
                        res["charging_case"] = bool(raw_c & 0x80)

                # ID 0x09: Versão Oficial de Firmware (ex: '4.9.0.0')
                elif cmd_id == 0x09 and len(payload) > 0:
                    try:
                        res["firmware_version"] = payload.decode("utf-8", errors="ignore").strip()
                    except Exception:
                        pass

                # ID 0x01: Status de Conexão TWS
                elif cmd_id == 0x01 and len(payload) >= 1:
                    res["tws_status"] = payload[0]

                idx += 4 + pkt_len
            else:
                idx += 1

        # 2. Parser do Protocolo Harman Clássico (Header 0xAA)
        if 0xAA in data:
            pos_aa = data.find(0xAA)
            if pos_aa + 3 <= len(data):
                cmd = data[pos_aa+1]
                length = data[pos_aa+2]
                payload = data[pos_aa+3 : pos_aa+3+length]

                # Informações do Dispositivo (0x11 ou 0x12)
                # Suporta formato estruturado TLV oficial do Harman Command3 e legado
                if cmd in (0x11, 0x12):
                    parsed_tlv = False

                    # 1. Decodificador oficial Harman Command3 (16-bit payloadLen LSB/MSB + payloadType no byte 4)
                    if pos_aa + 4 <= len(data):
                        cmd3_len = data[pos_aa+2] | (data[pos_aa+3] << 8)
                        if pos_aa + 4 + cmd3_len <= len(data) and cmd3_len >= 1:
                            t_idx = pos_aa + 5  # pula payloadType no byte pos_aa+4
                            end_tlv = pos_aa + 4 + cmd3_len
                            while t_idx + 3 <= end_tlv:
                                fid = (data[t_idx] << 8) | data[t_idx+1]
                                flen = data[t_idx+2]
                                if t_idx + 3 + flen > end_tlv:
                                    break
                                fval = data[t_idx+3 : t_idx+3+flen]
                                if fid in (4, 6, 12, 25, 26, 27, 28):
                                    parsed_tlv = True
                                    cls._extract_harman_feature(res, fid, fval)
                                t_idx += 3 + flen

                    # 2. Varredura flexível de TLVs sobre o payload
                    if not parsed_tlv and len(payload) >= 3:
                        for try_start in (0, 1, 2):
                            p_idx = try_start
                            while p_idx + 3 <= len(payload):
                                fid = (payload[p_idx] << 8) | payload[p_idx+1]
                                flen = payload[p_idx+2]
                                if flen == 0 or p_idx + 3 + flen > len(payload):
                                    break
                                fval = payload[p_idx+3 : p_idx+3+flen]
                                if fid in (4, 6, 12, 25, 26, 27, 28):
                                    parsed_tlv = True
                                    cls._extract_harman_feature(res, fid, fval)
                                p_idx += 3 + flen
                            if parsed_tlv:
                                break

                    # 2. Fallback para cabeçalhos legados de posição fixa
                    if not parsed_tlv and len(payload) >= 18:
                        try:
                            raw_name = payload[0:16].split(b'\x00')[0]
                            res["device_name"] = raw_name.decode("utf-8", errors="ignore").strip()
                        except Exception:
                            pass
                        res["pid"] = f"{payload[16]:02X}{payload[17]:02X}"
                        if len(payload) >= 20 and "battery_left" not in res:
                            res["battery_left"] = payload[18] & 0x7F
                            res["charging_left"] = bool(payload[18] & 0x80)
                        if len(payload) >= 21 and "battery_right" not in res:
                            res["battery_right"] = payload[19] & 0x7F
                            res["charging_right"] = bool(payload[19] & 0x80)
                        if len(payload) >= 22 and "battery_case" not in res:
                            res["battery_case"] = payload[20] & 0x7F
                            res["charging_case"] = bool(payload[20] & 0x80)

                # Resposta de Bateria Específica (0x25)
                # Formato oficial Harman (BatteryInfoCmd.parseBatteryInfo):
                # payload[0] = subCommand (1 = Battery Status)
                # payload[1] = leftChargeStatus, payload[2] = rightChargeStatus
                # payload[3] = leftBatteryLevel, payload[4] = rightBatteryLevel
                # payload[5] = boxChargeStatus,  payload[6] = boxBatteryLevel
                elif cmd == 0x25 and len(payload) >= 5:
                    sub_cmd = payload[0]
                    if sub_cmd == 1 and len(payload) >= 5:
                        res["charging_left"] = bool(payload[1])
                        res["charging_right"] = bool(payload[2])
                        res["battery_left"] = payload[3]
                        res["battery_right"] = payload[4]
                        if len(payload) >= 7:
                            res["charging_case"] = bool(payload[5])
                            res["battery_case"] = payload[6]
                    elif len(payload) >= 3 and payload[0] <= 100:
                        # Fallback clássico 3-byte BES TWS [L, R, Case]
                        res["battery_left"] = payload[0] & 0x7F
                        res["charging_left"] = bool(payload[0] & 0x80)
                        res["battery_right"] = payload[1] & 0x7F
                        res["charging_right"] = bool(payload[1] & 0x80)
                        res["battery_case"] = payload[2] & 0x7F
                        res["charging_case"] = bool(payload[2] & 0x80)

                # Status de Modos de Som / ANC / Ambient / TalkThru (0x91)
                elif cmd == 0x91:
                    # Formato oficial Harman (HandleParse.parseData):
                    # subCmd 0x13 = Todos os modos desligados (OFF)
                    # subCmd 0x10 ou 0x12 = Lista de pares (type, value) onde type 1=ANC, 2=Ambient, 3=TalkThru
                    if len(payload) >= 1 and payload[0] == 0x13:
                        res["anc_mode"] = AncMode.OFF
                    elif len(payload) >= 3 and payload[0] in (0x10, 0x12):
                        pair_count = (len(payload) - 1) // 2
                        active_mode = AncMode.OFF
                        for p in range(pair_count):
                            t_id = payload[1 + p * 2]
                            val = payload[2 + p * 2]
                            if val != 0:
                                if t_id == 1:
                                    active_mode = AncMode.ANC
                                elif t_id == 2:
                                    active_mode = AncMode.AMBIENT_AWARE
                                elif t_id == 3:
                                    active_mode = AncMode.TALKTHRU
                        res["anc_mode"] = active_mode
                    elif len(payload) == 1:
                        # Resposta simples com 1 byte de status/filtro
                        f_val = payload[0]
                        if f_val == 1:
                            res["anc_mode"] = AncMode.ANC
                        elif f_val == 2:
                            res["anc_mode"] = AncMode.AMBIENT_AWARE
                        elif f_val == 3:
                            res["anc_mode"] = AncMode.TALKTHRU
                        elif f_val == 0:
                            res["anc_mode"] = AncMode.OFF

                # Status geral (0x21)
                elif cmd == 0x21:
                    if len(payload) >= 1:
                        res["anc_status"] = payload[0]

        # 3. Parser de ACK de comando BES (ex: '07 10 00 00')
        if b'\x07\x10\x00\x00' in data:
            res["cmd_ack"] = "ANC_OK"

        # 4. Parser de Protocolo 4 da Harman (Header 0xDCF0 em Little-Endian: [0xF0, 0xDC])
        if len(data) >= 8 and data[0] == 0xF0 and data[1] == 0xDC:
            p4_info = Protocol4Handler.parse_packet(data)
            res.update(p4_info)

        return res

class Protocol4Handler:
    """
    Gerenciador de Comandos do Protocolo 4 Oficial Harman/JBL (Header 0xDCF0).
    Utilizado na nova geração de fones Harman (Tour Pro 2/3, Live 3 Series, Soundgear, etc.).
    Totalmente engenheirado a partir de com.harman.protocol4.AssembleCmd4 e DeviceInfoList4Cmd.
    """
    HEADER_IDENTIFIER = 0xDCF0          # ConstCmd4.HEADER_IDENTIFIER
    HEADER_IDENTIFIER_FORWARD = 0xDCF1  # ConstCmd4.HEADER_IDENTIFIER_FORWARD

    # HeaderCommandID
    CMD_GET_DEVICE_INFO = 0x0001
    CMD_SET_DEVICE_INFO = 0x0002
    CMD_NOTIFY_APP = 0x0003
    CMD_NOTIFY_DEVICE = 0x0004
    CMD_RESET_FACTORY = 0x00FF

    # Mapeamento oficial de Features (protocol4_commands.json)
    FEATURE_MTU = 0x0001
    FEATURE_HEARTBEAT = 0x0002
    FEATURE_PRODUCT_ID = 0x0004
    FEATURE_COLOR_ID = 0x0005
    FEATURE_DEVICE_NAME = 0x0006
    FEATURE_MAC = 0x000A
    FEATURE_FIRMWARE = 0x000C
    FEATURE_BATTERY_LEFT = 0x000D
    FEATURE_BATTERY_RIGHT = 0x000E
    FEATURE_CASE_BATTERY = 0x1F03
    FEATURE_ANC = 0x0018
    FEATURE_AMBIENT_AWARE = 0x0019
    FEATURE_TALKTHRU = 0x001A
    FEATURE_ADAPTIVE_ANC = 0x001B
    FEATURE_SPATIAL_MODE = 0x0021
    FEATURE_SIDETONE = 0x0023  # VoiceAware
    FEATURE_AUDIO_LIMITER = 0x0027
    FEATURE_EQ_INFO = 0x0E02
    FEATURE_EQ_CURVE = 0x0E7F

    @classmethod
    def build_packet(cls, cmd_id: int, payload: bytes = b'', mtu: int = 512) -> List[bytes]:
        """
        Monta lista de quadros Protocol 4 conforme AssembleCmd4.generateCmdList:
        [ID_LSB, ID_MSB, CMD_LSB, CMD_MSB, PacketCount, PacketIndex, Size_LSB, Size_MSB, ...Payload]
        """
        if not payload:
            # Pacote sem payload: tamanho 0 (2 bytes nulos)
            pkt = bytearray([
                cls.HEADER_IDENTIFIER & 0xFF,
                (cls.HEADER_IDENTIFIER >> 8) & 0xFF,
                cmd_id & 0xFF,
                (cmd_id >> 8) & 0xFF,
                1,  # PacketCount
                0,  # PacketIndex
                0,  # Size LSB
                0   # Size MSB
            ])
            return [bytes(pkt)]

        packets = []
        payload_len = len(payload)
        packet_count = (payload_len + mtu - 1) // mtu if mtu > 0 else 1

        for idx in range(packet_count):
            start = idx * mtu
            chunk = payload[start : start + mtu]
            chunk_len = len(chunk)

            pkt = bytearray([
                cls.HEADER_IDENTIFIER & 0xFF,
                (cls.HEADER_IDENTIFIER >> 8) & 0xFF,
                cmd_id & 0xFF,
                (cmd_id >> 8) & 0xFF,
                packet_count & 0xFF,
                idx & 0xFF,
                chunk_len & 0xFF,
                (chunk_len >> 8) & 0xFF
            ])
            pkt.extend(chunk)
            packets.append(bytes(pkt))

        return packets

    @classmethod
    def build_get_features(cls, feature_ids: List[int]) -> List[bytes]:
        """Gera comando de leitura (GET_DEVICE_INFO_0001) para uma lista de Feature IDs"""
        payload = bytearray()
        for fid in feature_ids:
            payload.append(fid & 0xFF)
            payload.append((fid >> 8) & 0xFF)
        return cls.build_packet(cls.CMD_GET_DEVICE_INFO, bytes(payload))

    @classmethod
    def build_set_feature_byte(cls, feature_id: int, value: int) -> List[bytes]:
        """Gera comando de escrita (SET_DEVICE_INFO_0002) para uma feature de 1 byte"""
        payload = bytearray([
            feature_id & 0xFF,
            (feature_id >> 8) & 0xFF,
            value & 0xFF
        ])
        return cls.build_packet(cls.CMD_SET_DEVICE_INFO, bytes(payload))

    @classmethod
    def set_anc_mode(cls, mode: AncMode) -> List[bytes]:
        """Configura ANC / Som Ambiente / TalkThru no Protocolo 4"""
        if mode == AncMode.ANC:
            # Liga ANC (0x18 = 1), Desliga AA (0x19 = 0), Desliga TT (0x1A = 0)
            payload = bytes([
                cls.FEATURE_ANC & 0xFF, (cls.FEATURE_ANC >> 8) & 0xFF, 1,
                cls.FEATURE_AMBIENT_AWARE & 0xFF, (cls.FEATURE_AMBIENT_AWARE >> 8) & 0xFF, 0,
                cls.FEATURE_TALKTHRU & 0xFF, (cls.FEATURE_TALKTHRU >> 8) & 0xFF, 0,
            ])
        elif mode == AncMode.AMBIENT_AWARE:
            payload = bytes([
                cls.FEATURE_ANC & 0xFF, (cls.FEATURE_ANC >> 8) & 0xFF, 0,
                cls.FEATURE_AMBIENT_AWARE & 0xFF, (cls.FEATURE_AMBIENT_AWARE >> 8) & 0xFF, 1,
                cls.FEATURE_TALKTHRU & 0xFF, (cls.FEATURE_TALKTHRU >> 8) & 0xFF, 0,
            ])
        elif mode == AncMode.TALKTHRU:
            payload = bytes([
                cls.FEATURE_ANC & 0xFF, (cls.FEATURE_ANC >> 8) & 0xFF, 0,
                cls.FEATURE_AMBIENT_AWARE & 0xFF, (cls.FEATURE_AMBIENT_AWARE >> 8) & 0xFF, 0,
                cls.FEATURE_TALKTHRU & 0xFF, (cls.FEATURE_TALKTHRU >> 8) & 0xFF, 1,
            ])
        else:
            payload = bytes([
                cls.FEATURE_ANC & 0xFF, (cls.FEATURE_ANC >> 8) & 0xFF, 0,
                cls.FEATURE_AMBIENT_AWARE & 0xFF, (cls.FEATURE_AMBIENT_AWARE >> 8) & 0xFF, 0,
                cls.FEATURE_TALKTHRU & 0xFF, (cls.FEATURE_TALKTHRU >> 8) & 0xFF, 0,
            ])
        return cls.build_packet(cls.CMD_SET_DEVICE_INFO, payload)

    @classmethod
    def build_eq_curve_packet(cls, gains_db: List[float]) -> List[bytes]:
        """
        Gera pacotes Protocol 4 para envio da curva de equalização (Feature 0x0E7F - EQCurve).
        Compatível com a especificação de comando SET_DEVICE_INFO (0x0002).
        """
        payload = bytearray([
            cls.FEATURE_EQ_CURVE & 0xFF,
            (cls.FEATURE_EQ_CURVE >> 8) & 0xFF,
            len(gains_db) & 0xFF
        ])
        for g in gains_db:
            val = int(round(g * 10))
            if val < 0:
                val = (val + 256) & 0xFF
            payload.append(val & 0xFF)
        return cls.build_packet(cls.CMD_SET_DEVICE_INFO, bytes(payload))

    @classmethod
    def parse_packet(cls, data: bytes) -> Dict[str, Any]:
        """Faz a interpretação de respostas e notificações do Protocolo 4"""
        res: Dict[str, Any] = {}
        if len(data) < 8:
            return res

        header_id = data[0] | (data[1] << 8)
        if header_id not in (cls.HEADER_IDENTIFIER, cls.HEADER_IDENTIFIER_FORWARD):
            return res

        cmd_id = data[2] | (data[3] << 8)
        pkt_count = data[4]
        pkt_index = data[5]
        payload_size = data[6] | (data[7] << 8)

        if len(data) < 8 + payload_size:
            return res

        payload = data[8 : 8 + payload_size]
        res["proto4_cmd_id"] = cmd_id

        # Se for notificação ou resposta de telemetria / confirmação
        if cmd_id in (cls.CMD_GET_DEVICE_INFO, cls.CMD_NOTIFY_APP, cls.CMD_SET_DEVICE_INFO):
            idx = 0
            while idx + 2 <= len(payload):
                fid = payload[idx] | (payload[idx+1] << 8)
                idx += 2

                if fid == cls.FEATURE_ANC and idx < len(payload):
                    val = payload[idx]
                    idx += 1
                    if val == 1:
                        res["anc_mode"] = AncMode.ANC
                elif fid == cls.FEATURE_AMBIENT_AWARE and idx < len(payload):
                    val = payload[idx]
                    idx += 1
                    if val == 1:
                        res["anc_mode"] = AncMode.AMBIENT_AWARE
                elif fid == cls.FEATURE_TALKTHRU and idx < len(payload):
                    val = payload[idx]
                    idx += 1
                    if val == 1:
                        res["anc_mode"] = AncMode.TALKTHRU
                elif fid == cls.FEATURE_BATTERY_LEFT and idx < len(payload):
                    res["battery_left"] = payload[idx] & 0x7F
                    res["charging_left"] = bool(payload[idx] & 0x80)
                    idx += 1
                elif fid == cls.FEATURE_BATTERY_RIGHT and idx < len(payload):
                    res["battery_right"] = payload[idx] & 0x7F
                    res["charging_right"] = bool(payload[idx] & 0x80)
                    idx += 1
                elif fid == cls.FEATURE_CASE_BATTERY and idx < len(payload):
                    res["battery_case"] = payload[idx] & 0x7F
                    res["charging_case"] = bool(payload[idx] & 0x80)
                    idx += 1
                elif fid == cls.FEATURE_SIDETONE and idx < len(payload):
                    res["voice_aware_level"] = payload[idx]
                    idx += 1
                else:
                    # Para features desconhecidas, pula 1 byte
                    idx += 1

        return res
