# this controller is adapted from the ryu simple_switch_13_step.py

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import dpid as dpid_lib
from ryu.lib import stplib
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.app import simple_switch_13
from ryu.app.wsgi import ControllerBase, route
from ryu.app.wsgi import WSGIApplication
import time


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

        self.stp = kwargs['stplib']
        wsgi = kwargs['wsgi']
        wsgi.register(IntentAPI, {'controller': self})

        self.base_stp_config = {
            'bridge': {'priority': 0x8000},
        }

    #! function to retrieve network state data (custom)
    def get_network_state(self):
        try: 
            # define state object
            state = {
                'datapaths': list(self.datapaths.keys()),
                'stp_config': self.stp.get_config(),
                'host_table': self.host_table,
                'mac_table': self.mac_to_port,
                'port_stats': self.port_stats,
                'stp_port_states': self.stp.get_port_states(),
                'port_description_stats': self.port_desc_stats,
                'flow_tables': self.flow_stats            
            }

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

                time.sleep(2)   # wait to populate flow_tables and port_stats

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

    # event handler to set up stp config dynamically (called upon switch connection event  )
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

    # event handler to handle port state change (built-in)
    @set_ev_cls(stplib.EventPortStateChange, MAIN_DISPATCHER)
    def _port_state_change_handler(self, ev):
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
        return
