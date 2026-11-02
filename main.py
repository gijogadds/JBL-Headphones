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
from gi.repository import Adw, Gio

from core.device_registry import DeviceRegistry
from core.bluetooth_backend import BluetoothBackend
from ui.main_window import MainWindow

class JBLApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.jbl.headphones.linux",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )
        self.registry = DeviceRegistry()
        self.backend = BluetoothBackend()

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = MainWindow(self, self.registry, self.backend)
        win.present()

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
    app = JBLApp()
    return app.run(sys.argv)

if __name__ == "__main__":
    sys.exit(main())
