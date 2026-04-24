import pexpect
import time
import re
import logging
import subprocess

log = logging.getLogger("assistant.bluetooth")

class BluetoothManager:
    def __init__(self):
        self.timeout = 10

    def _run_command(self, command):
        """Helper to run a simple bluetoothctl command and return output."""
        try:
            result = subprocess.run(["bluetoothctl", command], capture_output=True, text=True, timeout=5)
            return result.stdout
        except Exception as e:
            log.error(f"Bluetooth command error: {e}")
            return ""

    def discover(self, duration=10):
        """Scans for nearby devices."""
        log.info(f"Scanning for Bluetooth devices for {duration}s...")
        self._run_command("power on")
        try:
            # We use pexpect to start scan, wait, and then list devices
            child = pexpect.spawn("bluetoothctl", encoding='utf-8', timeout=duration + 5)
            child.sendline("power on")
            child.sendline("agent on")
            child.sendline("default-agent")
            child.sendline("scan on")
            time.sleep(duration)
            child.sendline("scan off")
            child.sendline("devices")
            child.expect("devices")
            output = child.before + child.after
            
            # Now actually get the list of devices properly
            child.sendline("devices")
            child.expect(pexpect.EOF, timeout=2) # Flush
        except:
            pass
            
        # Re-run a clean 'devices' command to get current cache
        output = self._run_command("devices")
        
        devices = []
        for line in output.splitlines():
            # Format: Device XX:XX:XX:XX:XX:XX DeviceName
            match = re.search(r"Device\s+(([0-9A-F]{2}:?){6})\s+(.*)", line, re.I)
            if match:
                devices.append({
                    "mac": match.group(1),
                    "name": match.group(3).strip()
                })
        return devices

    def get_paired_devices(self):
        """Returns list of paired devices."""
        output = self._run_command("paired-devices")
        devices = []
        for line in output.splitlines():
            match = re.search(r"Device\s+(([0-9A-F]{2}:?){6})\s+(.*)", line, re.I)
            if match:
                devices.append({
                    "mac": match.group(1),
                    "name": match.group(3).strip()
                })
        return devices

    def get_info(self, mac):
        """Gets detailed info for a device (to check if connected)."""
        output = self._run_command(f"info {mac}")
        info = {
            "mac": mac,
            "connected": "Connected: yes" in output,
            "paired": "Paired: yes" in output,
            "trusted": "Trusted: yes" in output
        }
        return info

    def connect(self, mac):
        """Pairs, trusts, and connects to a device."""
        log.info(f"Attempting to connect to {mac}...")
        try:
            child = pexpect.spawn(f"bluetoothctl", encoding='utf-8', timeout=20)
            
            # Trust first
            child.sendline(f"trust {mac}")
            child.expect(f"trust {mac} succeeded|Changing {mac} trust succeeded", timeout=5)
            
            # Pair
            child.sendline(f"pair {mac}")
            # Handle potential passkey confirmation
            index = child.expect(["Pairing successful", "Confirm passkey", "Enter PIN code", "Failed to pair", pexpect.TIMEOUT], timeout=15)
            if index == 1: # Confirm passkey
                child.sendline("yes")
                child.expect("Pairing successful")
            elif index == 2: # PIN
                child.sendline("0000") # Common default
                child.expect("Pairing successful")
            
            # Connect
            child.sendline(f"connect {mac}")
            child.expect("Connection successful", timeout=10)
            
            child.sendline("quit")
            child.close()
            return True
        except Exception as e:
            log.error(f"Failed to connect to {mac}: {e}")
            return False

    def disconnect(self, mac):
        """Disconnects a device."""
        log.info(f"Disconnecting {mac}...")
        self._run_command(f"disconnect {mac}")
        return True

    def remove(self, mac):
        """Removes (unpairs) a device."""
        log.info(f"Removing device {mac}...")
        self._run_command(f"remove {mac}")
        return True

    def get_status(self):
        """Returns details about the currently connected audio device if any."""
        paired = self.get_paired_devices()
        for dev in paired:
            info = self.get_info(dev['mac'])
            if info['connected']:
                dev.update(info)
                return dev
        return None
