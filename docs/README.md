# Horus OpenWrt Controller

## Overview
The Horus Controller is a centralized management system designed to run on OpenWrt routers. It acts as the "Brain" of the network, automatically discovering, provisioning, and monitoring satellite access points (Clients) using a custom Layer 2 protocol (HMP).

## Key Features
- **Zero-Touch Provisioning**: Auto-discovers Horus APs on the local Layer 2 broadcast domain without requiring DHCP or IP configurations.
- **Layer 2 HMP**: Uses raw ethernet sockets (EtherType `0x88B5`) to bypass IP routing complexities and ensure robust local network discovery.
- **Centralized Wi-Fi Management**: Pushes SSID, Password, and Radio configurations to all adopted APs simultaneously.
- **Real-time Telemetry**: Monitors the uptime, connected clients, and firmware versions of all network nodes.
- **LuCI Web Interface**: Fully integrated into the native OpenWrt LuCI dashboard for easy user interaction.

## Documentation Index
Please refer to the following documents for deep dives into specific topics:
1. [Architecture & Golden Rules](architecture.md) - The core philosophy, Layer 2 vs Layer 3 rules, and protocol design.
2. [File Structure](FILE_STRUCTURE.md) - Where everything is located within the IPK package.
3. [API & Protocols](API_AND_PROTOCOLS.md) - Packet structures and HMP JSON payloads (the real, implemented wire format).
4. [Troubleshooting](TROUBLESHOOTING.md) - How to debug common issues.
5. [UI Design System](UI_DESIGN_SYSTEM.md) - The shared frontend design system (colors, components).
6. [Changelog](CHANGELOG.md) - What was found and fixed in the latest repair/redesign session.
7. **[AI Agent Rules](AI_AGENT_RULES.md) - Read this before making any change. Documents real incidents where a well-intentioned edit broke a deployed device.**
