"""
Interface Gráfica Nativa em GTK4 + Libadwaita para JBL Headphones no Linux.
Adaptação dinâmica para qualquer um dos 128 modelos suportados.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio

import os
from typing import Optional, List, Dict, Any
from core.device_registry import DeviceRegistry, DeviceModel
from core.protocol import Protocol3Handler, Protocol4Handler, AncMode, VoiceAwareLevel
from core.bluetooth_backend import BluetoothBackend, BluetoothDevice
from ui.tray_indicator import JBLTrayIndicator

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, registry: DeviceRegistry, backend: BluetoothBackend):
        super().__init__(application=app, title="JBL Headphones Linux")
        self.set_default_size(720, 800)
        self.set_icon_name("io.github.jbl.headphones.linux")
        
        self.registry = registry
        self.backend = backend
        self.current_model: Optional[DeviceModel] = None
        self.active_anc_mode = AncMode.OFF
        self.active_preset_idx = 0
        self._updating_anc_ui = False
        self._updating_preset_ui = False
        self.eq_sliders: List[Gtk.Scale] = []
        self.frequencies = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

        # Configurar Indicador de Barra Superior (Top Bar Tray)
        self.tray_indicator = JBLTrayIndicator(
            on_toggle_window=self._toggle_window_visibility,
            on_set_anc=self._apply_anc_mode_from_external,
            on_set_preset=self._apply_preset_from_external,
            on_refresh=self._detect_connected_device,
            on_quit=lambda: self.get_application().quit()
        )

        # Intercepta solicitação de fechamento para minimizar para a barra superior
        self.connect("close-request", self._on_close_request)

        # Configurar callback de atualizações de telemetria
        self.backend.on_status_changed = self._on_backend_status_changed

        self._build_ui()
        self._detect_connected_device()

    def _on_close_request(self, window):
        """Oculta a janela em vez de fechar, mantendo o app ativo na barra superior."""
        self.set_visible(False)
        return True

    def _toggle_window_visibility(self):
        """Alterna a visibilidade da janela ao clicar no ícone da barra superior."""
        GLib.idle_add(self._do_toggle_visibility)

    def _do_toggle_visibility(self):
        if self.props.visible:
            self.set_visible(False)
        else:
            self.set_visible(True)
            self.present()

    def _build_ui(self):
        # Caixa principal vertical
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_content(main_box)

        # HeaderBar do Adwaita
        header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle(title="JBL Headphones", subtitle="Procurando fones...")
        header.set_title_widget(self.title_widget)

        # Botão de Atualizar / Recarregar Dispositivos
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Procurar Fones JBL Conectados")
        refresh_btn.connect("clicked", lambda _: self._detect_connected_device())
        header.pack_end(refresh_btn)

        main_box.append(header)

        # Toast Overlay para balões elegantes de confirmação imediata
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_vexpand(True)
        main_box.append(self.toast_overlay)

        # Área de rolagem para o conteúdo
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self.toast_overlay.set_child(scroller)

        # Container Adwaita Clamp para manter a interface elegante e centralizada
        clamp = Adw.Clamp()
        clamp.set_maximum_size(680)
        scroller.set_child(clamp)

        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.content_box.set_margin_top(18)
        self.content_box.set_margin_bottom(24)
        self.content_box.set_margin_start(16)
        self.content_box.set_margin_end(16)
        clamp.set_child(self.content_box)

        # 1. Card de Status e Foto do Dispositivo
        self._build_device_status_card()

        # 2. Card de Cancelamento de Ruído (ANC / Som Ambiente)
        self._build_anc_card()

        # 3. Card do Equalizador Oficial de 10 Bandas
        self._build_equalizer_card()

        # 4. Card de Recursos Adicionais (VoiceAware, Latência, Find Buds)
        self._build_extra_features_card()

        # 5. Card de Simulação e Seleção de Modelos
        self._build_model_selector_card()

    def _build_device_status_card(self):
        # 1. Hero Card: Foto Oficial em Alta Resolução do Fone
        self.hero_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.hero_box.set_halign(Gtk.Align.CENTER)
        self.hero_box.set_margin_top(8)
        self.hero_box.set_margin_bottom(12)
        self.hero_box.set_visible(False)

        self.device_hero_image = Gtk.Image()
        self.device_hero_image.set_pixel_size(210)
        self.hero_box.append(self.device_hero_image)

        self.content_box.append(self.hero_box)

        # 2. Grupo de Informações de Conexão e Bateria
        status_group = Adw.PreferencesGroup(title="Status do Dispositivo")
        self.content_box.append(status_group)

        self.device_banner = Adw.ActionRow()
        self.device_banner.set_title("Nenhum fone conectado")
        self.device_banner.set_subtitle("Conecte seu fone JBL pelo Bluetooth do sistema")

        # Container de prefixo (Ícone ou Miniatura da Foto)
        prefix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        
        self.device_thumb = Gtk.Image()
        self.device_thumb.set_pixel_size(44)
        self.device_thumb.set_visible(False)
        prefix_box.append(self.device_thumb)

        self.device_icon = Gtk.Image.new_from_icon_name("audio-headphones-symbolic")
        self.device_icon.set_pixel_size(36)
        prefix_box.append(self.device_icon)

        self.device_banner.add_prefix(prefix_box)

        # Badge de status geral / bateria
        self.battery_badge = Gtk.Label(label="--%")
        self.battery_badge.add_css_class("heading")
        self.battery_badge.add_css_class("accent")
        self.device_banner.add_suffix(self.battery_badge)

        status_group.add(self.device_banner)

        # 3. Níveis Detalhados de Bateria em Tempo Real (Esquerdo, Direito, Estojo)
        # Fone Esquerdo (L)
        self.row_battery_left = Adw.ActionRow(title="Fone Esquerdo (L)")
        self.row_battery_left.set_subtitle("Telemetria em tempo real")
        self.icon_left = Gtk.Image.new_from_icon_name("audio-headset-symbolic")
        self.row_battery_left.add_prefix(self.icon_left)
        
        box_suffix_l = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.progress_battery_left = Gtk.ProgressBar()
        self.progress_battery_left.set_size_request(80, 8)
        self.progress_battery_left.set_valign(Gtk.Align.CENTER)
        box_suffix_l.append(self.progress_battery_left)
        self.badge_battery_left = Gtk.Label(label="--%")
        self.badge_battery_left.add_css_class("title-3")
        box_suffix_l.append(self.badge_battery_left)
        self.row_battery_left.add_suffix(box_suffix_l)
        status_group.add(self.row_battery_left)

        # Fone Direito (R)
        self.row_battery_right = Adw.ActionRow(title="Fone Direito (R)")
        self.row_battery_right.set_subtitle("Telemetria em tempo real")
        self.icon_right = Gtk.Image.new_from_icon_name("audio-headset-symbolic")
        self.row_battery_right.add_prefix(self.icon_right)
        
        box_suffix_r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.progress_battery_right = Gtk.ProgressBar()
        self.progress_battery_right.set_size_request(80, 8)
        self.progress_battery_right.set_valign(Gtk.Align.CENTER)
        box_suffix_r.append(self.progress_battery_right)
        self.badge_battery_right = Gtk.Label(label="--%")
        self.badge_battery_right.add_css_class("title-3")
        box_suffix_r.append(self.badge_battery_right)
        self.row_battery_right.add_suffix(box_suffix_r)
        status_group.add(self.row_battery_right)

        # Estojo de Carregamento (Case)
        self.row_battery_case = Adw.ActionRow(title="Estojo de Carregamento (Case)")
        self.row_battery_case.set_subtitle("Status de bateria do estojo")
        self.icon_case = Gtk.Image.new_from_icon_name("battery-symbolic")
        self.row_battery_case.add_prefix(self.icon_case)
        
        box_suffix_c = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.progress_battery_case = Gtk.ProgressBar()
        self.progress_battery_case.set_size_request(80, 8)
        self.progress_battery_case.set_valign(Gtk.Align.CENTER)
        box_suffix_c.append(self.progress_battery_case)
        self.badge_battery_case = Gtk.Label(label="--%")
        self.badge_battery_case.add_css_class("title-3")
        box_suffix_c.append(self.badge_battery_case)
        self.row_battery_case.add_suffix(box_suffix_c)
        status_group.add(self.row_battery_case)

        # Dica de sincronização inteligente TWS
        self.row_case_tip = Adw.ActionRow(title="Sincronização do Estojo")
        self.row_case_tip.set_subtitle("💡 O estojo se comunica com os fones pelos pinos de contato. Ao terminar de carregar na tomada, coloque um fone no estojo por 1s para atualizar o percentual.")
        icon_tip = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        self.row_case_tip.add_prefix(icon_tip)
        status_group.add(self.row_case_tip)

    def _build_anc_card(self):
        self.anc_group = Adw.PreferencesGroup(title="Controle de Som e Cancelamento de Ruído")
        self.content_box.append(self.anc_group)

        anc_row = Adw.ActionRow(title="Modo de Som Ambiente")
        anc_row.set_subtitle("Alterne entre isolamento e conscientização do ambiente")

        # Seletor de Modos (Segmented Button)
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.add_css_class("linked")

        self.btn_anc = Gtk.ToggleButton(label="🔇 ANC")
        self.btn_anc.set_tooltip_text("Cancelamento Ativo de Ruído")
        self.btn_anc.connect("toggled", lambda b: self._on_anc_button_toggled(AncMode.ANC, b))
        btn_box.append(self.btn_anc)

        self.btn_ambient = Gtk.ToggleButton(label="👂 Ambiente")
        self.btn_ambient.set_tooltip_text("Ambient Aware (Som do ambiente amplificado)")
        self.btn_ambient.set_group(self.btn_anc)
        self.btn_ambient.connect("toggled", lambda b: self._on_anc_button_toggled(AncMode.AMBIENT_AWARE, b))
        btn_box.append(self.btn_ambient)

        self.btn_talkthru = Gtk.ToggleButton(label="💬 TalkThru")
        self.btn_talkthru.set_tooltip_text("TalkThru (Música baixa e voz amplificada para conversar)")
        self.btn_talkthru.set_group(self.btn_anc)
        self.btn_talkthru.connect("toggled", lambda b: self._on_anc_button_toggled(AncMode.TALKTHRU, b))
        btn_box.append(self.btn_talkthru)

        self.btn_off = Gtk.ToggleButton(label="⚪ Desligado")
        self.btn_off.set_group(self.btn_anc)
        self.btn_off.set_active(True)
        self.btn_off.connect("toggled", lambda b: self._on_anc_button_toggled(AncMode.OFF, b))
        btn_box.append(self.btn_off)

        anc_row.add_suffix(btn_box)
        self.anc_group.add(anc_row)

    def _build_equalizer_card(self):
        self.eq_group = Adw.PreferencesGroup(title="Equalizador Oficial JBL (10 Bandas)")
        self.content_box.append(self.eq_group)

        # Seletor de Presets
        self.preset_row = Adw.ComboRow(title="Predefinição de Equalização")
        preset_names = ["Jazz", "Vocal", "Bass", "Extreme Bass", "Club", "Studio", "Pop", "Personalizado"]
        self.preset_model = Gtk.StringList.new(preset_names)
        self.preset_row.set_model(self.preset_model)
        self.preset_row.connect("notify::selected", self._on_preset_selected)
        self.eq_group.add(self.preset_row)

        # Sliders das 10 frequências
        sliders_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sliders_box.set_homogeneous(True)
        sliders_box.set_margin_top(12)
        sliders_box.set_margin_bottom(12)

        for i, freq in enumerate(self.frequencies):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            
            # Label de ganho em tempo real
            val_lbl = Gtk.Label(label="0 dB")
            val_lbl.add_css_class("caption")

            # Slider vertical (-10 dB a +10 dB)
            slider = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, -10.0, 10.0, 0.5)
            slider.set_inverted(True)
            slider.set_value(0.0)
            slider.set_vexpand(True)
            slider.set_size_request(-1, 140)
            
            # Atualiza o label conforme move
            slider.connect("value-changed", lambda s, l=val_lbl: l.set_text(f"{s.get_value():+.1f} dB"))
            self.eq_sliders.append(slider)

            # Label de frequência
            freq_str = f"{freq}Hz" if freq < 1000 else f"{freq//1000}kHz"
            freq_lbl = Gtk.Label(label=freq_str)
            freq_lbl.add_css_class("caption")
            freq_lbl.add_css_class("dim-label")

            col.append(val_lbl)
            col.append(slider)
            col.append(freq_lbl)
            sliders_box.append(col)

        eq_container = Adw.ActionRow()
        eq_container.set_child(sliders_box)
        self.eq_group.add(eq_container)

        # Botão de envio/aplicação do equalizador
        btn_row = Adw.ActionRow()
        apply_eq_btn = Gtk.Button(label="Aplicar Equalização nos Fones")
        apply_eq_btn.add_css_class("suggested-action")
        apply_eq_btn.connect("clicked", lambda _: self._apply_custom_eq())
        btn_row.add_suffix(apply_eq_btn)
        self.eq_group.add(btn_row)

    def _build_extra_features_card(self):
        self.extra_group = Adw.PreferencesGroup(title="Recursos Adicionais e Áudio")
        self.content_box.append(self.extra_group)

        # VoiceAware (Retorno da própria voz em chamadas)
        voice_row = Adw.ComboRow(title="VoiceAware (Retorno de Voz)")
        voice_row.set_subtitle("Permite ouvir sua própria voz durante ligações")
        voice_opts = ["Desligado", "Baixo", "Médio", "Alto"]
        voice_row.set_model(Gtk.StringList.new(voice_opts))
        voice_row.connect("notify::selected", self._on_voice_aware_selected)
        self.extra_group.add(voice_row)

        # Smart Audio & Video
        smart_mode_row = Adw.ComboRow(title="Modo Inteligente (Smart Audio &amp; Video)")
        smart_mode_row.set_subtitle("Otimiza qualidade para música ou sincronismo para vídeos")
        smart_mode_row.set_model(Gtk.StringList.new(["Modo Normal", "Modo Música (Alta Fidelidade)", "Modo Vídeo (Baixa Latência)"]))
        self.extra_group.add(smart_mode_row)

        # Localizar meus fones (Find My Buds)
        find_row = Adw.ActionRow(title="Buscar Meus Fones (Find My Buds)")
        find_row.set_subtitle("Emite um sinal sonoro de alerta no fone selecionado")
        
        find_left_btn = Gtk.Button(label="Tocar Esquerdo")
        find_left_btn.connect("clicked", lambda _: self._ring_earbud(True, False))
        find_row.add_suffix(find_left_btn)

        find_right_btn = Gtk.Button(label="Tocar Direito")
        find_right_btn.connect("clicked", lambda _: self._ring_earbud(False, True))
        find_row.add_suffix(find_right_btn)

        self.extra_group.add(find_row)

    def _build_model_selector_card(self):
        model_group = Adw.PreferencesGroup(title="Modelo JBL Detectado / Simulação")
        self.content_box.append(model_group)

        self.model_combo = Adw.ComboRow(title="Modelo em Uso")
        self.model_combo.set_subtitle("O app adapta a interface automaticamente de acordo com o modelo")

        model_names = [m.name for m in self.registry.all_models]
        self.model_strings = Gtk.StringList.new(model_names)
        self.model_combo.set_model(self.model_strings)
        self.model_combo.connect("notify::selected", self._on_model_combo_changed)

        model_group.add(self.model_combo)

    def _detect_connected_device(self):
        """Escaneia os fones conectados pelo BlueZ D-Bus e configura a interface."""
        devices = self.backend.scan_jbl_devices()
        connected = [d for d in devices if d.connected]
        paired = [d for d in devices if not d.connected]

        if connected:
            dev = connected[0]
            self.backend.connect(dev)
            
            # Encontrar modelo correspondente
            matched_model = self.registry.find_from_bluetooth(dev.name, dev.modalias)
            if matched_model:
                self._apply_model(matched_model)
                try:
                    idx = [m.name for m in self.registry.all_models].index(matched_model.name)
                    self.model_combo.set_selected(idx)
                except ValueError:
                    pass

            self.title_widget.set_subtitle(f"Conectado: {dev.name}")
            self.device_banner.set_title(dev.name)
            self.device_banner.set_subtitle(f"MAC: {dev.mac} | PID: {matched_model.pid.upper() if matched_model else 'N/A'}")
            
            if dev.battery_percentage is not None:
                self.battery_badge.set_text(f"{dev.battery_percentage}%")
                self.tray_indicator.update_battery(overall=dev.battery_percentage)
            else:
                self.battery_badge.set_text("Conectado")

            self.tray_indicator.update_device(dev.name, True)

            # Envia requisições de telemetria completa via BLE e RFCOMM
            self.backend.send_raw(Protocol3Handler.REQ_DEV_INFO)
            self.backend.send_raw(Protocol3Handler.REQ_BATTERY_INFO)
            self.backend.send_raw(Protocol3Handler.REQ_ANC_MODES)

        elif paired:
            dev = paired[0]
            matched_model = self.registry.find_from_bluetooth(dev.name, dev.modalias)
            if matched_model:
                self._apply_model(matched_model)
                try:
                    idx = [m.name for m in self.registry.all_models].index(matched_model.name)
                    self.model_combo.set_selected(idx)
                except ValueError:
                    pass

            self.title_widget.set_subtitle(f"Pareado: {dev.name} (Desconectado)")
            self.device_banner.set_title(dev.name)
            self.device_banner.set_subtitle(f"MAC: {dev.mac} | Fone pareado no sistema (Tentando reconectar...)")
            self.battery_badge.set_text("Desconectado")
            self.tray_indicator.update_device(dev.name, False)

            # Tenta restabelecer conexão BlueZ em segundo plano
            self.backend.connect_bluez(dev.mac)
            self.backend.connect(dev)
        else:
            self.title_widget.set_subtitle("Nenhum fone conectado")
            self.device_banner.set_title("Nenhum fone conectado")
            self.device_banner.set_subtitle("Conecte seu fone JBL pelo Bluetooth do sistema")
            self.battery_badge.set_text("--%")
            self.tray_indicator.update_device("Nenhum fone conectado", False)
            default_model = self.registry.find_by_name("JBL Tune Buds 2")
            if default_model:
                self._apply_model(default_model)

    def _apply_model(self, model: DeviceModel):
        """Adapta a visibilidade dos cards e a foto oficial de acordo com o modelo."""
        self.current_model = model
        
        # Atualiza a foto oficial do fone
        if model.image_path and os.path.exists(model.image_path):
            self.device_hero_image.set_from_file(model.image_path)
            self.hero_box.set_visible(True)
            self.device_thumb.set_from_file(model.image_path)
            self.device_thumb.set_visible(True)
            self.device_icon.set_visible(False)
        else:
            self.hero_box.set_visible(False)
            self.device_thumb.set_visible(False)
            self.device_icon.set_visible(True)

        # Oculta ou exibe cards baseado nas capacidades do fone
        self.anc_group.set_visible(model.has_anc)
        self.eq_group.set_visible(model.has_equalizer)
        self.extra_group.set_visible(model.has_voice_aware or model.has_find_my_buds)

    def _on_model_combo_changed(self, combo, _):
        idx = combo.get_selected()
        if 0 <= idx < len(self.registry.all_models):
            selected_model = self.registry.all_models[idx]
            self._apply_model(selected_model)

    def _on_anc_button_toggled(self, mode: AncMode, button: Gtk.ToggleButton):
        if self._updating_anc_ui or not button.get_active():
            return

        self.active_anc_mode = mode
        
        # 1. Envia pacotes oficiais Harman Protocol 3 (BES / Clássico)
        pkts_p3 = Protocol3Handler.set_anc_mode(mode)
        for pkt in pkts_p3:
            self.backend.send_raw(pkt)

        # 2. Envia pacotes oficiais Harman Protocol 4 (Geração Moderna)
        pkts_p4 = Protocol4Handler.set_anc_mode(mode)
        for pkt in pkts_p4:
            self.backend.send_raw(pkt)

        # Atualiza indicador da barra superior
        self.tray_indicator.update_anc_mode(mode)

        # Notificação visual elegante Adwaita (Toast)
        labels = {
            AncMode.ANC: "🔇 Cancelamento Ativo de Ruído (ANC) ativado",
            AncMode.AMBIENT_AWARE: "👂 Som Ambiente (Ambient Aware) ativado",
            AncMode.TALKTHRU: "💬 TalkThru ativado",
            AncMode.OFF: "⚪ Modos de som desligados"
        }
        toast = Adw.Toast.new(labels.get(mode, "Modo de som alterado"))
        toast.set_timeout(2)
        self.toast_overlay.add_toast(toast)

    def _apply_anc_mode_from_external(self, mode: AncMode):
        """Chamado a partir do menu suspenso da barra superior para sincronizar a interface."""
        GLib.idle_add(self._do_apply_anc_from_external, mode)

    def _do_apply_anc_from_external(self, mode: AncMode):
        self._updating_anc_ui = True
        try:
            if mode == AncMode.ANC:
                self.btn_anc.set_active(True)
            elif mode == AncMode.AMBIENT_AWARE:
                self.btn_ambient.set_active(True)
            elif mode == AncMode.TALKTHRU:
                self.btn_talkthru.set_active(True)
            else:
                self.btn_off.set_active(True)
        finally:
            self._updating_anc_ui = False

        self.active_anc_mode = mode
        pkts_p3 = Protocol3Handler.set_anc_mode(mode)
        for pkt in pkts_p3:
            self.backend.send_raw(pkt)
        pkts_p4 = Protocol4Handler.set_anc_mode(mode)
        for pkt in pkts_p4:
            self.backend.send_raw(pkt)
        self.tray_indicator.update_anc_mode(mode)

    def _on_preset_selected(self, combo, _):
        if self._updating_preset_ui:
            return
        idx = combo.get_selected()
        self.active_preset_idx = idx
        self.tray_indicator.update_eq_preset(idx)

        preset_names = ["Jazz", "Vocal", "Bass", "Extreme Bass", "Club", "Studio", "Pop"]
        presets_gains = {
            0: [4.0, 3.0, 1.0, 2.5, -1.5, -1.5, 0.0, 1.0, 3.0, 4.0],  # Jazz
            1: [-2.0, -1.5, 0.0, 1.0, 3.0, 3.5, 2.0, 1.0, 0.0, -1.0], # Vocal
            2: [5.5, 5.0, 3.5, 1.5, 0.0, 0.0, 0.0, 0.5, 1.0, 1.5],   # Bass
            3: [7.0, 6.5, 5.0, 2.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0],   # Extreme Bass
            4: [4.0, 3.0, 2.0, 0.0, -1.0, 0.0, 2.0, 3.0, 4.0, 4.5],  # Club
            5: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # Studio (Flat)
            6: [3.0, 2.0, 1.0, 0.0, 2.0, 3.0, 2.0, 1.5, 2.5, 3.0],   # Pop
        }

        if idx in presets_gains:
            gains = presets_gains[idx]
            for slider, gain in zip(self.eq_sliders, gains):
                slider.set_value(gain)
            pkt_preset = Protocol3Handler.set_eq_preset(idx)
            pkt_eq2 = Protocol3Handler.build_eq2_packet(gains, preset_id=idx)
            self.backend.send_raw(pkt_preset)
            self.backend.send_raw(pkt_eq2)
            # Envio simultâneo para modelos compatíveis com Protocolo 4
            for p4_pkt in Protocol4Handler.build_eq_curve_packet(gains):
                self.backend.send_raw(p4_pkt)
            p_name = preset_names[idx] if idx < len(preset_names) else ""
            toast = Adw.Toast.new(f"🎵 Predefinição JBL aplicada: {p_name}")
            toast.set_timeout(2)
            self.toast_overlay.add_toast(toast)

    def _apply_preset_from_external(self, idx: int):
        """Chamado a partir do menu da barra superior para selecionar um preset de equalização."""
        GLib.idle_add(self._do_apply_preset_from_external, idx)

    def _do_apply_preset_from_external(self, idx: int):
        self._updating_preset_ui = True
        try:
            if hasattr(self, 'preset_row'):
                self.preset_row.set_selected(idx)
        finally:
            self._updating_preset_ui = False
        self._on_preset_selected(self.preset_row, None)

    def _apply_custom_eq(self):
        gains = [s.get_value() for s in self.eq_sliders]
        pkt = Protocol3Handler.build_eq2_packet(gains, preset_id=0)
        self.backend.send_raw(pkt)
        for p4_pkt in Protocol4Handler.build_eq_curve_packet(gains):
            self.backend.send_raw(p4_pkt)
        toast = Adw.Toast.new("✅ Curva de equalização oficial (10 bandas) aplicada nos fones!")
        toast.set_timeout(2)
        self.toast_overlay.add_toast(toast)

    def _on_voice_aware_selected(self, combo, _):
        level = VoiceAwareLevel(combo.get_selected())
        pkt = Protocol3Handler.set_voice_aware(level)
        self.backend.send_raw(pkt)

    def _ring_earbud(self, ring_left: bool, ring_right: bool):
        pkt = Protocol3Handler.set_find_my_buds(ring_left, ring_right)
        self.backend.send_raw(pkt)

    def _on_backend_status_changed(self, status: Dict[str, Any]):
        """Executado na thread principal para atualizar a UI de forma segura."""
        GLib.idle_add(self._update_ui_from_status, status)

    def _update_ui_from_status(self, status: Dict[str, Any]):
        # Atualização de status BLE / Conexão BlueZ
        if status.get("ble_connected"):
            if self.backend.connected_device:
                self.title_widget.set_subtitle(f"Conectado: {self.backend.connected_device.name} (GATT BLE Ativo)")
                self.tray_indicator.update_device(self.backend.connected_device.name, True)

        if "bluez_connected" in status:
            is_conn = status["bluez_connected"]
            dev_name = status.get("device_name", "Fone JBL")
            if not is_conn:
                self.title_widget.set_subtitle(f"Pareado: {dev_name} (Desconectado)")
                self.battery_badge.set_text("Desconectado")
                self.tray_indicator.update_device(dev_name, False)

        # Sincronização em tempo real de ANC (toque no fone ou resposta de comando)
        if "anc_mode" in status:
            mode = status["anc_mode"]
            self.active_anc_mode = mode
            self.tray_indicator.update_anc_mode(mode)
            self._updating_anc_ui = True
            try:
                if mode == AncMode.ANC:
                    self.btn_anc.set_active(True)
                elif mode == AncMode.AMBIENT_AWARE:
                    self.btn_ambient.set_active(True)
                elif mode == AncMode.TALKTHRU:
                    self.btn_talkthru.set_active(True)
                else:
                    self.btn_off.set_active(True)
            finally:
                self._updating_anc_ui = False

            if status.get("anc_source") == "earbud_notification":
                labels = {
                    AncMode.ANC: "🔇 Cancelamento de Ruído (ANC) ativado no fone",
                    AncMode.AMBIENT_AWARE: "👂 Som Ambiente (Ambient Aware) ativado no fone",
                    AncMode.TALKTHRU: "💬 TalkThru ativado no fone",
                    AncMode.OFF: "⚪ Modos de som desligados no fone"
                }
                toast = Adw.Toast.new(labels.get(mode, "Modo de som alterado"))
                toast.set_timeout(2)
                self.toast_overlay.add_toast(toast)

        if "battery_overall" in status:
            bat = status["battery_overall"]
            self.battery_badge.set_text(f"{bat}%")
            self.tray_indicator.update_battery(overall=bat)
            # Se ainda não recebemos telemetria individual dos fones L/R, reflete a bateria geral
            if self.badge_battery_left.get_text().startswith("--"):
                self.badge_battery_left.set_text(f"{bat}%")
                self.progress_battery_left.set_fraction(max(0.0, min(1.0, bat / 100.0)))
                self.row_battery_left.set_subtitle("Conexão Bluetooth padrão (BlueZ)")

        if "raw_packet" in status:
            raw_pkt = status["raw_packet"]
            parsed = Protocol3Handler.parse_packet(raw_pkt)
            parsed_p4 = Protocol4Handler.parse_packet(raw_pkt)
            for k, v in parsed_p4.items():
                if k not in parsed or parsed[k] is None:
                    parsed[k] = v

            if "anc_mode" in parsed and "anc_mode" not in status:
                status["anc_mode"] = parsed["anc_mode"]
                mode = parsed["anc_mode"]
                self.active_anc_mode = mode
                self.tray_indicator.update_anc_mode(mode)
                self._updating_anc_ui = True
                try:
                    if mode == AncMode.ANC:
                        self.btn_anc.set_active(True)
                    elif mode == AncMode.AMBIENT_AWARE:
                        self.btn_ambient.set_active(True)
                    elif mode == AncMode.TALKTHRU:
                        self.btn_talkthru.set_active(True)
                    else:
                        self.btn_off.set_active(True)
                finally:
                    self._updating_anc_ui = False
            
            if "device_name" in parsed:
                dname = parsed["device_name"]
                self.device_banner.set_title(dname)
                self.tray_indicator.update_device(dname, True)

            if "firmware_version" in parsed:
                fw = parsed["firmware_version"]
                curr_sub = self.device_banner.get_subtitle() or ""
                if "FW:" not in curr_sub:
                    self.device_banner.set_subtitle(f"{curr_sub} | FW: {fw}")

            if "battery_left" in parsed or "battery_right" in parsed or "battery_case" in parsed:
                l = parsed.get("battery_left")
                r = parsed.get("battery_right")
                c = parsed.get("battery_case")
                charging_l = parsed.get("charging_left", False)
                charging_r = parsed.get("charging_right", False)
                charging_c = parsed.get("charging_case", False)

                if l is not None and l <= 100:
                    txt_l = f"{l}%" + (" ⚡ Carregando" if charging_l else "")
                    self.badge_battery_left.set_text(txt_l)
                    self.progress_battery_left.set_fraction(max(0.0, min(1.0, l / 100.0)))
                    self.row_battery_left.set_subtitle("⚡ No estojo (Carregando)" if charging_l else "Em uso")

                if r is not None and r <= 100:
                    txt_r = f"{r}%" + (" ⚡ Carregando" if charging_r else "")
                    self.badge_battery_right.set_text(txt_r)
                    self.progress_battery_right.set_fraction(max(0.0, min(1.0, r / 100.0)))
                    self.row_battery_right.set_subtitle("⚡ No estojo (Carregando)" if charging_r else "Em uso")

                if c is not None and c <= 100:
                    txt_c = f"{c}%" + (" ⚡ Carregando" if charging_c else "")
                    self.badge_battery_case.set_text(txt_c)
                    self.progress_battery_case.set_fraction(max(0.0, min(1.0, c / 100.0)))
                    if charging_c:
                        self.row_battery_case.set_subtitle("⚡ Conectado à alimentação (Carregando)")
                    elif c == 100:
                        self.row_battery_case.set_subtitle("⚡ Estojo 100% carregado")
                    elif not charging_l and not charging_r:
                        self.row_battery_case.set_subtitle(f"Última leitura ({c}%) | Coloque o fone no estojo para sincronizar")
                    else:
                        self.row_battery_case.set_subtitle("Carga restante do estojo (sincronizado)")

                # Calcula média real e justa dos fones conectados
                active_buds = [val for val in (l, r) if val is not None and 0 < val <= 100]
                avg_bat = None
                if active_buds:
                    avg_bat = sum(active_buds) // len(active_buds)
                    is_charging = charging_l or charging_r
                    self.battery_badge.set_text(f"{avg_bat}%{' ⚡' if is_charging else ''}")

                self.tray_indicator.update_battery(
                    overall=avg_bat if avg_bat is not None else (self.backend.connected_device.battery_percentage if self.backend.connected_device else None),
                    l=l,
                    r=r,
                    c=c,
                    ch_l=charging_l,
                    ch_r=charging_r,
                    ch_c=charging_c
                )
