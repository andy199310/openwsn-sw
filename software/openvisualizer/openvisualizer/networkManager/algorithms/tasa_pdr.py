import json
import logging
import urllib

log = logging.getLogger('scheduleAlgorithms')
log.setLevel(logging.ERROR)
log.addHandler(logging.NullHandler())


def tasa_pdr_algorithms(motes, local_queue, edges, max_assignable_slot, start_offset, max_assignable_channel, pdr):

    # pdr = 0.7
    mote_default_pdr = 0.8

    url = "http://127.0.0.1/pdr.php"
    response = urllib.urlopen(url)
    mote_pdr_list = json.loads(response.read())

    input_motes = motes
    motes = {}

    # pre-process
    for mote in input_motes:
        parent = None
        for edge in edges:
            if edge["u"] == mote:
                parent = edge["v"]
                break

        mote_pdr = mote_default_pdr
        log.debug(mote)
        if mote in mote_pdr_list:
            mote_pdr = mote_pdr_list[mote]

        motes[mote] = {
            "id": mote,
            "parent": parent,
            "done": False,
            "busy": False,
            "pdr": mote_pdr,
            "local_queue": local_queue[mote],
            "global_queue": local_queue[mote]
        }

    # calculate global_queue
    for key, mote in motes.items():
        current_mote = mote
        while current_mote['parent'] is not None:
            # find next parent
            for small_key, small_mote in motes.items():
                if small_mote['id'] == current_mote['parent']:
                    next_parent = small_mote
                    next_parent['global_queue'] += current_mote['local_queue']
                    current_mote = next_parent
                    break

    all_done = False

    now_slot_offset = start_offset
    now_channel_offset = 0
    got_new_cell = False

    schedule_result = list()

    while not all_done:
        # find largest GQ and LQ >= 1
        largest_global_queue = -1
        target_mote = None
        for key, mote in motes.items():
            if mote['global_queue'] > largest_global_queue and \
                            mote['local_queue'] >= 1 and \
                            mote['busy'] == False and \
                            mote['done'] == False and \
                            mote['parent'] is not None and \
                            motes[mote['parent']]['busy'] == False:
                largest_global_queue = mote['global_queue']
                target_mote = mote

        if target_mote is None:
            largest_local_queue = -1
            for key, mote in motes.items():
                if mote['local_queue'] > largest_local_queue and \
                                mote['busy'] == False and \
                                mote['done'] == False and \
                                mote['parent'] is not None and \
                                motes[mote['parent']]['busy'] == False:
                    largest_local_queue = mote['local_queue']
                    target_mote = mote

        if target_mote is None:
            # cannot find any mote to schedule
            if got_new_cell is True:
                for key, mote in motes.items():
                    mote['busy'] = False
                now_slot_offset += 1
                now_channel_offset = 0
                got_new_cell = False
                continue
            else:
                log.debug("End scheduling")
                break

        # assign schedule

        parent_mote = motes[target_mote['parent']]

        schedule_result.append({
            'slotOffset': now_slot_offset,
            'channelOffset': now_channel_offset,
            'from': target_mote['id'],
            'to': parent_mote['id']
        })

        # modify GQ, LQ
        local_queue_diff = min(1, target_mote['local_queue']) * target_mote['pdr']
        target_mote['local_queue'] = target_mote['local_queue'] - local_queue_diff
        target_mote['global_queue'] = target_mote['global_queue'] - local_queue_diff
        target_mote['busy'] = True

        parent_mote['local_queue'] = parent_mote['local_queue'] + local_queue_diff
        parent_mote['busy'] = True

        if target_mote['local_queue'] < 0.05 and target_mote['global_queue'] < 0.05:
            target_mote['done'] = True
            # remove local queue from all parent path
            target_parent = motes[target_mote['parent']]
            while target_parent is not None:
                target_parent['global_queue'] = target_parent['global_queue'] - target_mote['local_queue']
                if target_parent['parent'] is None:
                    break
                target_parent = motes[target_parent['parent']]

        got_new_cell = True
        now_channel_offset += 1

    return True, schedule_result
