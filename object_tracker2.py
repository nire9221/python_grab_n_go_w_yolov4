import os
# comment out below line to enable tensorflow logging outputs
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import time
import tensorflow as tf
physical_devices = tf.config.experimental.list_physical_devices('GPU')
if len(physical_devices) > 0:
    tf.config.experimental.set_memory_growth(physical_devices[0], True)
from absl import app, flags, logging
from absl.flags import FLAGS
import core.utils as utils
from core.yolov4 import filter_boxes
from tensorflow.python.saved_model import tag_constants
from core.config import cfg
from core.object_distance import *
from PIL import Image
import cv2
import numpy as np
import matplotlib.pyplot as plt
from tensorflow.compat.v1 import ConfigProto
from tensorflow.compat.v1 import InteractiveSession
############ deep sort imports #############
from deep_sort import preprocessing, nn_matching
from deep_sort.detection import Detection
from deep_sort.tracker import Tracker
from tools import generate_detections as gdet
import DBConn as db
import copy
from pose_estimation import skeleton_visualizer, visualization, skeletons
from collections import Counter
import pyrealsense2.pyrealsense2 as rs
# import dlib


flags.DEFINE_string('framework', 'tf', '(tf, tflite, trt')
flags.DEFINE_string('weights', './checkpoints/yolov4-416',
                    'path to weights file')
flags.DEFINE_integer('size', 416, 'resize images to')
flags.DEFINE_boolean('tiny', False, 'yolo or yolo-tiny')
flags.DEFINE_string('model', 'yolov4', 'yolov3 or yolov4')
flags.DEFINE_string('video', '036322250716', 'path to input video or set to 0 for webcam')
flags.DEFINE_string('output', None, 'path to output video')
flags.DEFINE_string('output_format', 'XVID', 'codec used in VideoWriter when saving video to file')
flags.DEFINE_float('iou', 0.50, 'iou threshold')
flags.DEFINE_float('score', 0.50, 'score threshold')
flags.DEFINE_boolean('dont_show', False, 'dont show video output')
flags.DEFINE_boolean('info', True, 'show detailed info of tracked objects')


def main(_argv):
    # Definition of the parameters
    max_cosine_distance = 0.4
    nn_budget = None
    nms_max_overlap = 1.0
    
    # initialize deep sort
    model_filename = 'model_data/mars-small128.pb'
    encoder = gdet.create_box_encoder(model_filename, batch_size=1)
    # calculate cosine distance metric
    metric = nn_matching.NearestNeighborDistanceMetric("cosine", max_cosine_distance, nn_budget)
    # initialize tracker
    tracker = Tracker(metric)

    # load configuration for object detector
    config = ConfigProto()
    config.gpu_options.allow_growth = True
    session = InteractiveSession(config=config)
    STRIDES, ANCHORS, NUM_CLASS, XYSCALE = utils.load_config(FLAGS)
    input_size = FLAGS.size
    video_path = FLAGS.video

    # identify different devices
    ctx = rs.context()
    devices = ctx.query_devices()
    # print(devices[0])

    # Configure streams
    pipeline = rs.pipeline()
    config = rs.config()
    # config.enable_device('036322250716')
    config.enable_device(FLAGS.video)
    # config.enable_stream(rs.stream.pose)

    # begin video capture
    vid = pipeline.start(config)


    # load tflite model if flag is set
    if FLAGS.framework == 'tflite':
        interpreter = tf.lite.Interpreter(model_path=FLAGS.weights)
        interpreter.allocate_tensors()
        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()
        print(input_details)
        print(output_details)
    # otherwise load standard tensorflow saved model
    else:
        saved_model_loaded = tf.saved_model.load(FLAGS.weights, tags=[tag_constants.SERVING])
        infer = saved_model_loaded.signatures['serving_default']

    
    out = None
    
    # get video ready to save locally if flag is set
    if FLAGS.output:
        # by default VideoCapture returns float instead of int
        width = int(vid.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(vid.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = int(vid.get(cv2.CAP_PROP_FPS))
        codec = cv2.VideoWriter_fourcc(*FLAGS.output_format)
        out = cv2.VideoWriter(FLAGS.output, codec, fps, (width, height))


    frame_num = 0
    # while video is running
    while True:
        frameset = pipeline.wait_for_frames()
        if frameset.is_frame(): 
            frame = frameset.get_color_frame()
            frame = np.asanyarray(frame.get_data())
            image = Image.fromarray(frame) 

        else:
            print('Video has ended or failed, try a different video format!')
            break


        frame_num +=1
        # print('Frame #: ', frame_num)
        frame_size = frame.shape[:2]
        image_data = cv2.resize(frame, (input_size, input_size))
        image_data = image_data / 255.
        image_data = image_data[np.newaxis, ...].astype(np.float32)
        start_time = time.time()

        
        # run detections on tflite if flag is set
        if FLAGS.framework == 'tflite':
            interpreter.set_tensor(input_details[0]['index'], image_data)
            interpreter.invoke()
            pred = [interpreter.get_tensor(output_details[i]['index']) for i in range(len(output_details))]
            # run detections using yolov3 if flag is set
            if FLAGS.model == 'yolov3' and FLAGS.tiny == True:
                boxes, pred_conf = filter_boxes(pred[1], pred[0], score_threshold=0.25,
                                                    input_shape=tf.constant([input_size, input_size]))
            else:
                boxes, pred_conf = filter_boxes(pred[0], pred[1], score_threshold=0.25,
                                                    input_shape=tf.constant([input_size, input_size]))
        else:
            batch_data = tf.constant(image_data)
            pred_bbox = infer(batch_data)
            for key, value in pred_bbox.items():
                boxes = value[:, :, 0:4]
                pred_conf = value[:, :, 4:]

        # 가장 높은 score부터 내림차순
        # 선택된 bbox와 나머지 bbox의 iou를 계산하여 iou thredhod (보통 0.5) 이상이면 제거
        # 객체당 하나의 bbox 가 남거나 더이상 계산할 bbox가 없을때까지 반복
        boxes, scores, classes, valid_detections = tf.image.combined_non_max_suppression(
            boxes=tf.reshape(boxes, (tf.shape(boxes)[0], -1, 1, 4)),
            scores=tf.reshape(
                pred_conf, (tf.shape(pred_conf)[0], -1, tf.shape(pred_conf)[-1])),
            max_output_size_per_class=50,
            max_total_size=50,
            iou_threshold=FLAGS.iou,
            score_threshold=FLAGS.score
        )

        # convert data to numpy arrays and slice out unused elements
        num_objects = valid_detections.numpy()[0]
        bboxes = boxes.numpy()[0]
        bboxes = bboxes[0:int(num_objects)]
        scores = scores.numpy()[0]
        scores = scores[0:int(num_objects)]
        classes = classes.numpy()[0]
        classes = classes[0:int(num_objects)]

################################## bounding box format #############################################  
        # format bounding boxes from normalized ymin, xmin, ymax, xmax ---> xmin, ymin, width, height
        original_h, original_w, _ = frame.shape
        bboxes = utils.format_boxes(bboxes, original_h, original_w)

        # store all predictions in one parameter for simplicity when calling functions
        pred_bbox = [bboxes, scores, classes, num_objects]

        # read in all class names from config
        class_names = utils.read_class_names(cfg.YOLO.CLASSES)

        # by default allow all classes in .names file
        # allowed_classes = list(class_names.values())
        
        # custom allowed classes (uncomment line below to customize tracker for only people)
        allowed_classes = ['person','cup','cell phone']

        # loop through objects and use class index to get class name, allow only classes in allowed_classes list
        names = []
        deleted_indx = []
        for i in range(num_objects):
            class_indx = int(classes[i])
            class_name = class_names[class_indx]
            if class_name not in allowed_classes:
                deleted_indx.append(i)
            else:
                names.append(class_name)
        names = np.array(names)
        # count = len(names)

                
        # delete detections that are not in allowed_classes
        bboxes = np.delete(bboxes, deleted_indx, axis=0)
        scores = np.delete(scores, deleted_indx, axis=0)

        # encode yolo detections and feed to tracker
        features = encoder(frame, bboxes)
        detections = [Detection(bbox, score, class_name, feature) for bbox, score, class_name, feature in zip(bboxes, scores, names, features)]

        #initialize color map
        cmap = plt.get_cmap('tab20b')
        colors = [cmap(i)[:3] for i in np.linspace(0, 1, 20)]

        # run non-maxima supression
        boxs = np.array([d.tlwh for d in detections])
        scores = np.array([d.confidence for d in detections])
        classes = np.array([d.class_name for d in detections])
        indices = preprocessing.non_max_suppression(boxs, classes, nms_max_overlap, scores)
        detections = [detections[i] for i in indices]       

        # Call the tracker
        tracker.predict()  #Kalman filter
        tracker.update(detections)

#################################### tracking + update cart ######################################
        idx=0
        person_list=[] # person center point
        item_list=[] # item center pint 
        track_ids =[]  
        track_cart = {} 
        cart_list=[]
        # update tracks
        for track in tracker.tracks:
            if not track.is_confirmed() or track.time_since_update > 1:
                continue 
            bbox = track.to_tlbr() 
            class_name = track.get_class()
            center_point = find_center(int(bbox[0]),int(bbox[1]),int(bbox[2]),int(bbox[3]))
            counted_classes = count_objects(pred_bbox, by_class = True, allowed_classes=track.class_name)

            color = colors[int(track.track_id) % len(colors)]
            color = [i * 255 for i in color]
            #draw bounding box 
            cv2.rectangle(frame, (int(bbox[0]), int(bbox[1])), (int(bbox[2]), int(bbox[3])), color, 1)
            #draw center point
            cv2.circle(frame, center_point ,5,color,-1)
            
            #center point list
            if track.class_name == 'person':
                person_list.append(center_point)
                #left-up text
                cv2.putText(frame, "{} id {} is being tracked ".format(track.class_name, str(track.track_id)), (5, 35+idx), cv2.FONT_HERSHEY_COMPLEX_SMALL, 1, (255,0, 0), 1)
                idx+=18
                track_ids.append(track.track_id)
                track_cart = {'user id' :track_ids, 'cart' : cart_list}

################################## face recognition ##############################
                # facedetector = dlib.get_frontal_face_detector()
                # faceRects = facedetector(frame)
                # for det in faceRects :
                #     x = det.left()
                #     y = det.top()
                #     w = det.right()
                #     h = det.bottom()
                #     cv2.rectangle(frame,(x,y),(w, h),(255,0,0),2)
##################################################################################                

            if track.class_name != 'person':
                item_list.append(center_point)
                for p in person_list:
                    for i in item_list:
                        # get distance btw person & items
                        if cal_distance(person_list,item_list) < 300.0 : 
                            #draw line between centerpoints
                            cv2.line(frame,(p[0],p[1]), (i[0],i[1]), color,2)
                            # add to cart
                            cart_list.append(counted_classes)
                            cart_list = list(map(dict, set(tuple(sorted(d.items())) for d in cart_list)))
                            track_cart.update(cart=cart_list)
                            print('track_carts', track_cart)
                            
                            # print('cart_list', cart_list)
                            cv2.putText(frame, "customer {} 's cart - {} : {}".format(track_cart['user id'],list(counted_classes.keys()),list(counted_classes.values())), (5, 75), cv2.FONT_HERSHEY_COMPLEX_SMALL, 1, (255,0, 0), 1)
            
            
                # db.add_to_cart(track_cart['user id'],track.class_name,list(counted_classes.values()))


                        #     ########## load user_id & cart_id based on track id ##########
                        #     ### when login_session is true  ==> cart_id will be created #### 
                            
                            
                            ########### add cart_detail to db ############## 
                            # ==> if class_name exists, just updates count 
                            #      else add/update class_name + count 
                            
            
                            # track_ids =[]  
                            # track_cart = {} 
                            # cart_list=[]

                            # track ids [
                            #            track_id1{[                           #1) track ids[0], 2) K : track ids[0] / V : [], 3) V=[{K=class_name : V=count}, {K,V ..} ]
                            #                      {class_name1 : 3}, 
                            #                      {class_name2 : 2}...]
                            #                     }
                            #            track_id2{                                #track ids[1] 
                            #                     ............
                            #                     }
                            #           ]

                        
            #????
            cv2.rectangle(frame, (int(bbox[0]), int(bbox[1]-30)), (int(bbox[0])+(len(class_name)+len(str(track.track_id)))*17, int(bbox[1])), color, -1)
            #annotation box
            cv2.putText(frame, class_name + "::: " + str(track.track_id),(int(bbox[0]), int(bbox[1]-10)),0, 0.75, (0,255,0),1)


     
            #(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))  xmin,ymin,xmax,ymax                  
            # if FLAGS.info:
            #     print("Tracker ID: {}, Class: {},  BBox Coords (xmin, ymin, xmax, ymax): {}".format(str(track.track_id), class_name, (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))))


        # calculate frames per second of running detections
        fps = 1.0 / (time.time() - start_time)
        # print("FPS: %.2f" % fps)
        result = np.asarray(frame)
        result = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)


        # Show images
        # cv2.namedWindow('RealSense', cv2.WINDOW_AUTOSIZE)
        # cv2.imshow('RealSense', frame)
        
        if not FLAGS.dont_show:
            cv2.imshow("Output Video", result)
        
        # if output flag is set, save video file
        if FLAGS.output:
            out.write(result)

        if cv2.waitKey(1) & 0xFF == ord('q'): break
    pipeline.stop()

if __name__ == '__main__':
    try:
        app.run(main)
    except SystemExit:
        pass