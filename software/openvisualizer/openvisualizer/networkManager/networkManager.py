# this is network manager!

import logging
from threading import Timer

from coap import coap
import operator

from openvisualizer.moteState import moteState
from openvisualizer.networkManager.algorithms.tasa import tasaSimpleAlgorithms

log = logging.getLogger('networkManager')
log.setLevel(logging.ERROR)
log.addHandler(logging.NullHandler())

from openvisualizer.eventBus import eventBusClient


class NetworkManager(eventBusClient.eventBusClient):

    def __init__(self):
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
        self.max_assignable_slot = 80
        self.start_offset = 20
        self.max_assignable_channel = 16
        self.lastNetworkUpdateCounter = 0
        self.max_entry_per_packet = 2
        self.motes = None
        self.edges = None
        self.scheduleTable = []
        self.dag_root_moteState = None
        self.schedule_back_off = 1
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
            succeed, results = tasaSimpleAlgorithms(motes, local_queue, edges, self.max_assignable_slot, self.start_offset, self.max_assignable_channel)
            if not succeed:
                log.critical("Scheduler cannot assign all edge!")
            # results = self._simplestAlgorithms(motes, edges, self.max_assignable_slot, self.start_offset, self.max_assignable_channel)
            log.debug("End algorithm")

            # make offset
            # for item in results:
            #     item[2] = (item[2] - self.start_offset) * 3 + self.start_offset

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

    def _findHopInTree(self, mote):
        for edge in self.edges:
            if edge['u'] == mote:
                return self._findHopInTree(edge['v']) + 1
        return 0

    def _checkTopology(self):
        for mote in self.motes:
            if self._findHopInTree(mote) is 0:
                if mote[-2:] == '01' or mote[-2:] == '88':  # TODO make it better
                    continue
                else:
                    return False
        return True
