import logging
import struct
from threading import Timer

from openvisualizer.moteState import moteState
from openvisualizer.networkManager.networkManager import NetworkManager

log = logging.getLogger('simulatorHelper')
log.setLevel(logging.ERROR)
log.addHandler(logging.NullHandler())

from openvisualizer.eventBus import eventBusClient


class SimulatorHelper(eventBusClient.eventBusClient):

    TICK_INTER_SECOND = 5

    SLOT_LENGTH = 15

    SIMULATION_TIME = 3600


    def __init__(self, openVisualizerApp):
        # log
        log.info("Simulator Helper started!")

        # store params

        # initialize parent class
        eventBusClient.eventBusClient.__init__(
            self,
            name='SimulatorHelper',
            registrations=[
                {
                    'sender': self.WILDCARD,
                    'signal': 'updateRootMoteState',
                    'callback': self._updateRootMoteState_notif,
                },
                {
                    'sender': self.WILDCARD,
                    'signal': 'targetPacketSniffer',
                    'callback': self._targetPacketSniffer,
                }
            ]
        )

        self._openVisualizerApp = openVisualizerApp
        self._dag_root_moteState = None

        self._packet_log = []
        self._analysis_packet = {}

        self._last_tick_asn = 0
        self._stuck_counter = 0
        self._timer = Timer(SimulatorHelper.TICK_INTER_SECOND, self._simulatorHelperTick)
        self._timer.start()

        log.info("Start running simulation for {0} seconds".format(SimulatorHelper.SIMULATION_TIME))


    # ======================== public ==========================================
    def close(self):
        pass

    # ======================== private =========================================
    def _simulatorHelperTick(self):
        log.debug("simulator helper tick!")
        # get current ASN
        if self._dag_root_moteState is not None:
            asn_state = self._dag_root_moteState.getStateElem(self._dag_root_moteState.ST_ASN)
            asn_list = asn_state.data[0]['asn'].asn
            asn = 0
            for asn_item in asn_list:
                asn = asn * 256 + asn_item
            asn_in_second = asn * SimulatorHelper.SLOT_LENGTH / 1000
            speed = float((asn - self._last_tick_asn) * SimulatorHelper.SLOT_LENGTH / 1000) / SimulatorHelper.TICK_INTER_SECOND
            log.debug("Current asn: {0}, second: {1} (Speed: {2:.2})".format(asn, asn_in_second, speed))

            if asn == self._last_tick_asn:
                log.warning("Maybe stuck, stuck counter {0}".format(self._stuck_counter))
                if self._stuck_counter > 5:
                    log.warning("Stuck for too long, abort simulation!")
                    self._stopSimulation()
                else:
                    self._stuck_counter += 1
            else:
                self._stuck_counter = 0

            if asn_in_second > SimulatorHelper.SIMULATION_TIME:
                self._stopSimulation()
                return

            self._last_tick_asn = asn

        self._printAnalysisLog()

        Timer(SimulatorHelper.TICK_INTER_SECOND, self._simulatorHelperTick).start()

    def _updateRootMoteState_notif(self, sender, signal, data):
        log.debug("Get update root")
        self._dag_root_moteState = data['rootMoteState']
        return

    def _targetPacketSniffer(self, sender, signal, data):
        log.debug("Get sniff packet")

        ipv6dic = data
        self._packet_log.append(ipv6dic)
        self._parsePacketAnalysis(ipv6dic)

    def _parsePacketAnalysis(self, new_packet):
        src_address = new_packet["src_addr"]
        app_payload = new_packet["app_payload"]

        report_payload = app_payload[-NetworkManager.CREPORT_ASN_PAYLOAD_LENGTH:]

        coap_format = ["<xx",  # padding
                       "BBBBB",  # StartASN
                       "BBBBB",  # EndASN
                       "B",  # numDeSync
                       "H",  # myRank
                       "B",  # parentTX
                       "B",  # parentTXACK
                       "H",  # lastSuccessLeft
                       "H",  # errorCounter
                       "H",  # creportasn_sequence
                       "H",  # lastCallbackSequence
                       "b",  # parentRssi
                       "B",  # temperature
                       ]
        coap_format_str = ''.join(coap_format)

        data = struct.unpack(coap_format_str, bytearray(report_payload))
        mote = src_address
        start_asn = 0
        end_asn = 0
        for i in range(0, 5, 1):
            start_asn += pow(256, i) * data[i]
            end_asn += pow(256, i) * data[i + 5]
        numDesync = data[10]
        myrank = data[11]
        tx = data[12]
        txACK = data[13]
        packet_sequence = data[16]
        last_success_left = data[14]
        error_counter = data[15]
        last_callback_sequence = data[17]
        parent_rssi = data[18]
        temperature = data[19]
        diff_in_asn = end_asn - start_asn

        self._appendAnalysisPacket(mote, start_asn, end_asn, packet_sequence)

    def _appendAnalysisPacket(self, mote, start_asn, end_asn, packet_sequence):
        mote_src = ':'.join('{0:02x}{1:02x}'.format(i, j) for i, j in zip(mote[0::2], mote[1::2]))
        new_entry = {"mote": mote_src,
                     "start_asn": start_asn,
                     "end_asn": end_asn,
                     "packet_sequence": packet_sequence,
                     "diff": end_asn - start_asn,
                     "duplicate": False}

        # TODO check order
        # check duplicate
        if mote_src in self._analysis_packet:
            past_same_entry = [x for x in self._analysis_packet[mote_src]
                               if x["packet_sequence"] is new_entry["packet_sequence"]]
            if len(past_same_entry) > 0:
                new_entry["duplicate"] = True

        # calculate miss packet and inter packet time
        if mote_src in self._analysis_packet:
            last_entry = [x for x in self._analysis_packet[mote_src] if x["duplicate"] is False][-1]
            new_entry["packet_loss"] = (new_entry["packet_sequence"] - last_entry["packet_sequence"] - 1)
            new_entry["inter_packet_time"] = new_entry["end_asn"] - last_entry["end_asn"]
        else:
            # that's mote first packet
            self._analysis_packet[mote_src] = []
            new_entry["packet_loss"] = 0
            new_entry["inter_packet_time"] = None  # TODO what XD (link with _printAnalysisLog)
            new_entry["diff"] = 50  # if this is first packet, set to half of slotframe length

        self._analysis_packet[mote_src].append(new_entry)

    def _printAnalysisLog(self):
        log.debug("| Mote |Count |Cnt!D |Avg.D |Avg.IP| Lost | Dup  |")
        for mote, entries in self._analysis_packet.iteritems():
            packet_entries_without_duplicate = [e for e in entries if e["duplicate"] is False]
            packet_entries_without_duplicate_length = len(packet_entries_without_duplicate)
            if packet_entries_without_duplicate_length == 0:
                continue
            log.debug("|{0:6}|{1:6}|{2:6}|{3:6}|{4:6}|{5:6}|{6:6}|".format(
                mote[-4:],
                len(entries),
                packet_entries_without_duplicate_length,
                sum(d['diff'] for d in packet_entries_without_duplicate) / packet_entries_without_duplicate_length,
                sum(d['inter_packet_time'] for d in packet_entries_without_duplicate if d['inter_packet_time'] is not None) / packet_entries_without_duplicate_length,
                sum(d['packet_loss'] for d in packet_entries_without_duplicate),
                len(entries) - packet_entries_without_duplicate_length
            ))

        log.debug("==================================================")

    def _stopSimulation(self):
        log.info("Stop simulation!")
        self._openVisualizerApp.close()
        self._exportSimulationResult()
        self._printAnalysisLog()
        import os
        import signal
        os.kill(os.getpid(), signal.SIGTERM)

    def _exportSimulationResult(self):
        log.debug(1)
        self._exportRawPacketLog()
        self._exportAnalysisLog()
        self._exportAnalysisResult()
        return

    def _exportRawPacketLog(self):
        import json
        with open('result-rawPacketLog.json', 'w') as fp:
            json.dump(self._packet_log, fp)

    def _exportAnalysisLog(self):
        import json
        with open('result-analysisLog.json', 'w') as fp:
            json.dump(self._analysis_packet, fp)

    def _exportAnalysisResult(self):
        import json
        simulation_result = list()
        for mote, entries in self._analysis_packet.iteritems():
            packet_entries_without_duplicate = [e for e in entries if e["duplicate"] is False]
            packet_entries_without_duplicate_length = len(packet_entries_without_duplicate)

            result_entry = {}
            result_entry["mote"] = mote
            result_entry["packet_count"] = len([e for e in entries])
            result_entry["packet_count_without_duplicate"] = packet_entries_without_duplicate_length
            result_entry["duplicate_packet_count"] = len([e for e in entries if e["duplicate"] is True])
            result_entry["packet_loss"] = sum(e["packet_loss"] for e in packet_entries_without_duplicate)

            result_entry["average_packet_latency"] = sum(e["diff"] for e in packet_entries_without_duplicate) / packet_entries_without_duplicate_length
            result_entry["average_inter_packet_time"] = sum(e["inter_packet_time"] for e in packet_entries_without_duplicate if e['inter_packet_time'] is not None) / packet_entries_without_duplicate_length

            result_entry["max_packet_latency"] = max(e["diff"] for e in packet_entries_without_duplicate)
            result_entry["max_inter_packet_time"] = max(e["inter_packet_time"] for e in packet_entries_without_duplicate)

            simulation_result.append(result_entry)

        with open('result-analysisResult.json', 'w') as fp:
            json.dump(simulation_result, fp)
