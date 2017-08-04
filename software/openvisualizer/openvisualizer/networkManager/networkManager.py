# this is network manager!

import logging
from threading import Timer

from coap import coap
import operator

from openvisualizer.moteState import moteState

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
            succeed, results = self._tasaSimpleAlgorithms(motes, local_queue, edges, self.max_assignable_slot, self.start_offset, self.max_assignable_channel)
            if not succeed:
                log.critical("Scheduler cannot assign all edge!")
            # results = self._simplestAlgorithms(motes, edges, self.max_assignable_slot, self.start_offset, self.max_assignable_channel)
            log.debug("End algorithm")
            log.debug("| From |  To  | Slot | Chan |")
            for item in results:
                log.debug("| {0:4} | {1:4} | {2:4} | {3:4} |".format(item[0][-4:], item[1][-4:], item[2], item[3]))
            log.debug("==============================")
            self.scheduleTable = results
            self._sendScheduleTableToMote(motes)
        except:
            log.error("Got Error!")
            import sys
            log.critical("Unexpected error:{0}".format(sys.exc_info()[0]))
            log.critical("Unexpected error:{0}".format(sys.exc_info()[1]))
        self.schedule_running = False

    def _sendScheduleTableToMote(self, motes):
        log.debug("Starting sending schedule. Total entry: {0}".format(len(self.scheduleTable)))
        for mote in motes:
            log.debug("Parsing {0}".format(mote))
            entryCount = 0
            is_root = False
            if mote[-2:] == '01' or mote[-2:] == '88' or mote[-4:] == 'a72e':   # TODO make it better
                is_root = True
            entrys = list()

            for schedule in self.scheduleTable:
                entry_type = -1
                neighbor = ''
                if schedule[0] == mote:
                    entry_type = 0x40           # TX
                    neighbor = schedule[1]
                elif schedule[1] == mote:
                    entry_type = 0x00           # RX
                    neighbor = schedule[0]

                if entry_type != -1:
                    schedule_entry = list()
                    schedule_entry.append(schedule[2])  # slot offset
                    schedule_entry.append(schedule[3])  # channel offset
                    schedule_entry.append(entry_type)         # type
                    # address
                    for byte in neighbor.split(':'):
                        schedule_entry.append(int(byte[:2], 16))
                        schedule_entry.append(int(byte[-2:], 16))
                    entrys.append(schedule_entry)

            log.debug("{0} have {1} entry to send. [max entry per packet:{2}]".format(mote, len(entrys), self.max_entry_per_packet))

            payload = list()
            for index in xrange(0, len(entrys), self.max_entry_per_packet):
                packet_sequence = index / self.max_entry_per_packet
                entry_group = entrys[index: index + self.max_entry_per_packet]
                log.debug("Sequence {0} have {1} entry".format(packet_sequence, len(entry_group)))

                # if index % self.max_entry_per_packet == 0:
                payload = list()
                if index == 0:
                    payload.append(0x80)    # first
                else:
                    payload.append(0x00)    # not first

                payload.append(len(entry_group))
                log.debug("Group Entry length: {0}".format(len(entry_group)))

                for entry in entry_group:
                    payload.extend(entry)

                payload = bytearray(payload)
                self._sendPayloadToMote(mote, payload, is_root)

            log.debug("{0} done".format(mote))

        log.debug("All Done!!#########################################")

    def _sendPayloadToMote(self, mote_address, payload, is_root):
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
                coapClient.post(path="green", timeout=20, payload=payload)
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

            log.debug("====================================")
        return

    def _updateRootMoteState_notif(self, sender, signal, data):
        log.debug("Get update root")
        log.debug(data)
        self.dag_root_moteState = data['rootMoteState']
        return

    def _simplestAlgorithms(self, motes, edges, max_assignable_slot, start_offset, max_assignable_channel):
        results = []
        in_motes = {}
        for mote in motes:
            in_motes[mote] = dict()
        for edge in edges:
            fromMote, fromMoteKey = in_motes[edge['u']], edge['u']
            toMote, toMoteKey = in_motes[edge['v']], edge['v']
            assigned = False
            for slotOffset in range(start_offset, start_offset + max_assignable_slot):
                log.debug("Trying: {0}".format(slotOffset))
                if slotOffset not in fromMote and slotOffset not in toMote:
                    log.debug("assign {0} -> {1}, using: {2}".format(fromMoteKey, toMoteKey, slotOffset))

                    fromMote[slotOffset] = [1, toMoteKey]
                    toMote[slotOffset] = [0, fromMoteKey]
                    results.append([fromMoteKey, toMoteKey, slotOffset, 0])
                    assigned = True
                    break
            if assigned == False:
                log.error("Cannot assign! {0}".format(edge))

        log.info("Done calculate!")
        return results

    def _tasaSimpleAlgorithms(self, motes, local_q, edges, max_assignable_slot, start_offset, max_assignable_channel):

        result = []
        edge_relation = {}
        global_q = {}
        children = {}
        leaf = list()

        # prepare data
        for relation in edges:
            edge_relation[relation['u']] = relation['v']
            global_q[relation['u']] = local_q[relation['u']]
            children[relation['v']] = list()  # initialize children, then produce later

        # get childrens
        for child in edges:
            if children[child['v']] != None:
                children[child['v']].append(child['u'])

        # get leafs
        parent = children.keys()
        for item in edges:
            if item['u'] not in parent:
                leaf.append(item['u'])
        # get root
        childTemp = edge_relation.keys()
        parentTemp = children.keys()
        for i in range(0, parentTemp.__len__(), 1):
            if parentTemp[i] not in childTemp:
                root = parentTemp[i]

        # produce global queue
        for nodes in edge_relation:
            now = nodes
            number = local_q[now]
            while now != root:
                # calculate global_q
                if edge_relation[now] != root:
                    global_q[edge_relation[now]] += number
                now = edge_relation[now]

        # get biggest global_q
        sorted_x = sorted(global_q.items(), key=lambda x: (x[1], x[0]), reverse=True)
        # print sorted_x

        # prepare to schedule
        cant_list = []  # check
        schedule_list = []  # prepare for lq & gq calculate
        # node_now = None
        for slotOffset in range(start_offset, start_offset + max_assignable_slot):  # 4-
            # if not sorted_x:#empty means all scheduled
            # break
            for channelOffset in range(0, max_assignable_channel, 1):  # max_assignable_channel
                for check in sorted_x:
                    if check[0] not in cant_list and local_q[check[0]] != 0:
                        temp = [k for k, v in global_q.iteritems() if
                                v == global_q[check[0]] and k not in cant_list]  # get keys by value
                        temp.sort()
                        if temp.__len__() == 1:
                            node_now = temp[0]
                        else:
                            localTemp = []
                            for localQ in temp:
                                if local_q[localQ] != 0:
                                    localTemp.append((localQ, local_q[localQ]))

                            temper = sorted(sorted(localTemp, key=lambda x: x[0]), key=lambda x: x[1],
                                            reverse=True)  # sort x[1], if same,then sort x[0]
                            node_now = temper[0][0]

                        # find node that can't schedule
                        # child_list
                        if node_now in children.keys():
                            for tempCheck in children[node_now]:
                                if tempCheck not in cant_list:
                                    cant_list.append(tempCheck)
                        # parent
                        tempParent = edge_relation[node_now]
                        if tempParent not in cant_list and tempParent != root:
                            cant_list.append(tempParent)
                        # parent's child_list
                        tempChildren = edge_relation[node_now]
                        for tempCheck in children[tempChildren]:
                            if tempCheck not in cant_list:
                                cant_list.append(tempCheck)

                        # record sheduled information
                        result.append([node_now, tempParent, slotOffset, channelOffset])
                        schedule_list.append(node_now)

                        break  # one cell only one, temporally

            # need to calculate lq & gq, and clear  schedule_list & cant_list, and reSorted sorted_x
            # calculate lq & gq
            for calNode in schedule_list:
                # local & global reduce 1 at same time
                local_q[calNode] -= 1
                global_q[calNode] -= 1
                # parent's local plus 1 and global is same
                if edge_relation[calNode] != root:
                    calParentNode = edge_relation[calNode]
                    local_q[calParentNode] += 1

            # clear  schedule_list & cant_list
            del cant_list[:]
            del schedule_list[:]

            # clean sorted_x and reSorted sorted_x and delete if gq = 0
            del sorted_x[:]
            sorted_temp = sorted(global_q.items(), key=operator.itemgetter(1), reverse=True)

            for prepareIn in sorted_temp:
                if prepareIn[1] != 0:
                    sorted_x.append(prepareIn)

            if not sorted_x:  # empty means all scheduled
                break

        if sorted_x:
            # print "not enough"
            return False, result
        else:
            # print "enough"
            return True, result
