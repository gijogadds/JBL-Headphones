"""
Indicador de Barra Superior (Top Bar Tray / StatusNotifierItem) para GNOME/Ubuntu.
Implementação nativa em D-Bus puro (org.kde.StatusNotifierItem + com.canonical.dbusmenu)
sem conflitos com GTK4 e perfeitamente integrado ao shell do sistema.
"""

import os
import sys
from typing import Optional, Callable, Dict, Any, List

try:
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
except ImportError:
    dbus = None

from core.protocol import AncMode

class TrayMenu(dbus.service.Object):
    """Implementa com.canonical.dbusmenu para renderizar o menu suspenso nativo na barra superior."""
    def __init__(self, bus: dbus.SessionBus, path: str, indicator: 'JBLTrayIndicator'):
        super().__init__(bus, path)
        self.indicator = indicator
        self.revision = 1

    @dbus.service.method('com.canonical.dbusmenu', in_signature='iiav', out_signature='u(ia{sv}av)')
    def GetLayout(self, parent_id: int, recursion_depth: int, property_names: List[str]):
        return (self.revision, self.indicator.build_menu_layout(parent_id))

    @dbus.service.method('com.canonical.dbusmenu', in_signature='aias', out_signature='a(ia{sv})')
    def GetGroupProperties(self, ids: List[int], property_names: List[str]):
        return []

    @dbus.service.method('com.canonical.dbusmenu', in_signature='isvu', out_signature='')
    def Event(self, item_id: int, event_id: str, data: Any, timestamp: int):
        if event_id == "clicked":
            self.indicator.handle_menu_click(item_id)

    @dbus.service.method('com.canonical.dbusmenu', in_signature='i', out_signature='b')
    def AboutToShow(self, item_id: int) -> bool:
        return False

    @dbus.service.signal('com.canonical.dbusmenu', signature='ui')
    def LayoutUpdated(self, revision: int, parent_id: int):
        pass

class JBLTrayIndicator(dbus.service.Object):
    """
    Exporta o StatusNotifierItem na sessão D-Bus e registra junto ao StatusNotifierWatcher do GNOME.
    """
    def __init__(
        self,
        on_toggle_window: Optional[Callable[[], None]] = None,
        on_set_anc: Optional[Callable[[AncMode], None]] = None,
        on_set_preset: Optional[Callable[[int], None]] = None,
        on_refresh: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None
    ):
        self.on_toggle_window = on_toggle_window
        self.on_set_anc = on_set_anc
        self.on_set_preset = on_set_preset
        self.on_refresh = on_refresh
        self.on_quit = on_quit

        self.device_name = "Nenhum fone conectado"
        self.is_connected = False
        self.battery_overall: Optional[int] = None
        self.bat_l: Optional[int] = None
        self.bat_r: Optional[int] = None
        self.bat_c: Optional[int] = None
        self.ch_l: bool = False
        self.ch_r: bool = False
        self.ch_c: bool = False
        self.active_anc = AncMode.OFF
        self.active_preset = 0

        self.menu_service: Optional[TrayMenu] = None
        self._registered = False

        if dbus is None:
            return

        try:
            DBusGMainLoop(set_as_default=True)
            self.bus = dbus.SessionBus()
            super().__init__(self.bus, '/StatusNotifierItem')
            self.menu_service = TrayMenu(self.bus, '/MenuBar', self)
            self._register_with_watcher()
        except Exception as e:
            print(f"[TrayIndicator] Erro ao inicializar D-Bus StatusNotifierItem: {e}", file=sys.stderr)

    def _register_with_watcher(self):
        try:
            if not self.bus.name_has_owner('org.kde.StatusNotifierWatcher'):
                print("[TrayIndicator] StatusNotifierWatcher não está ativo no momento.")
                return

            watcher = self.bus.get_object('org.kde.StatusNotifierWatcher', '/StatusNotifierWatcher')
            watcher_iface = dbus.Interface(watcher, 'org.kde.StatusNotifierWatcher')
            watcher_iface.RegisterStatusNotifierItem('/StatusNotifierItem')
            self._registered = True
            print("[TrayIndicator] Registrado com sucesso no StatusNotifierWatcher do sistema!")
        except Exception as e:
            print(f"[TrayIndicator] Aviso ao registrar no watcher: {e}", file=sys.stderr)

    # Propriedades D-Bus de org.kde.StatusNotifierItem
    @dbus.service.method('org.freedesktop.DBus.Properties', in_signature='ss', out_signature='v')
    def Get(self, interface: str, prop: str):
        return self.GetAll(interface).get(prop, "")

    @dbus.service.method('org.freedesktop.DBus.Properties', in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface: str):
        icon_path = os.path.expanduser("~/.local/share/icons/hicolor/256x256/apps")
        title = f"JBL Headphones - {self.device_name}"
        return {
            'Category': dbus.String('ApplicationStatus'),
            'Id': dbus.String('io.github.jbl.headphones.linux'),
            'Title': dbus.String(title),
            'Status': dbus.String('Active'),
            'IconName': dbus.String('io.github.jbl.headphones.linux'),
            'IconThemePath': dbus.String(icon_path),
            'Menu': dbus.ObjectPath('/MenuBar'),
            'ItemIsMenu': dbus.Boolean(False),
        }

    @dbus.service.method('org.kde.StatusNotifierItem', in_signature='ii', out_signature='')
    def Activate(self, x: int, y: int):
        """Clique no ícone da barra superior: alterna a visibilidade da janela principal."""
        if self.on_toggle_window:
            self.on_toggle_window()

    @dbus.service.method('org.kde.StatusNotifierItem', in_signature='ii', out_signature='')
    def ContextMenu(self, x: int, y: int):
        pass

    @dbus.service.method('org.kde.StatusNotifierItem', in_signature='is', out_signature='')
    def Scroll(self, delta: int, orientation: str):
        pass

    def build_menu_layout(self, parent_id: int):
        """Gera a árvore de itens do menu suspenso nativo da barra superior."""
        children = []

        # 1. Título do Dispositivo
        dev_title = f"🎧 {self.device_name}"
        if self.is_connected:
            dev_title += " (Conectado)"
        children.append((100, {'label': dbus.String(dev_title), 'enabled': dbus.Boolean(False)}, []))

        # 2. Informações de Bateria
        if self.is_connected:
            bat_parts = []
            if self.bat_l is not None and self.bat_l <= 100:
                bat_parts.append(f"L: {self.bat_l}%{'⚡' if self.ch_l else ''}")
            if self.bat_r is not None and self.bat_r <= 100:
                bat_parts.append(f"R: {self.bat_r}%{'⚡' if self.ch_r else ''}")
            if self.bat_c is not None and self.bat_c <= 100:
                bat_parts.append(f"Case: {self.bat_c}%{'⚡' if self.ch_c else ''}")

            if bat_parts:
                bat_text = "🔋 " + " | ".join(bat_parts)
            elif self.battery_overall is not None:
                bat_text = f"🔋 Bateria: {self.battery_overall}%"
            else:
                bat_text = "🔋 Bateria: Lendo..."
            children.append((101, {'label': dbus.String(bat_text), 'enabled': dbus.Boolean(False)}, []))

        children.append((102, {'type': dbus.String('separator')}, []))

        # 3. Submenu / Itens de Controle de Ruído (ANC)
        anc_label = "Controle de Som e ANC"
        anc_children = [
            (201, {'label': dbus.String(f"{'● ' if self.active_anc == AncMode.ANC else '  '}🔇 Cancelamento Ativo (ANC)")}, []),
            (202, {'label': dbus.String(f"{'● ' if self.active_anc == AncMode.AMBIENT_AWARE else '  '}👂 Som Ambiente (Ambient)")}, []),
            (203, {'label': dbus.String(f"{'● ' if self.active_anc == AncMode.TALKTHRU else '  '}💬 Modo Conversa (TalkThru)")}, []),
            (204, {'label': dbus.String(f"{'● ' if self.active_anc == AncMode.OFF else '  '}⚪ Desligado")}, []),
        ]
        children.append((200, {
            'label': dbus.String(anc_label),
            'children-display': dbus.String('submenu')
        }, anc_children))

        # 4. Submenu de Equalizador
        presets = ["Jazz", "Vocal", "Bass", "Extreme Bass", "Club", "Studio (Flat)", "Pop"]
        eq_children = []
        for idx, p_name in enumerate(presets):
            prefix = "● " if self.active_preset == idx else "  "
            eq_children.append((300 + idx, {'label': dbus.String(f"{prefix}🎵 {p_name}")}, []))

        children.append((350, {
            'label': dbus.String("Predefinições de Equalizador"),
            'children-display': dbus.String('submenu')
        }, eq_children))

        children.append((400, {'type': dbus.String('separator')}, []))

        # 5. Ações da Aplicação
        children.append((401, {'label': dbus.String("👁️ Abrir / Ocultar Janela")}, []))
        children.append((402, {'label': dbus.String("🔄 Procurar Fones / Reconectar")}, []))
        children.append((403, {'type': dbus.String('separator')}, []))
        children.append((404, {'label': dbus.String("❌ Sair do JBL Headphones")}, []))

        root = (0, {'children-display': dbus.String('submenu')}, children)
        return root

    def handle_menu_click(self, item_id: int):
        """Despacha cliques de itens do menu suspenso."""
        # ANC Modes
        if item_id == 201 and self.on_set_anc:
            self.on_set_anc(AncMode.ANC)
        elif item_id == 202 and self.on_set_anc:
            self.on_set_anc(AncMode.AMBIENT_AWARE)
        elif item_id == 203 and self.on_set_anc:
            self.on_set_anc(AncMode.TALKTHRU)
        elif item_id == 204 and self.on_set_anc:
            self.on_set_anc(AncMode.OFF)

        # EQ Presets
        elif 300 <= item_id <= 306 and self.on_set_preset:
            preset_idx = item_id - 300
            self.on_set_preset(preset_idx)

        # App Actions
        elif item_id == 401 and self.on_toggle_window:
            self.on_toggle_window()
        elif item_id == 402 and self.on_refresh:
            self.on_refresh()
        elif item_id == 404 and self.on_quit:
            self.on_quit()

    def update_device(self, name: str, connected: bool):
        self.device_name = name if name else "Nenhum fone conectado"
        self.is_connected = connected
        self._notify_layout_changed()

    def update_battery(
        self,
        overall: Optional[int] = None,
        l: Optional[int] = None,
        r: Optional[int] = None,
        c: Optional[int] = None,
        ch_l: bool = False,
        ch_r: bool = False,
        ch_c: bool = False
    ):
        if overall is not None:
            self.battery_overall = overall
        if l is not None:
            self.bat_l = l
            self.ch_l = ch_l
        if r is not None:
            self.bat_r = r
            self.ch_r = ch_r
        if c is not None:
            self.bat_c = c
            self.ch_c = ch_c
        self._notify_layout_changed()

    def update_anc_mode(self, mode: AncMode):
        self.active_anc = mode
        self._notify_layout_changed()

    def update_eq_preset(self, preset_idx: int):
        self.active_preset = preset_idx
        self._notify_layout_changed()

    def _notify_layout_changed(self):
        if self.menu_service:
            self.menu_service.revision += 1
            try:
                self.menu_service.LayoutUpdated(self.menu_service.revision, 0)
            except Exception:
                pass
