import logging
from threading import Timer

from openvisualizer.moteState import moteState

log = logging.getLogger('simulatorHelper')
log.setLevel(logging.ERROR)
log.addHandler(logging.NullHandler())

from openvisualizer.eventBus import eventBusClient


class SimulatorHelper(eventBusClient.eventBusClient):

    TICK_INTER_SECOND = 5

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
                    'signal': 'targetPackerSniffer',
                    'callback': self._targetPacketSniffer,
                }
            ]
        )

        self.openVisualizerApp = openVisualizerApp

        self.timer = Timer(SimulatorHelper.TICK_INTER_SECOND, self._simulatorHelperTick)
        self.timer.start()


    # ======================== public ==========================================
    def close(self):
        pass

    # ======================== private =========================================
    def _simulatorHelperTick(self):
        log.debug("simulator helper tick!")
        # get current ASN
        if self.dag_root_moteState is not None:
            asn_state = self.dag_root_moteState.getStateElem(self.dag_root_moteState.ST_ASN)
            asn_list = asn_state.data[0]['asn'].asn
            asn = 0
            for asn_item in asn_list:
                asn = asn * 256 + asn_item
            asn_in_second = asn / 100
            log.debug("Current asn: {0}, second: {1}".format(asn, asn_in_second))

            if asn_in_second > 3600:
                log.info("Stop simulation!")
                self.openVisualizerApp.close()
                import os
                import signal
                os.kill(os.getpid(), signal.SIGTERM)
                return

        Timer(SimulatorHelper.TICK_INTER_SECOND, self._simulatorHelperTick).start()

    def _updateRootMoteState_notif(self, sender, signal, data):
        log.debug("Get update root")
        log.debug(data)
        self.dag_root_moteState = data['rootMoteState']
        return

    def _targetPacketSniffer(self, sender, signal, data):
        log.debug("Get sniff packet")
