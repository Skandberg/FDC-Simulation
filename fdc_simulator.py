# fdc_simulator.py
import time
import datetime
import sys
from collections import defaultdict
import json
import os

class FDCController:
    """
    Simulation of the FDC Fire Damper Controller based on the manual.
    Receives commands via stdin and outputs status via stdout.
    Accelerated version: No sleep delays for instant response.
    Added per-zone logging and save/load state.
    """

    def __init__(self, model_type='FDC-2KJ', mode='fire', zones=2):
        """
        Initialize the controller.
        - model_type: e.g., 'FDC-2KJ' (230V-24V, 2 zones)
        - mode: 'fire' (open normal, close on alarm) or 'smoke' (closed normal, open on alarm)
        - zones: 2 or 4
        """
        self.model_type = model_type
        self.mode = mode  # 'fire' or 'smoke'
        self.zones = zones if zones in [2, 4] else 2
        self.powered = False
        self.damper_positions = {i: 'closed' for i in range(1, self.zones + 1)}  # 'open' or 'closed'
        self.alarm_active = {i: False for i in range(1, self.zones + 1)}  # Per-zone alarm active
        self.smoke_alarm = {i: False for i in range(1, self.zones + 1)}
        self.thermal_alarm = {i: False for i in range(1, self.zones + 1)}
        self.external_alarm = False
        self.test_mode = False
        self.invert_position = False  # From input or config
        self.smoke_detector_type = 'NO'  # 'NO' or 'NC'
        self.operation_time = 90  # seconds, default for position change (but not used for sleep)
        self.test_time = 120  # seconds, default for full test
        self.comm_timeout = 120  # seconds, for Modbus/BACnet
        self.comm_timeout_enabled = False
        self.auto_test_enabled = False
        self.auto_test_interval_hours = 24  # default
        self.auto_test_hour = 0
        self.auto_test_minute = 0
        self.next_auto_test = None
        self.rtc = datetime.datetime(2025, 9, 10, 11, 20)  # Updated to 11:20 AM +04
        self.alarm_history = []  # List of alarm codes
        self.dip_sw1 = 0  # Modbus/BACnet Slave ID (0-127)
        self.dip_sw4 = {'DIP5': 0, 'DIP6': 1, 'DIP7': 0}  # 0=Modbus,1=BACnet; DIP6:1=ALARM,0=FAN; DIP7:0=Smoke,1=Fire
        self.relay_mode = 'ALARM' if self.dip_sw4['DIP6'] else 'FAN'
        self.relay_state = 'OPEN'  # 'OPEN' or 'CLOSED'
        self.analog_out = 0.0  # 0-10V status
        self.modbus_registers = self._init_modbus_registers()
        self.bacnet_objects = self._init_bacnet_objects()
        self.led_status = 'OFF'  # 'ON', 'FLASH', 'OFF'
        self.led_fault = 'OFF'
        self.temp_sensor = {i: 20.0 for i in range(1, self.zones + 1)}  # Per-zone temperature
        # Per-zone logs
        self.logs = {i: [] for i in range(1, self.zones + 1)}

    def _init_modbus_registers(self):
        """Initialize Modbus holding registers based on manual section 5."""
        regs = defaultdict(int)
        # Control registers (from page 12-13)
        regs[101] = 0  # Test/Retest (write 1 to start)
        regs[102] = 0  # Smoke detector reset (write 1)
        regs[103] = 0  # Invert damper position (0/1)
        regs[104] = 0  # Smoke detector type (0=NO,1=NC)
        regs[105] = 0  # Clear alarm history (write 1)
        # Config registers (page 14)
        regs[300] = self._get_hw_type()  # HW type
        regs[301] = self.dip_sw1  # Slave ID
        regs[302] = int(self.comm_timeout_enabled)  # Timeout enable
        regs[303] = self.comm_timeout  # Timeout value
        regs[304] = self.operation_time  # Operation time
        regs[305] = self.test_time  # Test time
        regs[306] = self.rtc.year
        regs[307] = self.rtc.month
        regs[308] = self.rtc.day
        regs[309] = self.rtc.hour
        regs[310] = self.rtc.minute
        regs[311] = self.auto_test_interval_hours
        regs[312] = self.auto_test_hour
        regs[313] = self.auto_test_minute
        regs[314] = int(self.auto_test_enabled)
        # Alarm registers (page 15)
        regs[401] = 0  # Active alarms bitmask
        for i in range(1, self.zones + 1):
            regs[401 + i] = 0  # Per zone alarms
        # History (501-520)
        for i in range(501, 521):
            regs[i] = 0
        return regs

    def _init_bacnet_objects(self):
        """Initialize BACnet objects based on manual section 6."""
        objs = {
            'AI': defaultdict(int),
            'AV': defaultdict(int),
            'BI': defaultdict(int),
            'BO': defaultdict(int),
        }
        # From page 16-19
        objs['AI'][1] = 0  # Active alarms bitmask (similar to Modbus 401)
        objs['AI'][2] = self._get_hw_type()
        objs['AI'][3] = self.dip_sw1
        objs['AI'][4] = self.rtc.year
        objs['AI'][5] = self.rtc.month
        objs['AI'][6] = self.rtc.day
        objs['AI'][7] = self.rtc.weekday() + 1  # 1=Monday
        objs['AI'][10] = self.comm_timeout
        objs['AV'][1] = self.operation_time
        objs['AV'][2] = self.test_time
        objs['AV'][3] = int(self.comm_timeout_enabled)
        for i in range(1, self.zones + 1):
            objs['BI'][i] = 0  # Damper position alarm zone i
        objs['BO'][1] = 0  # Test start
        objs['BO'][2] = 0  # Smoke reset
        objs['BO'][3] = int(self.invert_position)
        return objs

    def _get_hw_type(self):
        types = {'FDC-2KJ': 1, 'FDC-2JJ': 2, 'FDC-2KK': 3, 'FDC-4KJ': 4, 'FDC-4JJ': 5, 'FDC-4KK': 6}
        return types.get(self.model_type, 1)

    def _add_log(self, zone, message):
        if zone not in self.logs:
            self.logs[zone] = []
        timestamp = self.rtc.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.logs[zone].append(entry)
        if len(self.logs[zone]) > 100:
            self.logs[zone].pop(0)
        print(entry)  # for console

    def get_logs(self, zone):
        """Returns list of logs for the specified zone"""
        return self.logs.get(zone, [])

    def power_on(self):
        self.powered = True
        self.rtc = datetime.datetime(2025, 9, 10, 11, 20)
        if not any(self.alarm_active.values()):
            self.perform_full_test()
        self._set_working_position()
        self._update_leds()
        self._update_relay()
        self._update_analog_out()
        for z in range(1, self.zones + 1):
            self._add_log(z, "Controller powered on")
        print("Controller powered on.")

    def power_off(self):
        self.powered = False
        for i in range(1, self.zones + 1):
            self.alarm_active[i] = False
        self.external_alarm = False
        for i in range(1, self.zones + 1):
            self.smoke_alarm[i] = False
            self.thermal_alarm[i] = False
        self._set_working_position()  # Reset to default positions
        self._update_leds()
        self._update_relay()
        self._update_analog_out()
        for z in range(1, self.zones + 1):
            self._add_log(z, "Controller powered off")
        print("Controller powered off.")

    def _set_working_position(self):
        pos = 'open' if self.mode == 'fire' else 'closed'
        if self.invert_position:
            pos = 'closed' if pos == 'open' else 'open'
        for i in range(1, self.zones + 1):
            self._change_damper_position(i, pos)

    def _change_damper_position(self, zone, position, simulate_time=False):
        if simulate_time:
            time.sleep(self.operation_time / 100)
        self.damper_positions[zone] = position
        self._add_log(zone, f"Damper moved to {position.upper()}")
        self._update_analog_out()

    def trigger_alarm(self, alarm_type, zone=None):
        if zone is None:
            zone = 1  # Default to zone 1 if not specified
        self.alarm_active[zone] = True
        if alarm_type == 'external':
            self.external_alarm = True
        elif alarm_type == 'smoke':
            self.smoke_alarm[zone] = True
        elif alarm_type == 'thermal':
            self.thermal_alarm[zone] = True
        self._add_to_history(alarm_type)
        alarm_pos = 'closed' if self.mode == 'fire' else 'open'
        if self.invert_position:
            alarm_pos = 'open' if alarm_pos == 'closed' else 'closed'
        self._change_damper_position(zone, alarm_pos)
        self._update_alarms_register()
        self._update_leds()
        self._update_relay()
        self._update_analog_out()
        self._add_log(zone, f"{alarm_type.capitalize()} alarm triggered")
        print(f"{alarm_type.capitalize()} alarm triggered in zone {zone}.")

    def reset_alarms(self, zone=None):
        if zone:
            self.alarm_active[zone] = False
            self.smoke_alarm[zone] = False
            self.thermal_alarm[zone] = False
            self._add_log(zone, "Alarms reset")
        else:
            for i in range(1, self.zones + 1):
                self.alarm_active[i] = False
            self.external_alarm = False
            for i in range(1, self.zones + 1):
                self.smoke_alarm[i] = False
                self.thermal_alarm[i] = False
            self._add_log(1, "All alarms reset")  # Log to zone 1 or all if needed
        self._set_working_position()
        self._update_alarms_register()
        self._update_leds()
        self._update_relay()
        self._update_analog_out()
        print("Alarms reset.")

    def perform_full_test(self):
        if any(self.alarm_active.values()):
            print("Can't perform test with active alarms.")
            return
        self.test_mode = True
        self._update_leds()
        for i in range(1, self.zones + 1):
            self._change_damper_position(i, 'closed')
            self._add_log(i, "Full test started: Damper closed")
        for i in range(1, self.zones + 1):
            self._change_damper_position(i, 'open')
            self._add_log(i, "Full test: Damper opened")
        for i in range(1, self.zones + 1):
            self._change_damper_position(i, 'closed')
            self._add_log(i, "Full test: Damper closed again")
        elapsed = 0  # Instant
        if elapsed > self.test_time:
            self.trigger_alarm('test_failure')
            print("Test failed: Time exceeded.")
        else:
            print("Test passed.")
            for i in range(1, self.zones + 1):
                self._add_log(i, "Full test passed")
        self.test_mode = False
        self._set_working_position()
        self._update_leds()

    def reset_smoke_detector(self):
        for i in range(1, self.zones + 1):
            self.smoke_alarm[i] = False
            self._add_log(i, "Smoke detectors reset")
        if not any(self.smoke_alarm.values()) and not any(self.thermal_alarm.values()) and not self.external_alarm:
            self.reset_alarms()
        print("Smoke detectors reset.")

    def set_invert_position(self, invert):
        self.invert_position = bool(invert)
        self._set_working_position()
        for i in range(1, self.zones + 1):
            self._add_log(i, f"Invert position set to {self.invert_position}")
        print(f"Invert position set to {self.invert_position}")

    def set_smoke_detector_type(self, typ):
        self.smoke_detector_type = typ.upper() if typ.upper() in ['NO', 'NC'] else 'NO'
        for i in range(1, self.zones + 1):
            self._add_log(i, f"Smoke detector type set to {self.smoke_detector_type}")
        print(f"Smoke detector type set to {self.smoke_detector_type}")

    def _update_analog_out(self):
        if not self.powered:
            self.analog_out = 0
        elif any(self.alarm_active.values()):
            alarms = sum([self.external_alarm, any(self.smoke_alarm.values()), any(self.thermal_alarm.values())])
            if alarms > 1:
                self.analog_out = 10
            elif any(self.smoke_alarm.values()):
                self.analog_out = 6
            elif any(self.thermal_alarm.values()):
                self.analog_out = 8
            else:
                self.analog_out = 4
        else:
            self.analog_out = 2

    def _update_relay(self):
        if self.relay_mode == 'ALARM':
            self.relay_state = 'CLOSED' if any(self.alarm_active.values()) else 'OPEN'
        else:
            if self.dip_sw4['DIP7'] == 0:
                self.relay_state = 'CLOSED' if any(self.alarm_active.values()) else 'OPEN'
            else:
                self.relay_state = 'OPEN' if any(self.alarm_active.values()) else 'CLOSED'

    def _update_leds(self):
        self.led_status = 'FLASH' if self.test_mode else ('ON' if self.powered else 'OFF')
        self.led_fault = 'ON' if any(self.alarm_active.values()) else 'OFF'

    def _update_alarms_register(self):
        bitmask = 0
        if self.external_alarm:
            bitmask |= 1 << 2
        if any(self.smoke_alarm.values()):
            bitmask |= 1 << 3
        if self.test_mode and False:  # Placeholder
            bitmask |= 1 << 4
        if self.comm_timeout_enabled and False:  # Placeholder
            bitmask |= 1 << 5
        self.modbus_registers[401] = bitmask
        for i in range(1, self.zones + 1):
            self.modbus_registers[401 + i] = int(self.smoke_alarm[i] or self.thermal_alarm[i])

    def _add_to_history(self, alarm_type):
        codes = {'position': 11, 'comm': 12, 'thermal': 20, 'external': 30, 'smoke': 40, 'test_failure': 50}
        code = codes.get(alarm_type, 0)
        if code:
            self.alarm_history.append(code)
            if len(self.alarm_history) > 20:
                self.alarm_history.pop(0)
            for i, c in enumerate(self.alarm_history):
                self.modbus_registers[501 + i] = c

    def modbus_read(self, reg):
        return self.modbus_registers.get(reg, 0)

    def modbus_write(self, reg, value):
        if reg == 101 and value == 1:
            self.perform_full_test()
        elif reg == 102 and value == 1:
            self.reset_smoke_detector()
        elif reg == 103:
            self.set_invert_position(value)
        elif reg == 104:
            self.set_smoke_detector_type('NC' if value else 'NO')
        elif reg == 105 and value == 1:
            self.alarm_history = []
            for i in range(1, self.zones + 1):
                self._add_log(i, "Alarm history cleared")
            print("Alarm history cleared.")
        elif reg == 302:
            self.comm_timeout_enabled = bool(value)
        elif reg == 303:
            self.comm_timeout = max(60, min(360, value))
        elif reg == 304:
            self.operation_time = max(60, min(360, value))
        elif reg == 305:
            self.test_time = max(60, min(360, value))
        elif reg in [306, 307, 308, 309, 310]:
            if reg == 306: self.rtc = self.rtc.replace(year=value)
            elif reg == 307: self.rtc = self.rtc.replace(month=value)
            elif reg == 308: self.rtc = self.rtc.replace(day=value)
            elif reg == 309: self.rtc = self.rtc.replace(hour=value)
            elif reg == 310: self.rtc = self.rtc.replace(minute=value)
            for i in range(1, self.zones + 1):
                self._add_log(i, "RTC updated")
            print("RTC updated.")
        elif reg == 311:
            self.auto_test_interval_hours = max(1, min(4464, value))
        elif reg == 312:
            self.auto_test_hour = value % 24
        elif reg == 313:
            self.auto_test_minute = value % 60
        elif reg == 314:
            self.auto_test_enabled = bool(value)
            if self.auto_test_enabled:
                self._schedule_next_auto_test()
            for i in range(1, self.zones + 1):
                self._add_log(i, f"Auto test enabled: {self.auto_test_enabled}")
            print(f"Auto test enabled: {self.auto_test_enabled}")
        self.modbus_registers[reg] = value

    def _schedule_next_auto_test(self):
        interval = datetime.timedelta(hours=self.auto_test_interval_hours)
        next_time = self.rtc.replace(hour=self.auto_test_hour, minute=self.auto_test_minute, second=0, microsecond=0)
        while next_time <= self.rtc:
            next_time += interval
        self.next_auto_test = next_time
        print(f"Next auto test scheduled at {self.next_auto_test}")

    def simulate_time_pass(self, seconds):
        self.rtc += datetime.timedelta(seconds=seconds)
        for i in range(1, self.zones + 1):
            self._add_log(i, f"Time advanced by {seconds} seconds. Current RTC: {self.rtc}")
        print(f"Time advanced by {seconds} seconds. Current RTC: {self.rtc}")
        if self.auto_test_enabled and self.next_auto_test and self.rtc >= self.next_auto_test:
            print("Auto test triggered by time pass.")
            self.perform_full_test()
            self._schedule_next_auto_test()

    def reset_to_defaults(self):
        self.operation_time = 90
        self.test_time = 120
        self.comm_timeout = 120
        self.comm_timeout_enabled = False
        self.auto_test_enabled = False
        self.alarm_history = []
        for i in range(1, self.zones + 1):
            self._add_log(i, "Reset to defaults")
        print("Reset to defaults.")

    def get_status(self):
        status = {
            'powered': self.powered,
            'mode': self.mode,
            'damper_positions': self.damper_positions,
            'alarm_active': self.alarm_active,
            'smoke_alarms': self.smoke_alarm,
            'thermal_alarms': self.thermal_alarm,
            'external_alarm': self.external_alarm,
            'analog_out': self.analog_out,
            'relay_state': self.relay_state,
            'led_status': self.led_status,
            'led_fault': self.led_fault,
            'rtc': self.rtc.strftime("%Y-%m-%d %H:%M:%S"),
            'auto_test_enabled': self.auto_test_enabled,
            'next_auto_test': self.next_auto_test.strftime("%Y-%m-%d %H:%M:%S") if self.next_auto_test else None,
            'alarm_history': self.alarm_history,
            'temp_sensor': self.temp_sensor
        }
        return status

    def save_state(self, file_path):
        state = {
            'model_type': self.model_type,
            'mode': self.mode,
            'zones': self.zones,
            'powered': self.powered,
            'damper_positions': {str(k): v for k, v in self.damper_positions.items()},
            'alarm_active': {str(k): v for k, v in self.alarm_active.items()},
            'smoke_alarm': {str(k): v for k, v in self.smoke_alarm.items()},
            'thermal_alarm': {str(k): v for k, v in self.thermal_alarm.items()},
            'external_alarm': self.external_alarm,
            'test_mode': self.test_mode,
            'invert_position': self.invert_position,
            'smoke_detector_type': self.smoke_detector_type,
            'operation_time': self.operation_time,
            'test_time': self.test_time,
            'comm_timeout': self.comm_timeout,
            'comm_timeout_enabled': self.comm_timeout_enabled,
            'auto_test_enabled': self.auto_test_enabled,
            'auto_test_interval_hours': self.auto_test_interval_hours,
            'auto_test_hour': self.auto_test_hour,
            'auto_test_minute': self.auto_test_minute,
            'next_auto_test': self.next_auto_test.isoformat() if self.next_auto_test else None,
            'rtc': self.rtc.isoformat(),
            'alarm_history': self.alarm_history,
            'dip_sw1': self.dip_sw1,
            'dip_sw4': self.dip_sw4,
            'relay_mode': self.relay_mode,
            'relay_state': self.relay_state,
            'analog_out': self.analog_out,
            'modbus_registers': dict(self.modbus_registers),
            'bacnet_objects': {k: dict(v) for k, v in self.bacnet_objects.items()},
            'led_status': self.led_status,
            'led_fault': self.led_fault,
            'temp_sensor': {str(k): v for k, v in self.temp_sensor.items()},
            'logs': {str(k): v for k, v in self.logs.items()}
        }
        with open(file_path, 'w') as f:
            json.dump(state, f)

    def load_state(self, file_path):
        with open(file_path, 'r') as f:
            state = json.load(f)
        self.model_type = state['model_type']
        self.mode = state['mode']
        self.zones = state['zones']
        self.powered = state['powered']
        self.damper_positions = {int(k): v for k, v in state['damper_positions'].items()}
        self.alarm_active = {int(k): v for k, v in state['alarm_active'].items()}
        self.smoke_alarm = {int(k): v for k, v in state['smoke_alarm'].items()}
        self.thermal_alarm = {int(k): v for k, v in state['thermal_alarm'].items()}
        self.external_alarm = state['external_alarm']
        self.test_mode = state['test_mode']
        self.invert_position = state['invert_position']
        self.smoke_detector_type = state['smoke_detector_type']
        self.operation_time = state['operation_time']
        self.test_time = state['test_time']
        self.comm_timeout = state['comm_timeout']
        self.comm_timeout_enabled = state['comm_timeout_enabled']
        self.auto_test_enabled = state['auto_test_enabled']
        self.auto_test_interval_hours = state['auto_test_interval_hours']
        self.auto_test_hour = state['auto_test_hour']
        self.auto_test_minute = state['auto_test_minute']
        self.next_auto_test = datetime.datetime.fromisoformat(state['next_auto_test']) if state['next_auto_test'] else None
        self.rtc = datetime.datetime.fromisoformat(state['rtc'])
        self.alarm_history = state['alarm_history']
        self.dip_sw1 = state['dip_sw1']
        self.dip_sw4 = state['dip_sw4']
        self.relay_mode = state['relay_mode']
        self.relay_state = state['relay_state']
        self.analog_out = state['analog_out']
        self.modbus_registers = defaultdict(int, state['modbus_registers'])
        self.bacnet_objects = {k: defaultdict(int, v) for k, v in state['bacnet_objects'].items()}
        self.led_status = state['led_status']
        self.led_fault = state['led_fault']
        self.temp_sensor = {int(k): v for k, v in state['temp_sensor'].items()}
        self.logs = {int(k): v for k, v in state['logs'].items()}

    def process_command(self, cmd):
        parts = cmd.strip().split()
        if not parts:
            return
        action = parts[0]

        if action == "power_on":
            self.power_on()
        elif action == "power_off":
            self.power_off()
        elif action == "trigger_smoke":
            if len(parts) > 1:
                zone = int(parts[1])
                self.trigger_alarm('smoke', zone)
        elif action == "trigger_thermal":
            if len(parts) > 1:
                zone = int(parts[1])
                self.trigger_alarm('thermal', zone)
        elif action == "trigger_external":
            self.trigger_alarm('external')
        elif action == "reset_alarms":
            if len(parts) > 1:
                zone = int(parts[1])
                self.reset_alarms(zone)
            else:
                self.reset_alarms()
        elif action == "reset_smoke":
            self.reset_smoke_detector()
        elif action == "perform_test":
            self.perform_full_test()
        elif action == "set_invert":
            if len(parts) > 1:
                invert = int(parts[1])
                self.set_invert_position(invert)
        elif action == "set_detector_type":
            if len(parts) > 1:
                typ = parts[1]
                self.set_smoke_detector_type(typ)
        elif action == "modbus_write":
            if len(parts) > 2:
                reg = int(parts[1])
                value = int(parts[2])
                self.modbus_write(reg, value)
        elif action == "modbus_read":
            if len(parts) > 1:
                reg = int(parts[1])
                value = self.modbus_read(reg)
                print(f"Modbus register {reg}: {value}")
        elif action == "simulate_time":
            if len(parts) > 1:
                seconds = int(parts[1])
                self.simulate_time_pass(seconds)
        elif action == "reset_defaults":
            self.reset_to_defaults()
        elif action == "status":
            print(json.dumps(self.get_status(), indent=2))
        elif action == "enable_auto_test":
            if len(parts) == 4:
                interval = int(parts[1])
                hour = int(parts[2])
                minute = int(parts[3])
                self.auto_test_interval_hours = interval
                self.auto_test_hour = hour
                self.auto_test_minute = minute
                self.auto_test_enabled = True
                self._schedule_next_auto_test()
                print(f"Auto-test enabled: {interval}h at {hour}:{minute:02d}, next at {self.next_auto_test}")
        elif action == "set_temp":
            if len(parts) >= 3:
                zone = int(parts[1])
                temp = float(parts[2])
                self.temp_sensor[zone] = temp
                self._add_log(zone, f"Temperature set to {temp}°C")
                print(f"Temperature set to {temp}°C in zone {zone}")
                if temp > 72 and not self.alarm_active[zone]:
                    self.trigger_alarm('thermal', zone)
            elif len(parts) == 2:
                temp = float(parts[1])
                self.temp_sensor[1] = temp
                self._add_log(1, f"Temperature set to {temp}°C")
                print(f"Temperature set to {temp}°C")
                if temp > 72 and not self.alarm_active[1]:
                    self.trigger_alarm('thermal', 1)
        elif action == "get_logs":
            if len(parts) > 1:
                zone = int(parts[1])
                print(json.dumps(self.get_logs(zone), indent=2))
        elif action == "save_state":
            if len(parts) > 1:
                file_path = parts[1]
                self.save_state(file_path)
                print(f"State saved to {file_path}")
        elif action == "load_state":
            if len(parts) > 1:
                file_path = parts[1]
                self.load_state(file_path)
                print(f"State loaded from {file_path}")
        elif action == "exit":
            print("Simulation exited.")
            sys.exit(0)
        else:
            print(f"Unknown command: {cmd}")

if __name__ == "__main__":
    controller = FDCController(model_type='FDC-2KJ', mode='fire', zones=2)
    save_file = 'fdc_sim_state.json'
    if os.path.exists(save_file):
        controller.load_state(save_file)
    print("FDC Controller Simulation started (accelerated mode). Waiting for commands from client...")
    for line in sys.stdin:
        controller.process_command(line)
    controller.save_state(save_file)