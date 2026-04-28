# Ansible Switch Manager — Implementation Plan

## Overview

A fully self-contained Ansible project for managing a network of dummy switches.
The topology is:

```
H1 (management)
 ├── A1-B
 ├── A1-A
 ├── B1-B
 ├── B1-A
 ├── C1-B
 ├── C1-A
 ├── D1-B
 └── D1-A
```

A Python-based interactive CLI (`menu.py`) acts as the "fool-proof" front-end:
it shows the topology, lets the user assign IPs to any switch, and runs ping checks.
Ansible playbooks do the actual "configuration" work under the hood.

---

## Project Structure

```
ansible_switch/
├── inventory/
│   └── hosts.ini              # All switches + their current IPs
├── group_vars/
│   └── all.yml                # Global vars (ansible_connection=local, etc.)
├── host_vars/                 # Per-switch IP overrides (written by menu.py)
│   ├── H1.yml
│   ├── A1-B.yml
│   └── ...
├── playbooks/
│   ├── show_topology.yml      # Pretty-prints the switch tree
│   ├── assign_ip.yml          # Assigns a dummy IP to a chosen switch
│   └── ping_check.yml         # Pings a switch (or all) and reports
├── roles/
│   └── switch_common/         # Reusable role: validate IP, apply config
│       ├── tasks/main.yml
│       └── defaults/main.yml
├── menu.py                    # Interactive Python CLI (main entry point)
├── ansible.cfg                # Project-level Ansible settings
└── README.md
```

---

## Proposed Changes

### [NEW] `inventory/hosts.ini`
Defines all 9 switches in groups (`management`, `tier_a`, `tier_b`, `tier_c`, `tier_d`).
Each starts with `ansible_host=127.0.0.1` as a safe dummy default.

### [NEW] `group_vars/all.yml`
Sets `ansible_connection: local` and `ansible_python_interpreter` so no real SSH is needed.

### [NEW] `host_vars/<switch>.yml` (one per switch)
Holds the current dummy IP for each device. Overwritten by `assign_ip.yml`.

### [NEW] `playbooks/show_topology.yml`
Uses `debug` tasks to print the full switch tree with current IPs.

### [NEW] `playbooks/assign_ip.yml`
Accepts `--extra-vars "target=A1-B new_ip=10.0.0.5"`.
Validates the IP format, writes it to `host_vars/<target>.yml`, then prints a confirmation.

### [NEW] `playbooks/ping_check.yml`
Accepts `--extra-vars "target=A1-B"` (or `target=all`).
Uses `ansible.builtin.ping` + optionally a shell `ping -n 1 <ip>` to simulate cmd-style output.

### [NEW] `roles/switch_common/`
Reusable logic: IP format validation, dummy interface "up" message.

### [NEW] `menu.py`
Python 3 interactive CLI. Requires no extra libraries (stdlib only).
Menu options:
  1. Show topology (calls `show_topology.yml`)
  2. Assign IP to a switch (calls `assign_ip.yml`)
  3. Ping a switch / all switches (calls `ping_check.yml`)
  4. Exit

---

## Verification Plan

- Run `python menu.py` → all menu options visible, no crashes
- Assign IP `192.168.1.10` to `A1-B` → `host_vars/A1-B.yml` updated
- Run topology → A1-B shows new IP
- Run ping check → output matches cmd-style ping result
- Invalid IP entry → error message shown, no crash
