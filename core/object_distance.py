import math
from deep_sort import track
from core.config import cfg
from core.utils import read_class_names

def find_center (xmin,ymin,xmax,ymax):
    # center_x = (int(left)+int(((right-left)/2)))
    # center_y = (int(top)+int(((bottom-top)/2)))
    center_x= int((xmin+xmax)/2)
    center_y= int((ymin+ymax)/2)
    return center_x,center_y


# parameter type : list[tuple())]
def cal_distance(ppl,items):
    dist = 0
    for p in ppl:
        for i in items:
            # x1 p[0]
            # y1 p[1]
            # x2 i[0]
            # y2 i[1]
            a = i[0]-p[0]
            b = i[1]-p[1]
            dist = math.sqrt((a*a)+(b*b))
            # print('distance:',dist)
    return dist


def count_objects(data, by_class = False, allowed_classes = list(read_class_names(cfg.YOLO.CLASSES).values())):
    boxes, scores, classes, num_objects = data

    #create dictionary to hold count of objects
    counts = dict()

    # if by_class = True then count objects per class
    if by_class:
        class_names = read_class_names(cfg.YOLO.CLASSES)

        # loop through total number of objects found
        for i in range(num_objects):
            # grab class index and convert into corresponding class name
            class_index = int(classes[i])
            class_name = class_names[class_index]
            if class_name in allowed_classes:
                counts[class_name] = counts.get(class_name, 0) + 1
            else:
                continue

    # else count total objects found
    else:
        counts['total object'] = num_objects
    
    return counts
