"""
Controlador Bluetooth Low Energy (BLE GATT) para Fones JBL no Linux.
Responsável pelo canal de controle prioritário de áudio acústico (ANC, Som Ambiente, TalkThru e Equalizador)
e pela sincronização bidirecional em tempo real de eventos de toque no fone físico.
Compatível com todos os modelos BLE da JBL (ex: JBL Tune Buds 2, Tune Beam 2, Live Pro 2, Tour Pro 2, etc.).
"""

import sys
import asyncio
import threading
import time
from typing import Optional, Callable, Dict, Any, List

from bleak import BleakScanner, BleakClient
from bleak.backends.device import BLEDevice

# UUIDs oficiais da Harman International / JBL
HARMAN_SERVICE_UUID = "65786365-6c70-6f69-6e74-2e636f6d0000"
HARMAN_NOTIFY_CHAR  = "65786365-6c70-6f69-6e74-2e636f6d0001"
HARMAN_WRITE_CHAR   = "65786365-6c70-6f69-6e74-2e636f6d0002"

class BLEController:
    def __init__(self, on_status_changed: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.on_status_changed = on_status_changed
        self._target_name_hint: str = ""
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._client: Optional[BleakClient] = None
        self.is_connected: bool = False
        self.connected_address: Optional[str] = None
        self._send_queue: Optional[asyncio.Queue] = None

    def start(self, device_name_hint: str = ""):
        """Inicia a thread em segundo plano com event loop asyncio dedicado."""
        self.stop()
        self._target_name_hint = device_name_hint
        self._running = True
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True, name="JBL-BLE-Worker")
        self._thread.start()

    def stop(self):
        """Encerra a conexão BLE e a thread com segurança."""
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._loop = None
        self.is_connected = False
        self.connected_address = None

    def send_cmd(self, data: bytes) -> bool:
        """Enfileira pacote binário para envio via GATT Write Characteristic de forma thread-safe."""
        if not data or not self._running or not self._loop or not self._send_queue:
            return False
        self._loop.call_soon_threadsafe(self._send_queue.put_nowait, data)
        return True

    def _run_event_loop(self):
        """Ponto de entrada da thread dedicada ao asyncio."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._send_queue = asyncio.Queue()
        try:
            self._loop.run_until_complete(self._main_supervisor())
        except Exception as e:
            print(f"[BLEController] Erro no loop: {e}", file=sys.stderr)
        finally:
            self._loop.close()

    async def _main_supervisor(self):
        """Supervisor de conexão contínua com reconexão automática e envio assíncrono."""
        while self._running:
            try:
                # 1. Localizar o dispositivo BLE correspondente
                device = await self._discover_target_device()
                if not device:
                    await asyncio.sleep(2.5)
                    continue

                print(f"[BLEController] Fone LE localizado: {device.address} ({device.name})")
                
                # 2. Conectar com BleakClient
                async with BleakClient(device, timeout=12.0) as client:
                    self._client = client
                    self.is_connected = True
                    self.connected_address = device.address
                    print(f"[BLEController] Conectado com sucesso ao GATT de {device.name}!")
                    
                    if self.on_status_changed:
                        self.on_status_changed({"ble_connected": True, "ble_address": device.address})

                    # 3. Inscrever em notificações
                    try:
                        await client.start_notify(HARMAN_NOTIFY_CHAR, self._handle_notification)
                        print("[BLEController] Notificações Harman ativadas com sucesso.")
                    except Exception as e:
                        print(f"[BLEController] Aviso ao ativar notificações: {e}", file=sys.stderr)

                    # 4. Enviar requisições iniciais de sincronização
                    req_anc = bytes([0xAA, 0x91, 0x01, 0x11])
                    req_info = bytes([0xAA, 0x11, 0x01, 0x00])
                    await self._write_raw(client, req_anc)
                    await self._write_raw(client, req_info)

                    # 5. Processar fila de envio e manter a conexão viva
                    while self._running and client.is_connected:
                        try:
                            # Espera comando para envio com timeout de 0.5s para checagem de integridade
                            data = await asyncio.wait_for(self._send_queue.get(), timeout=0.5)
                            await self._write_raw(client, data)
                            self._send_queue.task_done()
                        except asyncio.TimeoutError:
                            pass
                        except Exception as e:
                            print(f"[BLEController] Erro ao enviar pacote BLE: {e}", file=sys.stderr)

            except Exception as e:
                print(f"[BLEController] Conexão LE interrompida: {e}. Tentando restabelecer...", file=sys.stderr)
            finally:
                self.is_connected = False
                self._client = None
                if self.on_status_changed:
                    self.on_status_changed({"ble_connected": False})
                if self._running:
                    await asyncio.sleep(2.0)

    async def _discover_target_device(self) -> Optional[BLEDevice]:
        """Varre dispositivos BLE procurando fones JBL com sufixo -LE ou serviço Harman."""
        try:
            target_clean = self._target_name_hint.replace("-LE", "").strip().upper()
            
            def filter_func(d: BLEDevice, adv) -> bool:
                name = (d.name or adv.local_name or "").upper()
                if "JBL" not in name:
                    return False
                if target_clean and target_clean in name:
                    return True
                if "-LE" in name or "BUDS" in name or "BEAM" in name or "FLEX" in name or "LIVE" in name or "TUNE" in name:
                    return True
                # Checa por serviço Harman
                if adv.service_uuids and HARMAN_SERVICE_UUID.lower() in [u.lower() for u in adv.service_uuids]:
                    return True
                return False

            dev = await BleakScanner.find_device_by_filter(filter_func, timeout=4.0)
            return dev
        except Exception as e:
            print(f"[BLEController] Erro na descoberta BLE: {e}", file=sys.stderr)
            return None

    async def _write_raw(self, client: BleakClient, data: bytes):
        """Escreve na característica GATT Write sem resposta obrigatória (Write Without Response)."""
        if not client or not client.is_connected:
            return
        await client.write_gatt_char(HARMAN_WRITE_CHAR, data, response=False)
        print(f"[BLEController] Pacote enviado ({len(data)} bytes): {data.hex(' ')}")

    def _handle_notification(self, sender: Any, data: bytes):
        """Trata notificações do fone físico e eventos de toque no auricular."""
        print(f"[BLEController] Notificação recebida ({len(data)} bytes): {data.hex(' ')}")
        if not self.on_status_changed:
            return

        status_update: Dict[str, Any] = {"raw_ble_packet": data}

        # 1. Notificação de modos de isolamento acústico / ANC (0xAA 0x91 ...)
        # Formato oficial Harman/BES:
        # Modo 1 (data[5]) = Cancelamento Ativo de Ruído (ANC)
        # Modo 2 (data[7]) = Som Ambiente (Ambient Aware)
        # Modo 3 (data[9]) = Modo Conversa (TalkThru)
        if len(data) >= 10 and data[0] == 0xAA and data[1] == 0x91 and data[3] == 0x12:
            anc_val = data[5]  # Modo 1 (ANC)
            aa_val = data[7]   # Modo 2 (Ambient Aware)
            tt_val = data[9]   # Modo 3 (TalkThru)

            if anc_val == 1:
                status_update["anc_mode"] = 1 # AncMode.ANC
            elif aa_val == 1:
                status_update["anc_mode"] = 2 # AncMode.AMBIENT_AWARE
            elif tt_val == 1:
                status_update["anc_mode"] = 3 # AncMode.TALKTHRU
            else:
                status_update["anc_mode"] = 0 # AncMode.OFF

            status_update["anc_source"] = "earbud_notification"

        elif len(data) >= 4 and data[0] == 0xAA and data[1] == 0x91 and data[3] == 0x13:
            status_update["anc_mode"] = 0 # AncMode.OFF
            status_update["anc_source"] = "earbud_notification"

        # 2. Notificação com informações do dispositivo e baterias (0xAA 0x12 ...)
        elif len(data) >= 20 and data[0] == 0xAA and data[1] == 0x12:
            status_update["raw_packet"] = data

        self.on_status_changed(status_update)
