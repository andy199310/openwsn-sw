# this is schedule distributor!

import logging
from difflib import SequenceMatcher
from threading import Timer

from coap import coap
import operator

from math import floor

from openvisualizer.moteState import moteState

log = logging.getLogger('scheduleDistributor')
log.setLevel(logging.ERROR)
log.addHandler(logging.NullHandler())

from openvisualizer.eventBus import eventBusClient


class ScheduleDistributor(eventBusClient.eventBusClient):

    CELL_TYPE_TX     = 0
    CELL_TYPE_RX     = 1
    CELL_TYPE_REMOVE = 8

    def __init__(self, openVisualizerApp):
        # log
        log.info("Schedule Distributor started!")

        # store params

        # initialize parent class
        eventBusClient.eventBusClient.__init__(
            self,
            name='ScheduleDistributor',
            registrations=[
                {
                    'sender': self.WILDCARD,
                    'signal': 'networkChanged',
                    'callback': self._networkChanged_notif,
                },
                {
                    'sender': self.WILDCARD,
                    'signal': 'scheduleChanged',
                    'callback': self._scheduleChanged_notif,
                },
                {
                    'sender': self.WILDCARD,
                    'signal': 'updateRootMoteState',
                    'callback': self._updateRootMoteState_notif,
                }
            ]
        )

        # local variables
        self._openVisualizerApp = openVisualizerApp
        self.max_entry_per_packet = 2
        self.motes = None
        self.edges = None
        self.overAllScheduleTable = []
        self.motesScheduleTable = {}
        self.pastMotesScheduleTable = {}
        self.dag_root_moteState = None


    # ======================== public ==========================================
    def close(self):
        pass

    # ======================== private =========================================
    def _networkChanged_notif(self,sender,signal,data):
        log.info("Get network changed")
        self.motes = data[0]
        self.edges = data[1]

    def _scheduleChanged_notif(self, sender, signal, data):
        log.info("Get schedule changed")
        self.overAllScheduleTable = data[0]

        if log.isEnabledFor(logging.DEBUG):
            self._printOverAllScheduleTable()

        self._breakScheduleTableToMoteScheduleTable()
        self._sendScheduleTableToMote()

    def _breakScheduleTableToMoteScheduleTable(self):
        # reset mote schedule table for compare
        self.motesScheduleTable = {}

        log.info("Total entry: {0}".format(len(self.overAllScheduleTable)))
        for entry in self.overAllScheduleTable:
            # set up TX
            self._addEntryToMoteScheduleTable(entry[0], entry[1], entry[2], entry[3], ScheduleDistributor.CELL_TYPE_TX)
            # set up RX
            self._addEntryToMoteScheduleTable(entry[1], entry[0], entry[2], entry[3], ScheduleDistributor.CELL_TYPE_RX)
        log.info("Done breaking scheduleTable for each motes")

    def _addEntryToMoteScheduleTable(self, mote, neighbor, slot_offset, channel_offset, cell_type):
        if mote not in self.motesScheduleTable:
            self.motesScheduleTable[mote] = []
        self.motesScheduleTable[mote].append({'neighbor': neighbor,
                                              'slotOffset': slot_offset,
                                              'channelOffset': channel_offset,
                                              'cellType': cell_type})

    def _copyScheduleTableToPastList(self, mote):
        self.pastMotesScheduleTable[mote] = self.motesScheduleTable[mote]

    def _getDifferentScheduleEntryList(self, mote_id):
        if mote_id not in self.pastMotesScheduleTable:
            return self.motesScheduleTable[mote_id]
        past_schedule_entry_list = self.pastMotesScheduleTable[mote_id]
        new_schedule_entry_list = self.motesScheduleTable[mote_id]

        different_list = list()
        for newEntry in new_schedule_entry_list:
            found_same_entry = [x for x in past_schedule_entry_list if x == newEntry]
            if len(found_same_entry) is 0:
                different_list.append(newEntry)
            else:
                found_same_entry[0]['found'] = True

        remove_entry_list = [x for x in past_schedule_entry_list if 'found' not in x]
        for remove_entry in remove_entry_list:
            remove_entry['cellType'] = ScheduleDistributor.CELL_TYPE_REMOVE

        # first remove than insert
        remove_entry_list.extend(different_list)
        return remove_entry_list

    def _getCommonLength(self, destination_address, entry_list):
        common_length = 100
        destination_address = destination_address.replace(":", "")
        sequence_matcher = SequenceMatcher(None, destination_address)
        for entry in entry_list:
            neighbor_address = entry["neighbor"].replace(":", "")
            sequence_matcher.set_seq2(neighbor_address)
            result = sequence_matcher.find_longest_match(0, len(destination_address), 0, len(neighbor_address))
            common_length = min(common_length, result.size)

        # max length is 19 (4*4 + 3:)
        common_length_in_bytes = 8 + (common_length - common_length % 2) / 2
        return common_length_in_bytes

    def _getAvailableEntryForApplicationLayerPayload(self, mote_id, common_length):
        mote_id_in_list = []
        mote_id_trim = mote_id.replace(":", "")
        for (c1, c2) in zip(mote_id_trim[0::2], mote_id_trim[1::2]):
            mote_id_in_list.append(int(c1 + c2, 16))

        route = self._dispatchAndGetResult(signal='getSourceRoute', data=mote_id_in_list)

        layer_2_mac = 23 + 2
        layer_3_lowpan = 22 + 1  # 1 for traffic class
        layer_4_udp = 8
        layer_7_coap = 17

        # TODO real source routing
        source_routing_length = 16

        max_physical_layer = 128

        available_byte = max_physical_layer - layer_2_mac - layer_3_lowpan - layer_4_udp - layer_7_coap - source_routing_length

        scheduling_header_length = 2
        each_entry_length = 2 + (16 - common_length)

        available_byte -= scheduling_header_length
        available_entry = floor(available_byte / each_entry_length)

        return available_entry

    def _sendScheduleTableToMote(self):
        # TODO sending order
        for mote_id, schedule_list in self.motesScheduleTable.iteritems():
            log.info("Process {0:4} schedule table which contain {1:2} entry.".format(mote_id, len(schedule_list)))

            different_entry_list = self._getDifferentScheduleEntryList(mote_id)
            log.info("{0:4} contain {1:2} entry that is different from previous.".format(mote_id, len(different_entry_list)))

            if log.isEnabledFor(logging.DEBUG):
                self._printScheduleDifferentList(different_entry_list)

            # calculate common length
            common_length = int(self._getCommonLength(mote_id, different_entry_list))

            # each packet entry length
            each_packet_entry_length = int(self._getAvailableEntryForApplicationLayerPayload(mote_id, common_length))

            log.info("Common length: {0}, Each packet entry length : {1}".format(common_length, each_packet_entry_length))

            for i in range(0, len(different_entry_list), each_packet_entry_length):
                current_packet_entry_list = different_entry_list[i:i+each_packet_entry_length]
                log.info("Sequence {0:2} have {1:2} entry to send".format((i/each_packet_entry_length)+1, len(current_packet_entry_list)))
                payload = self._assemblePayloadFromEntryList(mote_id, common_length, current_packet_entry_list)
                try:
                    self._sendPayloadToMote(mote_id, payload)
                except:
                    log.error("Got Error!")
                    import sys
                    log.critical("Unexpected error:{0}".format(sys.exc_info()[0]))
                    log.critical("Unexpected error:{0}".format(sys.exc_info()[1]))
                log.info("__________________________________________________")

            self.pastMotesScheduleTable[mote_id] = self.motesScheduleTable[mote_id]

            log.info("Done send to {0:4}".format(mote_id))
            log.info("====================================")

    def _assemblePayloadFromEntryList(self, mote_id, common_length, entry_list):
        payload = list()
        common_length_in_char = 32 - (common_length * 2)

        # header
        # common length (b4) + pad (4b)
        payload.append(((common_length & 0x0F) << 4))

        # entry count
        payload.append(len(entry_list))

        # entry list
        for entry in entry_list:
            # Type (b4) + channel (b4)
            payload.append(((entry['cellType'] & 0x0F) << 4) | (entry['channelOffset'] & 0x0F))
            payload.append(entry['slotOffset'])
            neighbor_address = entry['neighbor']
            neighbor_address = neighbor_address.replace(':', '')
            neighbor_address = neighbor_address[-common_length_in_char:]

            for address1, address2 in zip(neighbor_address[::2], neighbor_address[1::2]):
                payload.append(int(address1 + address2, 16))

        return bytearray(payload)

    def _sendPayloadToMote(self, mote_address, payload):
        is_root = False
        if mote_address[-2:] == '01' or mote_address[-2:] == '88':  # TODO make it better
            is_root = True

        if is_root:
            log.debug("GO root")
            self.dispatch(
                signal='cmdToMote',
                data={
                    'serialPort': self.dag_root_moteState.moteConnector.serialport,
                    'action': self.dag_root_moteState.ADD_SCHEDULE,
                    'payload': payload
                },
            )
            return
        else:
            try:

                log.debug("GO mote")
                from coapthon.client.helperclient import HelperClient
                host = "bbbb::"+":".join('0' if i.count('0')==4 else i.lstrip('0') for i in mote_address.split(':'))
                coapClient = HelperClient(server=(host, 5683))
                coapClient.post(path="s", timeout=20, payload=payload)
                coapClient.stop()
                # c = coap.coap(udpPort=5466+self.lastNetworkUpdateCounter)
                # c.maxRetransmit = 2
                # p = c.POST('coap://[bbbb::{0}]/green'.format(mote_address), payload=payload)
                # c.close()
            except:
                log.error("Got Error!")
                # c.close()
                import sys
                log.critical("Unexpected error:{0}".format(sys.exc_info()[0]))
                log.critical("Unexpected error:{0}".format(sys.exc_info()[1]))

        return

    def _updateRootMoteState_notif(self, sender, signal, data):
        log.debug("Get update root")
        log.debug(data)
        self.dag_root_moteState = data['rootMoteState']
        return

    def _findHopInTree(self, mote):
        for edge in self.edges:
            if edge['u'] == mote:
                return self._findHopInTree(edge['v']) + 1
        return 0

    def _printOverAllScheduleTable(self):
        log.debug("| From |  To  | Slot | Chan |")
        for item in self.overAllScheduleTable:
            log.debug("| {0:4} | {1:4} | {2:4} | {3:4} |".format(item[0][-4:], item[1][-4:], item[2], item[3]))
        log.debug("-----------------------------")

    def _printScheduleDifferentList(self, different_list):
        log.debug("| Type | Chan | Slot | Addr |")
        for different_entry in different_list:
            log.debug("| {0:4} | {1:4} | {2:4} | {3:4} |".format(different_entry['cellType'],
                                                                 different_entry['channelOffset'],
                                                                 different_entry['slotOffset'],
                                                                 different_entry['neighbor'][-4:]))
        log.debug("-----------------------------")
