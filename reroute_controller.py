import json

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (
    CONFIG_DISPATCHER,
    MAIN_DISPATCHER,
    set_ev_cls
)
from ryu.ofproto import ofproto_v1_3
from ryu.app.wsgi import WSGIApplication, ControllerBase, route
from webob import Response


H1_MAC = "42:b5:72:d8:2f:7e"
H2_MAC = "62:36:11:ac:5c:0d"

ARP_ETH_TYPE = 0x0806
LOSS_THRESHOLD = 0.05

REST_INSTANCE = "reroute_controller"


class RerouteRestController(ControllerBase):

    def __init__(self, req, link, data, **config):
        super().__init__(req, link, data, **config)
        self.sdn_app = data[REST_INSTANCE]

    @route("reroute", "/sdn/reroute", methods=["POST"])
    def trigger_reroute(self, req, **kwargs):

        try:
            body = json.loads(req.body.decode("utf-8"))
            loss_rate = float(body.get("loss_rate", 0))

            if not 0 <= loss_rate <= 1:
                raise ValueError("loss_rate must be between 0 and 1")

            self.sdn_app.logger.info(
                "Application reported packet loss: %.2f%%",
                loss_rate * 100
            )

            if loss_rate >= LOSS_THRESHOLD:
                self.sdn_app.loss_triggered = True
            else:
                self.sdn_app.loss_triggered = False

            self.sdn_app.install_routes()

            result = {
                "status": "SUCCESS",
                "loss_rate": loss_rate,
                "threshold": LOSS_THRESHOLD,
                "active_path": (
                    "BACKUP"
                    if self.sdn_app.primary_failed
                    or self.sdn_app.loss_triggered
                    else "PRIMARY"
                )
            }

            return Response(
                content_type="application/json",
                body=json.dumps(result).encode("utf-8")
            )

        except Exception as exc:
            return Response(
                status=400,
                content_type="application/json",
                body=json.dumps({"error": str(exc)}).encode("utf-8")
            )


class RerouteController(app_manager.RyuApp):

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {"wsgi": WSGIApplication}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.datapaths = {}
        self.primary_failed = False
        self.loss_triggered = False

        # Track the operational state of all primary-path ports.
        self.primary_port_up = {
            (1, 2): True,
            (2, 1): True,
            (2, 2): True,
            (4, 2): True
        }

        wsgi = kwargs["wsgi"]
        wsgi.register(
            RerouteRestController,
            {REST_INSTANCE: self}
        )

    def add_flow(self, dp, priority, match, out_port):

        parser = dp.ofproto_parser
        ofproto = dp.ofproto

        actions = [parser.OFPActionOutput(out_port)]

        instructions = [
            parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS,
                actions
            )
        ]

        dp.send_msg(parser.OFPFlowMod(
            datapath=dp,
            priority=priority,
            match=match,
            instructions=instructions
        ))

    def install_routes(self):

        backup = self.primary_failed or self.loss_triggered

        self.logger.info(
            "Installing %s path",
            "BACKUP" if backup else "PRIMARY"
        )

        for dp in self.datapaths.values():

            parser = dp.ofproto_parser
            ofproto = dp.ofproto
            dpid = dp.id

            dp.send_msg(parser.OFPFlowMod(
                datapath=dp,
                command=ofproto.OFPFC_DELETE,
                out_port=ofproto.OFPP_ANY,
                out_group=ofproto.OFPG_ANY,
                match=parser.OFPMatch()
            ))

            self.add_flow(
                dp, 200,
                parser.OFPMatch(eth_type=ARP_ETH_TYPE),
                ofproto.OFPP_FLOOD
            )

            if dpid == 1:

                next_hop = 3 if backup else 2

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(in_port=1, eth_dst=H2_MAC),
                    next_hop
                )

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(in_port=next_hop, eth_dst=H1_MAC),
                    1
                )
                # Allow communication with the API host on S1 port 4
                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(in_port=1, eth_dst="02:00:00:00:00:fe"),
                    4
                )

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(in_port=4, eth_dst=H1_MAC),
                    1
                )
            elif dpid == 2 and not backup:

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(in_port=1, eth_dst=H2_MAC),
                    2
                )

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(in_port=2, eth_dst=H1_MAC),
                    1
                )

            elif dpid == 3 and backup:

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(in_port=1, eth_dst=H2_MAC),
                    2
                )

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(in_port=2, eth_dst=H1_MAC),
                    1
                )

            elif dpid == 4:

                path_port = 3 if backup else 2

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(in_port=path_port, eth_dst=H2_MAC),
                    1
                )

                self.add_flow(
                    dp, 100,
                    parser.OFPMatch(in_port=1, eth_dst=H1_MAC),
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

        self.logger.info(
            "Port status event: switch=%s port=%s reason=%s state=%s",
            dp.id, msg.desc.port_no, msg.reason, msg.desc.state
        )

        # Update the state of this particular primary-path port.
        self.primary_port_up[key] = (
        bool(msg.desc.state & dp.ofproto.OFPPS_LIVE)
        and not bool(msg.desc.state & dp.ofproto.OFPPS_LINK_DOWN)
        )
        # The primary path has failed if ANY monitored port is down.
        primary_failed_now = not all(self.primary_port_up.values())

        if primary_failed_now != self.primary_failed:

            self.primary_failed = primary_failed_now

            if self.primary_failed:
                self.logger.warning(
                    "PRIMARY PATH FAILURE detected. Switching to BACKUP."
                )
            else:
                self.logger.info(
                    "ALL PRIMARY PATH PORTS RESTORED. Switching to PRIMARY."
                )

            self.install_routes()
