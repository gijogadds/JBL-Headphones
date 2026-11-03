"""
Interface Gráfica Nativa em GTK4 + Libadwaita para JBL Headphones no Linux.
Adaptação dinâmica para qualquer um dos 128 modelos suportados.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio

import os
import time
from typing import Optional, List, Dict, Any
from core.device_registry import DeviceRegistry, DeviceModel
from core.equalizer import EQ_PRESET_GAINS, EQ_PRESET_NAMES, identify_eq_preset
from core.protocol import Protocol3Handler, Protocol4Handler, AncMode, VoiceAwareLevel
from core.bluetooth_backend import BluetoothBackend, BluetoothDevice
from ui.tray_indicator import JBLTrayIndicator

class MainWindow(Adw.ApplicationWindow):
    def __init__(
        self, 
        app: Adw.Application, 
        registry: DeviceRegistry, 
        backend: BluetoothBackend,
        start_in_tray: bool = False,
        auto_close_on_disconnect: bool = True
    ):
        super().__init__(application=app, title="JBL Headphones Linux")
        self.set_default_size(720, 800)
        self.set_icon_name("io.github.jbl.headphones.linux")
        
        self.start_in_tray = start_in_tray
        self.auto_close_on_disconnect = auto_close_on_disconnect
        self._device_ever_connected = False
        self._ble_connected = False
        self._shutdown_timer_id: Optional[int] = None

        self.registry = registry
        self.backend = backend
        self.current_model: Optional[DeviceModel] = None
        self._device_mac = ""
        self._device_pid = ""
        self._device_firmware = ""
        self.active_anc_mode: Optional[AncMode] = None
        self.active_preset_idx = 0
        self._updating_anc_ui = False
        self._updating_preset_ui = False
        self._updating_extra_ui = False
        self._eq_debounce_timer: Optional[int] = None
        self._balance_debounce_timer: Optional[int] = None
        self._smart_mode_transition_deadline = 0.0
        self._smart_mode_transition_timer: Optional[int] = None
        self._smart_mode_disconnect_seen = False
        self._smart_mode_last_reconnect_attempt = 0.0
        self.eq_sliders: List[Gtk.Scale] = []
        self.frequencies = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

        # Configurar Indicador de Barra Superior (Top Bar Tray)
        self.tray_indicator = JBLTrayIndicator(
            on_toggle_window=self._toggle_window_visibility,
            on_set_anc=self._apply_anc_mode_from_external,
            on_set_preset=self._apply_preset_from_external,
            on_set_smart_mode=self._apply_smart_mode_from_external,
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

    def _schedule_auto_shutdown(self):
        """Se os fones forem desligados, encerra o programa automaticamente após breve tolerância."""
        if self._shutdown_timer_id is not None:
            return
        print("[MainWindow] Fones desconectados. Aguardando 3.0s para encerramento automático...")
        self._shutdown_timer_id = GLib.timeout_add(3000, self._do_auto_shutdown)

    def _cancel_auto_shutdown(self):
        if self._shutdown_timer_id is not None:
            GLib.source_remove(self._shutdown_timer_id)
            self._shutdown_timer_id = None

    def _do_auto_shutdown(self):
        self._shutdown_timer_id = None
        if self._smart_mode_transition_deadline > time.monotonic():
            self._shutdown_timer_id = GLib.timeout_add_seconds(
                3, self._do_auto_shutdown
            )
            return False
        # Verifica se algum dispositivo JBL continua conectado no sistema
        devices = self.backend.scan_jbl_devices()
        connected = [d for d in devices if d.connected]
        if not connected:
            print("[MainWindow] Fones desligados. Encerrando o aplicativo automaticamente.")
            app = self.get_application()
            if app:
                app.quit()
        return False

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

        # Área de rolagem para o conteúdo (com rolagem cinética desativada para evitar tremor ao mover sliders)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_kinetic_scrolling(False)
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
        self.progress_battery_left.set_size_request(72, 8)
        self.progress_battery_left.set_valign(Gtk.Align.CENTER)
        box_suffix_l.append(self.progress_battery_left)
        self.badge_battery_left = Gtk.Label(label="--%")
        self.badge_battery_left.add_css_class("title-3")
        self.badge_battery_left.set_width_chars(6)
        self.badge_battery_left.set_xalign(1.0)
        box_suffix_l.append(self.badge_battery_left)
        box_suffix_l.set_size_request(152, -1)
        box_suffix_l.set_halign(Gtk.Align.END)
        self.row_battery_left.add_suffix(box_suffix_l)
        status_group.add(self.row_battery_left)

        # Fone Direito (R)
        self.row_battery_right = Adw.ActionRow(title="Fone Direito (R)")
        self.row_battery_right.set_subtitle("Telemetria em tempo real")
        self.icon_right = Gtk.Image.new_from_icon_name("audio-headset-symbolic")
        self.row_battery_right.add_prefix(self.icon_right)
        
        box_suffix_r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.progress_battery_right = Gtk.ProgressBar()
        self.progress_battery_right.set_size_request(72, 8)
        self.progress_battery_right.set_valign(Gtk.Align.CENTER)
        box_suffix_r.append(self.progress_battery_right)
        self.badge_battery_right = Gtk.Label(label="--%")
        self.badge_battery_right.add_css_class("title-3")
        self.badge_battery_right.set_width_chars(6)
        self.badge_battery_right.set_xalign(1.0)
        box_suffix_r.append(self.badge_battery_right)
        box_suffix_r.set_size_request(152, -1)
        box_suffix_r.set_halign(Gtk.Align.END)
        self.row_battery_right.add_suffix(box_suffix_r)
        status_group.add(self.row_battery_right)

        # Estojo de Carregamento (Case)
        self.row_battery_case = Adw.ActionRow(title="Estojo de Carregamento (Case)")
        self.row_battery_case.set_subtitle("Status de bateria do estojo")
        self.icon_case = Gtk.Image.new_from_icon_name("battery-symbolic")
        self.row_battery_case.add_prefix(self.icon_case)
        
        box_suffix_c = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.progress_battery_case = Gtk.ProgressBar()
        self.progress_battery_case.set_size_request(72, 8)
        self.progress_battery_case.set_valign(Gtk.Align.CENTER)
        box_suffix_c.append(self.progress_battery_case)
        self.badge_battery_case = Gtk.Label(label="--%")
        self.badge_battery_case.add_css_class("title-3")
        self.badge_battery_case.set_width_chars(6)
        self.badge_battery_case.set_xalign(1.0)
        box_suffix_c.append(self.badge_battery_case)
        box_suffix_c.set_size_request(152, -1)
        box_suffix_c.set_halign(Gtk.Align.END)
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
        self.btn_off.connect("toggled", lambda b: self._on_anc_button_toggled(AncMode.OFF, b))
        btn_box.append(self.btn_off)

        anc_row.add_suffix(btn_box)
        self.anc_group.add(anc_row)

    def _build_equalizer_card(self):
        self.eq_group = Adw.PreferencesGroup(title="Equalizador Oficial JBL (10 Bandas)")
        self.content_box.append(self.eq_group)

        # Seletor de Presets
        self.preset_row = Adw.ComboRow(title="Predefinição de Equalização")
        self.preset_model = Gtk.StringList.new(list(EQ_PRESET_NAMES))
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
            val_lbl.set_size_request(48, -1)
            val_lbl.set_xalign(0.5)

            # Slider vertical (-10 dB a +10 dB)
            slider = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, -10.0, 10.0, 0.5)
            slider.set_inverted(True)
            slider.set_value(0.0)
            slider.set_vexpand(True)
            slider.set_size_request(-1, 140)
            slider.set_round_digits(1)
            
            # Atualiza o label conforme move e aplica equalização em tempo real debounced
            slider.connect("value-changed", self._on_slider_value_changed, val_lbl)
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
        self.extra_group = Adw.PreferencesGroup(title="Recursos Avançados e Áudio")
        self.content_box.append(self.extra_group)

        # 1. Modo Inteligente (Smart Audio & Video)
        self.smart_mode_row = Adw.ComboRow(title="Modo Inteligente de Áudio/Vídeo")
        self.smart_mode_row.set_subtitle("Áudio prioriza fidelidade; vídeo e jogos reduzem a latência.")
        smart_opts = ["Normal", "Áudio", "Vídeo"]
        self.smart_mode_row.set_model(Gtk.StringList.new(smart_opts))
        self.smart_mode_row.connect("notify::selected", self._on_smart_audio_video_selected)
        self.extra_group.add(self.smart_mode_row)

        # 2. Balanço de Áudio Estéreo Esquerdo / Direito (Left / Right Sound Balance)
        self.balance_row = Adw.ActionRow(title="Balanço de Som (Esquerdo / Direito)")
        self.balance_row.set_subtitle("Distribuição estéreo entre os fones")

        balance_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        balance_box.set_valign(Gtk.Align.CENTER)

        lbl_l = Gtk.Label(label="E")
        lbl_l.add_css_class("dim-label")
        balance_box.append(lbl_l)

        self.balance_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -16.0, 16.0, 1.0)
        self.balance_scale.set_size_request(180, -1)
        self.balance_scale.set_value(0.0)
        self.balance_scale.set_round_digits(0)
        self.balance_scale.add_mark(0.0, Gtk.PositionType.BOTTOM, None)
        self.balance_scale.connect("value-changed", self._on_balance_changed)
        balance_box.append(self.balance_scale)

        lbl_r = Gtk.Label(label="D")
        lbl_r.add_css_class("dim-label")
        balance_box.append(lbl_r)

        self.balance_val_lbl = Gtk.Label(label="Centro (Equilibrado)")
        self.balance_val_lbl.set_size_request(130, -1)
        self.balance_val_lbl.set_xalign(0.0)
        self.balance_val_lbl.add_css_class("caption")
        balance_box.append(self.balance_val_lbl)

        self.balance_row.add_suffix(balance_box)
        self.extra_group.add(self.balance_row)

        # 3. Desligamento Automático por Inatividade (Auto Power Off)
        self.auto_off_row = Adw.ComboRow(title="Desligamento Automático por Inatividade")
        self.auto_off_row.set_subtitle("Desliga os fones se nenhum áudio for reproduzido para economizar bateria")
        auto_off_opts = ["Nunca / Desativado", "15 minutos", "30 minutos", "1 hora (60 min)", "2 horas (120 min)"]
        self.auto_off_row.set_model(Gtk.StringList.new(auto_off_opts))
        self.auto_off_row.connect("notify::selected", self._on_auto_power_off_selected)
        self.extra_group.add(self.auto_off_row)

        # 4. Limitador de Volume Safe Sound (85 dB)
        self.safe_sound_row = Adw.SwitchRow(title="Proteção Auditiva Safe Sound (85 dB)")
        self.safe_sound_row.set_subtitle("Limita o volume a 85 dB para proteger a audição conforme recomendações da OMS")
        self.safe_sound_row.connect("notify::active", self._on_safe_sound_toggled)
        self.extra_group.add(self.safe_sound_row)

        # 5. VoiceAware (Retorno da própria voz em chamadas)
        self.voice_row = Adw.ComboRow(title="VoiceAware (Retorno de Voz)")
        self.voice_row.set_subtitle("Permite ouvir sua própria voz com clareza durante chamadas")
        voice_opts = ["Desligado", "Baixo", "Médio", "Alto"]
        self.voice_row.set_model(Gtk.StringList.new(voice_opts))
        self.voice_row.connect("notify::selected", self._on_voice_aware_selected)
        self.extra_group.add(self.voice_row)

        # 6. Localizar meus fones (Find My Buds)
        self.find_row = Adw.ActionRow(title="Buscar Meus Fones (Find My Buds)")
        self.find_row.set_subtitle("Emite um sinal sonoro de alerta no auricular selecionado")
        
        find_left_btn = Gtk.Button(label="Tocar Esquerdo")
        find_left_btn.connect("clicked", lambda _: self._ring_earbud(True, False))
        self.find_row.add_suffix(find_left_btn)

        find_right_btn = Gtk.Button(label="Tocar Direito")
        find_right_btn.connect("clicked", lambda _: self._ring_earbud(False, True))
        self.find_row.add_suffix(find_right_btn)

        find_both_btn = Gtk.Button(label="Tocar Ambos")
        find_both_btn.connect("clicked", lambda _: self._ring_earbud(True, True))
        self.find_row.add_suffix(find_both_btn)

        find_stop_btn = Gtk.Button(label="Parar alerta")
        find_stop_btn.connect("clicked", lambda _: self._ring_earbud(False, False))
        self.find_row.add_suffix(find_stop_btn)

        self.extra_group.add(self.find_row)

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
            self._device_ever_connected = True
            self._cancel_auto_shutdown()
            dev = connected[0]
            self.backend.connect(dev)
            
            # Encontrar modelo correspondente
            matched_model = self.registry.find_from_bluetooth(dev.name, dev.modalias)
            if matched_model:
                self._apply_model(matched_model)
                try:
                    idx = self.registry.all_models.index(matched_model)
                    self.model_combo.set_selected(idx)
                except ValueError:
                    pass

            self.title_widget.set_subtitle(f"Conectado: {dev.name}")
            self.device_banner.set_title(dev.name)
            self._device_mac = dev.mac
            self._device_pid = matched_model.pid.upper() if matched_model else "N/A"
            self._device_firmware = ""
            self._update_device_metadata()
            
            if dev.battery_percentage is not None:
                self.battery_badge.set_text(f"{dev.battery_percentage}%")
                self.tray_indicator.update_battery(overall=dev.battery_percentage)
            else:
                self.battery_badge.set_text("Conectado")

            self.tray_indicator.update_device(dev.name, True)

            if (
                not matched_model
                or not matched_model.uses_harman_ble_gen3_profile
                or self.backend.ble_controller.is_connected
            ):
                self._request_device_state()

        elif paired:
            dev = paired[0]
            matched_model = self.registry.find_from_bluetooth(dev.name, dev.modalias)
            if matched_model:
                self._apply_model(matched_model)
                try:
                    idx = self.registry.all_models.index(matched_model)
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
        else:
            self.title_widget.set_subtitle("Nenhum fone conectado")
            self.device_banner.set_title("Nenhum fone conectado")
            self.device_banner.set_subtitle("Conecte seu fone JBL pelo Bluetooth do sistema")
            self.device_banner.set_tooltip_text(None)
            self.battery_badge.set_text("--%")
            self.tray_indicator.update_device("Nenhum fone conectado", False)
            self.current_model = None
            default_model = self.registry.find_by_name("JBL Tune Buds 2")
            if default_model:
                self._apply_model(default_model)

    def _update_device_metadata(self):
        details = []
        if self._device_pid:
            details.append(f"PID: {self._device_pid}")
        if self._device_firmware:
            details.append(f"FW: {self._device_firmware}")
        self.device_banner.set_subtitle(" | ".join(details) or "Conectado")

        full_details = []
        if self._device_mac:
            full_details.append(f"MAC: {self._device_mac}")
        full_details.extend(details)
        self.device_banner.set_tooltip_text(" | ".join(full_details) or None)

    def _request_device_state(self):
        if self.current_model and self.current_model.protocol_version == 4:
            feature_ids = [
                Protocol4Handler.FEATURE_BATTERY_LEFT,
                Protocol4Handler.FEATURE_BATTERY_RIGHT,
                Protocol4Handler.FEATURE_CASE_BATTERY,
                Protocol4Handler.FEATURE_AUTO_POWER_OFF,
                Protocol4Handler.FEATURE_LR_BALANCE,
                Protocol4Handler.FEATURE_ANC,
                Protocol4Handler.FEATURE_AMBIENT_AWARE,
                Protocol4Handler.FEATURE_TALKTHRU,
                Protocol4Handler.FEATURE_SIDETONE,
                Protocol4Handler.FEATURE_AUDIO_LIMITER,
                Protocol4Handler.FEATURE_SMART_SWITCH,
                Protocol4Handler.FEATURE_EQ_INFO,
            ]
            for packet in Protocol4Handler.build_get_features(feature_ids):
                self.backend.send_raw(packet)
            return

        if self.current_model and self.current_model.uses_harman_ble_gen3_profile:
            packets = (
                Protocol3Handler.REQ_BATTERY_INFO,
                Protocol3Handler.REQ_ANC_MODES,
                Protocol3Handler.REQ_SMART_SWITCH_GEN3,
                Protocol3Handler.REQ_LR_BALANCE,
                Protocol3Handler.build_command3_get([
                    Protocol3Handler.DEVICE_INFO_AUTO_OFF,
                    Protocol3Handler.DEVICE_INFO_VOICE_AWARE,
                    Protocol3Handler.DEVICE_INFO_SAFE_SOUND,
                ]),
                Protocol3Handler.request_eq_settings2(202),
                Protocol3Handler.request_eq_settings2(201),
                Protocol3Handler.request_eq_settings2(255),
            )
        else:
            packets = (
                Protocol3Handler.REQ_DEV_INFO,
                Protocol3Handler.REQ_BATTERY_INFO,
                Protocol3Handler.REQ_ANC_MODES,
                Protocol3Handler.REQ_SMART_SWITCH,
                Protocol3Handler.REQ_LR_BALANCE,
                Protocol3Handler.REQ_AUTO_OFF,
                Protocol3Handler.REQ_SAFE_SOUND,
            )
        for packet in packets:
            self.backend.send_raw(packet)

    def _send_packets(self, packets: List[bytes]) -> bool:
        results = [self.backend.send_control(packet) for packet in packets]
        if results and not all(results):
            if (
                any(packet.startswith(b"\xF0\xDC") for packet in packets)
                or (
                    getattr(self.backend.ble_controller, "has_control_candidate", False)
                    and not self.backend.ble_controller.is_connected
                )
            ):
                message = "Comando não enviado: o controle GATT BLE do fone ainda não conectou."
            else:
                message = "Comando não enviado: nenhum canal Bluetooth está disponível."
            toast = Adw.Toast.new(message)
            toast.set_timeout(4)
            self.toast_overlay.add_toast(toast)
            return False
        return bool(results)

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
        
        # Visibilidade individual dos recursos avançados
        self.voice_row.set_visible(model.has_voice_aware)
        self.smart_mode_row.set_visible(model.has_smart_audio and model.protocol_version == 3)
        self.balance_row.set_visible(model.has_lr_balance)
        self.auto_off_row.set_visible(model.has_auto_power_off)
        self.safe_sound_row.set_visible(model.has_safe_sound)
        self.find_row.set_visible(model.has_find_my_buds and model.protocol_version == 3)

        has_any_extra = (
            model.has_voice_aware or 
            model.has_smart_audio or 
            model.has_lr_balance or 
            model.has_auto_power_off or 
            model.has_safe_sound or 
            model.has_find_my_buds
        )
        self.extra_group.set_visible(has_any_extra)

    def _on_model_combo_changed(self, combo, _):
        idx = combo.get_selected()
        if 0 <= idx < len(self.registry.all_models):
            selected_model = self.registry.all_models[idx]
            self._apply_model(selected_model)

    def _on_anc_button_toggled(self, mode: AncMode, button: Gtk.ToggleButton):
        if self._updating_anc_ui or not button.get_active():
            return

        self.active_anc_mode = mode
        
        packets = (
            Protocol4Handler.set_anc_mode(mode)
            if self.current_model and self.current_model.protocol_version == 4
            else Protocol3Handler.set_anc_mode(mode)
        )
        if not self._send_packets(packets):
            return

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
        packets = (
            Protocol4Handler.set_anc_mode(mode)
            if self.current_model and self.current_model.protocol_version == 4
            else Protocol3Handler.set_anc_mode(mode)
        )
        self._send_packets(packets)
        self.tray_indicator.update_anc_mode(mode)

    @staticmethod
    def _format_db(val: float) -> str:
        if abs(val) < 0.05:
            return "0 dB"
        return f"{val:+.1f} dB"

    def _on_preset_selected(self, combo, _):
        if self._updating_preset_ui:
            return
        idx = combo.get_selected()
        self.active_preset_idx = idx
        self.tray_indicator.update_eq_preset(idx)

        if idx in EQ_PRESET_GAINS:
            gains = EQ_PRESET_GAINS[idx]
            self._updating_preset_ui = True
            try:
                for slider, gain in zip(self.eq_sliders, gains):
                    slider.set_value(gain)
            finally:
                self._updating_preset_ui = False
            if self.current_model and self.current_model.protocol_version == 4:
                packets = Protocol4Handler.build_eq_curve_packet(gains)
            elif self.current_model and self.current_model.uses_harman_ble_gen3_profile:
                packets = [Protocol3Handler.build_eq2_packet(gains, preset_id=idx)]
            else:
                packets = [Protocol3Handler.set_eq_preset(idx)]
            if not self._send_packets(packets):
                return
            p_name = EQ_PRESET_NAMES[idx] if idx < len(EQ_PRESET_NAMES) else ""
            toast = Adw.Toast.new(f"🎵 Predefinição JBL aplicada: {p_name}")
            toast.set_timeout(2)
            self.toast_overlay.add_toast(toast)
        elif idx == 7:
            # Personalizado
            self._apply_custom_eq(show_toast=True)

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

    def _on_slider_value_changed(self, slider: Gtk.Scale, label: Gtk.Label):
        label.set_text(self._format_db(slider.get_value()))
        if self._updating_preset_ui:
            return
        # Marca predefinição como 'Personalizado' (índice 7)
        if hasattr(self, 'preset_row') and self.preset_row.get_selected() != 7:
            self._updating_preset_ui = True
            try:
                self.preset_row.set_selected(7)
            finally:
                self._updating_preset_ui = False
        # Aplicação contínua debounced (200ms) nos fones em tempo real
        if self._eq_debounce_timer is not None:
            GLib.source_remove(self._eq_debounce_timer)
        self._eq_debounce_timer = GLib.timeout_add(200, self._debounced_apply_eq)

    def _debounced_apply_eq(self):
        self._eq_debounce_timer = None
        self._apply_custom_eq(show_toast=False)
        return False

    def _apply_custom_eq(self, show_toast: bool = True):
        gains = [s.get_value() for s in self.eq_sliders]
        packets = (
            Protocol4Handler.build_eq_curve_packet(gains)
            if self.current_model and self.current_model.protocol_version == 4
            else [Protocol3Handler.build_eq2_packet(gains, preset_id=7)]
        )
        if not self._send_packets(packets):
            return
        if show_toast:
            toast = Adw.Toast.new("✅ Curva de equalização oficial (10 bandas) aplicada nos fones!")
            toast.set_timeout(2)
            self.toast_overlay.add_toast(toast)

    def _on_smart_audio_video_selected(self, combo, _):
        if self._updating_extra_ui:
            return
        if self.current_model and self.current_model.protocol_version == 4:
            return
        if self._smart_mode_transition_deadline > time.monotonic():
            return
        idx = combo.get_selected()
        mode_map = {0: "normal", 1: "audio", 2: "video"}
        mode = mode_map.get(idx, "normal")
        self._send_smart_audio_video_mode(mode)

    def _smart_audio_video_packet(self, mode: str) -> bytes:
        if self.current_model and self.current_model.uses_harman_ble_gen3_profile:
            return Protocol3Handler.set_smart_audio_video_gen3(mode)
        return Protocol3Handler.set_smart_audio_video(mode)

    def _apply_smart_mode_from_external(self, mode: str):
        """Chamado a partir do menu suspenso da barra superior para alternar o modo Smart Audio & Video."""
        GLib.idle_add(self._do_apply_smart_mode_from_external, mode)

    def _do_apply_smart_mode_from_external(self, mode: str):
        if self._smart_mode_transition_deadline > time.monotonic():
            return
        mode_map = {"normal": 0, "audio": 1, "video": 2}
        if mode in mode_map and hasattr(self, 'smart_mode_row'):
            self._updating_extra_ui = True
            try:
                self.smart_mode_row.set_selected(mode_map[mode])
            finally:
                self._updating_extra_ui = False
        self._send_smart_audio_video_mode(mode)

    def _send_smart_audio_video_mode(self, mode: str):
        if not self._send_packets([self._smart_audio_video_packet(mode)]):
            return

        self._smart_mode_transition_deadline = time.monotonic() + 30
        self._smart_mode_disconnect_seen = False
        self._smart_mode_last_reconnect_attempt = time.monotonic()
        self.smart_mode_row.set_sensitive(False)
        self.smart_mode_row.set_subtitle(
            "A conexão de áudio pode reiniciar; aguardando o fone reconectar."
        )
        if self._smart_mode_transition_timer is not None:
            GLib.source_remove(self._smart_mode_transition_timer)
        self._smart_mode_transition_timer = GLib.timeout_add_seconds(
            30, self._on_smart_mode_transition_timeout
        )
        self.tray_indicator.update_smart_mode(mode)

    def _handle_smart_mode_connection(self, connected: bool):
        now = time.monotonic()
        if self._smart_mode_transition_deadline <= now:
            return

        if connected:
            if self._smart_mode_disconnect_seen:
                self._finish_smart_mode_transition(reconnected=True)
            return

        self._smart_mode_disconnect_seen = True
        if now - self._smart_mode_last_reconnect_attempt < 5:
            return

        device = self.backend.connected_device
        if device and self.backend.connect_bluez(device.mac):
            self._smart_mode_last_reconnect_attempt = now

    def _finish_smart_mode_transition(self, reconnected: bool = False):
        timer_id = self._smart_mode_transition_timer
        self._smart_mode_transition_timer = None
        if reconnected and timer_id is not None:
            GLib.source_remove(timer_id)
        self._smart_mode_transition_deadline = 0.0
        self.smart_mode_row.set_sensitive(True)
        self.smart_mode_row.set_subtitle(
            "Áudio prioriza fidelidade; vídeo e jogos reduzem a latência."
        )
        if reconnected:
            toast = Adw.Toast.new(
                "Conexão Bluetooth restaurada; retome a reprodução se necessário."
            )
        elif self._smart_mode_disconnect_seen:
            toast = Adw.Toast.new(
                "O áudio não reconectou automaticamente. Reconecte o fone pelo Bluetooth do sistema."
            )
        else:
            return False
        toast.set_timeout(4)
        self.toast_overlay.add_toast(toast)
        return False

    def _on_smart_mode_transition_timeout(self):
        self._smart_mode_transition_timer = None
        return self._finish_smart_mode_transition()

    def _on_balance_changed(self, scale: Gtk.Scale):
        val = int(round(scale.get_value()))
        if val == 0:
            self.balance_val_lbl.set_text("Centro (Equilibrado)")
        elif val < 0:
            self.balance_val_lbl.set_text(f"Esquerdo ({abs(val)})")
        else:
            self.balance_val_lbl.set_text(f"Direito ({val})")

        if self._updating_extra_ui:
            return

        if self._balance_debounce_timer is not None:
            GLib.source_remove(self._balance_debounce_timer)
        self._balance_debounce_timer = GLib.timeout_add(150, self._debounced_apply_balance, val)

    def _debounced_apply_balance(self, val: int):
        self._balance_debounce_timer = None
        packets = (
            Protocol4Handler.set_lr_balance(val)
            if self.current_model and self.current_model.protocol_version == 4
            else [Protocol3Handler.set_lr_balance(val)]
        )
        self._send_packets(packets)
        return False

    def _on_auto_power_off_selected(self, combo, _):
        if self._updating_extra_ui:
            return
        idx = combo.get_selected()
        time_map = {0: 0, 1: 15, 2: 30, 3: 60, 4: 120}
        minutes = time_map.get(idx, 0)
        enabled = minutes > 0

        if self.current_model and self.current_model.protocol_version == 4:
            packets = Protocol4Handler.set_auto_power_off(minutes, enabled)
        elif self.current_model and self.current_model.uses_harman_ble_gen3_profile:
            packets = [Protocol3Handler.set_auto_power_off_gen3(minutes, enabled)]
        else:
            packets = [Protocol3Handler.set_auto_power_off(minutes, enabled)]
        if not self._send_packets(packets):
            return

        if enabled:
            toast = Adw.Toast.new(f"⏱️ Desligamento automático: {minutes} min de inatividade")
        else:
            toast = Adw.Toast.new("⏱️ Desligamento automático desativado (Nunca)")
        toast.set_timeout(2)
        self.toast_overlay.add_toast(toast)

    def _on_safe_sound_toggled(self, switch, _):
        if self._updating_extra_ui:
            return
        active = switch.get_active()
        packets = (
            Protocol4Handler.set_safe_sound(active)
            if self.current_model and self.current_model.protocol_version == 4
            else [Protocol3Handler.set_safe_sound(active)]
        )
        if not self._send_packets(packets):
            return

        if active:
            toast = Adw.Toast.new("🛡️ Proteção auditiva Safe Sound ativada (85 dB)")
        else:
            toast = Adw.Toast.new("🛡️ Proteção auditiva Safe Sound desativada")
        toast.set_timeout(2)
        self.toast_overlay.add_toast(toast)

    def _on_voice_aware_selected(self, combo, _):
        if self._updating_extra_ui:
            return
        level = VoiceAwareLevel(combo.get_selected())
        if self.current_model and self.current_model.protocol_version == 4:
            packets = Protocol4Handler.set_voice_aware(level)
        elif self.current_model and self.current_model.uses_harman_ble_gen3_profile:
            packets = [Protocol3Handler.set_voice_aware_gen3(level)]
        else:
            packets = [Protocol3Handler.set_voice_aware(level)]
        self._send_packets(packets)

    def _ring_earbud(self, ring_left: bool, ring_right: bool):
        packets = Protocol3Handler.set_find_my_buds(ring_left, ring_right)
        self._send_packets(packets)

    def _on_backend_status_changed(self, status: Dict[str, Any]):
        """Executado na thread principal para atualizar a UI de forma segura."""
        GLib.idle_add(self._update_ui_from_status, status)

    def _update_ui_from_status(self, status: Dict[str, Any]):
        # Atualização de status BLE / Conexão BlueZ
        if status.get("ble_connected"):
            if self.backend.connected_device:
                if not self._ble_connected:
                    self._request_device_state()
                self._ble_connected = True
                self.title_widget.set_subtitle(f"Conectado: {self.backend.connected_device.name} (GATT BLE Ativo)")
                self.tray_indicator.update_device(self.backend.connected_device.name, True)
                self._device_ever_connected = True
                self._cancel_auto_shutdown()
        elif "ble_connected" in status:
            self._ble_connected = False

        if "bluez_connected" in status:
            is_conn = status["bluez_connected"]
            self._handle_smart_mode_connection(is_conn)
            dev_name = status.get("device_name", "Fone JBL")
            if not is_conn:
                self.title_widget.set_subtitle(f"Pareado: {dev_name} (Desconectado)")
                self.battery_badge.set_text("Desconectado")
                self.tray_indicator.update_device(dev_name, False)
                if self.auto_close_on_disconnect and self._device_ever_connected:
                    self._schedule_auto_shutdown()
            else:
                self._device_ever_connected = True
                self._cancel_auto_shutdown()
                self.title_widget.set_subtitle(f"Conectado: {dev_name}")
                self.tray_indicator.update_device(dev_name, True)

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

            if "eq_gains" in parsed and len(parsed["eq_gains"]) == len(self.eq_sliders):
                self._updating_preset_ui = True
                try:
                    for slider, gain in zip(self.eq_sliders, parsed["eq_gains"]):
                        slider.set_value(gain)
                    self.preset_row.set_selected(
                        identify_eq_preset(parsed.get("eq_category"), parsed["eq_gains"])
                    )
                finally:
                    self._updating_preset_ui = False

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
                self._device_firmware = str(parsed["firmware_version"])
                self._update_device_metadata()

            if "battery_left" in parsed or "battery_right" in parsed or "battery_case" in parsed:
                l = parsed.get("battery_left")
                r = parsed.get("battery_right")
                c = parsed.get("battery_case")
                charging_l = parsed.get("charging_left", False)
                charging_r = parsed.get("charging_right", False)
                charging_c = parsed.get("charging_case", False)

                if l is not None and l <= 100:
                    txt_l = f"{l}%" + (" ⚡" if charging_l else "")
                    self.badge_battery_left.set_text(txt_l)
                    self.badge_battery_left.set_tooltip_text(
                        f"{l}% — {'Carregando' if charging_l else 'Em uso'}"
                    )
                    self.progress_battery_left.set_fraction(max(0.0, min(1.0, l / 100.0)))
                    self.row_battery_left.set_subtitle("⚡ No estojo (Carregando)" if charging_l else "Em uso")

                if r is not None and r <= 100:
                    txt_r = f"{r}%" + (" ⚡" if charging_r else "")
                    self.badge_battery_right.set_text(txt_r)
                    self.badge_battery_right.set_tooltip_text(
                        f"{r}% — {'Carregando' if charging_r else 'Em uso'}"
                    )
                    self.progress_battery_right.set_fraction(max(0.0, min(1.0, r / 100.0)))
                    self.row_battery_right.set_subtitle("⚡ No estojo (Carregando)" if charging_r else "Em uso")

                if c is not None and c <= 100:
                    txt_c = f"{c}%" + (" ⚡" if charging_c else "")
                    self.badge_battery_case.set_text(txt_c)
                    self.badge_battery_case.set_tooltip_text(
                        f"{c}% — {'Carregando' if charging_c else 'Carga restante'}"
                    )
                    self.progress_battery_case.set_fraction(max(0.0, min(1.0, c / 100.0)))
                    if charging_c:
                        self.row_battery_case.set_subtitle("⚡ Conectado à alimentação (Carregando)")
                    elif c == 100:
                        self.row_battery_case.set_subtitle("⚡ Estojo 100% carregado")
                    elif not charging_l and not charging_r:
                        self.row_battery_case.set_subtitle(
                            f"Última leitura ({c}%) · recoloque um fone no estojo para atualizar"
                        )
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

            # Sincronização de Desligamento Automático
            if "auto_off_minutes" in parsed or "auto_off_minutes" in status:
                mins = status.get("auto_off_minutes", parsed.get("auto_off_minutes"))
                enabled = status.get("auto_off_enabled", parsed.get("auto_off_enabled", mins > 0))
                idx_map = {0: 0, 15: 1, 30: 2, 60: 3, 120: 4}
                sel_idx = idx_map.get(mins if enabled else 0, 0)
                self._updating_extra_ui = True
                try:
                    self.auto_off_row.set_selected(sel_idx)
                finally:
                    self._updating_extra_ui = False

            # Sincronização de Balanço L/R
            if "lr_balance_offset" in parsed or "lr_balance_offset" in status:
                offset = status.get("lr_balance_offset", parsed.get("lr_balance_offset"))
                if offset is not None:
                    self._updating_extra_ui = True
                    try:
                        self.balance_scale.set_value(float(offset))
                        if offset == 0:
                            self.balance_val_lbl.set_text("Centro (Equilibrado)")
                        elif offset < 0:
                            self.balance_val_lbl.set_text(f"Esquerdo ({abs(offset)})")
                        else:
                            self.balance_val_lbl.set_text(f"Direito ({offset})")
                    finally:
                        self._updating_extra_ui = False

            # Sincronização de Smart Audio & Video
            if "smart_audio_video_mode" in parsed or "smart_audio_video_mode" in status:
                smode = status.get("smart_audio_video_mode", parsed.get("smart_audio_video_mode"))
                smode_map = {"normal": 0, "audio": 1, "video": 2}
                if smode in smode_map:
                    self._updating_extra_ui = True
                    try:
                        self.smart_mode_row.set_selected(smode_map[smode])
                    finally:
                        self._updating_extra_ui = False

            # Sincronização do VoiceAware/Sidetone
            if "voice_aware_level" in parsed or "voice_aware_level" in status:
                level = status.get("voice_aware_level", parsed.get("voice_aware_level"))
                enabled = status.get(
                    "voice_aware_enabled",
                    parsed.get("voice_aware_enabled", bool(level and level > 0)),
                )
                if level is not None:
                    self._updating_extra_ui = True
                    try:
                        self.voice_row.set_selected(
                            max(0, min(3, int(level))) if enabled else 0
                        )
                    finally:
                        self._updating_extra_ui = False

            # Sincronização de Proteção Auditiva Safe Sound
            if "safe_sound_enabled" in parsed or "safe_sound_enabled" in status:
                ss = status.get("safe_sound_enabled", parsed.get("safe_sound_enabled"))
                if ss is not None:
                    self._updating_extra_ui = True
                    try:
                        self.safe_sound_row.set_active(bool(ss))
                    finally:
                        self._updating_extra_ui = False
