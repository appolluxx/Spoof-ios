# iOS GPS Location Simulation Tool (spoof.py)

This tool allows you to lock an iOS device's reported GPS coordinates to a static location via Apple's native developer simulation service. No jailbreak, macOS, or Xcode is required.

## Prerequisites

### Host OS (Kali Linux)
1. **Python 3.10+**
2. **usbmuxd**: Required for USB communication.
   ```bash
   sudo apt install usbmuxd
   ```
3. **Avahi Daemon**: Required for Wi-Fi discovery (`--network` mode).
   ```bash
   sudo apt install avahi-daemon
   sudo systemctl enable --now avahi-daemon
   ```

### iOS Device
1. **Developer Mode**: Must be enabled in **Settings > Privacy & Security > Developer Mode**. (Requires a reboot).
2. **Trust Handshake**: The device must trust the host computer. For Wi-Fi mode, the device must have been USB-paired with the host at least once.

## Installation

1. Install the required Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Basic USB Simulation
Note: On Linux, simulating location on **iOS 17+** may require `sudo` to establish the QUIC tunnel.
```bash
sudo python3 spoof.py --lat 13.7563 --lon 100.5018
```

### Wi-Fi Simulation
Requires Avahi and a prior USB pairing.
```bash
python spoof.py --lat 35.6762 --lon 139.6503 --network
```

### Targeted Device Simulation
Required if multiple devices are connected.
```bash
python spoof.py --lat 40.7128 --lon -74.0060 --udid abc123def456
```

### Auto-Stop Simulation
```bash
python spoof.py --lat 51.5074 --lon -0.1278 --duration 300
```

## CLI Arguments

| Argument | Description |
| --- | --- |
| `--lat` | **Required**. Latitude in decimal degrees (-90.0 to 90.0). |
| `--lon` | **Required**. Longitude in decimal degrees (-180.0 to 180.0). |
| `--network` | Connect over Wi-Fi instead of USB. |
| `--udid` | Target a specific device by UDID. |
| `--duration` | Auto-stop after N seconds. |

## Program Flow
1. **Validation**: Checks latitude and longitude ranges.
2. **Discovery**: Scans for USB or Network devices via usbmuxd/mDNS.
3. **Pairing**: Establishes a secure connection. Prompts for "Trust" if needed.
4. **Protocol Detection**: Automatically switches between Lockdown (iOS < 17) and RSD/DVT (iOS 17+).
5. **DDI Mounting**: Automatically mounts the Developer Disk Image.
6. **Simulation**: Injects coordinates and maintains a keep-alive heartbeat.
7. **Teardown**: On exit (Ctrl+C or duration), sends a STOP command to restore real GPS.

## Troubleshooting

- **[ERR] No USB device found**: Ensure the cable is connected and Developer Mode is ON.
- **[ERR] No network device found**: Ensure both devices are on the same Wi-Fi and `avahi-daemon` is running.
- **[ERR] Device not trusted**: Unlock the iPhone and tap "Trust" on the popup.
- **[ERR] Failed to setup RSD/DDI**: iOS 17+ requires an internet connection on the host to download and verify the Developer Disk Image.

## Compatibility
- **iOS 15 / 16**: Fully supported via Lockdown.
- **iOS 17**: Fully supported via RSD/DVT over QUIC tunnel.
- **iOS 18+**: Untested.
