from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (
    CONFIG_DISPATCHER,
    MAIN_DISPATCHER,
    set_ev_cls
)
from ryu.ofproto import ofproto_v1_3

H1_MAC = "42:b5:72:d8:2f:7e"
H2_MAC = "62:36:11:ac:5c:0d"

ARP_ETH_TYPE = 0x0806


class RerouteController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.datapaths = {}
        self.primary_failed = False

    def add_flow(self, dp, priority, match, out_port):
        parser = dp.ofproto_parser
        ofproto = dp.ofproto

        actions = [parser.OFPActionOutput(out_port)]
        instructions = [
            parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS, actions
            )
        ]

        dp.send_msg(parser.OFPFlowMod(
            datapath=dp,
            priority=priority,
            match=match,
            instructions=instructions
        ))

    def install_routes(self):
        backup = self.primary_failed

        self.logger.info(
            "Installing %s path",
            "BACKUP" if backup else "PRIMARY"
        )

        for dp in self.datapaths.values():
            parser = dp.ofproto_parser
            ofproto = dp.ofproto
            dpid = dp.id

            # Remove old flows before installing current rules.
            dp.send_msg(parser.OFPFlowMod(
                datapath=dp,
                command=ofproto.OFPFC_DELETE,
                out_port=ofproto.OFPP_ANY,
                out_group=ofproto.OFPG_ANY,
                match=parser.OFPMatch()
            ))

            # NEW: Flood ARP packets so hosts can discover MAC addresses.
            self.add_flow(
                dp,
                200,
                parser.OFPMatch(eth_type=ARP_ETH_TYPE),
                ofproto.OFPP_FLOOD
            )

            # s1: connects h1, s2 and s3.
            if dpid == 1:
                next_hop = 3 if backup else 2

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(
                        in_port=1, eth_dst=H2_MAC
                    ),
                    next_hop
                )

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(
                        in_port=next_hop, eth_dst=H1_MAC
                    ),
                    1
                )

            # s2: primary path.
            elif dpid == 2 and not backup:
                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(
                        in_port=1, eth_dst=H2_MAC
                    ),
                    2
                )

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(
                        in_port=2, eth_dst=H1_MAC
                    ),
                    1
                )

            # s3: backup path.
            elif dpid == 3 and backup:
                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(
                        in_port=1, eth_dst=H2_MAC
                    ),
                    2
                )

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(
                        in_port=2, eth_dst=H1_MAC
                    ),
                    1
                )

            # s4: connects h2, s2 and s3.
            elif dpid == 4:
                path_port = 3 if backup else 2

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(
                        in_port=path_port, eth_dst=H2_MAC
                    ),
                    1
                )

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(
                        in_port=1, eth_dst=H1_MAC
                    ),
                    path_port
                )

    @set_ev_cls(
        ofp_event.EventOFPSwitchFeatures,
        CONFIG_DISPATCHER
    )
    def switch_features(self, ev):
        dp = ev.msg.datapath
        self.datapaths[dp.id] = dp
        self.install_routes()

    @set_ev_cls(
        ofp_event.EventOFPPortStatus,
        MAIN_DISPATCHER
    )
    def port_status(self, ev):
        msg = ev.msg
        dp = msg.datapath

        primary_ports = {
            (1, 2), (2, 1), (2, 2), (4, 2)
        }

        key = (dp.id, msg.desc.port_no)

        if key not in primary_ports:
            return

        if msg.desc.state & dp.ofproto.OFPPS_LINK_DOWN:
            if not self.primary_failed:
                self.primary_failed = True
                self.install_routes()
        else:
            if self.primary_failed:
                self.primary_failed = False
                self.install_routes()
