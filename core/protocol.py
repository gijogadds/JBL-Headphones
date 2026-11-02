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
    CMD_SET_AUTO_OFF = 0x33
    CMD_SET_SMART_SWITCH = 0x81
    CMD_REQ_SMART_SWITCH = 0x82
    CMD_SET_SAFE_SOUND = 0xA5
    CMD_SET_LR_BALANCE = 0xA8

    # Comandos de Requisição Adicionais Oficiais
    REQ_AUTO_OFF = bytes([0xAA, 0x33, 0x01, 0x00])
    REQ_SMART_SWITCH = bytes([0xAA, 0x82, 0x01, 0x00])
    REQ_LR_BALANCE = bytes([0xAA, 0xA8, 0x01, 0x01])
    REQ_SAFE_SOUND = bytes([0xAA, 0xA5, 0x01, 0x01])

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

    # Mapeamento oficial Harman de predefinições para categorias do chip BES (standard_preset_eq.json & EqCatIndex)
    HARMAN_PRESET_MAP = {
        0: 1,    # Jazz -> Categoria 1
        1: 2,    # Vocal -> Categoria 2
        2: 3,    # Bass -> Categoria 3
        3: 9,    # Extreme Bass -> Categoria 9
        4: 6,    # Club -> Categoria 6
        5: 7,    # Studio -> Categoria 7
        6: 13,   # Pop -> Categoria 13
        7: 103,  # Personalizado / Custom -> Categoria 103 (0x67, EqCatIndex.CUSTOM_EQ)
    }

    # Tabela CRC16-IBM / ARC para fragmentação oficial Harman GenGroupCmd (0xAA 0xEF)
    CRC16_TABLE = [
        0x0000, 0xC0C1, 0xC181, 0x0140, 0xC301, 0x03C0, 0x0280, 0xC241,
        0xC601, 0x06C0, 0x0780, 0xC741, 0x0500, 0xC5C1, 0xC481, 0x0440,
        0xCC01, 0x0CC0, 0x0D80, 0xCD41, 0x0F00, 0xCFC1, 0xCE81, 0x0E40,
        0x0A00, 0xCAC1, 0xCB81, 0x0B40, 0xC901, 0x09C0, 0x0880, 0xC841,
        0xD801, 0x18C0, 0x1980, 0xD941, 0x1B00, 0xDBC1, 0xDA81, 0x1A40,
        0x1E00, 0xDEC1, 0xDF81, 0x1F40, 0xDD01, 0x1DC0, 0x1C80, 0xDC41,
        0x1400, 0xD4C1, 0xD581, 0x1540, 0xD701, 0x17C0, 0x1680, 0xD641,
        0xD201, 0x12C0, 0x1380, 0xD341, 0x1100, 0xD1C1, 0xD081, 0x1040,
        0xF001, 0x30C0, 0x3180, 0xF141, 0x3300, 0xF3C1, 0xF281, 0x3240,
        0x3600, 0xF6C1, 0xF781, 0x3740, 0xF501, 0x35C0, 0x3480, 0xF441,
        0x3C00, 0xFCC1, 0xFD81, 0x3D40, 0xFF01, 0x3FC0, 0x3E80, 0xFE41,
        0xFA01, 0x3AC0, 0x3B80, 0xFB41, 0x3900, 0xF9C1, 0xF881, 0x3840,
        0x2800, 0xE8C1, 0xE981, 0x2940, 0xEB01, 0x2BC0, 0x2A80, 0xEA41,
        0xEE01, 0x2EC0, 0x2F80, 0xEF41, 0x2D00, 0xEDC1, 0xEC81, 0x2C40,
        0xE401, 0x24C0, 0x2580, 0xE541, 0x2700, 0xE7C1, 0xE681, 0x2640,
        0x2200, 0xE2C1, 0xE381, 0x2340, 0xE101, 0x21C0, 0x2080, 0xE041,
        0xA001, 0x60C0, 0x6180, 0xA141, 0x6300, 0xA3C1, 0xA281, 0x6240,
        0x6600, 0xA6C1, 0xA781, 0x6740, 0xA501, 0x65C0, 0x6480, 0xA441,
        0x6C00, 0xACC1, 0xAD81, 0x6D40, 0xAF01, 0x6FC0, 0x6E80, 0xAE41,
        0xAA01, 0x6AC0, 0x6B80, 0xAB41, 0x6900, 0xA9C1, 0xA881, 0x6840,
        0x7800, 0xB8C1, 0xB981, 0x7940, 0xBB01, 0x7BC0, 0x7A80, 0xBA41,
        0xBE01, 0x7EC0, 0x7F80, 0xBF41, 0x7D00, 0xBDC1, 0xBC81, 0x7C40,
        0xB401, 0x74C0, 0x7580, 0xB541, 0x7700, 0xB7C1, 0xB681, 0x7640,
        0x7200, 0xB2C1, 0xB381, 0x7340, 0xB101, 0x71C0, 0x7080, 0xB041,
        0x5000, 0x90C1, 0x9181, 0x5140, 0x9301, 0x53C0, 0x5280, 0x9241,
        0x9601, 0x56C0, 0x5780, 0x9741, 0x5500, 0x95C1, 0x9481, 0x5440,
        0x9C01, 0x5CC0, 0x5D80, 0x9D41, 0x5F00, 0x9FC1, 0x9E81, 0x5E40,
        0x5A00, 0x9AC1, 0x9B81, 0x5B40, 0x9901, 0x59C0, 0x5880, 0x9841,
        0x8801, 0x48C0, 0x4980, 0x8941, 0x4B00, 0x8BC1, 0x8A81, 0x4A40,
        0x4E00, 0x8EC1, 0x8F81, 0x4F40, 0x8D01, 0x4DC0, 0x4C80, 0x8C41,
        0x4400, 0x84C1, 0x8581, 0x4540, 0x8701, 0x47C0, 0x4680, 0x8641,
        0x8201, 0x42C0, 0x4380, 0x8341, 0x4100, 0x81C1, 0x8081, 0x4040
    ]

    @classmethod
    def calc_crc16(cls, data: bytes) -> int:
        """Calcula CRC16-IBM / ARC usado nos pacotes oficiais GenGroupCmd."""
        crc = 0
        for b in data:
            crc = ((crc >> 8) & 0xFF) ^ cls.CRC16_TABLE[(crc ^ b) & 0xFF]
        return crc & 0xFFFF

    @classmethod
    def fragment_packet(cls, data: bytes, chunk_size: int = 18) -> List[bytes]:
        """
        Divide pacotes grandes usando o protocolo oficial Harman GenGroupCmd (0xAA 0xEF).
        Formato: [0xAA, 0xEF, len_lsb, len_msb, packageCount, packageIndex, crc_lsb, crc_msb, ...chunk]
        Onde len = len(chunk) + 4.
        """
        if len(data) <= chunk_size:
            return [data]
        total = (len(data) + chunk_size - 1) // chunk_size
        crc = cls.calc_crc16(data)
        fragments = []
        for i in range(total):
            chunk = data[i * chunk_size : (i + 1) * chunk_size]
            length = len(chunk) + 4
            pkt = bytearray([
                0xAA, 0xEF,
                length & 0xFF, (length >> 8) & 0xFF,
                total & 0xFF, i & 0xFF,
                crc & 0xFF, (crc >> 8) & 0xFF
            ])
            pkt.extend(chunk)
            fragments.append(bytes(pkt))
        return fragments

    @classmethod
    def set_eq_preset(cls, preset_id: int) -> bytes:
        """
        Define o preset do equalizador oficial JBL de acordo com CommandHeader.SET_EQ_PRESET (0xAA 0x40):
        Categorias Harman BES oficiais:
        0 (Jazz): 1, 1 (Vocal): 2, 2 (Bass): 3, 3 (Extreme Bass): 9, 
        4 (Club): 6, 5 (Studio): 7, 6 (Pop): 13
        """
        harman_cat = cls.HARMAN_PRESET_MAP.get(preset_id, preset_id)
        return bytes([0xAA, 0x40, 0x01, harman_cat & 0xFF])

    @classmethod
    def build_eq2_packet(cls, gains: List[float], preset_id: int = 7) -> bytes:
        """
        Monta o pacote oficial do Equalizador EQSettings2 (0xAA 0xA2) de alta fidelidade
        extraído do APK oficial (EQCmd.sendCmd / QMultiply10EQ).
        Utilizado por todos os fones modernos JBL BES (Tune Buds 2, Tune Beam 2, etc.).
        Header de 16 bytes:
          0: subSetCmd10 (0x03)
          1: category (1B, preset_id mapeado para Harman Category: 103 para Custom EQ)
          2..5: calibration (4B float <f, 0.0)
          6: sampleRate (1B, 0)
          7..10: leftGain (4B float <f, 0.0 ou -5.8 para Extreme Bass)
          11..14: rightGain (4B float <f, 0.0 ou -5.8 para Extreme Bass)
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
        left_gain = -5.8 if harman_cat == 9 else 0.0
        right_gain = -5.8 if harman_cat == 9 else 0.0
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

    @classmethod
    def set_auto_power_off(cls, timeout_minutes: int, enabled: bool = True) -> bytes:
        """
        Define o desligamento automático por inatividade do fone (SET_AUTO_OFF = 0xAA 0x33).
        Payload: 1 byte: bit 7 (0x80) indica habilitado, bits 0-6 representam minutos (ex: 15, 30, 60, 120).
        Valor 0x00 desativa o desligamento automático (Nunca desligar).
        """
        if not enabled or timeout_minutes <= 0:
            val = 0x00
        else:
            val = 0x80 | (timeout_minutes & 0x7F)
        return cls.build_packet(cls.CMD_SET_AUTO_OFF, bytes([val]))

    @classmethod
    def set_lr_balance(cls, balance: int, enabled: bool = True) -> bytes:
        """
        Define o balanço de som estéreo Esquerdo / Direito (LeftRightSoundBalanceCmd = 0xAA 0xA8).
        balance: valor relativo de -16 (100% Esquerdo) até +16 (100% Direito), sendo 0 o centro equilibrado.
        No protocolo oficial: level = 100 + balance (intervalo de 84 a 116, sendo 100 o centro).
        Quadro: [0xAA, 0xA8, 0x05, subSetCmd=0x00, FEATURE_STATUS=0x01, isOn, FEATURE_BALANCE=0x02, level]
        """
        level = max(84, min(116, 100 + balance))
        is_on = 1 if enabled else 0
        payload = bytes([0x00, 0x01, is_on, 0x02, level])
        return cls.build_packet(cls.CMD_SET_LR_BALANCE, payload)

    @classmethod
    def set_smart_audio_video(cls, mode: str = "normal") -> bytes:
        """
        Define o modo de sincronização inteligente de áudio e vídeo (Smart Audio & Video = 0xAA 0x81).
        Alterna entre baixa latência para vídeos/jogos e alta fidelidade para música.
        mode:
          - "audio": Modo Música (Alta Fidelidade) -> [256, 53, 130, 230]
          - "video": Modo Vídeo (Baixa Latência)   -> [197, 46, 100, 200]
          - "normal": Modo Padrão                 -> [197, 46, 130, 230]
        Quadro: [0xAA, 0x81, 0x08, aac_hi, aac_lo, sbc_hi, sbc_lo, lat_hi, lat_lo, lat2_hi, lat2_lo]
        """
        mode = mode.lower()
        if mode == "video":
            aac, sbc, lat, lat2 = 197, 46, 100, 200
        elif mode == "audio":
            aac, sbc, lat, lat2 = 256, 53, 130, 230
        else: # normal
            aac, sbc, lat, lat2 = 197, 46, 130, 230

        payload = bytes([
            (aac >> 8) & 0xFF, aac & 0xFF,
            (sbc >> 8) & 0xFF, sbc & 0xFF,
            (lat >> 8) & 0xFF, lat & 0xFF,
            (lat2 >> 8) & 0xFF, lat2 & 0xFF
        ])
        return cls.build_packet(cls.CMD_SET_SMART_SWITCH, payload)

    @classmethod
    def set_safe_sound(cls, enabled: bool) -> bytes:
        """
        Define o limitador acústico de proteção auditiva Safe Sound a 85 dB (SafeSoundCmd = 0xAA 0xA5).
        """
        payload = bytes([0x00, 0x01, 1 if enabled else 0])
        return cls.build_packet(cls.CMD_SET_SAFE_SOUND, payload)

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

                # Desligamento Automático por Inatividade (0x33)
                elif cmd == 0x33 and len(payload) >= 1:
                    raw_val = payload[0]
                    res["auto_off_enabled"] = bool(raw_val & 0x80)
                    res["auto_off_minutes"] = raw_val & 0x7F

                # Balanço Esquerdo / Direito (0xA8)
                elif cmd == 0xA8 and len(payload) >= 4:
                    for idx_b in range(len(payload) - 1):
                        if payload[idx_b] == 0x01:
                            res["lr_balance_enabled"] = bool(payload[idx_b + 1])
                        elif payload[idx_b] == 0x02:
                            lvl = payload[idx_b + 1]
                            res["lr_balance_level"] = lvl
                            res["lr_balance_offset"] = lvl - 100

                # Modo Smart Audio & Video (0x81 ou 0x82)
                elif cmd in (0x81, 0x82) and len(payload) >= 8:
                    aac = (payload[0] << 8) | payload[1]
                    sbc = (payload[2] << 8) | payload[3]
                    lat = (payload[4] << 8) | payload[5]
                    lat2 = (payload[6] << 8) | payload[7]
                    res["smart_switch_aac"] = aac
                    res["smart_switch_sbc"] = sbc
                    res["smart_switch_latency"] = lat
                    if lat <= 100:
                        res["smart_audio_video_mode"] = "video"
                    elif aac == 256:
                        res["smart_audio_video_mode"] = "audio"
                    else:
                        res["smart_audio_video_mode"] = "normal"

                # Limitador de Volume Safe Sound (0xA5)
                elif cmd == 0xA5 and len(payload) >= 2:
                    for idx_s in range(len(payload) - 1):
                        if payload[idx_s] == 0x01:
                            res["safe_sound_enabled"] = bool(payload[idx_s + 1])

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
    FEATURE_AUTO_POWER_OFF = 0x0012
    FEATURE_LR_BALANCE = 0x0015
    FEATURE_ANC = 0x0018
    FEATURE_AMBIENT_AWARE = 0x0019
    FEATURE_TALKTHRU = 0x001A
    FEATURE_ADAPTIVE_ANC = 0x001B
    FEATURE_SPATIAL_MODE = 0x0021
    FEATURE_SIDETONE = 0x0023  # VoiceAware
    FEATURE_AUDIO_LIMITER = 0x0027
    FEATURE_AUTO_PLAY_PAUSE = 0x002A
    FEATURE_EQ_INFO = 0x0E02
    FEATURE_EQ_CURVE = 0x0E7F
    FEATURE_SMART_SWITCH = 0x100F
    FEATURE_CASE_BATTERY = 0x1F03

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
    def set_auto_power_off(cls, timeout_minutes: int, enabled: bool = True) -> List[bytes]:
        """Configura Desligamento Automático no Protocolo 4 (Feature 0x0012)"""
        val = ((1 if enabled and timeout_minutes > 0 else 0) << 15) | (timeout_minutes & 0x7FFF)
        payload = bytes([
            cls.FEATURE_AUTO_POWER_OFF & 0xFF, (cls.FEATURE_AUTO_POWER_OFF >> 8) & 0xFF,
            val & 0xFF, (val >> 8) & 0xFF
        ])
        return cls.build_packet(cls.CMD_SET_DEVICE_INFO, payload)

    @classmethod
    def set_lr_balance(cls, balance: int, enabled: bool = True) -> List[bytes]:
        """Configura Balanço L/R no Protocolo 4 (Feature 0x0015)"""
        level = max(84, min(116, 100 + balance))
        val = ((1 if enabled else 0) << 7) | (level & 0x7F)
        payload = bytes([
            cls.FEATURE_LR_BALANCE & 0xFF, (cls.FEATURE_LR_BALANCE >> 8) & 0xFF,
            val & 0xFF
        ])
        return cls.build_packet(cls.CMD_SET_DEVICE_INFO, payload)

    @classmethod
    def set_safe_sound(cls, enabled: bool) -> List[bytes]:
        """Configura Limitador de Volume 85dB no Protocolo 4 (Feature 0x0027)"""
        val = 0x80 if enabled else 0x00
        payload = bytes([
            cls.FEATURE_AUDIO_LIMITER & 0xFF, (cls.FEATURE_AUDIO_LIMITER >> 8) & 0xFF,
            val & 0xFF
        ])
        return cls.build_packet(cls.CMD_SET_DEVICE_INFO, payload)

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
                elif fid == cls.FEATURE_AUTO_POWER_OFF and idx + 2 <= len(payload):
                    val = payload[idx] | (payload[idx+1] << 8)
                    res["auto_off_enabled"] = bool(val & 0x8000)
                    res["auto_off_minutes"] = val & 0x7FFF
                    idx += 2
                elif fid == cls.FEATURE_LR_BALANCE and idx < len(payload):
                    val = payload[idx]
                    res["lr_balance_enabled"] = bool(val & 0x80)
                    lvl = val & 0x7F
                    res["lr_balance_level"] = lvl
                    res["lr_balance_offset"] = lvl - 100
                    idx += 1
                elif fid == cls.FEATURE_AUDIO_LIMITER and idx < len(payload):
                    val = payload[idx]
                    res["safe_sound_enabled"] = bool(val & 0x80)
                    idx += 1
                elif fid == cls.FEATURE_SMART_SWITCH and idx + 8 <= len(payload):
                    aac = (payload[idx] << 8) | payload[idx+1]
                    sbc = (payload[idx+2] << 8) | payload[idx+3]
                    lat = (payload[idx+4] << 8) | payload[idx+5]
                    res["smart_switch_latency"] = lat
                    if lat <= 100:
                        res["smart_audio_video_mode"] = "video"
                    elif aac == 256:
                        res["smart_audio_video_mode"] = "audio"
                    else:
                        res["smart_audio_video_mode"] = "normal"
                    idx += 8
                else:
                    # Para features desconhecidas, pula 1 byte
                    idx += 1

        return res
