#!/usr/bin/env python3
"""Run and instrument the dual-path Mininet UDP recovery experiment."""

from __future__ import annotations

import argparse
import csv
import signal
import subprocess
import sys
import time

from datetime import datetime, timezone
from pathlib import Path

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.log import setLogLevel, info

from network_config import (
    add_controller_arguments,
    assert_controller_reachable,
    configure_hosts
)

from topology import DualPathTopo


HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)

    add_controller_arguments(p)

    p.add_argument(
        "--loss",
        type=float,
        default=0.0,
        help="Packet loss percentage on primary S2-S4 link"
    )

    p.add_argument(
        "--delay",
        default="0ms",
        help="Network delay"
    )

    p.add_argument(
        "--duration",
        type=float,
        default=30,
        help="Duration of UDP experiment in seconds"
    )

    p.add_argument(
        "--sender-command",
        default="",
        help="Command to run on h1"
    )

    p.add_argument(
        "--receiver-command",
        default="",
        help="Command to run on h2"
    )

    p.add_argument(
        "--output",
        default="",
        help="CSV output path"
    )

    p.add_argument(
        "--skip-controller-check",
        action="store_true"
    )

    return p.parse_args()


def tc_netem(node, iface: str, loss: float, delay: str):

    if not (0 <= loss < 100):
        raise ValueError("--loss must be between 0 and 100")

    args = [
        "tc", "qdisc", "replace",
        "dev", iface,
        "root", "netem"
    ]

    if loss:
        args += ["loss", f"{loss:g}%"]

    if delay != "0ms":
        args += ["delay", delay]

    result = node.cmd(" ".join(args) + " 2>&1")

    if result.strip():
        raise RuntimeError(
            f"tc failed on {node.name}:{iface}: {result}"
        )


def start_command(host, command: str):

    if not command:
        return None

    log_path = RESULTS / f"{host.name}-application.log"

    log_file = open(log_path, "w")

    proc = host.popen(
        command,
        shell=True,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True
    )

    log_file.close()

    return proc


def create_management_link(h1):

    """Connect H1 to Ubuntu host for Ryu REST communication."""

    subprocess.run(
        [
            "ip", "link", "add",
            "veth-ryu", "type", "veth",
            "peer", "name", "veth-h1"
        ],
        check=True
    )

    subprocess.run(
        [
            "ip", "addr", "add",
            "192.168.100.1/30",
            "dev", "veth-ryu"
        ],
        check=True
    )

    subprocess.run(
        ["ip", "link", "set", "veth-ryu", "up"],
        check=True
    )

    subprocess.run(
        [
            "ip", "link", "set",
            "veth-h1", "netns", str(h1.pid)
        ],
        check=True
    )

    h1.cmd("ip addr add 192.168.100.2/30 dev veth-h1")
    h1.cmd("ip link set veth-h1 up")

    info("*** H1 management connection established\n")


def main():

    args = parse_args()

    # Prepare CSV output path before starting the experiment.
    out = (
        Path(args.output)
        if args.output
        else RESULTS / (
            "run-" +
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + ".csv"
        )
    )

    out.parent.mkdir(parents=True, exist_ok=True)

    if not args.skip_controller_check:
        assert_controller_reachable(
            None,
            args.controller_ip,
            args.controller_port
        )

    # Create Mininet network.
    net = Mininet(
        topo=DualPathTopo(),
        link=TCLink,
        controller=None,
        autoSetMacs=False,
        autoStaticArp=False,
        build=True
    )

    net.addController(
        "ryu",
        controller=RemoteController,
        ip=args.controller_ip,
        port=args.controller_port,
        protocols="OpenFlow13"
    )

    procs = []

    try:

        info("*** Starting network\n")

        net.start()

        configure_hosts(net)

        create_management_link(net.get("h1"))

        # Apply packet loss and delay to both ends of primary link.
        tc_netem(
            net.get("s2"),
            "s2-eth2",
            args.loss,
            args.delay
        )

        tc_netem(
            net.get("s4"),
            "s4-eth2",
            args.loss,
            args.delay
        )

        info("*** Waiting for controller flows\n")

        time.sleep(2)

        # Start receiver first.
        receiver = start_command(
            net.get("h2"),
            args.receiver_command
        )

        if receiver:
            procs.append(receiver)

        time.sleep(0.5)

        # Start sender.
        sender = start_command(
            net.get("h1"),
            args.sender_command
        )

        if sender:
            procs.append(sender)

        # Run UDP experiment for configured duration.
        start = time.monotonic()

        deadline = start + max(0.1, args.duration)

        with out.open("w", newline="") as f:

            writer = csv.writer(f)

            writer.writerow([
                "utc_timestamp",
                "elapsed_s",
                "event",
                "configured_loss_pct",
                "delay",
                "notes"
            ])

            writer.writerow([
                datetime.now(timezone.utc).isoformat(),
                0,
                "experiment_start",
                args.loss,
                args.delay,
                "Application metrics available in application logs"
            ])

            f.flush()

            while time.monotonic() < deadline:
                time.sleep(
                    min(1, deadline - time.monotonic())
                )

            writer.writerow([
                datetime.now(timezone.utc).isoformat(),
                round(time.monotonic() - start, 6),
                "experiment_end",
                args.loss,
                args.delay,
                "UDP experiment completed"
            ])

        print(f"\nCSV metadata written to {out}")

        # IMPORTANT:
        # Keep Mininet running and open its interactive CLI.
        # Cleanup happens only after the user types exit.

        info("\n*** UDP experiment completed\n")
        info("*** Mininet is still running\n")
        info("*** Enter Mininet commands or type exit to stop\n\n")

        CLI(net)

    finally:

        info("\n*** Cleaning up experiment\n")

        # Stop application processes.
        for proc in procs:

            if proc and proc.poll() is None:

                proc.send_signal(signal.SIGINT)

                try:
                    proc.wait(timeout=2)

                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

        # Stop Mininet.
        net.stop()

        # Remove management interface.
        subprocess.run(
            ["ip", "link", "delete", "veth-ryu"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        info("*** Cleanup completed\n")


if __name__ == "__main__":

    setLogLevel("info")

    try:
        main()

    except (RuntimeError, ValueError) as exc:

        print(
            f"ERROR: {exc}",
            file=sys.stderr
        )

        sys.exit(2)
