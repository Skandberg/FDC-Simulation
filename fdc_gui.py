# Modified fdc_gui.py
import kivy
kivy.require('2.3.1')

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.checkbox import CheckBox
import datetime
import json
import os

class FDCController:
    def __init__(self, model_type, mode, zones):
        self.model_type = model_type
        self.mode = mode
        self.zones = zones
        self.damper_positions = {i: 'closed' for i in range(1, zones+1)}
        self.alarm_active = {i: False for i in range(1, zones+1)}
        self.smoke_alarms = {i: False for i in range(1, zones+1)}
        self.thermal_alarms = {i: False for i in range(1, zones+1)}
        self.external_alarms = {i: False for i in range(1, zones+1)}
        self.temp_sensor = {i: 20 for i in range(1, zones+1)}
        self.zone_names = {i: f"Zone {i}" for i in range(1, zones+1)}
        self.led_status = 'OFF'
        self.relay_state = 'OPEN'
        self.logs = {i: [] for i in range(1, zones+1)}
        self.test_mode = False
        self.auto_test_enabled = False
        self.auto_test_interval_hours = 24
        self.auto_test_hour = 0
        self.auto_test_minute = 0
        self.next_auto_test = None
        self.test_reports = []

    def get_status(self):
        return {
            'damper_positions': self.damper_positions,
            'smoke_alarms': self.smoke_alarms,
            'thermal_alarms': self.thermal_alarms,
            'external_alarms': self.external_alarms,
            'temp_sensor': self.temp_sensor,
            'led_status': self.led_status,
            'relay_state': self.relay_state,
        }

    def get_logs(self, zone):
        return self.logs.get(zone, [])

    def get_test_reports(self):
        return self.test_reports

    def trigger_alarm(self, type, zone):
        if type == 'smoke':
            self.smoke_alarms[zone] = True
            msg = "Smoke alarm triggered"
        elif type == 'thermal':
            self.thermal_alarms[zone] = True
            msg = "Thermal alarm triggered"
        elif type == 'external':
            self.external_alarms[zone] = True
            msg = "External alarm triggered"
        self.alarm_active[zone] = True
        ts = datetime.datetime.now()
        self.logs[zone].append((ts, msg))
        self._update_leds()
        self._update_relay()

    def _set_working_position(self):
        pass

    def _update_leds(self):
        any_alarm = any(self.alarm_active.values())
        if self.test_mode or any_alarm:
            self.led_status = 'FLASH'
        else:
            self.led_status = 'OFF'

    def _update_relay(self):
        any_alarm = any(self.alarm_active.values())
        if any_alarm:
            self.relay_state = 'CLOSED'
        else:
            self.relay_state = 'OPEN'

    def _update_analog_out(self):
        pass

    def perform_full_test(self):
        ts = datetime.datetime.now()
        report = {'timestamp': ts, 'zones': {}, 'status': 'PASSED'}
        if any(self.alarm_active.values()):
            for i in range(1, self.zones + 1):
                self.logs[i].append((ts, "Test failed: Active alarms detected"))
                report['zones'][i] = ["Failed: Active alarms detected"]
                report['status'] = 'FAILED'
            self.test_reports.append(report)
            for i in range(1, self.zones + 1):
                self.logs[i].append((ts, f"Test Report - Status: {report['status']}, Zone {i}: {report['zones'][i][0]}"))
            return
        self.test_mode = True
        self._update_leds()
        for i in range(1, self.zones + 1):
            self.damper_positions[i] = 'closed'
            self.logs[i].append((ts, "Full test started: Damper closed"))
            report['zones'][i] = ["Damper closed"]
        for i in range(1, self.zones + 1):
            self.damper_positions[i] = 'open'
            self.logs[i].append((ts, "Full test: Damper opened"))
            report['zones'][i].append("Damper opened")
        for i in range(1, self.zones + 1):
            self.damper_positions[i] = 'closed'
            self.logs[i].append((ts, "Full test: Damper closed again"))
            report['zones'][i].append("Damper closed again")
        for i in range(1, self.zones + 1):
            self.logs[i].append((ts, "Full test passed"))
            report['zones'][i].append("Test passed")
        self.test_mode = False
        self._set_working_position()
        self._update_leds()
        self.test_reports.append(report)
        for i in range(1, self.zones + 1):
            self.logs[i].append((ts, f"Test Report - Status: {report['status']}, Zone {i}: {', '.join(report['zones'][i])}"))
        if len(self.test_reports) > 50:
            self.test_reports.pop(0)

    def _schedule_next_auto_test(self):
        now = datetime.datetime.now()
        next_time = now.replace(hour=self.auto_test_hour, minute=self.auto_test_minute, second=0, microsecond=0)
        interval = datetime.timedelta(hours=self.auto_test_interval_hours)
        while next_time <= now:
            next_time += interval
        self.next_auto_test = next_time
        ts = datetime.datetime.now()
        for i in range(1, self.zones + 1):
            self.logs[i].append((ts, f"Next auto test scheduled at {next_time.strftime('%Y-%m-%d %H:%M:%S')}"))

    def set_auto_test_params(self, enabled, interval, hour, minute):
        self.auto_test_enabled = enabled
        self.auto_test_interval_hours = max(1, interval)
        self.auto_test_hour = hour % 24
        self.auto_test_minute = minute % 60
        ts = datetime.datetime.now()
        status = "enabled" if enabled else "disabled"
        for i in range(1, self.zones + 1):
            self.logs[i].append((ts, f"Auto test {status}: Interval {interval}h, Time {hour:02d}:{minute:02d}"))
        if enabled:
            self._schedule_next_auto_test()

    def save_state(self, file_path):
        state = {
            'model_type': self.model_type,
            'mode': self.mode,
            'zone_names': {str(k): v for k, v in self.zone_names.items()},
            'damper_positions': {str(k): v for k, v in self.damper_positions.items()},
            'alarm_active': {str(k): v for k, v in self.alarm_active.items()},
            'smoke_alarms': {str(k): v for k, v in self.smoke_alarms.items()},
            'thermal_alarms': {str(k): v for k, v in self.thermal_alarms.items()},
            'external_alarms': {str(k): v for k, v in self.external_alarms.items()},
            'temp_sensor': {str(k): v for k, v in self.temp_sensor.items()},
            'logs': {str(k): [(ts.isoformat(), msg) for ts, msg in v] for k, v in self.logs.items()},
            'test_mode': self.test_mode,
            'auto_test_enabled': self.auto_test_enabled,
            'auto_test_interval_hours': self.auto_test_interval_hours,
            'auto_test_hour': self.auto_test_hour,
            'auto_test_minute': self.auto_test_minute,
            'next_auto_test': self.next_auto_test.isoformat() if self.next_auto_test else None,
            'test_reports': [{'timestamp': r['timestamp'].isoformat(), 'zones': r['zones'], 'status': r['status']} for r in self.test_reports]
        }
        with open(file_path, 'w') as f:
            json.dump(state, f)

    def load_state(self, file_path):
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                state = json.load(f)
            self.model_type = state.get('model_type', self.model_type)
            self.mode = state.get('mode', self.mode)
            self.zone_names = {int(k): v for k, v in state.get('zone_names', {}).items()}
            self.damper_positions = {int(k): v for k, v in state.get('damper_positions', {}).items()}
            self.alarm_active = {int(k): v for k, v in state.get('alarm_active', {}).items()}
            self.smoke_alarms = {int(k): v for k, v in state.get('smoke_alarms', {}).items()}
            self.thermal_alarms = {int(k): v for k, v in state.get('thermal_alarms', {}).items()}
            self.external_alarms = {int(k): v for k, v in state.get('external_alarms', {}).items()}
            self.temp_sensor = {int(k): v for k, v in state.get('temp_sensor', {}).items()}
            self.logs = {int(k): [(datetime.datetime.fromisoformat(ts), msg) for ts, msg in v] for k, v in state.get('logs', {}).items()}
            self.zones = max(self.zone_names.keys() or [0])
            self.test_mode = state.get('test_mode', False)
            self.auto_test_enabled = state.get('auto_test_enabled', False)
            self.auto_test_interval_hours = state.get('auto_test_interval_hours', 24)
            self.auto_test_hour = state.get('auto_test_hour', 0)
            self.auto_test_minute = state.get('auto_test_minute', 0)
            self.next_auto_test = datetime.datetime.fromisoformat(state['next_auto_test']) if state.get('next_auto_test') else None
            self.test_reports = [{'timestamp': datetime.datetime.fromisoformat(r['timestamp']), 'zones': r['zones'], 'status': r['status']} for r in state.get('test_reports', [])]

Window.clearcolor = (0.12, 0.12, 0.12, 1)

class ZoneCard(Button):
    def __init__(self, zone_number, select_callback, name=None, **kwargs):
        super().__init__(**kwargs)
        self.zone_number = zone_number
        self.select_callback = select_callback
        self.name = name if name else f"Zone {zone_number}"
        self.text = self.name
        self.size_hint_y = None
        self.height = 50
        self.background_normal = ''
        self.color = (1,1,1,1)
        self.font_size = 18
        self.on_press = lambda: self.select_callback(self.zone_number)
        self.base_color = (0.2,0.2,0.2,1)
        self.selected_color = (0.2,0.6,0.9,1)
        self.alarm_color = (1,0.2,0.2,1)
        self.is_selected = False
        self.has_alarm = False
        self.blink_state = False
        self.background_color = self.base_color
        self.on_touch_down_original = self.on_touch_down
        self.on_touch_down = self._touch_down_override

    def _touch_down_override(self, touch):
        if hasattr(touch, 'button') and touch.button == 'right':
            return True
        return self.on_touch_down_original(touch)

    def set_selected(self, selected):
        self.is_selected = selected
        self.update_color()

    def set_status(self, has_alarm):
        self.has_alarm = has_alarm
        self.update_color()

    def blink(self, dt):
        if self.has_alarm and not self.is_selected:
            self.blink_state = not self.blink_state
            self.background_color = self.alarm_color if self.blink_state else self.base_color
        else:
            self.update_color()

    def update_color(self):
        if self.is_selected:
            self.background_color = self.selected_color
        elif self.has_alarm:
            self.background_color = self.alarm_color
        else:
            self.background_color = self.base_color

    def set_name(self, name):
        self.name = name
        self.text = name

class ZoneInfo(BoxLayout):
    def __init__(self, controller, **kwargs):
        super().__init__(orientation='vertical', padding=20, spacing=20, **kwargs)
        self.controller = controller
        self.info_labels = {}
        self.add_widget(Widget(size_hint_y=0.2))
        self.info_container = BoxLayout(orientation='vertical', spacing=20, size_hint=(1, None))
        self.info_container.bind(minimum_height=self.info_container.setter('height'))
        self.add_widget(self.info_container)
        self.add_widget(Widget(size_hint_y=0.2))
        for key in ['Damper', 'Smoke', 'Thermal', 'External', 'Temperature', 'LED', 'Relay']:
            lbl = Label(text="", font_size=36, color=(1,1,1,1), size_hint_y=None, height=60)
            self.info_labels[key] = lbl
            self.info_container.add_widget(lbl)

    def update_info(self, zone):
        status = self.controller.get_status()
        z = zone
        damper_state = status['damper_positions'].get(z, 'closed')
        self.info_labels['Damper'].text = f"Damper: {damper_state.upper()}"
        self.info_labels['Damper'].color = (0,1,0,1) if damper_state=='open' else (1,0,0,1)
        smoke = status['smoke_alarms'].get(z, False)
        self.info_labels['Smoke'].text = f"Smoke Alarm: {'ON' if smoke else 'OFF'}"
        self.info_labels['Smoke'].color = (1,0,0,1) if smoke else (0,1,0,1)
        thermal = status['thermal_alarms'].get(z, False)
        self.info_labels['Thermal'].text = f"Thermal Alarm: {'ON' if thermal else 'OFF'}"
        self.info_labels['Thermal'].color = (1,0,0,1) if thermal else (0,1,0,1)
        external = status['external_alarms'].get(z, False)
        self.info_labels['External'].text = f"External Alarm: {'ON' if external else 'OFF'}"
        self.info_labels['External'].color = (1,0,0,1) if external else (0,1,0,1)
        temp = status['temp_sensor'].get(z, 20)
        self.info_labels['Temperature'].text = f"Temperature: {temp}°C"
        if temp <= 50:
            self.info_labels['Temperature'].color = (0,1,0,1)
        elif temp <= 72:
            self.info_labels['Temperature'].color = (1,1,0,1)
        else:
            self.info_labels['Temperature'].color = (1,0,0,1)
        led_status = status['led_status']
        self.info_labels['LED'].text = f"LED: {led_status}"
        if led_status=='ON':
            self.info_labels['LED'].color = (0,1,0,1)
        elif led_status=='FLASH':
            self.info_labels['LED'].color = (1,1,0,1)
        else:
            self.info_labels['LED'].color = (0.5,0.5,0.5,1)
        relay = status['relay_state']
        self.info_labels['Relay'].text = f"Relay: {relay}"
        self.info_labels['Relay'].color = (0,1,0,1) if relay=='CLOSED' else (1,0,0,1)

class LogItem(Button):
    def __init__(self, text, select_callback, **kwargs):
        super().__init__(**kwargs)
        self.text = text
        self.size_hint_y = None
        self.height = 30
        self.background_normal = ''
        self.background_color = (0.2,0.2,0.2,1)
        self.color = (1,1,1,1)
        self.select_callback = select_callback
        self.halign = 'left'

    def on_press(self):
        try:
            self.select_callback(self)
        except Exception:
            pass

    def set_selected(self, value: bool):
        try:
            if value:
                self.background_color = (0.2,0.6,0.9,1)
            else:
                self.background_color = (0.2,0.2,0.2,1)
        except Exception:
            pass

class LogPanel(BoxLayout):
    def __init__(self, controller, get_current_zone, **kwargs):
        super().__init__(orientation='vertical', **kwargs)
        self.controller = controller
        self.get_current_zone = get_current_zone
        self.scroll = ScrollView()
        self.log_box = BoxLayout(orientation='vertical', size_hint_y=None, spacing=5, padding=(4,4,4,10))
        self.log_box.bind(minimum_height=self.log_box.setter('height'))
        self.scroll.add_widget(self.log_box)
        self.add_widget(self.scroll)
        save_btn = Button(text='Save Logs', size_hint_y=None, height=50, background_color=(0.3,0.7,1,1), on_press=self.save_logs)
        self.add_widget(save_btn)
        self.displayed_texts = []
        self.displayed_raw = []
        self.selected_item = None
        self.current_zone_tracked = None
        Clock.schedule_interval(lambda dt: self.update_logs(), 1)
        self.scroll.bind(on_touch_down=self._on_scroll_touch_down)

    def save_logs(self, instance):
        zone = self.get_current_zone()
        if zone is None:
            popup = Popup(title='No Zone', content=Label(text="No zone selected."), size_hint=(0.4,0.2))
            popup.open()
            return
        logs = self.controller.get_logs(zone)
        if not logs:
            popup = Popup(title='No Logs', content=Label(text="No logs to save."), size_hint=(0.4,0.2))
            popup.open()
            return
        file_name = f"logs_zone_{zone}.txt"
        with open(file_name, 'w') as f:
            for ts, msg in logs:
                f.write(f"{ts.strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")
        popup = Popup(title='Saved', content=Label(text=f"Logs saved to {file_name}"), size_hint=(0.4,0.2))
        popup.open()

    def _format_entry_to_text(self, entry):
        if entry is None:
            return "None"
        date_str = datetime.date.today().strftime('%Y-%m-%d')
        if isinstance(entry, (list, tuple)):
            if len(entry) >= 2:
                ts = entry[0]
                msg = entry[1]
                if isinstance(ts, datetime.datetime):
                    ts_str = ts.strftime('%Y-%m-%d %H:%M:%S')
                elif isinstance(ts, datetime.time):
                    time_str = ts.strftime('%H:%M:%S')
                    ts_str = f"{date_str} {time_str}"
                else:
                    ts_str = str(ts)
                    if len(ts_str) in (5, 8) and ts_str.count(':') in (1, 2):
                        ts_str = f"{date_str} {ts_str}"
                return f"{ts_str} - {msg}"
            elif len(entry) >= 1:
                msg = str(entry[0])
            else:
                msg = ""
        else:
            msg = str(entry)
        ts_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return f"{ts_str} - {msg}"

    def update_logs(self):
        zone = self.get_current_zone()
        if zone is None:
            if self.current_zone_tracked is not None:
                self.current_zone_tracked = None
                self.displayed_texts = []
                self.displayed_raw = []
                self.log_box.clear_widgets()
            return
        if hasattr(self.controller, 'get_logs'):
            try:
                logs = self.controller.get_logs(zone) or []
            except Exception as e:
                logs = [f"Error getting logs: {e}"]
        else:
            logs = [f"No logs available for zone {zone}"]
        recent_entries = logs[-50:]
        if zone != self.current_zone_tracked:
            self.current_zone_tracked = zone
            self.displayed_texts = []
            self.displayed_raw = []
            self.log_box.clear_widgets()
        try:
            at_bottom = self.scroll.scroll_y <= 0.01
        except Exception:
            at_bottom = True
        new_entries = [e for e in recent_entries if e not in self.displayed_raw]
        for e in new_entries:
            text = self._format_entry_to_text(e)
            if text not in self.displayed_texts:
                item = LogItem(text=text, select_callback=self.select_item)
                self.log_box.add_widget(item)
                self.displayed_texts.append(text)
                self.displayed_raw.append(e)
        if len(self.displayed_texts) > 50:
            to_remove = len(self.displayed_texts) - 50
            self.displayed_texts = self.displayed_texts[to_remove:]
            self.displayed_raw = self.displayed_raw[to_remove:]
            try:
                for _ in range(to_remove):
                    if self.log_box.children:
                        oldest = self.log_box.children[-1]
                        self.log_box.remove_widget(oldest)
            except Exception:
                pass
        if self.selected_item:
            try:
                if self.selected_item.text not in self.displayed_texts:
                    self.selected_item = None
            except Exception:
                self.selected_item = None
        if at_bottom and self.selected_item is None:
            Clock.schedule_once(lambda dt: setattr(self.scroll, 'scroll_y', 0), 0.01)

    def select_item(self, item):
        if self.selected_item and self.selected_item is item:
            return
        if self.selected_item and self.selected_item is not item:
            try:
                self.selected_item.set_selected(False)
            except Exception:
                pass
        self.selected_item = item
        try:
            self.selected_item.set_selected(True)
        except Exception:
            pass

    def _on_scroll_touch_down(self, instance, touch):
        if not self.scroll.collide_point(*touch.pos):
            return False
        for child in self.log_box.children:
            try:
                local = child.to_widget(*touch.pos)
                if child.collide_point(*local):
                    return False
            except Exception:
                continue
        if self.selected_item:
            try:
                self.selected_item.set_selected(False)
            except Exception:
                pass
            self.selected_item = None
        return False

class TestPanel(BoxLayout):
    def __init__(self, controller, **kwargs):
        super().__init__(orientation='vertical', padding=20, spacing=20, **kwargs)
        self.controller = controller

        self.time_label = Label(text="", font_size=24, size_hint_y=None, height=40)
        self.add_widget(self.time_label)

        enable_box = BoxLayout(size_hint_y=None, height=40)
        enable_label = Label(text="Enable Auto Test:", size_hint_x=0.7)
        self.enable_checkbox = CheckBox(active=self.controller.auto_test_enabled)
        self.enable_checkbox.bind(active=self.on_enable_change)
        enable_box.add_widget(enable_label)
        enable_box.add_widget(self.enable_checkbox)
        self.add_widget(enable_box)

        interval_box = BoxLayout(size_hint_y=None, height=40)
        interval_label = Label(text="Interval (hours):", size_hint_x=0.7)
        self.interval_input = TextInput(text=str(self.controller.auto_test_interval_hours), multiline=False)
        interval_box.add_widget(interval_label)
        interval_box.add_widget(self.interval_input)
        self.add_widget(interval_box)

        time_box = BoxLayout(size_hint_y=None, height=40)
        hour_label = Label(text="Hour:", size_hint_x=0.3)
        self.hour_input = TextInput(text=str(self.controller.auto_test_hour), multiline=False)
        min_label = Label(text="Minute:", size_hint_x=0.3)
        self.min_input = TextInput(text=str(self.controller.auto_test_minute), multiline=False)
        time_box.add_widget(hour_label)
        time_box.add_widget(self.hour_input)
        time_box.add_widget(min_label)
        time_box.add_widget(self.min_input)
        self.add_widget(time_box)

        self.next_label = Label(text="", font_size=24, size_hint_y=None, height=40)
        self.add_widget(self.next_label)

        apply_btn = Button(text='Apply Changes', size_hint_y=None, height=50, background_color=(0.3,0.7,1,1))
        apply_btn.bind(on_press=self.apply_changes)
        self.add_widget(apply_btn)

        test_btn = Button(text='Perform Full Test', size_hint_y=None, height=50, background_color=(0.3,1,0.3,1))
        test_btn.bind(on_press=lambda x: self.controller.perform_full_test())
        self.add_widget(test_btn)

        report_btn = Button(text='View Test Reports', size_hint_y=None, height=50, background_color=(0.3,0.7,1,1))
        report_btn.bind(on_press=self.show_reports)
        self.add_widget(report_btn)

        Clock.schedule_interval(self.update, 1)

    def update(self, dt):
        self.time_label.text = f"Current Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        next_str = self.controller.next_auto_test.strftime('%Y-%m-%d %H:%M:%S') if self.controller.next_auto_test else 'None'
        self.next_label.text = f"Next Test: {next_str}"
        self.enable_checkbox.active = self.controller.auto_test_enabled

    def on_enable_change(self, instance, value):
        try:
            interval = int(self.interval_input.text)
            hour = int(self.hour_input.text)
            minute = int(self.min_input.text)
            self.controller.set_auto_test_params(value, interval, hour, minute)
        except ValueError:
            pass

    def apply_changes(self, instance):
        try:
            interval = int(self.interval_input.text)
            hour = int(self.hour_input.text)
            minute = int(self.min_input.text)
            self.controller.set_auto_test_params(self.enable_checkbox.active, interval, hour, minute)
            self.interval_input.text = str(self.controller.auto_test_interval_hours)
            self.hour_input.text = str(self.controller.auto_test_hour)
            self.min_input.text = str(self.controller.auto_test_minute)
        except ValueError:
            pass

    def show_reports(self, instance):
        reports = self.controller.get_test_reports()
        if not reports:
            popup = Popup(title='No Reports', content=Label(text="No test reports available."), size_hint=(0.4,0.2))
            popup.open()
            return
        scroll = ScrollView()
        report_box = BoxLayout(orientation='vertical', size_hint_y=None, spacing=5, padding=10)
        report_box.bind(minimum_height=report_box.setter('height'))
        for report in reversed(reports[-10:]):
            ts = report['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            status = report['status']
            lbl = Label(text=f"{ts} - {status}", size_hint_y=None, height=30, color=(1,1,1,1))
            report_box.add_widget(lbl)
            for zone, actions in report['zones'].items():
                for action in actions:
                    report_box.add_widget(Label(text=f"  Zone {zone}: {action}", size_hint_y=None, height=30, color=(0.8,0.8,0.8,1)))
        scroll.add_widget(report_box)
        popup = Popup(title='Test Reports', content=scroll, size_hint=(0.6,0.6))
        popup.open()

class FDCGUI(BoxLayout):
    def __init__(self, controller, **kwargs):
        super().__init__(orientation='horizontal', **kwargs)
        self.controller = controller
        self.current_zone = None
        self.zone_buttons = {}
        if not hasattr(self.controller, 'logs'):
            self.controller.logs = {z: [] for z in self.controller.zone_names.keys()}
        self.left_panel = BoxLayout(orientation='vertical', size_hint_x=0.25, spacing=10)
        self.scroll = ScrollView()
        self.zone_panel = BoxLayout(orientation='vertical', spacing=5, size_hint_y=None)
        self.zone_panel.bind(minimum_height=self.zone_panel.setter('height'))
        self.scroll.add_widget(self.zone_panel)
        self.left_panel.add_widget(self.scroll)
        control_box = BoxLayout(size_hint_y=None, height=50, spacing=5)
        add_btn = Button(text='Add Zone', background_color=(0.3,1,0.3,1), on_press=lambda x:self.prompt_add_zone())
        remove_btn = Button(text='Remove Zone', background_color=(1,0.3,0.3,1), on_press=lambda x:self.remove_zone())
        control_box.add_widget(add_btn)
        control_box.add_widget(remove_btn)
        self.left_panel.add_widget(control_box)
        save_box = BoxLayout(size_hint_y=None, height=50)
        save_btn = Button(text='Save Configuration', background_color=(0.3,0.7,1,1), size_hint_x=0.5, pos_hint={'center_x': 0.5}, on_press=lambda x: self.save_state())
        save_box.add_widget(save_btn)
        self.left_panel.add_widget(save_box)
        self.tabs = TabbedPanel(do_default_tab=False, size_hint_x=0.75)
        self.info_tab = TabbedPanelItem(text='Info')
        self.info_panel = ZoneInfo(controller)
        self.info_tab.add_widget(self.info_panel)
        self.tabs.add_widget(self.info_tab)
        self.log_tab = TabbedPanelItem(text='Logs')
        self.log_panel = LogPanel(controller, lambda: self.current_zone)
        self.log_tab.add_widget(self.log_panel)
        self.tabs.add_widget(self.log_tab)
        self.test_tab = TabbedPanelItem(text='Test')
        self.test_panel = TestPanel(controller)
        self.test_tab.add_widget(self.test_panel)
        self.tabs.add_widget(self.test_tab)
        self.add_widget(self.left_panel)
        self.add_widget(self.tabs)
        zones_list = sorted(self.controller.zone_names.keys())
        for z in zones_list:
            name = self.controller.zone_names.get(z, f"Zone {z}")
            self.add_zone_button(z, name=name)
        if zones_list:
            self.current_zone = min(zones_list)
        Clock.schedule_interval(lambda dt:self.update_info(), 1)
        Clock.schedule_interval(lambda dt:self.blink_zones(dt), 0.5)
        Clock.schedule_interval(lambda dt: self.save_state(), 30)
        Clock.schedule_interval(lambda dt: self.check_auto_test(dt), 60)
        self.bottom_controls = BoxLayout(size_hint_y=None, height=60, spacing=10)
        self.bottom_controls.add_widget(Button(text='Trigger Smoke', background_color=(1,0.3,0.3,1),
                                             on_press=lambda x: self.trigger_smoke()))
        self.bottom_controls.add_widget(Button(text='Trigger Thermal', background_color=(1,0.5,0,1),
                                             on_press=lambda x: self.trigger_thermal()))
        self.bottom_controls.add_widget(Button(text='Reset Alarms', background_color=(0.3,1,0.3,1),
                                             on_press=lambda x:self.reset_zone_alarms()))
        self.bottom_controls.add_widget(Button(text='Temp +10°C', background_color=(0.5,0.5,1,1),
                                             on_press=lambda x:self.set_temp(10)))
        self.bottom_controls.add_widget(Button(text='Temp -10°C', background_color=(0.5,0.5,1,1),
                                             on_press=lambda x:self.set_temp(-10)))
        self.bottom_controls.add_widget(Button(text='Trigger Alarm', background_color=(1,0,0,1),
                                             on_press=lambda x: self.trigger_external()))
        self.info_panel.add_widget(self.bottom_controls)

    def check_auto_test(self, dt):
        if self.controller.auto_test_enabled and self.controller.next_auto_test and datetime.datetime.now() >= self.controller.next_auto_test:
            self.controller.perform_full_test()
            self.controller._schedule_next_auto_test()

    def trigger_smoke(self):
        if self.current_zone is not None:
            self.controller.trigger_alarm('smoke', self.current_zone)
            self.save_state()

    def trigger_thermal(self):
        if self.current_zone is not None:
            self.controller.trigger_alarm('thermal', self.current_zone)
            self.save_state()

    def trigger_external(self):
        if self.current_zone is not None:
            self.controller.trigger_alarm('external', self.current_zone)
            self.save_state()

    def save_state(self):
        self.controller.save_state('fdc_state.json')

    def add_zone_button(self, zone_number, name=None):
        btn = ZoneCard(zone_number, self.select_zone, name=name)
        self.zone_buttons[zone_number] = btn
        self.zone_panel.add_widget(btn)
        self.update_selection()

    def prompt_add_zone(self):
        new_zone = max(self.zone_buttons.keys() or [0]) + 1
        box = BoxLayout(orientation='vertical', padding=10, spacing=10)
        ti = TextInput(text=f"Zone {new_zone}", multiline=False, size_hint_y=None, height=40)
        box.add_widget(ti)
        btn_box = BoxLayout(size_hint_y=None, height=40, spacing=5)
        ok_btn = Button(text='OK', background_color=(0.3,1,0.3,1))
        cancel_btn = Button(text='Cancel', background_color=(1,0.3,0.3,1))
        btn_box.add_widget(ok_btn)
        btn_box.add_widget(cancel_btn)
        box.add_widget(btn_box)
        popup = Popup(title='Enter Zone Name', content=box, size_hint=(0.5,0.3))
        popup.open()
        def add_zone_action(instance):
            name = ti.text.strip() or f"Zone {new_zone}"
            try:
                self.controller.zone_names[new_zone] = name
                self.controller.damper_positions[new_zone] = 'closed'
                self.controller.alarm_active[new_zone] = False
                self.controller.smoke_alarms[new_zone] = False
                self.controller.thermal_alarms[new_zone] = False
                self.controller.external_alarms[new_zone] = False
                self.controller.temp_sensor[new_zone] = 20
                self.controller.logs[new_zone] = []
            except Exception:
                pass
            self.add_zone_button(new_zone, name=name)
            self.current_zone = new_zone
            self.update_selection()
            popup.dismiss()
            self.save_state()
        ok_btn.bind(on_press=add_zone_action)
        cancel_btn.bind(on_press=lambda x: popup.dismiss())

    def remove_zone(self):
        if self.zone_buttons:
            zone_to_remove = self.current_zone
            try:
                btn = self.zone_buttons.pop(zone_to_remove)
                self.zone_panel.remove_widget(btn)
            except Exception:
                pass
            try:
                self.controller.zone_names.pop(zone_to_remove, None)
                self.controller.damper_positions.pop(zone_to_remove, None)
                self.controller.alarm_active.pop(zone_to_remove, None)
                self.controller.smoke_alarms.pop(zone_to_remove, None)
                self.controller.thermal_alarms.pop(zone_to_remove, None)
                self.controller.external_alarms.pop(zone_to_remove, None)
                self.controller.temp_sensor.pop(zone_to_remove, None)
                self.controller.logs.pop(zone_to_remove, None)
            except Exception:
                pass
            if self.zone_buttons:
                available_zones = sorted(self.zone_buttons.keys())
                closest = min(available_zones, key=lambda x: abs(x - zone_to_remove))
                self.current_zone = closest
            else:
                self.current_zone = None
            self.update_selection()
            self.save_state()

    def select_zone(self, zone_number):
        self.current_zone = zone_number
        self.update_selection()

    def update_selection(self):
        for z, btn in self.zone_buttons.items():
            btn.set_selected(z == self.current_zone)

    def update_info(self):
        if self.current_zone is None:
            for lbl in self.info_panel.info_labels.values():
                lbl.text = ""
            return
        try:
            self.info_panel.update_info(self.current_zone)
        except Exception:
            pass
        try:
            status = self.controller.get_status()
        except Exception:
            status = {}
        for z, btn in self.zone_buttons.items():
            try:
                has_alarm = status.get('smoke_alarms', {}).get(z, False) or status.get('thermal_alarms', {}).get(z, False) or status.get('external_alarms', {}).get(z, False)
            except Exception:
                has_alarm = False
            btn.set_status(has_alarm)

    def blink_zones(self, dt):
        for btn in self.zone_buttons.values():
            btn.blink(dt)

    def reset_zone_alarms(self):
        if self.current_zone is None:
            return
        try:
            self.controller.alarm_active[self.current_zone] = False
            self.controller.smoke_alarms[self.current_zone] = False
            self.controller.thermal_alarms[self.current_zone] = False
            self.controller.external_alarms[self.current_zone] = False
            self.controller._set_working_position()
            self.controller._update_leds()
            self.controller._update_relay()
            self.controller._update_analog_out()
            ts = datetime.datetime.now()
            msg = "Alarm deactivated"
            self.controller.logs[self.current_zone].append((ts, msg))
        except Exception:
            pass
        self.save_state()

    def set_temp(self, delta):
        if self.current_zone is None:
            return
        try:
            self.controller.temp_sensor[self.current_zone] += delta
            if self.controller.temp_sensor[self.current_zone] > 72:
                self.controller.trigger_alarm('thermal', self.current_zone)
        except Exception:
            pass
        self.save_state()

class FDCApp(App):
    def build(self):
        Window.fullscreen = False  # Set windowed mode
        Window.maximize()  # Maximize the window
        controller = FDCController(model_type='FDC-2KJ', mode='fire', zones=0)
        save_file = 'fdc_state.json'
        controller.load_state(save_file)
        return FDCGUI(controller)

    def on_stop(self):
        self.root.save_state()

if __name__ == '__main__':
    FDCApp().run()