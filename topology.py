#!/usr/bin/env python3

from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel


class TwoPathTopo(Topo):
    def build(self):
        # Add switches
        s1 = self.addSwitch("s1")
        s2 = self.addSwitch("s2")
        s3 = self.addSwitch("s3")
        s4 = self.addSwitch("s4")

        # Add hosts
        h1 = self.addHost("h1", ip="10.0.0.1/24", mac="42:b5:72:d8:2f:7e")
        h2 = self.addHost("h2", ip="10.0.0.2/24", mac="62:36:11:ac:5c:0d")

        # Connect hosts
        self.addLink(h1, s1)
        self.addLink(s4, h2)

        # Primary path
        self.addLink(s1, s2)
        self.addLink(s2, s4)

        # Backup path
        self.addLink(s1, s3)
        self.addLink(s3, s4)


def run():
    topo = TwoPathTopo()

    net = Mininet(
        topo=topo,
        controller=None,
        switch=OVSSwitch
    )

    net.addController(
        "c0",
        controller=RemoteController,
        ip="127.0.0.1",
        port=6653
    )

    net.start()

    print("\nTwo-path topology started.")
    print("Primary path: s1 -> s2 -> s4")
    print("Backup path:  s1 -> s3 -> s4")
    print("\nRun 'pingall' to test connectivity.")
    print("Run 'exit' to stop the topology.\n")

    CLI(net)
    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    run()
