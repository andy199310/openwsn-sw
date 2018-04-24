# this is network manager!

import logging
from threading import Timer

from coap import coap
import operator

from openvisualizer.moteState import moteState
from openvisualizer.networkManager.algorithms.tasa import tasaSimpleAlgorithms
from openvisualizer.networkManager.algorithms.tasa_pdr import tasa_pdr_algorithms

log = logging.getLogger('networkManager')
log.setLevel(logging.ERROR)
log.addHandler(logging.NullHandler())

from openvisualizer.eventBus import eventBusClient


class NetworkManager(eventBusClient.eventBusClient):

    CREPORT_ASN_PAYLOAD_LENGTH = 27

    SCHEDULE_IN_SLOTFRAME_SUCCESS_RATE = 0.95

    def __init__(self, openVisualizerApp):
        # log
        log.info("Network Manager started!")

        # store params

        # initialize parent class
        eventBusClient.eventBusClient.__init__(
            self,
            name='NetworkManager',
            registrations=[
                {
                    'sender': self.WILDCARD,
                    'signal': 'networkChanged',
                    'callback': self._networkChanged_notif,
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
        if self._openVisualizerApp.gScheduler is None:
            self._scheduler = "TASA"
        else:
            self._scheduler = self._openVisualizerApp.gScheduler
        self.max_assignable_slot = 80
        self.start_offset = 20
        self.max_assignable_channel = 16
        self.lastNetworkUpdateCounter = 0
        self.max_entry_per_packet = 2
        self.motes = None
        self.edges = None
        self.scheduleTable = []
        self.dag_root_moteState = None
        self.schedule_back_off = 30
        self.schedule_running = False


    # ======================== public ==========================================
    def close(self):
        pass

    def getSchedule(self):
        return self.scheduleTable

    # ======================== private =========================================
    def _networkChanged_notif(self,sender,signal,data):
        log.info("Get network changed")
        self.lastNetworkUpdateCounter += 1
        log.debug("New counter: {0}".format(self.lastNetworkUpdateCounter))
        self.motes = data[0]
        self.edges = data[1]

        if self._checkTopology() is False:
            log.warning("Topology is not complete, stop schedule!")
            return

        # wait x second for newer dao
        timer = Timer(self.schedule_back_off, self._doCalculate, [self.lastNetworkUpdateCounter])
        timer.start()
        log.debug("End!")

    def _doCalculate(self, *args, **kwargs):
        if self.lastNetworkUpdateCounter > args[0]:
            log.debug("[PASS] Calculate counter: {0} is older than {1}".format(args[0], self.lastNetworkUpdateCounter))
            return
        if self.schedule_running:
            log.debug("[DELAY] Someone is running. Wait for next time. {0}, {1}".format(args[0], self.lastNetworkUpdateCounter))
            timer = Timer(self.schedule_back_off, self._doCalculate, [self.lastNetworkUpdateCounter])
            timer.start()
            return
        try:
            self.schedule_running = True
            log.debug("Real calculate! {0}".format(args[0]))
            motes = self.motes
            edges = self.edges
            log.debug("Mote count: {0}".format(len(motes)))
            log.debug("Edge count: {0}".format(len(edges)))
            log.debug("Start algorithm")
            local_queue = {}
            for mote in motes:
                local_queue[mote] = 1

            succeed = False
            results = []

            # TODO better PDR
            if self._openVisualizerApp.gPDRr is None:
                pdr = 1
            else:
                pdr = self._openVisualizerApp.gPDRr

            if self._scheduler == "TASA":
                succeed, results = tasaSimpleAlgorithms(motes, local_queue, edges, self.max_assignable_slot, self.start_offset, self.max_assignable_channel)

            elif self._scheduler == "SB-TASA":
                succeed, results = tasaSimpleAlgorithms(motes, local_queue, edges, self.max_assignable_slot, self.start_offset, self.max_assignable_channel)
                repeat_time = 1
                error_rate = 1 - pdr
                while error_rate > 1 - NetworkManager.SCHEDULE_IN_SLOTFRAME_SUCCESS_RATE:
                    repeat_time += 1
                    error_rate *= (1 - pdr)
                new_results = []
                for item in results:
                    base_slot_offset = item[2] - self.start_offset
                    for i in range(0, repeat_time):
                        new_slot_offset = self.start_offset + base_slot_offset * repeat_time + i
                        new_results.append([item[0], item[1], new_slot_offset, item[3]])
                results = new_results

            elif self._scheduler == "FB-TASA":
                succeed, results = tasaSimpleAlgorithms(motes, local_queue, edges, self.max_assignable_slot, self.start_offset, self.max_assignable_channel)
                repeat_time = 1
                error_rate = 1 - pdr
                while error_rate > 1 - NetworkManager.SCHEDULE_IN_SLOTFRAME_SUCCESS_RATE:
                    repeat_time += 1
                    error_rate *= (1 - pdr)
                new_results = []
                slot_number_list = [e[2] for e in results]
                schedule_length = max(slot_number_list) - min(slot_number_list) + 1
                for item in results:
                    base_slot_offset = item[2] - self.start_offset
                    for i in range(0, repeat_time):
                        new_slot_offset = self.start_offset + schedule_length * i + base_slot_offset
                        new_results.append([item[0], item[1], new_slot_offset, item[3]])
                results = new_results

            elif self._scheduler == "GTASA":
                succeed, results = tasa_pdr_algorithms(motes, local_queue, edges, self.max_assignable_slot, self.start_offset, self.max_assignable_channel, pdr)
                schedule_output = []
                for schedule_item in results:
                    schedule_output.append([
                        schedule_item["from"],
                        schedule_item["to"],
                        schedule_item["slotOffset"],
                        schedule_item["channelOffset"],
                    ])
                results = schedule_output

            else:
                log.error("Cannot find scheduler {0}".format(self._scheduler))

            # results = new_results
            # succeed, results = tasa_pdr_algorithms(motes, local_queue, edges, self.max_assignable_slot, self.start_offset, self.max_assignable_channel, pdr)

            if not succeed:
                log.critical("Scheduler cannot assign all edge!")
            # results = self._simplestAlgorithms(motes, edges, self.max_assignable_slot, self.start_offset, self.max_assignable_channel)
            log.debug("End algorithm")

            # make offset
            for item in results:
                item[2] = (item[2] - self.start_offset) * 2 + self.start_offset

            log.debug("| From |  To  | Slot | Chan |")
            for item in results:
                log.debug("| {0:4} | {1:4} | {2:4} | {3:4} |".format(item[0][-4:], item[1][-4:], item[2], item[3]))
            log.debug("==============================")
            self.scheduleTable = results

            nothing = []    # nothing is prevent eventBus from merge list in results
            self.dispatch(
                signal='scheduleChanged',
                data=(results, nothing)
            )

            # self._sendScheduleTableToMote(motes)
        except:
            log.error("Got Error!")
            import sys
            log.critical("Unexpected error:{0}".format(sys.exc_info()[0]))
            log.critical("Unexpected error:{0}".format(sys.exc_info()[1]))
        self.schedule_running = False

    def _updateRootMoteState_notif(self, sender, signal, data):
        log.debug("Get update root")
        log.debug(data)
        self.dag_root_moteState = data['rootMoteState']
        return

    def _findHopInTree(self, mote, level):
        if level > 100:
            return 0
        for edge in self.edges:
            if edge['u'] == mote:
                return self._findHopInTree(edge['v'], level + 1) + 1
        return 0

    def _checkTopology(self):
        for mote in self.motes:
            if self._findHopInTree(mote, 0) is 0 or self._findHopInTree(mote, 0) > 95:
                if mote[-2:] == '01' or mote[-2:] == '88':  # TODO make it better
                    continue
                else:
                    return False
        return True
