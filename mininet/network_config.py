#!/usr/bin/env python3
"""Shared network settings and helpers for the Mininet experiment scripts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkConfig:
    controller_ip: str = "127.0.0.1"
    controller_port: int = 6653
    openflow_version: str = "OpenFlow13"
    sender_ip: str = "10.0.0.1"
    receiver_ip: str = "10.0.0.2"
    udp_port: int = 5001


DEFAULT = NetworkConfig()


def add_controller_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--controller-ip", default=DEFAULT.controller_ip,
                        help="Reachable IP address of the remote Ryu controller")
    parser.add_argument("--controller-port", type=int, default=DEFAULT.controller_port,
                        help="Ryu OpenFlow TCP port (usually 6653)")


def configure_hosts(net) -> None:
    """Set deterministic host addresses and ARP entries after startup."""
    h1, h2 = net.get("h1"), net.get("h2")
    h1.setIP(DEFAULT.sender_ip + "/24")
    h2.setIP(DEFAULT.receiver_ip + "/24")
    h1.setARP(DEFAULT.receiver_ip, h2.MAC())
    h2.setARP(DEFAULT.sender_ip, h1.MAC())


def assert_controller_reachable(net, ip: str, port: int) -> None:
    """Fail early with a useful message if the controller endpoint is absent."""
    import socket

    try:
        with socket.create_connection((ip, port), timeout=2):
            pass
    except OSError as exc:
        raise RuntimeError(
            f"Cannot reach Ryu at {ip}:{port}. Start Ryu and check host/firewall routing."
        ) from exc
