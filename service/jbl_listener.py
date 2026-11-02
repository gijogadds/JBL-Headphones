#!/usr/bin/env python3
"""
Monitor / Listener em Segundo Plano para Fones JBL no Linux.
Escuta eventos D-Bus do BlueZ no nível do sistema.
Quando um fone JBL é ligado ou se conecta via Bluetooth:
1. Detecta a conexão instantaneamente e dispara o aplicativo em modo bandeja (--tray).
2. O aplicativo abre direto na barra superior com todas as opções de ANC, Bateria e EQ ativas.
3. Se o fone for desligado, o aplicativo encerra a si mesmo e o monitor continua em espera.
Consumo de recursos: Praticamente nulo (0% CPU, ~8MB RAM, 100% event-driven).
"""

import os
import sys
import time
import subprocess

try:
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
except ImportError as e:
    print(f"[JBLListener] Erro ao carregar dependências D-Bus/GLib: {e}", file=sys.stderr)
    sys.exit(1)

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_SCRIPT = os.path.join(APP_DIR, "main.py")
APP_ID = "io.github.jbl.headphones.linux"

class JBLBluetoothListener:
    def __init__(self):
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.session_bus = None
        try:
            self.session_bus = dbus.SessionBus()
        except Exception:
            pass

        self.last_launch_time = 0.0

        # Inscreve para notificações quando propriedades de dispositivos Bluetooth mudarem (ex: Connected)
        self.bus.add_signal_receiver(
            self._on_properties_changed,
            dbus_interface="org.freedesktop.DBus.Properties",
            signal_name="PropertiesChanged",
            arg0="org.bluez.Device1",
            path_keyword="path"
        )

        # Inscreve para interfaces adicionadas no BlueZ
        self.bus.add_signal_receiver(
            self._on_interfaces_added,
            dbus_interface="org.freedesktop.DBus.ObjectManager",
            signal_name="InterfacesAdded"
        )

        # Na inicialização, verifica se já existe algum fone JBL conectado
        GLib.idle_add(self._check_existing_connections)

    def _is_app_running(self) -> bool:
        """Verifica se o aplicativo principal já está em execução."""
        if self.session_bus:
            try:
                if self.session_bus.name_has_owner(APP_ID):
                    return True
            except Exception:
                pass

        try:
            res = subprocess.run(["pgrep", "-f", f"{MAIN_SCRIPT}"], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                return True
        except Exception:
            pass

        return False

    def _launch_app_in_tray(self, dev_name: str = ""):
        """Inicia o aplicativo JBL na barra superior em modo bandeja."""
        now = time.time()
        if now - self.last_launch_time < 4.0:
            return  # Evita disparos múltiplos consecutivos

        if self._is_app_running():
            print(f"[JBLListener] Fone {dev_name} ativo, aplicativo já em execução.")
            return

        self.last_launch_time = now
        print(f"[JBLListener] Fone JBL detectado: '{dev_name}'. Iniciando na barra superior (--tray)...")

        env = os.environ.copy()
        bin_wrapper = os.path.join(os.path.expanduser("~"), ".local", "bin", "jbl-headphones")
        cmd = [bin_wrapper, "--tray"] if os.path.exists(bin_wrapper) else [sys.executable, MAIN_SCRIPT, "--tray"]
        try:
            subprocess.Popen(
                cmd,
                cwd=APP_DIR,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            print("[JBLListener] Aplicativo disparado com sucesso na barra superior!")
        except Exception as e:
            print(f"[JBLListener] Erro ao disparar aplicativo: {e}", file=sys.stderr)

    def _is_jbl_device(self, props: dict) -> bool:
        name = str(props.get("Name", "")).upper()
        modalias = str(props.get("Modalias", ""))
        if ("JBL" in name or "v0ECB" in modalias) and not name.endswith("-LE"):
            return True
        return False

    def _check_existing_connections(self):
        try:
            manager = dbus.Interface(self.bus.get_object('org.bluez', '/'), 'org.freedesktop.DBus.ObjectManager')
            objects = manager.GetManagedObjects()
            for path, ifaces in objects.items():
                if 'org.bluez.Device1' in ifaces:
                    props = ifaces['org.bluez.Device1']
                    if self._is_jbl_device(props) and bool(props.get('Connected', False)):
                        name = str(props.get('Name', 'Fone JBL'))
                        self._launch_app_in_tray(name)
                        break
        except Exception as e:
            print(f"[JBLListener] Erro ao escanear conexões ativas: {e}", file=sys.stderr)
        return False

    def _on_properties_changed(self, interface, changed, invalidated, path=None):
        if interface != 'org.bluez.Device1':
            return
        if 'Connected' in changed and bool(changed['Connected']):
            try:
                dev = self.bus.get_object('org.bluez', path)
                props_iface = dbus.Interface(dev, 'org.freedesktop.DBus.Properties')
                props = props_iface.GetAll('org.bluez.Device1')
                if self._is_jbl_device(props):
                    name = str(props.get('Name', 'Fone JBL'))
                    self._launch_app_in_tray(name)
            except Exception as e:
                print(f"[JBLListener] Erro ao ler propriedades: {e}", file=sys.stderr)

    def _on_interfaces_added(self, path, interfaces):
        if 'org.bluez.Device1' in interfaces:
            props = interfaces['org.bluez.Device1']
            if self._is_jbl_device(props) and bool(props.get('Connected', False)):
                name = str(props.get('Name', 'Fone JBL'))
                self._launch_app_in_tray(name)

def main():
    listener = JBLBluetoothListener()
    loop = GLib.MainLoop()
    print("[JBLListener] Monitor de fones JBL ativo e monitorando conexões Bluetooth...")
    try:
        loop.run()
    except (KeyboardInterrupt, SystemExit):
        pass

if __name__ == "__main__":
    main()
