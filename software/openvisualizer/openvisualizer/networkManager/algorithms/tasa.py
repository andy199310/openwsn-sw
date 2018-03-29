def tasaSimpleAlgorithms(motes, local_q, edges, max_assignable_slot, start_offset, max_assignable_channel):
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
