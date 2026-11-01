#!/usr/bin/env python3

from mininet.topo import Topo


class DualPathTopo(Topo):
    def build(self, **_opts):

        h1 = self.addHost(
            "h1", ip="10.0.0.1/24",
            mac="42:b5:72:d8:2f:7e"
        )

        h2 = self.addHost(
            "h2", ip="10.0.0.2/24",
            mac="62:36:11:ac:5c:0d"
        )

        s1 = self.addSwitch("s1", dpid="0000000000000001",
                            protocols="OpenFlow13")
        s2 = self.addSwitch("s2", dpid="0000000000000002",
                            protocols="OpenFlow13")
        s3 = self.addSwitch("s3", dpid="0000000000000003",
                            protocols="OpenFlow13")
        s4 = self.addSwitch("s4", dpid="0000000000000004",
                            protocols="OpenFlow13")

        # Host connections
        self.addLink(h1, s1, port1=0, port2=1)
        self.addLink(s4, h2, port1=1, port2=0)

        # Primary path
        self.addLink(s1, s2, port1=2, port2=1)
        self.addLink(s2, s4, port1=2, port2=2)

        # Backup path
        self.addLink(s1, s3, port1=3, port2=1)
        self.addLink(s3, s4, port1=2, port2=3)


topos = {"dualpath": lambda: DualPathTopo()}
