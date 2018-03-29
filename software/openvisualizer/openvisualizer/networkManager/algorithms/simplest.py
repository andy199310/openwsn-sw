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
            if slotOffset not in fromMote and slotOffset not in toMote:

                fromMote[slotOffset] = [1, toMoteKey]
                toMote[slotOffset] = [0, fromMoteKey]
                results.append([fromMoteKey, toMoteKey, slotOffset, 0])
                assigned = True
                break

    return results
