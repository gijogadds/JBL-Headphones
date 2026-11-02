"""
Gerenciador de Perfis e Registro de Modelos JBL para Linux.
Indexa todos os modelos suportados extraídos do aplicativo oficial.
"""

import os
import json
import glob
from typing import Dict, Any, Optional, List

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
MODELS_DIR = os.path.join(DATA_DIR, "models")
PRESETS_FILE = os.path.join(DATA_DIR, "presets", "standard_preset_eq.json")

class DeviceModel:
    def __init__(self, data: Dict[str, Any], filepath: str):
        self.raw_data = data
        self.filepath = filepath
        self.name: str = data.get("name", "JBL Headphone Desconhecido")
        self.pid: str = str(data.get("pid", "")).lower()
        self.protocol_version: int = int(data.get("protocolVersion", 3))
        self.ui_features: List[Dict[str, Any]] = data.get("uiFeatures", [])
        
        # Mapeamento rápido de recursos suportados
        self.features_set = {f.get("name") for f in self.ui_features if "name" in f}
        
    @property
    def image_path(self) -> Optional[str]:
        base_name = os.path.splitext(os.path.basename(self.filepath))[0]
        clean = base_name.replace("jbl_", "")
        for ext in [".png", ".webp"]:
            for name in [base_name, clean, f"jbl_{clean}"]:
                candidate = os.path.join(DATA_DIR, "images", f"{name}{ext}")
                if os.path.exists(candidate):
                    return candidate
        return None
        
    @property
    def has_anc(self) -> bool:
        return "ANC" in self.features_set or "AscCard" in self.features_set
        
    @property
    def has_ambient_aware(self) -> bool:
        return "AA" in self.features_set
        
    @property
    def has_talkthru(self) -> bool:
        return "TT" in self.features_set
        
    @property
    def has_equalizer(self) -> bool:
        return "EQCard" in self.features_set or "EQ" in self.features_set
        
    @property
    def has_gestures(self) -> bool:
        return "GestureCard" in self.features_set
        
    @property
    def has_spatial_audio(self) -> bool:
        return "Spatial3DCard" in self.features_set
        
    @property
    def has_voice_aware(self) -> bool:
        return "VoiceAwareCard" in self.features_set

    @property
    def has_smart_audio(self) -> bool:
        return "SmartAudioVideoCard" in self.features_set or "SmartAudio" in self.features_set

    @property
    def has_lr_balance(self) -> bool:
        return "LeftRightBalanceCard" in self.features_set or "LeftRightBalance2Card" in self.features_set or "LRBalance" in self.features_set

    @property
    def has_auto_power_off(self) -> bool:
        return "AutoPowerOffCard" in self.features_set or "PowerSavingCard" in self.features_set or "AutoOff" in self.features_set

    @property
    def has_safe_sound(self) -> bool:
        return "SafeSoundCard" in self.features_set or "AudioLimiterCard" in self.features_set

    @property
    def has_find_my_buds(self) -> bool:
        return "FindMyBudCard" in self.features_set

class DeviceRegistry:
    def __init__(self):
        self.models_by_pid: Dict[str, DeviceModel] = {}
        self.models_by_name: Dict[str, DeviceModel] = {}
        self.all_models: List[DeviceModel] = []
        self._load_models()
        self._load_presets()
        
    def _load_models(self):
        json_files = glob.glob(os.path.join(MODELS_DIR, "*.json"))
        for fpath in json_files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    model = DeviceModel(data, fpath)
                    if model.pid:
                        self.models_by_pid[model.pid] = model
                    self.models_by_name[model.name.lower()] = model
                    self.all_models.append(model)
            except Exception as e:
                pass
                
        # Ordenar por nome para exibição agradável
        self.all_models.sort(key=lambda m: m.name)

    def _load_presets(self):
        self.eq_presets: List[Dict[str, Any]] = []
        if os.path.exists(PRESETS_FILE):
            try:
                with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.eq_presets = data.get("preset", [])
            except Exception:
                pass

    def find_by_pid(self, pid: str) -> Optional[DeviceModel]:
        clean_pid = pid.lower().strip()
        if clean_pid.startswith("0x"):
            clean_pid = clean_pid[2:]
        clean_pid = clean_pid.lstrip("0")
        for k, model in self.models_by_pid.items():
            if k.lstrip("0") == clean_pid:
                return model
        return None

    def find_by_name(self, name: str) -> Optional[DeviceModel]:
        target = name.lower().strip()
        # Busca exata
        if target in self.models_by_name:
            return self.models_by_name[target]
            
        # Busca parcial
        for model in self.all_models:
            if model.name.lower() in target or target in model.name.lower():
                return model
        return None

    def find_from_bluetooth(self, device_name: str, modalias: Optional[str] = None) -> Optional[DeviceModel]:
        # Tentar extrair PID do modalias (ex: bluetooth:v0ECBp210Cd001F)
        if modalias and "p" in modalias:
            try:
                parts = modalias.split("p")
                if len(parts) > 1:
                    pid_hex = parts[1][:4]
                    found = self.find_by_pid(pid_hex)
                    if found:
                        return found
            except Exception:
                pass
                
        # Se não achou pelo modalias, buscar pelo nome do dispositivo
        return self.find_by_name(device_name)
