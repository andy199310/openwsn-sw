import logging

from openvisualizer.networkManager.algorithms.tasa_pdr import tasa_pdr_algorithms

old_schedule_result = []
old_link_usage = {}
first_time_run = True

log = logging.getLogger('scheduleAlgorithms')
log.setLevel(logging.ERROR)
log.addHandler(logging.NullHandler())


def tasa_pdr_inc_algorithms(motes, local_queue, edges, max_assignable_slot, start_offset, max_assignable_channel, pdr, app):
    global old_link_usage
    global old_schedule_result
    global first_time_run

    if len(edges) < 6:
        log.warning("Stop by TASA_pdr_INC! not complete!")
        return False, []
    else:
        # set 8, 9 link up
        if first_time_run:
            app.simengine.propagation.createConnection(4, 8)
            app.simengine.propagation.updateConnection(4, 8, pdr)
            app.simengine.propagation.createConnection(5, 9)
            app.simengine.propagation.updateConnection(5, 9, pdr)


    # use new topology to get new schedule table
    succeed, new_schedule_table = tasa_pdr_algorithms(motes, local_queue, edges, max_assignable_slot, start_offset, max_assignable_channel, pdr)

    # first time schedule
    if len(old_schedule_result) == 0:
        log.info("Use new schedule table!")
        new_schedule_table = _stretch_schedule_table(new_schedule_table, max_assignable_slot, start_offset)
        old_schedule_result = new_schedule_table
        old_link_usage = {}
        for item in old_schedule_result:
            dict_key = '_'.join([item['from'], item['to']])
            if dict_key not in old_link_usage:
                old_link_usage[dict_key] = 0
            old_link_usage[dict_key] += 1
        return succeed, new_schedule_table

    # get link usage
    new_link_usage = {}
    for item in new_schedule_table:
        dict_key = '_'.join([item['from'], item['to']])
        if dict_key not in new_link_usage:
            new_link_usage[dict_key] = 0
        new_link_usage[dict_key] += 1

    # compare new and old link usage
    log.debug("Old link")
    log.debug(old_link_usage)
    log.debug("new link")
    log.debug(new_link_usage)

    for key, use_count in new_link_usage.items():

        if key in old_link_usage:
            log.debug("Old")
            log.debug("N: {0}, O: {1}".format(use_count, old_link_usage[key]))
            # the link is exist in old schedule table
            if use_count > old_link_usage[key]:
                # need more link
                transmitter, receiver = key.split('_')
                add_succeed = _add_exist_link_to_schedule(transmitter, receiver, use_count - old_link_usage[key], start_offset, max_assignable_slot)
                continue

            elif use_count < old_link_usage[key]:
                # remove link
                pass

        if key not in old_link_usage:
            log.debug("New")
            # new link, add all link before RX's first TX
            transmitter, receiver = key.split('_')
            add_succeed = _add_new_link_to_schedule(transmitter, receiver, use_count, start_offset, max_assignable_slot)
            continue

    old_link_usage = {}
    for item in old_schedule_result:
        dict_key = '_'.join([item['from'], item['to']])
        if dict_key not in old_link_usage:
            old_link_usage[dict_key] = 0
        old_link_usage[dict_key] += 1

    return True, old_schedule_result


def _stretch_schedule_table(origin_schedule_table, max_assignable_slot, start_offset):
    origin_schedule_slot_list = [e['slotOffset'] for e in origin_schedule_table]
    origin_max_slot_offset = max(origin_schedule_slot_list)
    origin_min_slot_offset = min(origin_schedule_slot_list)

    origin_schedule_length = origin_max_slot_offset - origin_min_slot_offset + 1

    assignable_slot_length = int(max_assignable_slot * 0.75)

    stretch_gap = int(assignable_slot_length / origin_schedule_length) - 1
    new_start_offset = int((max_assignable_slot - assignable_slot_length) / 2) + start_offset

    stretched_schedule_table = []
    for item in origin_schedule_table:
        old_slot_offset = item['slotOffset']
        new_slot_offset = (old_slot_offset - start_offset) * stretch_gap + new_start_offset
        stretched_schedule_table.append({
            'slotOffset': new_slot_offset,
            'channelOffset': item['channelOffset'],
            'from': item['from'],
            'to': item['to']
        })

    return stretched_schedule_table


def _add_new_link_to_schedule(link_transmitter, link_receiver, link_count, start_offset, max_assignable_slot):
    global old_schedule_result

    # get link receiver's first TX
    filter_entry = [e for e in old_schedule_result if e['from'] == link_receiver]
    first_tx_offset = min([e['slotOffset'] for e in filter_entry])

    for current_slot_offset in range(first_tx_offset, start_offset, -1):
        # find conflict
        conflict_entry = [e for e in old_schedule_result
                          if (e['from'] == link_receiver or e['to'] == link_receiver)
                          and e['slotOffset'] == current_slot_offset]

        if len(conflict_entry) == 0:
            # can assign to this slot
            same_slot_entry = [e for e in old_schedule_result
                               if e['slotOffset'] == current_slot_offset]
            same_slot_entry_channel_list = [e['channelOffset'] for e in same_slot_entry]

            for current_channel_offset in range(0, max_assignable_slot, 1):
                if current_channel_offset in same_slot_entry_channel_list:
                    continue
                else:
                    log.info("Add {}->{} inc to {} / {}".format(link_transmitter, link_receiver, current_slot_offset, current_channel_offset))
                    link_count -= 1
                    old_schedule_result.append({
                        'slotOffset': current_slot_offset,
                        'channelOffset': current_channel_offset,
                        'from': link_transmitter,
                        'to': link_receiver
                    })
                    break

        if link_count <= 0:
            return True

    return False


def _add_exist_link_to_schedule(link_transmitter, link_receiver, link_count, start_offset, max_assignable_slot):
    global old_schedule_result

    # get link receiver's last TX
    filter_entry = [e for e in old_schedule_result if e['from'] == link_transmitter]
    last_tx_offset = max([e['slotOffset'] for e in filter_entry])

    for current_slot_offset in range(last_tx_offset, start_offset + max_assignable_slot, 1):
        # find conflict
        conflict_entry = [e for e in old_schedule_result
                          if (e['from'] == link_receiver or e['to'] == link_receiver or e['from'] == link_transmitter or e['to'] == link_transmitter)
                          and e['slotOffset'] == current_slot_offset]

        if len(conflict_entry) == 0:
            # can assign to this slot
            same_slot_entry = [e for e in old_schedule_result
                               if e['slotOffset'] == current_slot_offset]
            same_slot_entry_channel_list = [e['channelOffset'] for e in same_slot_entry]

            for current_channel_offset in range(0, max_assignable_slot, 1):
                if current_channel_offset in same_slot_entry_channel_list:
                    continue
                else:
                    log.info("Add {}->{} inc to {} / {}".format(link_transmitter, link_receiver, current_slot_offset, current_channel_offset))
                    link_count -= 1
                    old_schedule_result.append({
                        'slotOffset': current_slot_offset,
                        'channelOffset': current_channel_offset,
                        'from': link_transmitter,
                        'to': link_receiver
                    })
                    break

        if link_count <= 0:
            return True

    return False


def _remove_exist_link_to_schedule(link_transmitter, link_receiver, remove_link_count, start_offset, max_assignable_slot):
    global old_schedule_result

    # get link transmitter's first TX
    filter_entry = [e for e in old_schedule_result if e['from'] == link_transmitter]
    tx_offset_list = [e['slotOffset'] for e in filter_entry]

    # TODO remove exist

    return
