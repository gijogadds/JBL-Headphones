#!/usr/bin/env python3
"""
JBL Headphones Controller for Linux.
Controle completo de fones JBL no Linux com interface nativa Adwaita / GTK4.
"""

import sys
import os

# Adiciona o diretório base ao sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib

from core.device_registry import DeviceRegistry
from core.bluetooth_backend import BluetoothBackend
from ui.main_window import MainWindow

class JBLApp(Adw.Application):
    def __init__(self, start_in_tray: bool = False, auto_close_on_disconnect: bool = True):
        super().__init__(
            application_id="io.github.jbl.headphones.linux",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )
        self.start_in_tray = start_in_tray
        self.auto_close_on_disconnect = auto_close_on_disconnect
        self.registry = DeviceRegistry()
        self.backend = BluetoothBackend()

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = MainWindow(
                self, 
                self.registry, 
                self.backend,
                start_in_tray=self.start_in_tray,
                auto_close_on_disconnect=self.auto_close_on_disconnect
            )
        if not self.start_in_tray:
            win.set_visible(True)
            win.present()
        else:
            win.set_visible(False)
            self.start_in_tray = False

    def do_shutdown(self):
        try:
            self.backend.disconnect()
        except Exception:
            pass
        try:
            Adw.Application.do_shutdown(self)
        except Exception:
            pass

def main():
    try:
        from dbus.mainloop.glib import DBusGMainLoop
        DBusGMainLoop(set_as_default=True)
    except Exception:
        pass

    GLib.set_prgname("io.github.jbl.headphones.linux")
    GLib.set_application_name("JBL Headphones")
    
    start_in_tray = "--tray" in sys.argv or "--minimized" in sys.argv
    no_autoclose = "--no-autoclose" in sys.argv
    
    clean_argv = [sys.argv[0]]
    for arg in sys.argv[1:]:
        if arg not in ("--tray", "--minimized", "--no-autoclose"):
            clean_argv.append(arg)
            
    app = JBLApp(start_in_tray=start_in_tray, auto_close_on_disconnect=(not no_autoclose))
    return app.run(clean_argv)

if __name__ == "__main__":
    sys.exit(main())
