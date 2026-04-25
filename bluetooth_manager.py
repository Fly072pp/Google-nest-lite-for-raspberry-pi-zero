import pexpect
import time
import re
import logging
import subprocess

log = logging.getLogger("assistant.bluetooth")

class BluetoothManager:
    def __init__(self):
        self.timeout = 20

    def _run_command(self, command):
        """Helper to run a simple bluetoothctl command and return output."""
        try:
            cmd_list = ["bluetoothctl"] + command.split()
            result = subprocess.run(cmd_list, capture_output=True, text=True, timeout=10)
            return result.stdout
        except Exception as e:
            log.error(f"Bluetooth command error for '{command}': {e}")
            return ""

    def power_on(self):
        """Ensures the Bluetooth adapter is powered on."""
        log.info("Turning Bluetooth power on...")
        self._run_command("power on")
        time.sleep(1) # Small delay to let it initialize

    def discover(self, duration=10):
        """Scans for nearby devices using pexpect for real-time discovery."""
        log.info(f"Scanning for Bluetooth devices for {duration}s...")
        self.power_on()
        
        devices = {} # Use dict to avoid duplicates
        
        try:
            # We use pexpect to catch [NEW] or [CHG] lines during scan
            child = pexpect.spawn("bluetoothctl", encoding='utf-8', timeout=duration + 5)
            
            child.sendline("scan on")
            
            start_time = time.time()
            # Regex for Device XX:XX:XX:XX:XX:XX Name
            pattern = r"Device\s+(([0-9A-F]{2}:?){6})\s+(.*)"
            
            while time.time() - start_time < duration:
                try:
                    # Expect any line with "Device"
                    index = child.expect([r"Device\s+(([0-9A-F]{2}:?){6})\s+(.*)", pexpect.TIMEOUT], timeout=1)
                    if index == 0:
                        mac = child.match.group(1)
                        name = child.match.group(3).strip()
                        # Clean name from potential color codes or extra tags
                        name = re.sub(r'\x1b\[[0-9;]*m', '', name)
                        if mac not in devices or (devices[mac] == mac and name != mac):
                            devices[mac] = name
                            log.debug(f"Discovered: {mac} ({name})")
                except pexpect.EOF:
                    break
            
            child.sendline("scan off")
            child.expect(["Discovery stopped", pexpect.TIMEOUT], timeout=2)
            child.sendline("quit")
            child.close()
        except Exception as e:
            log.error(f"Discovery error: {e}")

        # Fallback/Complement: get all known devices from cache
        output = self._run_command("devices")
        for line in output.splitlines():
            match = re.search(r"Device\s+(([0-9A-F]{2}:?){6})\s+(.*)", line, re.I)
            if match:
                mac = match.group(1)
                name = match.group(3).strip()
                if mac not in devices:
                    devices[mac] = name

        return [{"mac": m, "name": n} for m, n in devices.items() if n]

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
        """Gets detailed info for a device."""
        output = self._run_command(f"info {mac}")
        return {
            "mac": mac,
            "connected": "Connected: yes" in output,
            "paired": "Paired: yes" in output,
            "trusted": "Trusted: yes" in output
        }

    def connect(self, mac):
        """Pairs, trusts, and connects to a device with interactive agent handling."""
        log.info(f"Connecting to {mac}...")
        self.power_on()
        
        try:
            child = pexpect.spawn("bluetoothctl", encoding='utf-8', timeout=30)
            
            # Start agent to handle pairing prompts
            child.sendline("agent on")
            child.expect(["Agent registered", "already registered"], timeout=5)
            child.sendline("default-agent")
            child.expect(["Default agent request successful", "already registered"], timeout=5)
            
            # Trust device
            child.sendline(f"trust {mac}")
            child.expect([f"trust {mac} succeeded", "Changing .* trust succeeded", "not available"], timeout=5)
            
            # Pair device
            log.info(f"Pairing with {mac}...")
            child.sendline(f"pair {mac}")
            
            # Handle various interactive prompts
            # 0: Success, 1: Confirm passkey, 2: PIN, 3: Failed, 4: Already paired
            index = child.expect([
                "Pairing successful", 
                "Confirm passkey", 
                "Enter PIN code", 
                "Failed to pair", 
                "already paired",
                pexpect.TIMEOUT
            ], timeout=20)
            
            if index == 1: # Confirm passkey
                log.info("Confirming passkey...")
                child.sendline("yes")
                child.expect("Pairing successful", timeout=10)
            elif index == 2: # PIN code
                log.info("Sending PIN 0000...")
                child.sendline("0000")
                child.expect("Pairing successful", timeout=10)
            elif index == 3:
                log.error(f"Pairing failed for {mac}")
                child.sendline("quit")
                return False
            
            # Connect
            log.info(f"Connecting to {mac}...")
            child.sendline(f"connect {mac}")
            res = child.expect(["Connection successful", "Failed to connect", pexpect.TIMEOUT], timeout=15)
            
            child.sendline("quit")
            child.close()
            
            return res == 0
        except Exception as e:
            log.error(f"Connection error for {mac}: {e}")
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
        """Returns details about the currently connected audio device."""
        paired = self.get_paired_devices()
        for dev in paired:
            info = self.get_info(dev['mac'])
            if info['connected']:
                dev.update(info)
                return dev
        return None

