#!/usr/bin/env python3
"""Run and instrument the dual-path Mininet UDP recovery experiment.

Run with sudo: sudo python3 experiments.py --controller-ip <RYU_IP>
Use --help for options. This is a small orchestration harness; the sender,
receiver, and Ryu failover behavior are supplied by the other project members.
"""

from __future__ import annotations

import argparse
import csv
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.log import setLogLevel, info

from network_config import add_controller_arguments, assert_controller_reachable, configure_hosts
from topology import DualPathTopo


HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    add_controller_arguments(p)
    p.add_argument("--loss", type=float, default=0.0,
                   help="Configured random packet loss percentage on primary S2-S4 link")
    p.add_argument("--delay", default="0ms", help="tc netem delay on primary S2-S4 link")
    p.add_argument("--duration", type=float, default=30,
                   help="Seconds to keep the experiment running")
    p.add_argument("--sender-command", default="",
                   help="Command to run on h1; quote the full command")
    p.add_argument("--receiver-command", default="",
                   help="Command to run on h2; quote the full command")
    p.add_argument("--output", default="", help="CSV path (default: results/run-<UTC>.csv)")
    p.add_argument("--skip-controller-check", action="store_true",
                   help="Skip TCP reachability check (use only if Ryu starts after this script)")
    return p.parse_args()


def tc_netem(node, iface: str, loss: float, delay: str) -> None:
    if not (0 <= loss < 100):
        raise ValueError("--loss must be between 0 (inclusive) and 100 (exclusive)")
    args = ["tc", "qdisc", "replace", "dev", iface, "root", "netem"]
    if loss:
        args += ["loss", f"{loss:g}%"]
    if delay != "0ms":
        args += ["delay", delay]
    if len(args) > 7 and node.cmd(" ".join(args) + " 2>&1").strip():
        raise RuntimeError(f"tc failed on {node.name}:{iface}: {node.cmd(' '.join(args))}")


def start_command(host, command: str):
    if not command:
        return None
    # Mininet host commands are executed in the host namespace. Keep output in
    # the run directory so the application logs can be correlated with CSV.
    log_path = RESULTS / f"{host.name}-application.log"
    return host.popen(command, shell=True, stdout=open(log_path, "w"),
                      stderr=subprocess.STDOUT, start_new_session=True)

def create_management_link(h1):
    """Connect H1 to the Ubuntu host for Ryu REST communication."""

    subprocess.run(
        ["ip", "link", "add", "veth-ryu", "type", "veth",
         "peer", "name", "veth-h1"],
        check=True
    )

    subprocess.run(
        ["ip", "addr", "add", "192.168.100.1/30",
         "dev", "veth-ryu"],
        check=True
    )

    subprocess.run(
        ["ip", "link", "set", "veth-ryu", "up"],
        check=True
    )

    subprocess.run(
        ["ip", "link", "set", "veth-h1",
         "netns", str(h1.pid)],
        check=True
    )

    h1.cmd("ip addr add 192.168.100.2/30 dev veth-h1")
    h1.cmd("ip link set veth-h1 up")

    info("*** H1 management connection established\\n")

def main():
    args = parse_args()
    if not args.skip_controller_check:
        assert_controller_reachable(None, args.controller_ip, args.controller_port)
    out = Path(args.output) if args.output else RESULTS / (
        "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".csv")
    out.parent.mkdir(parents=True, exist_ok=True)

    net = Mininet(topo=DualPathTopo(), link=TCLink, controller=None, autoSetMacs=False,
                  autoStaticArp=False, build=True)
    net.addController("ryu", controller=RemoteController, ip=args.controller_ip,
                      port=args.controller_port, protocols="OpenFlow13")
    procs = []
    try:
        info("*** Starting network\n")
        net.start()
        configure_hosts(net)
        create_management_link(net.get("h1"))
        # Apply impairment to both ends of the primary S2-S4 link.
        tc_netem(net.get("s2"), "s2-eth2", args.loss, args.delay)
        tc_netem(net.get("s4"), "s4-eth2", args.loss, args.delay)
        info("*** Waiting for controller flows; confirm both routes are installed\n")
        time.sleep(2)
        procs.append(start_command(net.get("h2"), args.receiver_command))
        time.sleep(0.5)
        procs.append(start_command(net.get("h1"), args.sender_command))
        start = time.monotonic()
        deadline = start + max(0.1, args.duration)
        with out.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["utc_timestamp", "elapsed_s", "event", "configured_loss_pct",
                             "delay", "notes"])
            writer.writerow([datetime.now(timezone.utc).isoformat(), 0, "experiment_start",
                             args.loss, args.delay, "Application-specific metrics belong in app logs"])
            f.flush()
            while time.monotonic() < deadline:
                time.sleep(min(1, deadline - time.monotonic()))
            writer.writerow([datetime.now(timezone.utc).isoformat(), round(time.monotonic()-start, 6),
                             "experiment_end", args.loss, args.delay,
                             "Join sequence/ACK/retransmission metrics from UDP application logs"])
        print(f"CSV metadata written to {out}")
    finally:
        for proc in procs:
            if proc and proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
        net.stop()
        subprocess.run(
            ["ip", "link", "delete", "veth-ryu"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )


if __name__ == "__main__":
    setLogLevel("info")
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
