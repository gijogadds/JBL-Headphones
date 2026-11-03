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
from core.protocol import Protocol3Handler

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
    COMMAND_QUEUE_MAX_AGE = 10.0

    def __init__(self, on_status_changed: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.on_status_changed = on_status_changed
        self.connected_device: Optional[BluetoothDevice] = None
        self._rfcomm_socket: Optional[socket.socket] = None
        self._rfcomm_channel: int = 17
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._send_queue: queue.Queue = queue.Queue(maxsize=256)
        self._ble_only_queue: queue.Queue = queue.Queue(maxsize=256)
        self._bluez_connecting: set[str] = set()
        self._connect_lock = threading.Lock()
        self._rfcomm_rx_buffer = bytearray()
        self.is_socket_connected = False
        
        # Controlador BLE dedicado para comandos de áudio e toques
        self.ble_controller = BLEController(on_status_changed=self._on_ble_status_changed)

        # Inscreve para notificações em tempo real do BlueZ
        self._system_bus = None
        if dbus is not None:
            try:
                self._system_bus = dbus.SystemBus()
                self._system_bus.add_signal_receiver(
                    self._on_bluez_properties_changed,
                    dbus_interface="org.freedesktop.DBus.Properties",
                    signal_name="PropertiesChanged",
                    arg0="org.bluez.Device1",
                    path_keyword="path"
                )
            except Exception as e:
                print(f"[BluetoothBackend] Aviso ao registrar sinal D-Bus: {e}", file=sys.stderr)

    def _on_bluez_properties_changed(self, interface, changed, invalidated, path=None):
        """Disparado instantaneamente quando o estado de conexão do dispositivo muda no BlueZ."""
        if interface != 'org.bluez.Device1':
            return
        if self.connected_device and path == self.connected_device.path:
            if 'Connected' in changed:
                is_conn = bool(changed['Connected'])
                self.connected_device.connected = is_conn
                print(f"[BluetoothBackend] Evento D-Bus imediato: {self.connected_device.name} Connected={is_conn}")
                if self.on_status_changed:
                    self.on_status_changed({"bluez_connected": is_conn, "device_name": self.connected_device.name})

    def _on_ble_status_changed(self, status: Dict[str, Any]):
        """Repassa atualizações do BLE para a UI."""
        if status.get("ble_connected"):
            self._flush_send_queue_to_ble(self._send_queue)
            self._flush_send_queue_to_ble(self._ble_only_queue)
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
        if (
            self._running
            and self.connected_device
            and self.connected_device.path == device.path
        ):
            self.connected_device = device
            return True

        self.disconnect()
        self.connected_device = device
        self._running = True
        self._rfcomm_rx_buffer.clear()
        
        # Inicia o controlador BLE com nome e MAC
        self.ble_controller.start(device.name, device.mac)

        # Inicia a thread clássica RFCOMM
        self._worker_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._worker_thread.start()
        return True

    def connect_bluez(self, mac: str) -> bool:
        """Solicita conexão BlueZ em uma thread para não bloquear a interface GTK."""
        if dbus is None:
            return False

        normalized_mac = mac.upper()
        with self._connect_lock:
            if normalized_mac in self._bluez_connecting:
                return True
            self._bluez_connecting.add(normalized_mac)

        threading.Thread(
            target=self._connect_bluez_worker,
            args=(normalized_mac,),
            daemon=True,
            name="JBL-BlueZ-Connect",
        ).start()
        return True

    def _connect_bluez_worker(self, mac: str):
        try:
            bus = dbus.SystemBus()
            manager = dbus.Interface(bus.get_object('org.bluez', '/'), 'org.freedesktop.DBus.ObjectManager')
            objects = manager.GetManagedObjects()
            for path, interfaces in objects.items():
                if 'org.bluez.Device1' in interfaces:
                    props = interfaces['org.bluez.Device1']
                    if str(props.get('Address', '')).upper() == mac.upper():
                        dev_obj = bus.get_object('org.bluez', path)
                        dev_iface = dbus.Interface(dev_obj, 'org.bluez.Device1')
                        print(f"[BluetoothBackend] Solicitando conexão BlueZ com {mac}...")
                        dev_iface.Connect()
                        for device in self.scan_jbl_devices():
                            if device.mac.upper() == mac and device.connected:
                                self.connect(device)
                                return
                        print(f"[BluetoothBackend] BlueZ não confirmou conexão com {mac}.", file=sys.stderr)
                        return
            print(f"[BluetoothBackend] Dispositivo JBL pareado não encontrado: {mac}.", file=sys.stderr)
        except Exception as e:
            print(f"[BluetoothBackend] Aviso ao conectar via BlueZ: {e}", file=sys.stderr)
        finally:
            with self._connect_lock:
                self._bluez_connecting.discard(mac)

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
            self._worker_thread.join(timeout=5.0)
        self.connected_device = None
        self._rfcomm_rx_buffer.clear()
        for pending in (self._send_queue, self._ble_only_queue):
            while True:
                try:
                    pending.get_nowait()
                    pending.task_done()
                except queue.Empty:
                    break

    def send_raw(self, data: bytes) -> bool:
        """
        Enfileira cada comando para um único transporte disponível.
        BLE é prioritário; RFCOMM atende dispositivos BLE-legados e telemetria.
        """
        if not data or not self._running:
            return False

        ble_only = data.startswith(b"\xF0\xDC")
        pending = self._ble_only_queue if ble_only else self._send_queue
        if self.ble_controller.is_connected and self.ble_controller.send_cmd(data):
            return True

        try:
            pending.put_nowait((time.monotonic(), data))
            return True
        except queue.Full:
            print("[BluetoothBackend] Fila de comandos cheia; pacote descartado.", file=sys.stderr)
            return False

    def send_control(self, data: bytes) -> bool:
        """Envia controles pelo GATT quando o anúncio do fone indica suporte Harman."""
        if not data or not self._running:
            return False

        if self.ble_controller.is_connected:
            return self.ble_controller.send_cmd(data)

        if data.startswith(b"\xF0\xDC"):
            print(
                "[BluetoothBackend] Controle não enviado: o canal GATT BLE ainda não conectou.",
                file=sys.stderr,
            )
            return False

        if getattr(self.ble_controller, "has_control_candidate", False):
            print(
                "[BluetoothBackend] Controle não enviado: o dispositivo Harman foi "
                "encontrado, mas o GATT ainda não está conectado.",
                file=sys.stderr,
            )
            return False

        return self.send_raw(data)

    def _flush_send_queue_to_ble(self, pending: queue.Queue):
        while True:
            try:
                queued_at, packet = pending.get_nowait()
            except queue.Empty:
                return

            if time.monotonic() - queued_at > self.COMMAND_QUEUE_MAX_AGE:
                print("[BluetoothBackend] Comando BLE expirado; descartado.", file=sys.stderr)
            elif not self.ble_controller.send_cmd(packet):
                try:
                    pending.put_nowait((queued_at, packet))
                except queue.Full:
                    print("[BluetoothBackend] Fila BLE indisponível; pacote descartado.", file=sys.stderr)
            pending.task_done()

    def _try_open_socket(self) -> bool:
        """Tenta abrir conexão RFCOMM no canal Harman SPP 17 (ou fallback 12, 1) com timeout reduzido."""
        if not self.connected_device or not self._running:
            return False
            
        target_mac = self.connected_device.mac
        candidate_channels = [17, 12, 1]
        
        for ch in candidate_channels:
            if not self._running:
                return False
            try:
                s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                s.settimeout(1.2)
                s.connect((target_mac, ch))
                s.settimeout(0.2)
                with self._lock:
                    self._rfcomm_channel = ch
                    self._rfcomm_socket = s
                    self.is_socket_connected = True
                print(f"[BluetoothBackend] Canal RFCOMM {ch} conectado com sucesso para {target_mac}!")
                return True
            except Exception:
                try:
                    s.close()
                except Exception:
                    pass
        return False

    def _run_loop(self):
        """Loop de fundo resiliente para telemetria BlueZ contínua, RFCOMM e esvaziamento de filas."""
        last_poll_time = 0.0
        last_rfcomm_attempt = 0.0

        while self._running:
            now = time.time()

            # 1. Recupera o canal RFCOMM após desconexões sem espera prolongada.
            if not self._rfcomm_socket and (now - last_rfcomm_attempt >= 5.0):
                last_rfcomm_attempt = now
                if self._try_open_socket():
                    try:
                        self.send_raw(bytes([0xAA, 0x11, 0x01, 0x00]))
                        self.send_raw(bytes([0xAA, 0x25, 0x01, 0x01]))
                    except Exception:
                        pass

            try:
                # 2. Processar comandos pendentes na fila de envio RFCOMM
                while not self._send_queue.empty():
                    try:
                        queued_at, cmd_pkt = self._send_queue.get_nowait()
                        if time.monotonic() - queued_at > self.COMMAND_QUEUE_MAX_AGE:
                            print("[BluetoothBackend] Comando RFCOMM expirado; descartado.", file=sys.stderr)
                            self._send_queue.task_done()
                            continue
                        if self.ble_controller.is_connected:
                            if not self.ble_controller.send_cmd(cmd_pkt):
                                try:
                                    self._send_queue.put_nowait((queued_at, cmd_pkt))
                                except queue.Full:
                                    print("[BluetoothBackend] Fila RFCOMM cheia; pacote descartado.", file=sys.stderr)
                                self._send_queue.task_done()
                                break
                        else:
                            with self._lock:
                                sock = self._rfcomm_socket
                                if sock:
                                    sock.sendall(cmd_pkt)
                                    print(f"[BluetoothBackend] Pacote RFCOMM enviado ({len(cmd_pkt)} bytes): {cmd_pkt.hex(' ')}")
                                else:
                                    try:
                                        self._send_queue.put_nowait((queued_at, cmd_pkt))
                                    except queue.Full:
                                        print("[BluetoothBackend] Fila RFCOMM cheia; pacote descartado.", file=sys.stderr)
                                    self._send_queue.task_done()
                                    break
                        self._send_queue.task_done()
                        time.sleep(0.03)
                    except queue.Empty:
                        break

                # 3. Polling de bateria do BlueZ a cada 2.5 segundos (funciona para todos os fones)
                if now - last_poll_time >= 2.5:
                    last_poll_time = now
                    if self.connected_device and dbus is not None:
                        try:
                            bus = dbus.SystemBus()
                            dev = bus.get_object('org.bluez', self.connected_device.path)
                            props = dbus.Interface(dev, 'org.freedesktop.DBus.Properties')
                            
                            # Verifica se o fone continua conectado no BlueZ
                            is_conn = bool(props.Get('org.bluez.Device1', 'Connected'))
                            self.connected_device.connected = is_conn
                            if self.on_status_changed:
                                self.on_status_changed({"bluez_connected": is_conn, "device_name": self.connected_device.name})

                            # Lê a bateria reportada pelo BlueZ
                            try:
                                bat = int(props.Get('org.bluez.Battery1', 'Percentage'))
                                self.connected_device.battery_percentage = bat
                                if self.on_status_changed:
                                    self.on_status_changed({"battery_overall": bat})
                            except Exception:
                                pass
                        except Exception:
                            pass

                # 4. Leitura do socket RFCOMM se conectado
                sock = self._rfcomm_socket
                if sock:
                    try:
                        raw_data = sock.recv(1024)
                        if raw_data:
                            print(f"[BluetoothBackend] RFCOMM Recebido ({len(raw_data)} bytes): {raw_data.hex(' ')}")
                            self._rfcomm_rx_buffer.extend(raw_data)
                            for packet in Protocol3Handler.extract_packets(self._rfcomm_rx_buffer):
                                if self.on_status_changed:
                                    self.on_status_changed({"raw_packet": packet})
                        else:
                            with self._lock:
                                if self._rfcomm_socket is sock:
                                    sock.close()
                                    self._rfcomm_socket = None
                                    self.is_socket_connected = False
                            last_rfcomm_attempt = 0.0
                    except (socket.timeout, BlockingIOError):
                        pass
                    except OSError as exc:
                        with self._lock:
                            if self._rfcomm_socket is sock:
                                try:
                                    sock.close()
                                except OSError:
                                    pass
                                self._rfcomm_socket = None
                            self.is_socket_connected = False
                        if not self._running:
                            break
                        print(
                            f"[BluetoothBackend] Canal RFCOMM interrompido: {exc}",
                            file=sys.stderr,
                        )
                        last_rfcomm_attempt = 0.0

                time.sleep(0.08)

            except Exception as e:
                if not self._running:
                    break
                print(f"[BluetoothBackend] Erro no loop de comunicação: {e}", file=sys.stderr)
                with self._lock:
                    self.is_socket_connected = False
                    if self._rfcomm_socket:
                        try:
                            self._rfcomm_socket.close()
                        except Exception:
                            pass
                        self._rfcomm_socket = None
                last_rfcomm_attempt = 0.0
                time.sleep(1.0)
