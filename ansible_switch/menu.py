#!/usr/bin/env python3
"""
menu.py — Ansible Switch Manager
Interactive CLI front-end for the ansible_switch project.
Runs on Python 3 (stdlib only — no pip installs needed).
"""

import os
import re
import sys
import subprocess
import platform
import ipaddress
import time
import threading
import msvcrt

from typing import Optional

# ──────────────────────────────────────────────────────────────────────────────
# SWITCH TOPOLOGY DEFINITION
# Order matters: H1 first, then pairs B/A per letter tier A→D
# ──────────────────────────────────────────────────────────────────────────────
SWITCHES = [
    {"name": "H1",   "tier": "MGMT", "group": "management", "default_ip": "127.0.0.1"},
    {"name": "A1-B", "tier": "A",    "group": "tier_a",     "default_ip": "10.0.1.2"},
    {"name": "A1-A", "tier": "A",    "group": "tier_a",     "default_ip": "10.0.1.3"},
    {"name": "B1-B", "tier": "B",    "group": "tier_b",     "default_ip": "10.0.2.2"},
    {"name": "B1-A", "tier": "B",    "group": "tier_b",     "default_ip": "10.0.2.3"},
    {"name": "C1-B", "tier": "C",    "group": "tier_c",     "default_ip": "10.0.3.2"},
    {"name": "C1-A", "tier": "C",    "group": "tier_c",     "default_ip": "10.0.3.3"},
    {"name": "D1-B", "tier": "D",    "group": "tier_d",     "default_ip": "10.0.4.2"},
    {"name": "D1-A", "tier": "D",    "group": "tier_d",     "default_ip": "10.0.4.3"},
]

SWITCH_NAMES = [s["name"] for s in SWITCHES]

# Path helpers — always relative to this script's directory
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
HOST_VARS_DIR = os.path.join(BASE_DIR, "host_vars")
PLAYBOOKS_DIR = os.path.join(BASE_DIR, "playbooks")


# ──────────────────────────────────────────────────────────────────────────────
# COLOUR HELPERS (work on Windows 10+ and all POSIX terminals)
# ──────────────────────────────────────────────────────────────────────────────
if platform.system() == "Windows":
    os.system("")   # enable ANSI escape codes on Windows console
    # Force UTF-8 output so box-drawing / Unicode chars don't crash on cp1252 terminals
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
MAGENTA= "\033[95m"
DIM    = "\033[2m"


def c(text, color):
    return f"{color}{text}{RESET}"


# ──────────────────────────────────────────────────────────────────────────────
# host_vars I/O
# ──────────────────────────────────────────────────────────────────────────────
def read_host_var(switch_name: str, key: str, default: str = "N/A") -> str:
    """Parse a single key from a switch's host_vars YAML file (no pyyaml needed)."""
    path = os.path.join(HOST_VARS_DIR, f"{switch_name}.yml")
    if not os.path.isfile(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(rf"^\s*{re.escape(key)}\s*:\s*['\"]?(.+?)['\"]?\s*$", line)
            if m:
                return m.group(1).strip()
    return default


def write_host_vars(switch_name: str, new_ip: str) -> None:
    """Overwrite the host_vars file for switch_name with the new IP (keep other fields)."""
    path = os.path.join(HOST_VARS_DIR, f"{switch_name}.yml")
    role = read_host_var(switch_name, "switch_role", "access")
    desc = read_host_var(switch_name, "switch_description", f"{switch_name} Switch")
    content = (
        "---\n"
        f'switch_ip: "{new_ip}"\n'
        f'switch_role: "{role}"\n'
        f'switch_description: "{desc}"\n'
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ──────────────────────────────────────────────────────────────────────────────
# DISPLAY HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def clear():
    os.system("cls" if platform.system() == "Windows" else "clear")


def print_banner():
    banner = r"""
  ╔══════════════════════════════════════════════════════════════╗
  ║          A N S I B L E   S W I T C H   M A N A G E R        ║
  ║                   Fool-Proof Network Tool                    ║
  ╚══════════════════════════════════════════════════════════════╝"""
    print(c(banner, CYAN + BOLD))
    print()


def print_topology():
    """Display the switch tree with current IPs read directly from host_vars."""
    print(c("  ┌─ TOPOLOGY ──────────────────────────────────────────────────┐", CYAN))
    prev_tier = None
    for idx, sw in enumerate(SWITCHES, start=1):
        ip   = read_host_var(sw["name"], "switch_ip", "—")
        role = read_host_var(sw["name"], "switch_role", "access")
        tier = sw["tier"]

        # Tier separator
        if tier != prev_tier:
            tier_label = f"  │  {'[ MGMT ]' if tier == 'MGMT' else f'[ Tier {tier} ]'}"
            print(c(tier_label, YELLOW))
            prev_tier = tier

        # Tree connector
        siblings = [s for s in SWITCHES if s["tier"] == tier]
        is_last  = siblings[-1]["name"] == sw["name"]
        connector = "  │    └──" if is_last else "  │    ├──"

        name_col = f"{sw['name']:<6}"
        ip_col   = f"IP: {ip:<15}"
        role_col = c(f"[{role}]", DIM)
        print(f"{c(connector, CYAN)} {c(name_col, BOLD)}  {c(ip_col, GREEN)}  {role_col}")

    print(c("  └────────────────────────────────────────────────────────────┘", CYAN))
    print()


def print_menu():
    options = [
        ("1", "Reset all IPs to defaults (refresh topology)"),
        ("2", "Assign IP to a switch"),
        ("3", "Ping a switch"),
        ("4", "Ping ALL switches"),
        ("5", "Run Ansible playbook manually"),
        ("6", "Live Network Discovery & Monitor"),
        ("0", "Exit"),
    ]
    print(c("  OPTIONS", MAGENTA + BOLD))
    for key, label in options:
        print(f"    {c(f'[{key}]', YELLOW)}  {label}")
    print()


# ──────────────────────────────────────────────────────────────────────────────
# NETWORK DISCOVERY UTILITIES
# ──────────────────────────────────────────────────────────────────────────────
def get_local_subnets():
    """Detect active local subnets using ipconfig (Windows)."""
    subnets = []
    try:
        output = subprocess.check_output(["ipconfig"], text=True, encoding="cp850")
        for line in output.splitlines():
            if "IPv4 Address" in line or "Dirección IPv4" in line:
                m = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                if m:
                    ip = m.group(1)
                    if not ip.startswith("127."):
                        # Assume /24 for simplicity in this dummy environment
                        parts = ip.split(".")
                        subnets.append(f"{parts[0]}.{parts[1]}.{parts[2]}.0/24")
    except Exception:
        pass
    return list(set(subnets))


def get_arp_table():
    """Parse the system ARP table."""
    devices = []
    try:
        output = subprocess.check_output(["arp", "-a"], text=True, encoding="cp850")
        # Regex for IP and MAC (Windows format)
        # 192.168.1.1           00-11-22-33-44-55     dynamic
        pattern = re.compile(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})")
        for line in output.splitlines():
            m = pattern.search(line)
            if m:
                ip, mac = m.group(1), m.group(2).replace("-", ":").upper()
                if not ip.startswith("224.") and not ip.startswith("239.") and ip != "255.255.255.255":
                    devices.append({"ip": ip, "mac": mac})
    except Exception:
        pass
    return devices


def background_ping_sweep(subnets):
    """Populate ARP table by pinging a few IPs in the background."""
    def sweep():
        for subnet in subnets:
            base = ".".join(subnet.split(".")[:-1])
            # Just ping .1, .2, .254 and a few others to keep it fast
            for i in [1, 2, 254]:
                target = f"{base}.{i}"
                if platform.system() == "Windows":
                    subprocess.run(["ping", "-n", "1", "-w", "100", target], 
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.run(["ping", "-c", "1", "-W", "1", target], 
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    t = threading.Thread(target=sweep, daemon=True)
    t.start()


# ──────────────────────────────────────────────────────────────────────────────
# INPUT HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def prompt(msg: str) -> str:
    try:
        return input(f"  {c('▶', CYAN)} {msg}: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return ""


def pick_switch(prompt_text: str = "Enter switch name (or number)") -> Optional[str]:
    """Show numbered list and let user pick by name or number."""
    print()
    for i, sw in enumerate(SWITCHES, 1):
        ip = read_host_var(sw["name"], "switch_ip", "—")
        print(f"    {c(str(i), YELLOW)}.  {sw['name']:<6}  {c(ip, GREEN)}")
    print()
    choice = prompt(prompt_text)
    if not choice:
        return None
    # Numeric selection
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(SWITCHES):
            return SWITCHES[idx]["name"]
        print(c("  ✗ Invalid number.", RED))
        return None
    # Name selection
    if choice in SWITCH_NAMES:
        return choice
    print(c(f"  ✗ '{choice}' is not a known switch.", RED))
    return None


def validate_ip(ip_str: str) -> bool:
    try:
        ipaddress.IPv4Address(ip_str)
        return True
    except ValueError:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# ACTIONS
# ──────────────────────────────────────────────────────────────────────────────
def action_reset_ips():
    """Restore every switch's IP to its factory default and rewrite host_vars."""
    print(c("\n  ── RESET IPs TO DEFAULTS ─────────────────────────────────────", CYAN))
    print()
    for sw in SWITCHES:
        default_ip = sw["default_ip"]
        write_host_vars(sw["name"], default_ip)
        print(f"    {c('✔', GREEN)}  {c(sw['name'], BOLD):<6}  → {c(default_ip, GREEN)}")
    print()
    print(c("  ✅  All IPs have been reset to their default values.", GREEN + BOLD))
    input("\n  Press ENTER to continue...")

def action_assign_ip():
    print(c("\n  ── ASSIGN IP ─────────────────────────────────────────────────", CYAN))
    target = pick_switch("Select switch")
    if not target:
        return

    while True:
        new_ip = prompt(f"New IP address for {c(target, BOLD)}")
        if not new_ip:
            print(c("  ✗ Cancelled.", RED))
            return
        if validate_ip(new_ip):
            break
        print(c(f"  ✗ '{new_ip}' is not a valid IPv4 address. Try again.", RED))

    write_host_vars(target, new_ip)
    print(c(f"\n  ✅  {target} → IP set to {new_ip}", GREEN + BOLD))
    print(c("      (host_vars file updated — Ansible will use this on next run)", DIM))
    input("\n  Press ENTER to continue...")


# ──────────────────────────────────────────────────────────────────────────────
# REAL PING — calls the OS ping command and streams live output
# ──────────────────────────────────────────────────────────────────────────────
def _real_ping(host: str, count: int = 4) -> bool:
    """
    Execute a real system ping against `host` and stream output to the console.
    Returns True if the ping succeeded (exit code 0), False otherwise.
    Works on Windows (ping -n) and Linux/macOS (ping -c).
    """
    is_windows = platform.system() == "Windows"
    # Build the ping command identical to what CMD / bash would run
    if is_windows:
        cmd = ["ping", "-n", str(count), host]
    else:
        cmd = ["ping", "-c", str(count), host]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        print(c("  ✗ 'ping' command not found on this system.", RED))
        return False

    # Stream output line by line in real time
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.rstrip()
        lower = line.lower()
        # Colour-code based on content
        if any(kw in lower for kw in ("reply from", "bytes from")):
            print(f"    {GREEN}{line}{RESET}")
        elif any(kw in lower for kw in ("request timed out", "destination host unreachable",
                                        "100% loss", "100% packet loss",
                                        "could not find host", "unknown host",
                                        "transmit failed")):
            print(f"    {RED}{line}{RESET}")
        elif any(kw in lower for kw in ("ping statistics", "packets:", "approximate",
                                        "minimum", "round-trip", "rtt", "packet loss")):
            print(f"    {DIM}{line}{RESET}")
        else:
            print(f"    {line}")

    proc.wait()
    return proc.returncode == 0


def action_ping(target_name: Optional[str] = None, ping_all: bool = False):
    """
    Perform a REAL ping to each switch's configured IP, or any custom host/IP.
    Uses the operating system's ping command — identical to running it in CMD.
    """
    if ping_all:
        # ── Ping ALL switches using their configured IPs ───────────────────────
        print(c("\n  ── PING ALL SWITCHES ─────────────────────────────────────────", CYAN))
        results = []
        for sw_name in SWITCH_NAMES:
            ip = read_host_var(sw_name, "switch_ip", "")
            if not ip or ip in ("", "N/A", "—"):
                print(c(f"\n  ⚠  {sw_name}: no IP configured — skipping.", YELLOW))
                results.append((sw_name, ip, None))
                continue

            print()
            print(c(f"  ── {sw_name} ({ip})", YELLOW + BOLD))
            print(c("  " + "─" * 58, DIM))
            ok = _real_ping(ip, count=2)          # 2 packets per host to keep it snappy
            if ok:
                print(c("  ✅  Reachable", GREEN + BOLD))
            else:
                print(c("  ✗   Unreachable", RED + BOLD))
            results.append((sw_name, ip, ok))

        # Summary table
        print()
        print(c("  ── SUMMARY ───────────────────────────────────────────────────", CYAN))
        for sw_name, ip, ok in results:
            if ok is None:
                status = c("NO IP", YELLOW)
            elif ok:
                status = c("UP   ✅", GREEN + BOLD)
            else:
                status = c("DOWN ✗", RED + BOLD)
            print(f"    {c(sw_name, BOLD):<14}  {c(ip or '—', DIM):<18}  {status}")

    else:
        # ── Single target ──────────────────────────────────────────────────────
        print(c("\n  ── PING ──────────────────────────────────────────────────────", CYAN))
        print()
        print(f"    {c('[1]', YELLOW)}  Ping a switch (uses its configured IP)")
        print(f"    {c('[2]', YELLOW)}  Ping any device / hostname / IP address")
        print()
        mode = prompt("Choose ping mode")

        if mode == "1":
            # Pick from topology
            sw_name = target_name or pick_switch("Select switch to ping")
            if not sw_name:
                return
            ip = read_host_var(sw_name, "switch_ip", "")
            if not ip or ip in ("", "N/A", "—"):
                print(c(f"\n  ⚠  {sw_name} has no IP configured. Assign one first.", YELLOW))
                input("\n  Press ENTER to continue...")
                return
            label = f"{sw_name} ({ip})"

        elif mode == "2":
            # Free-form host
            ip = prompt("Enter hostname or IP address to ping (e.g. 8.8.8.8 or google.com)")
            if not ip:
                return
            label = ip
            sw_name = None

        else:
            print(c("  ✗ Invalid choice.", RED))
            input("\n  Press ENTER to continue...")
            return

        count_str = prompt("How many ping packets? [default: 4]")
        count = int(count_str) if count_str.isdigit() and int(count_str) > 0 else 4

        print()
        print(c(f"  Pinging {label} with {count} packet(s) ...", YELLOW))
        print(c("  " + "─" * 58, DIM))

        ok = _real_ping(ip, count=count)

        print(c("  " + "─" * 58, DIM))
        if ok:
            print(c(f"  ✅  {label} is reachable.", GREEN + BOLD))
        else:
            print(c(f"  ✗   {label} is unreachable or did not respond.", RED + BOLD))

    input("\n  Press ENTER to continue...")


def action_run_playbook():
    print(c("\n  ── RUN PLAYBOOK ──────────────────────────────────────────────", CYAN))
    playbooks = [
        "show_topology.yml",
        "assign_ip.yml",
        "ping_check.yml",
    ]
    for i, pb in enumerate(playbooks, 1):
        print(f"    {c(str(i), YELLOW)}.  {pb}")
    print()
    choice = prompt("Select playbook (number)")
    if not choice or not choice.isdigit():
        return
    idx = int(choice) - 1
    if not (0 <= idx < len(playbooks)):
        print(c("  ✗ Invalid choice.", RED))
        return

    pb_path = os.path.join(PLAYBOOKS_DIR, playbooks[idx])
    extra   = prompt("Extra vars (leave blank for none, e.g. target=A1-B new_ip=10.0.0.5)")
    cmd     = ["ansible-playbook", pb_path]
    if extra:
        cmd += ["-e", extra]

    print(c(f"\n  Running: {' '.join(cmd)}\n", DIM))
    subprocess.run(cmd, cwd=BASE_DIR)
    input("\n  Press ENTER to continue...")


def action_live_monitor():
    """Live-refreshing view of connected devices."""
    subnets = get_local_subnets()
    background_ping_sweep(subnets)
    
    try:
        while True:
            clear()
            print_banner()
            print(c(f"  ── LIVE NETWORK MONITOR ({' , '.join(subnets)}) ───────────", CYAN + BOLD))
            print(c("  (Press Ctrl+C to return to main menu)", DIM))
            print()
            
            # Get current state
            arp_devices = get_arp_table()
            known_ips = {}
            for sw_name in SWITCH_NAMES:
                ip = read_host_var(sw_name, "switch_ip", "")
                if ip and ip not in ("", "N/A", "—"):
                    known_ips[ip] = sw_name
            
            # Table Header
            print(f"    {c('STATUS', BOLD):<12} {c('IP ADDRESS', BOLD):<18} {c('MAC ADDRESS', BOLD):<20} {c('ASSIGNED TO', BOLD)}")
            print(f"    {c('─' * 70, DIM)}")
            
            seen_ips = set()
            
            # Show known devices first
            for ip, name in known_ips.items():
                seen_ips.add(ip)
                # Check if it's in ARP
                in_arp = any(d["ip"] == ip for d in arp_devices)
                mac = next((d["mac"] for d in arp_devices if d["ip"] == ip), "??:??:??:??:??:??")
                
                status = c("ONLINE", GREEN) if in_arp else c("OFFLINE", RED)
                print(f"    {status:<21} {c(ip, BOLD):<18} {c(mac, DIM):<20} {c(name, YELLOW)}")

            # Show other discovered devices
            for dev in arp_devices:
                if dev["ip"] in seen_ips:
                    continue
                status = c("DISCOVERED", CYAN)
                print(f"    {status:<21} {c(dev['ip'], BOLD):<18} {c(dev['mac'], DIM):<20} {c('—', DIM)}")
            print()
            print(c("  Options: [A] Assign discovered IP to Switch  [R] Refresh now  [Q] Back", YELLOW))
            
            # Wait indefinitely for a keypress (blocking)
            choice = None
            while True:
                if msvcrt.kbhit():
                    choice = msvcrt.getch().decode("utf-8").lower()
                    break
                time.sleep(0.1)

            if choice == "q":
                return
            elif choice == "r":
                background_ping_sweep(subnets)
                continue
            elif choice == "a":
                # Assignment logic
                print()
                target_ip = prompt("Enter the DISCOVERED IP to assign")
                if not target_ip: continue
                
                # Verify it's in the list
                if not any(d["ip"] == target_ip for d in arp_devices):
                    print(c(f"  ✗ IP '{target_ip}' not found in discovery list.", RED))
                    time.sleep(1.5)
                    continue
                
                target_sw = pick_switch(f"Assign {target_ip} to which switch?")
                if target_sw:
                    write_host_vars(target_sw, target_ip)
                    print(c(f"\n  ✅  {target_sw} now assigned to {target_ip}", GREEN + BOLD))
                    time.sleep(2)
    except KeyboardInterrupt:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────────────────────────────────────
def main():
    while True:
        clear()
        print_banner()
        print_topology()
        print_menu()

        choice = prompt("Choose an option")

        if choice == "1":
            action_reset_ips()

        elif choice == "2":
            action_assign_ip()

        elif choice == "3":
            action_ping()

        elif choice == "4":
            action_ping(ping_all=True)

        elif choice == "5":
            action_run_playbook()

        elif choice == "6":
            action_live_monitor()

        elif choice == "0":
            clear()
            print(c("\n  👋  Goodbye!\n", CYAN + BOLD))
            sys.exit(0)

        else:
            print(c("  ✗ Invalid option. Press ENTER and try again.", RED))
            input()


if __name__ == "__main__":
    main()
