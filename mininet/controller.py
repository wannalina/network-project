# this controller is adapted from the ryu simple_switch_13_step.py

import json
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import dpid as dpid_lib
from ryu.lib import stplib
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.app import simple_switch_13
from ryu.app.wsgi import ControllerBase, route
from ryu.app.wsgi import WSGIApplication
from webob import Response


class SimpleSwitch13(simple_switch_13.SimpleSwitch13):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {
        'wsgi': WSGIApplication,
        'stplib': stplib.Stp
    }

    def __init__(self, *args, **kwargs):
        super(SimpleSwitch13, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.host_table = {}
        self.port_stats = {}
        self.port_desc_stats = {}
        self.flow_stats = {}   
        self.stp_port_state = {}     

        self.stp = kwargs['stplib']
        wsgi = kwargs['wsgi']
        wsgi.register(IntentAPI, {'controller': self})

        self.base_stp_config = {
            'bridge': {'priority': 0x8000},
        }

    #! function to retrieve network state data (custom)
    def get_network_state(self):
        try: 
            # iterate through datapaths to get flow entries
            for dpid, dp in self.datapaths.items():
                parser = dp.ofproto_parser
                ofproto = dp.ofproto

                # request flow stats
                req = parser.OFPFlowStatsRequest(dp)
                dp.send_msg(req)

                # request port stats
                port_req = parser.OFPPortStatsRequest(dp, 0, ofproto.OFPP_ANY)
                dp.send_msg(port_req)

                # request port descriptions
                port_desc_req = parser.OFPPortDescStatsRequest(dp)
                dp.send_msg(port_desc_req)

            # define state object
            state = {
                "switches": list(self.datapaths.keys()),
                'host_table': self.host_table,
                'mac_table': self.mac_to_port,
                'port_stats': self.port_stats,
                'stp_port_states': self.stp_port_state,
                'port_description_stats': self.port_desc_stats,
                'flow_tables': self.flow_stats            
            }

            for dpid in self.datapaths.keys():
                # populate latest vals
                state["flow_tables"][dpid] = self.flow_stats.get(dpid, [])
                state["port_stats"][dpid] = self.port_stats.get(dpid, [])
                state["port_description_stats"][dpid] = self.port_desc_stats.get(dpid, [])

            return state

        except Exception as e: 
            print(f"Error getting network state: {e}")
            return None


    # function to delete flow entries (built-in)
    def delete_flow(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        for dst in self.mac_to_port[datapath.id].keys():
            match = parser.OFPMatch(eth_dst=dst)
            mod = parser.OFPFlowMod(
                datapath, command=ofproto.OFPFC_DELETE,
                out_port=ofproto.OFPP_ANY, out_group=ofproto.OFPG_ANY,
                priority=1, match=match)
            datapath.send_msg(mod)


    # change port state (enable/disable)
    def set_port_state(self, dpid, port, disable=True):
        try:
            datapath = self.datapaths.get(dpid)
            if not datapath:
                return f"Datapath {dpid} not found"

            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser

            config = ofproto.OFPPC_PORT_DOWN if disable else 0
            mask = ofproto.OFPPC_PORT_DOWN

            req = parser.OFPPortMod(
                datapath=datapath,
                port_no=port,
                hw_addr=datapath.ports[port].hw_addr,
                config=config,
                mask=mask,
                advertise=0
            )
            datapath.send_msg(req)
            state = "disabled" if disable else "enabled"
            return f"Port {port} on switch {dpid} has been {state}"

        except Exception as e:
            return f"Error setting port state: {e}"


    # get host location in the network
    def get_host_location(self, action_obj):
        try:
            mac = action_obj["mac"]
            for dpid, macs in self.mac_to_port.items():
                if mac in macs:
                    return f"Host {mac} is at switch {dpid} port {macs[mac]}"
            return f"Host {mac} not found in MAC table"
        except Exception as e:
            return f"Error locating host: {e}"


    # trace packet route
    def trace_route(self, action_obj):
        try:
            src = action_obj.get("src_mac")
            dst = action_obj.get("dst_mac")
            if not src or not dst:
                return "Missing source or destination MAC"

            trace = []
            visited = set()
            current_mac = src

            while current_mac in visited:
                break  # avoid loops

            for dpid, macs in self.mac_to_port.items():
                if current_mac in macs:
                    trace.append({"switch": dpid, "port": macs[current_mac]})
                    visited.add(current_mac)
                    if current_mac == dst:
                        break
            if not trace:
                return f"Unable to trace route from {src} to {dst}"
            return trace
        except Exception as e:
            return f"Error tracing route: {e}"


    # event handler to set up stp config dynamically (called upon switch connection event)
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def _stp_switch_connected(self, ev):
        dpid = ev.dp.id
        self.logger.info("STP: Switch connected with DPID %s", dpid)

        # Set dynamic STP config per switch
        if dpid == dpid_lib.str_to_dpid('0000000000000001'):
            config = {'bridge': {'priority': 0x8000}}
        elif dpid == dpid_lib.str_to_dpid('0000000000000002'):
            config = {'bridge': {'priority': 0x9000}}
        else:
            config = self.base_stp_config

        # Apply config
        self.stp.set_config({dpid: config})
        self.logger.info("STP config applied to DPID %s: %s", dpid, config)


    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        flows = []
        for stat in ev.msg.body:
            actions = []
            for inst in stat.instructions:
                if hasattr(inst, "actions"):
                    for a in inst.actions:
                        if a.__class__.__name__ == "OFPActionOutput":
                            actions.append({"type": "output", "port": a.port})
            flows.append({
                "priority": stat.priority,
                "match": str(stat.match),
                "actions": actions,
                "packets": stat.packet_count,
                "bytes": stat.byte_count,
            })
        self.flow_stats[dpid] = flows


    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def _port_desc_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        self.port_desc_stats[dpid] = [vars(p) for p in ev.msg.body]


    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        self.port_stats[dpid] = [vars(stat) for stat in ev.msg.body]


    # event handler to handle packet_in event (built-in)
    @set_ev_cls(stplib.EventPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        dst = eth.dst
        src = eth.src

        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})

        self.logger.info("packet in %s %s %s %s", dpid, src, dst, in_port)

        # learn a mac address to avoid FLOOD next time.
        self.mac_to_port[dpid][src] = in_port
        self.host_table[src] = {"dpid": dpid, "port": in_port}

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # install a flow to avoid packet_in next time
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
            self.add_flow(datapath, 1, match, actions)

        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

    # event handler to handle topology change (built-in)
    @set_ev_cls(stplib.EventTopologyChange, MAIN_DISPATCHER)
    def _topology_change_handler(self, ev):
        dp = ev.dp
        dpid_str = dpid_lib.dpid_to_str(dp.id)
        msg = 'Receive topology change event. Flush MAC table.'
        self.logger.debug("[dpid=%s] %s", dpid_str, msg)

        if dp.id in self.mac_to_port:
            self.delete_flow(dp)
            del self.mac_to_port[dp.id]


    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.logger.info("Registering datapath: %s", datapath.id)
                self.datapaths[datapath.id] = datapath
        elif ev.state == 'DEAD_DISPATCHER':
            if datapath.id in self.datapaths:
                self.logger.info("Unregistering datapath: %s", datapath.id)
                self.datapaths.pop(datapath.id, None)


    # event handler to handle port state change (built-in)
    @set_ev_cls(stplib.EventPortStateChange, MAIN_DISPATCHER)
    def _port_state_change_handler(self, ev):
        self.stp_port_state.setdefault(ev.dp.id, {})[ev.port_no] = ev.port_state
        dpid_str = dpid_lib.dpid_to_str(ev.dp.id)
        of_state = {stplib.PORT_STATE_DISABLE: 'DISABLE',
                    stplib.PORT_STATE_BLOCK: 'BLOCK',
                    stplib.PORT_STATE_LISTEN: 'LISTEN',
                    stplib.PORT_STATE_LEARN: 'LEARN',
                    stplib.PORT_STATE_FORWARD: 'FORWARD'}
        self.logger.debug("[dpid=%s][port=%d] state=%s",
                        dpid_str, ev.port_no, of_state[ev.port_state])



# Intent API for Ryu controller
class IntentAPI(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(IntentAPI, self).__init__(req, link, data, **config)
        self.controller = data['controller']


    @route('intent', '/intent/get-state', methods=['GET'])
    def get_state(self, req, **kwargs):
        state = self.controller.get_network_state()
        res_body = json.dumps(state).encode('utf-8')
        return Response(content_type='application/json', body=res_body)


    @route('intent', '/intent/implement', methods=['POST'])
    def post_action(self, req, **kwargs):
        actions = req.json or []
        results = []

        for action in actions: 
            action_type = action.get("action")

            if action_type == "install_flow":
                switch = int(action["switch"])
                dp = self.controller.datapaths.get(switch)
                src_mac = action['src_mac']
                dst_mac = action['dst_mac']
                in_port = int(action['in_port'])
                out_port = int(action['out_port'])
                parser = datapath.ofproto_parser
                match = parser.OFPMatch(in_port=in_port, eth_src=src_mac, eth_dst=dst_mac)

                self.controller.add_flow(dp, 1, match, parser.OFPActionOutput(out_port))
                result = "Flow added successfully"

            elif action_type == "delete_flow":
                switch = int(action['switch'])
                datapath = self.controller.datapaths.get(switch)
                self.controller.delete_flow(datapath)
                result = "Flow deleted successfully"

            elif action_type == "block_port":
                switch = int(action['switch'])
                port = int(action['port'])
                result = self.controller.set_port_state(switch, port, disable=True)

            elif action_type == "unblock_port":
                switch = int(action['switch'])
                port = int(action['port'])
                result = self.controller.set_port_state(switch, port, disable=False)

            elif action_type == "request_port_stats": 
                result = self.controller.port_stats

            elif action_type == "host_location": 
                result = self.controller.get_host_location(action)

            elif action_type == "trace_route": 
                result = self.controller.trace_route(action)

            else: 
                pass

            results.append(result)
        return Response(content_type='application/json', body=json.dumps({"results": results}).encode('utf-8'))  