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
        root = self.indicator.build_menu_layout(parent_id)
        serialized = self.indicator.serialize_node(root)
        return (dbus.UInt32(self.revision), serialized)

    @dbus.service.method('com.canonical.dbusmenu', in_signature='aias', out_signature='a(ia{sv})')
    def GetGroupProperties(self, ids: List[int], property_names: List[str]):
        res = dbus.Array([], signature='(ia{sv})')
        m = self.indicator.get_all_menu_items_map()
        for item_id in ids:
            p = m.get(int(item_id), {})
            d = dbus.Dictionary({}, signature='sv')
            for k, v in p.items():
                if isinstance(v, bool):
                    d[dbus.String(k)] = dbus.Boolean(v, variant_level=1)
                elif isinstance(v, int):
                    d[dbus.String(k)] = dbus.Int32(v, variant_level=1)
                else:
                    d[dbus.String(k)] = dbus.String(str(v), variant_level=1)
            res.append((dbus.Int32(item_id), d))
        return res

    @dbus.service.method('com.canonical.dbusmenu', in_signature='isvu', out_signature='')
    def Event(self, item_id: int, event_id: str, data: Any, timestamp: int):
        if event_id in ("clicked", "activate"):
            self.indicator.handle_menu_click(int(item_id))

    @dbus.service.method('com.canonical.dbusmenu', in_signature='i', out_signature='b')
    def AboutToShow(self, item_id: int) -> bool:
        return False

    @dbus.service.signal('com.canonical.dbusmenu', signature='ui')
    def LayoutUpdated(self, revision: int, parent_id: int):
        pass

    @dbus.service.signal('com.canonical.dbusmenu', signature='a(ia{sv})a(ias)')
    def ItemsPropertiesUpdated(self, updatedProps: Any, removedProps: Any):
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
        on_set_smart_mode: Optional[Callable[[str], None]] = None,
        on_refresh: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None
    ):
        self.on_toggle_window = on_toggle_window
        self.on_set_anc = on_set_anc
        self.on_set_preset = on_set_preset
        self.on_set_smart_mode = on_set_smart_mode
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
        self.active_smart_mode = "normal"

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
        """Clique com botão secundário / menu de contexto: alterna visibilidade."""
        if self.on_toggle_window:
            self.on_toggle_window()

    @dbus.service.method('org.kde.StatusNotifierItem', in_signature='ii', out_signature='')
    def SecondaryActivate(self, x: int, y: int):
        if self.on_toggle_window:
            self.on_toggle_window()

    @dbus.service.method('org.kde.StatusNotifierItem', in_signature='is', out_signature='')
    def Scroll(self, delta: int, orientation: str):
        pass

    def serialize_node(self, node):
        """Converte recursivamente um nó de menu (id, props, children) em formato D-Bus estritamente tipado."""
        item_id, props, children = node
        dbus_children = dbus.Array([], signature='v')
        for child in children:
            child_struct = self.serialize_node(child)
            dbus_children.append(dbus.Struct(child_struct, signature='(ia{sv}av)', variant_level=1))

        dbus_props = dbus.Dictionary({}, signature='sv')
        for k, v in props.items():
            if isinstance(v, bool):
                dbus_props[dbus.String(k)] = dbus.Boolean(v, variant_level=1)
            elif isinstance(v, int):
                dbus_props[dbus.String(k)] = dbus.Int32(v, variant_level=1)
            else:
                dbus_props[dbus.String(k)] = dbus.String(str(v), variant_level=1)

        return (dbus.Int32(item_id), dbus_props, dbus_children)

    def get_all_menu_items_map(self) -> Dict[int, Dict[str, Any]]:
        """Mapeia todas as propriedades de todos os itens do menu por ID para atendimento a GetGroupProperties."""
        items_map = {}
        def collect(node):
            items_map[node[0]] = node[1]
            for child in node[2]:
                collect(child)

        root = self.build_menu_layout(0)
        collect(root)
        return items_map

    def build_menu_layout(self, parent_id: int):
        """Gera a árvore de itens do menu suspenso nativo da barra superior."""
        children = []

        # 1. Título do Dispositivo
        dev_title = f"🎧 {self.device_name}"
        if self.is_connected:
            dev_title += " (Conectado)"
        children.append((100, {'label': dev_title, 'enabled': False}, []))

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
            children.append((101, {'label': bat_text, 'enabled': False}, []))

        children.append((102, {'type': 'separator'}, []))

        # 3. Submenu / Itens de Controle de Ruído (ANC)
        anc_label = "Controle de Som e ANC"
        anc_children = [
            (201, {'label': f"{'● ' if self.active_anc == AncMode.ANC else '  '}🔇 Cancelamento Ativo (ANC)"}, []),
            (202, {'label': f"{'● ' if self.active_anc == AncMode.AMBIENT_AWARE else '  '}👂 Som Ambiente (Ambient)"}, []),
            (203, {'label': f"{'● ' if self.active_anc == AncMode.TALKTHRU else '  '}💬 Modo Conversa (TalkThru)"}, []),
            (204, {'label': f"{'● ' if self.active_anc == AncMode.OFF else '  '}⚪ Desligado"}, []),
        ]
        children.append((200, {
            'label': anc_label,
            'children-display': 'submenu'
        }, anc_children))

        # 4. Submenu de Equalizador
        presets = ["Jazz", "Vocal", "Bass", "Extreme Bass", "Club", "Studio (Flat)", "Pop"]
        eq_children = []
        for idx, p_name in enumerate(presets):
            prefix = "● " if self.active_preset == idx else "  "
            eq_children.append((300 + idx, {'label': f"{prefix}🎵 {p_name}"}, []))

        children.append((350, {
            'label': "Predefinições de Equalizador",
            'children-display': 'submenu'
        }, eq_children))

        # 5. Submenu de Modo Áudio / Vídeo (Latência)
        smart_children = [
            (381, {'label': f"{'● ' if self.active_smart_mode == 'normal' else '  '}⚪ Modo Normal (Padrão)"}, []),
            (382, {'label': f"{'● ' if self.active_smart_mode == 'audio' else '  '}🎵 Modo Áudio (Alta Fidelidade)"}, []),
            (383, {'label': f"{'● ' if self.active_smart_mode == 'video' else '  '}🎬 Modo Vídeo (Baixa Latência)"}, []),
        ]
        children.append((380, {
            'label': "Modo Áudio & Vídeo (Latência)",
            'children-display': 'submenu'
        }, smart_children))

        children.append((400, {'type': 'separator'}, []))

        # 6. Ações da Aplicação
        children.append((401, {'label': "👁️ Abrir / Ocultar Janela"}, []))
        children.append((402, {'label': "🔄 Procurar Fones / Reconectar"}, []))
        children.append((403, {'type': 'separator'}, []))
        children.append((404, {'label': "❌ Sair do JBL Headphones"}, []))

        if parent_id == 200:
            return (200, {'label': anc_label, 'children-display': 'submenu'}, anc_children)
        elif parent_id == 350:
            return (350, {'label': "Predefinições de Equalizador", 'children-display': 'submenu'}, eq_children)
        elif parent_id == 380:
            return (380, {'label': "Modo Áudio & Vídeo (Latência)", 'children-display': 'submenu'}, smart_children)

        root = (0, {'children-display': 'submenu'}, children)
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

        # Smart Audio & Video Modes
        elif item_id == 381 and self.on_set_smart_mode:
            self.on_set_smart_mode("normal")
        elif item_id == 382 and self.on_set_smart_mode:
            self.on_set_smart_mode("audio")
        elif item_id == 383 and self.on_set_smart_mode:
            self.on_set_smart_mode("video")

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

    def update_smart_mode(self, mode: str):
        self.active_smart_mode = mode
        self._notify_layout_changed()

    def _notify_layout_changed(self):
        if self.menu_service:
            self.menu_service.revision += 1
            try:
                self.menu_service.LayoutUpdated(dbus.UInt32(self.menu_service.revision), dbus.Int32(0))
            except Exception:
                pass
