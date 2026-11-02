"""
Gerenciador de Conexão Bluetooth Dual (Classic RFCOMM + BLE GATT) para fones JBL no Linux.
Combina canal RFCOMM Clássico (telemetria TWS BES) com Controlador BLE GATT Harman
para comandos acústicos prioritários (ANC, Som Ambiente, TalkThru e Equalizador Oficial)
e sincronização bidirecional em tempo real de eventos de toque no fone.
"""

import sys
import socket
import threading
import queue
import time
from typing import Optional, Callable, Dict, Any, List

from core.ble_controller import BLEController

try:
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
except ImportError:
    dbus = None

class BluetoothDevice:
    def __init__(self, path: str, name: str, mac: str, connected: bool, modalias: str = ""):
        self.path = path
        self.name = name
        self.mac = mac
        self.connected = connected
        self.modalias = modalias
        self.battery_percentage: Optional[int] = None

class BluetoothBackend:
    def __init__(self, on_status_changed: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.on_status_changed = on_status_changed
        self.connected_device: Optional[BluetoothDevice] = None
        self._rfcomm_socket: Optional[socket.socket] = None
        self._rfcomm_channel: int = 17
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._send_queue: queue.Queue = queue.Queue()
        self.is_socket_connected = False
        
        # Controlador BLE dedicado para comandos de áudio e toques
        self.ble_controller = BLEController(on_status_changed=self._on_ble_status_changed)

    def _on_ble_status_changed(self, status: Dict[str, Any]):
        """Repassa atualizações do BLE para a UI."""
        if self.on_status_changed:
            self.on_status_changed(status)

    def scan_jbl_devices(self) -> List[BluetoothDevice]:
        """Localiza todos os dispositivos JBL conectados ou pareados no Linux."""
        devices = []
        if dbus is None:
            return devices
            
        try:
            bus = dbus.SystemBus()
            manager = dbus.Interface(bus.get_object('org.bluez', '/'), 'org.freedesktop.DBus.ObjectManager')
            objects = manager.GetManagedObjects()
            
            for path, interfaces in objects.items():
                if 'org.bluez.Device1' in interfaces:
                    dev_props = interfaces['org.bluez.Device1']
                    name = str(dev_props.get('Name', ''))
                    mac = str(dev_props.get('Address', ''))
                    connected = bool(dev_props.get('Connected', False))
                    modalias = str(dev_props.get('Modalias', ''))
                    
                    # Filtra por nome JBL ou fornecedor Harman (0ECB)
                    if "JBL" in name.upper() or "v0ECB" in modalias:
                        # Ignora os nós LE puros na lista principal de áudio clássico
                        if name.endswith("-LE"):
                            continue
                        bdev = BluetoothDevice(path, name, mac, connected, modalias)
                        
                        # Tenta ler a bateria do BlueZ
                        if 'org.bluez.Battery1' in interfaces:
                            bat_props = interfaces['org.bluez.Battery1']
                            try:
                                bdev.battery_percentage = int(bat_props.get('Percentage', 0))
                            except Exception:
                                pass
                        devices.append(bdev)
        except Exception as e:
            print(f"[BluetoothBackend] Erro ao escanear BlueZ: {e}", file=sys.stderr)
            
        return devices

    def connect(self, device: BluetoothDevice) -> bool:
        """Inicia a conexão de controle dual (Classic RFCOMM + BLE GATT) com o dispositivo."""
        self.disconnect()
        self.connected_device = device
        self._running = True
        
        # Inicia o controlador BLE em segundo plano
        self.ble_controller.start(device.name)

        # Inicia a thread clássica RFCOMM
        self._worker_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._worker_thread.start()
        return True

    def disconnect(self):
        """Fecha as conexões Classic e BLE com o dispositivo."""
        self._running = False
        self.is_socket_connected = False
        
        # Para o controlador BLE
        self.ble_controller.stop()

        with self._lock:
            if self._rfcomm_socket:
                try:
                    self._rfcomm_socket.close()
                except Exception:
                    pass
                self._rfcomm_socket = None
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
        self.connected_device = None

    def send_raw(self, data: bytes) -> bool:
        """
        Envia pacote binário simultaneamente via canal BLE GATT e RFCOMM Classic.
        Garante entrega prioritária imediata de comandos acústicos (ANC, EQ) e telemetria.
        """
        if not data:
            return False
            
        # 1. Envio prioritário pelo BLE GATT (canal principal dos fones JBL modernos)
        self.ble_controller.send_cmd(data)
        
        # 2. Envio pelo canal RFCOMM Classic (compatibilidade com modelos legados)
        self._send_queue.put(data)
        return True

    def _try_open_socket(self) -> bool:
        """Tenta abrir conexão RFCOMM no canal Harman SPP 17 (ou fallback 12, 1)."""
        if not self.connected_device or not self._running:
            return False
            
        target_mac = self.connected_device.mac
        candidate_channels = [17, 12, 1]
        
        for ch in candidate_channels:
            if not self._running:
                return False
            try:
                s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                s.settimeout(5.0)
                s.connect((target_mac, ch))
                s.settimeout(0.3)
                with self._lock:
                    self._rfcomm_channel = ch
                    self._rfcomm_socket = s
                    self.is_socket_connected = True
                print(f"[BluetoothBackend] Canal RFCOMM {ch} conectado com sucesso para {target_mac}!")
                return True
            except Exception as e:
                try:
                    s.close()
                except Exception:
                    pass
        return False

    def _run_loop(self):
        """Loop de fundo para leitura contínua e envio da fila de comandos."""
        last_poll_time = 0.0
        while self._running:
            if not self._rfcomm_socket:
                self.is_socket_connected = False
                if not self._try_open_socket():
                    time.sleep(2.0)
                    continue
                # Ao conectar com sucesso, envia comandos iniciais de identificação e telemetria
                try:
                    self.send_raw(bytes([0xAA, 0x11, 0x01, 0x00]))
                    self.send_raw(bytes([0xAA, 0x25, 0x01, 0x00]))
                except Exception:
                    pass

            try:
                # 1. Processar todos os comandos pendentes na fila de envio (Send Queue)
                while not self._send_queue.empty() and self._rfcomm_socket:
                    try:
                        cmd_pkt = self._send_queue.get_nowait()
                        with self._lock:
                            if self._rfcomm_socket:
                                self._rfcomm_socket.send(cmd_pkt)
                                print(f"[BluetoothBackend] Pacote enviado ({len(cmd_pkt)} bytes): {cmd_pkt.hex(' ')}")
                        self._send_queue.task_done()
                        time.sleep(0.04) # pequeno intervalo para estabilidade do microcontrolador
                    except queue.Empty:
                        break

                now = time.time()
                # 2. Polling periódico de bateria do BlueZ a cada 3 segundos
                if now - last_poll_time >= 3.0:
                    last_poll_time = now
                    if self.connected_device and dbus is not None:
                        try:
                            bus = dbus.SystemBus()
                            dev = bus.get_object('org.bluez', self.connected_device.path)
                            props = dbus.Interface(dev, 'org.freedesktop.DBus.Properties')
                            bat = int(props.Get('org.bluez.Battery1', 'Percentage'))
                            self.connected_device.battery_percentage = bat
                            if self.on_status_changed:
                                self.on_status_changed({"battery_overall": bat})
                        except Exception:
                            pass

                # 3. Leitura contínua não-bloqueante do socket RFCOMM
                if self._rfcomm_socket:
                    try:
                        raw_data = self._rfcomm_socket.recv(1024)
                        if raw_data:
                            print(f"[BluetoothBackend] Recebido ({len(raw_data)} bytes): {raw_data.hex(' ')}")
                            if self.on_status_changed:
                                self.on_status_changed({"raw_packet": raw_data})
                    except (socket.timeout, BlockingIOError):
                        pass
                
                time.sleep(0.05)

            except Exception as e:
                print(f"[BluetoothBackend] Conexão perdida no loop: {e}", file=sys.stderr)
                with self._lock:
                    self.is_socket_connected = False
                    if self._rfcomm_socket:
                        try:
                            self._rfcomm_socket.close()
                        except Exception:
                            pass
                        self._rfcomm_socket = None
                time.sleep(2.0)
