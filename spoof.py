    #!/usr/bin/env python3
import argparse
import asyncio
import signal
import sys
import time
from datetime import datetime
from typing import Optional, Union

from pymobiledevice3.exceptions import (
    ConnectionFailedError,
    NotPairedError,
    PairingError,
)
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.mobile_image_mounter import auto_mount
from pymobiledevice3.services.simulate_location import DtSimulateLocation
from pymobiledevice3.usbmux import list_devices

# Try to import iOS 17+ specific services
try:
    from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
    from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
    from pymobiledevice3.services.lockdown_tunnel import LockdownTunnelService
    HAS_RSD = True
except ImportError:
    HAS_RSD = False

# Constants
HEARTBEAT_INTERVAL = 10
RETRY_GAP = 5
MAX_RETRY_ATTEMPTS = 3

def log(prefix, message):
    print(f"[{prefix}]  {message}")

def validate_coords(lat: float, lon: float):
    if not (-90.0 <= lat <= 90.0):
        log("ERR", f"Invalid latitude: {lat}. Must be between -90 and 90.")
        sys.exit(2)
    if not (-180.0 <= lon <= 180.0):
        log("ERR", f"Invalid longitude: {lon}. Must be between -180 and 180.")
        sys.exit(2)

class GPSSpoofer:
    def __init__(self, lat: float, lon: float, udid: Optional[str] = None, network: bool = False, duration: Optional[int] = None):
        self.lat = lat
        self.lon = lon
        self.udid = udid
        self.network = network
        self.duration = duration
        self.start_time = None
        self.device = None
        self.lockdown = None
        self.rsd = None
        self.location_service = None
        self.is_ios17_plus = False
        self.running = True

    async def discover_device(self):
        log("INFO", f"Scanning for {'network' if self.network else 'USB'} devices...")
        
        devices = await list_devices()
        if self.network:
            # Filter for network devices
            devices = [d for d in devices if d.connection_type == 'Network']
        else:
            # Filter for USB devices
            devices = [d for d in devices if d.connection_type == 'USB']

        if self.udid:
            devices = [d for d in devices if d.serial == self.udid]

        if not devices:
            if self.network:
                log("ERR", "No network device found. Check same Wi-Fi + Avahi (systemctl status avahi-daemon).")
            else:
                log("ERR", "No USB device found. Check cable + Developer Mode (Settings > Privacy & Security).")
            sys.exit(1)

        if len(devices) > 1 and not self.udid:
            log("ERR", "Multiple devices detected. Please specify --udid:")
            for d in devices:
                print(f"  - {d.serial} ({d.connection_type})")
            sys.exit(1)

        self.device = devices[0]
        log("INFO", f"Device found: {self.device.serial} ({self.device.connection_type})")

    async def perform_pairing(self):
        attempts = 0
        while attempts < MAX_RETRY_ATTEMPTS:
            try:
                self.lockdown = await create_using_usbmux(serial=self.device.serial)
                log("INFO", "Pairing record loaded.")
                return
            except (NotPairedError, PairingError):
                log("WARN", "Device not trusted. Please unlock device and tap 'Trust'.")
                attempts += 1
                if attempts < MAX_RETRY_ATTEMPTS:
                    log("INFO", f"Retrying in {RETRY_GAP}s (Attempt {attempts}/{MAX_RETRY_ATTEMPTS})...")
                    await asyncio.sleep(RETRY_GAP)
                else:
                    log("ERR", "Failed to pair after multiple attempts.")
                    sys.exit(1)
            except Exception as e:
                log("ERR", f"Connection failed: {e}")
                sys.exit(1)

    async def setup_protocol(self):
        version = self.lockdown.product_version
        log("INFO", f"iOS Version: {version}")
        
        major_version = int(version.split('.')[0])
        self.is_ios17_plus = major_version >= 17

        if self.is_ios17_plus:
            log("INFO", "Protocol: RSD (iOS 17+)")
            if not HAS_RSD:
                log("ERR", "pymobiledevice3 RSD support missing. Please update the library.")
                sys.exit(1)
            
            try:
                # Mount DDI first (required for DVT services)
                log("INFO", "Mounting DDI (iOS 17+)...")
                await auto_mount(self.lockdown)
                log("INFO", "DDI mounted successfully.")

                # Start RSD Tunnel
                tunnel_service = LockdownTunnelService(self.lockdown)
                # Note: start_tunnel is an async context manager in recent versions
                self.rsd_ctx = tunnel_service.start_tunnel()
                self.rsd = await self.rsd_ctx.__aenter__()
                log("INFO", "RSD Tunnel established.")
            except Exception as e:
                log("ERR", f"Failed to setup RSD/DDI: {e}")
                log("INFO", "Tip: iOS 17+ DDI mounting requires an internet connection.")
                sys.exit(1)
        else:
            log("INFO", "Protocol: Lockdown (iOS < 17)")
            try:
                log("INFO", "Mounting DDI...")
                await auto_mount(self.lockdown)
                log("INFO", "DDI mounted successfully.")
            except Exception as e:
                log("ERR", f"Failed to mount DDI: {e}")
                sys.exit(1)

    async def start_simulation(self):
        try:
            if self.is_ios17_plus:
                # Use LocationSimulation (Instruments)
                self.location_service = LocationSimulation(self.rsd)
                await self.location_service.set(self.lat, self.lon)
            else:
                # Use Lockdown Service
                self.location_service = DtSimulateLocation(self.lockdown)
                await self.location_service.set(self.lat, self.lon)
            
            log("INFO", f"Simulation started: lat={self.lat}, lon={self.lon}")
        except Exception as e:
            log("ERR", f"Failed to start simulation: {e}")
            sys.exit(1)

    async def stop_simulation(self):
        if not self.location_service:
            return

        log("STOP", "Releasing simulation...")
        try:
            if self.is_ios17_plus:
                await self.location_service.clear()
            else:
                await self.location_service.clear()
            
            log("OK", "Simulation stopped. Device GPS restored.")
        except asyncio.TimeoutError:
            log("WARN", "Stop command sent but no ACK. GPS may still be simulated. Reconnect and retry.")
        except Exception as e:
            log("WARN", f"Error during teardown: {e}")
        finally:
            if self.is_ios17_plus and hasattr(self, 'rsd_ctx'):
                await self.rsd_ctx.__aexit__(None, None, None)

    async def run(self):
        await self.discover_device()
        await self.perform_pairing()
        await self.setup_protocol()
        await self.start_simulation()

        self.start_time = datetime.now()
        log("HOLD", "Holding... press Ctrl+C to stop.")

        try:
            while self.running:
                elapsed = datetime.now() - self.start_time
                elapsed_str = str(elapsed).split('.')[0].zfill(8)
                log("BEAT", f"Session alive -- {elapsed_str}")
                
                if self.duration and elapsed.total_seconds() >= self.duration:
                    log("INFO", "Duration reached.")
                    break
                
                await asyncio.sleep(HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            log("STOP", "Ctrl+C received.")
        finally:
            await self.stop_simulation()

def main():
    parser = argparse.ArgumentParser(description="iOS GPS Location Simulation Tool")
    parser.add_argument("--lat", type=float, required=True, help="Latitude (-90.0 to 90.0)")
    parser.add_argument("--lon", type=float, required=True, help="Longitude (-180.0 to 180.0)")
    parser.add_argument("--network", action="store_true", help="Connect over Wi-Fi instead of USB")
    parser.add_argument("--udid", type=str, help="Target a specific device by UDID")
    parser.add_argument("--duration", type=int, help="Auto-stop after N seconds")

    args = parser.parse_args()

    validate_coords(args.lat, args.lon)

    spoofer = GPSSpoofer(
        lat=args.lat,
        lon=args.lon,
        udid=args.udid,
        network=args.network,
        duration=args.duration
    )

    loop = asyncio.get_event_loop()
    
    # Handle Ctrl+C
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(spoofer)))

    try:
        loop.run_until_complete(spoofer.run())
    except Exception as e:
        log("ERR", f"Fatal error: {e}")
        sys.exit(1)
    finally:
        loop.close()

async def shutdown(spoofer):
    spoofer.running = False
    # The loop will finish the current sleep and then exit the while loop

if __name__ == "__main__":
    main()
