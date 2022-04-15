# imports
from calendar import c
from cv2 import log
from configs import config
from configs.mailer import Mailer
from configs.detection import detect_people
from scipy.spatial import distance as dist 
from twilio.rest import Client 
import numpy as np
import argparse
import imutils
import cv2
import os
import pyttsx3
import threading
import time
import json
import csv
import pandas as pd

#analytics
x_value = 0
totalViolations = 0
realtimeFields = ["x_value", "config.Human_Data", "detectedViolators", "totalViolations" ]

with open('realtimeData.csv', 'w') as csv_file:
    csv_writer = csv.DictWriter(csv_file, fieldnames=realtimeFields)
    csv_writer.writeheader()

# Initial list of points for top down view
f = open('test-config.json','r')
TopdownPointConfig = json.loads(f.read())
list_points = list((
    TopdownPointConfig['TopLeft'],
    TopdownPointConfig['TopRight'],
    TopdownPointConfig['BottomLeft'],
    TopdownPointConfig['BottomRight']
))
f.close()
TopLeft_calibrate = False
TopRight_calibrate = False
BottomLeft_calibrate = False
BottomRight_calibrate = False
Calibrate_checker = False

def sms_email_notification():
    Mailer().send(config.MAIL)
    account_sid = 'AC67d82c2b1cf7ae7ddd8bd3e5a2096fd6' 
    auth_token = 'b138eabbee8359096b2376f161147023' 
    client = Client(account_sid, auth_token) 
    message = client.messages.create(  
                                messaging_service_sid='MG6cf9a8edf7c73ae932b2e6ac7ba1eab5', 
                                body='Multiple violators have been identified',      
                                to='+639162367611' 
                            ) 
    
    print(message.sid)


#mouse click callback for top down conversion
def CallBackFunc(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        print("Left button of the mouse is clicked - position (", x, ", ",y, ")")
        global TopLeft_calibrate, TopRight_calibrate, BottomLeft_calibrate, BottomRight_calibrate, Calibrate_checker, list_points
        if TopLeft_calibrate == True:
            list_points[0] = [x,y]
            TopdownPointConfig["TopLeft"] = [x,y]
            f = open("test-config.json", "w")
            json.dump(TopdownPointConfig, f)
            f.close()
            TopLeft_calibrate = False
            Calibrate_checker = False
        if TopRight_calibrate == True:
            list_points[1] = [x,y]
            TopdownPointConfig["TopRight"] = [x,y]
            f = open("test-config.json", "w")
            json.dump(TopdownPointConfig, f)
            f.close()
            TopRight_calibrate = False
            Calibrate_checker = False
        if BottomLeft_calibrate == True:
            list_points[2] = [x,y]
            TopdownPointConfig["BottomLeft"] = [x,y]
            f = open("test-config.json", "w")
            json.dump(TopdownPointConfig, f)
            f.close()
            BottomLeft_calibrate = False
            Calibrate_checker = False
        if BottomRight_calibrate == True:
            list_points[3] = [x,y]
            TopdownPointConfig["BottomRight"] = [x,y]
            f = open("test-config.json", "w")
            json.dump(TopdownPointConfig, f)
            f.close()
            BottomRight_calibrate = False
            Calibrate_checker = False

#text to speech converter
stopFrameCheck = False
def voice_alarm():
    engine = pyttsx3.init()
    # engine.stop()
    voices = engine.getProperty('voices')
    engine.setProperty('voice', voices[1].id)
    engine.setProperty('rate', 150)
    engine.setProperty('volume', 1)
    engine.say("Please observe social distancing")
    engine.runAndWait()

t = threading.Thread(target=voice_alarm)

# construct the argument parser and parse the arguments
ap = argparse.ArgumentParser()
ap.add_argument("-i", "--input", type=str, default="", help="path to (optional) input video file")
ap.add_argument("-o", "--output", type=str, default="", help="path to (optional) output video file")
ap.add_argument("-d", "--display", type=int, default=1, help="whether or not output frame should be displayed")
args = vars(ap.parse_args())

# load the COCO class labels the YOLO model was trained on
labelsPath = os.path.sep.join([config.MODEL_PATH, "coco.names"])
LABELS = open(labelsPath).read().strip().split("\n")

# derive the paths to the YOLO tiny weights and model configuration
# weightsPath = os.path.sep.join([config.MODEL_PATH, "yolov3-tiny.weights"])
# configPath = os.path.sep.join([config.MODEL_PATH, "yolov3-tiny.cfg"])

# derive the paths to the YOLO tiny weights and model configuration
weightsPath = os.path.sep.join([config.MODEL_PATH, "yolov3.weights"])
configPath = os.path.sep.join([config.MODEL_PATH, "yolov3.cfg"])

# load the YOLO object detector trained on COCO dataset (80 classes)
print("[INFO] loading YOLO from disk...")
net = cv2.dnn.readNetFromDarknet(configPath, weightsPath)

# check if GPU is to be used or not
if config.USE_GPU:
    # set CUDA s the preferable backend and target
    print("[INFO] setting preferable backend and target to CUDA...")
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)

# determine only the "output" layer names that we need from YOLO
ln = net.getLayerNames()
ln = [ln[i[0] - 1] for i in net.getUnconnectedOutLayers()]

# initialize the video stream and pointer to output video file
print("[INFO] accessing video stream...")
# open input video if available else webcam stream
vs = cv2.VideoCapture(args["input"] if args["input"] else 0)
writer = None
previousFrameViolation = 0
# loop over the frames from the video stream
while True:
    # num += 1
    # read the next frame from the input video
    (grabbed, orig_frame) = vs.read()
    # if the frame was not grabbed, then that's the end fo the stream 
    if not grabbed:
        break
    
    if (stopFrameCheck == False):
        if (previousFrameViolation != 0):
            frameCounter += 1
        
        else:
            frameCounter = 0
    
    else:
        frameCounter = 0
 
    # resize the frame and then detect people (only people) in it
    frame = imutils.resize(orig_frame, width=1200)
    birdeyeframe= imutils.resize(orig_frame, width=1200)
    results = detect_people(frame, net, ln, personIdx=LABELS.index("person"))

    # initialize the set of indexes that violate the minimum social distance
    violate = set()

    #initialize variables for bird eye conversion
    array_ground_points = list()
    array_boxes = list()

    # ensure there are at least two people detections (required in order to compute the
    # the pairwise distance maps)
    if len(results) >= 2:
        # extract all centroids from the results and compute the Euclidean distances
        # between all pairs of the centroids
        centroids = np.array([r[2] for r in results])
        D = dist.cdist(centroids, centroids, metric="euclidean")

        # loop over the upper triangular of the distance matrix
        for i in range(0, D.shape[0]):
            for j in range(i+1, D.shape[1]):
                # check to see if the distance between any two centroid pairs is less
                # than the configured number of pixels
                if D[i, j] < config.MIN_DISTANCE:
                    # update the violation set with the indexes of the centroid pairs
                    violate.add(i)
                    violate.add(j)
    
    # loop over the results
    for (i, (prob, bbox, centroid)) in enumerate(results):
        # extract teh bounding box and centroid coordinates, then initialize the color of the annotation
        (startX, startY, endX, endY) = bbox
        (cX, cY) = centroid
        array_ground_points.append((cX, endY))
        array_boxes.append((startX,startY,endX,endY))
        color = (0, 255, 0)

        # if the index pair exists within the violation set, then update the color
        if i in violate:
            color = (0, 0, 255)

        # draw (1) a bounding box around the person and (2) the centroid coordinates of the person
        cv2.rectangle(frame, (startX, startY), (endX, endY), color, 2)
        cv2.circle(frame, (cX, cY), 5, color, 1)
        cv2.line(frame, list_points[0], list_points[1], (225,0,0), 1)
        cv2.line(frame, list_points[0], list_points[2], (225,0,0), 1)
        cv2.line(frame, list_points[1], list_points[3], (225,0,0), 1)
        cv2.line(frame, list_points[2], list_points[3], (225,0,0), 1)
    
    #threshold value
    Threshold = "Threshold limit: {}".format(config.Threshold)
    cv2.putText(frame, Threshold, (350, frame.shape[0] - 50),
        cv2.FONT_HERSHEY_SIMPLEX, 0.60, (255, 255, 255), 2)

    # draw the total number of social distancing violations on the output frame
    text = "Social Distancing Violations: {}".format(len(violate))
    detectedViolators = format(len(violate))
    cv2.putText(frame, text, (18, frame.shape[0] - 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    #total no of violations
    totalViolation = "Total Violation Warning: {}".format(totalViolations)
    cv2.putText(frame, totalViolation, (18, frame.shape[0] - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    #frame counter
    frameText = "Frame Counter: {}".format(frameCounter)
    cv2.putText(frame, frameText, (350, frame.shape[0] - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    
    #------------------------------Bird eye----------------------------------------#
    # bird eye view sample 
    if (config.TOP_DOWN):
        #top left
        if (TopLeft_calibrate == True):
            cv2.circle (frame, list_points[0], 5, (0,255,0), -1)
        else:
            cv2.circle (frame, list_points[0], 5, (0,0,255), -1)
        #top right
        if (TopRight_calibrate == True):
            cv2.circle (frame, list_points[1], 5, (0,255,0), -1)
        else:
            cv2.circle (frame, list_points[1], 5, (0,0,255), -1)
        #bottom left
        if (BottomLeft_calibrate == True):
            cv2.circle (frame, list_points[2], 5, (0,255,0), -1)
        else:
            cv2.circle (frame, list_points[2], 5, (0,0,255), -1)
        #bottom right
        if (BottomRight_calibrate == True):
            cv2.circle (frame, list_points[3], 5, (0,255,0), -1)
        else:
            cv2.circle (frame, list_points[3], 5, (0,0,255), -1)
        width = 350
        height = 650

        pts1 = np.float32([list_points[0], list_points[1], list_points[2], list_points[3]])
        pts2 = np.float32([[0,0], [width,0], [0,height], [width,height]])
        matrix = cv2.getPerspectiveTransform(pts1, pts2)
        blank_image = np.zeros((height,width,3), np.uint8)
        result = cv2.warpPerspective(birdeyeframe, matrix, (width, height))
        list_points_to_detect = np.float32(array_ground_points).reshape(-1, 1, 2)
        transformed_points = cv2.perspectiveTransform(list_points_to_detect, matrix)
        transformed_points_list = list()
        for i in range(0,transformed_points.shape[0]):
            transformed_points_list.append([transformed_points[i][0][0],transformed_points[i][0][1]])
        for point in transformed_points_list:
            x,y = point
            BIG_CIRCLE = 40  
            SMALL_CIRCLE = 3
            COLOR = (0, 255, 0)
            if transformed_points_list.index(point) in violate:
                COLOR = (0,0,255)
            cv2.circle(result, (int(x),int(y)), BIG_CIRCLE, COLOR, 2)
            cv2.circle(result, (int(x),int(y)), SMALL_CIRCLE, COLOR, -1)
            
        cv2.imshow("Bird Eye View", result)
    

    #------------------------------Alert function----------------------------------#
    if len(violate) >= config.Threshold:
        if (t.is_alive() == True):
            stopFrameCheck = True
        else:
            t = threading.Thread(target=voice_alarm)
            #t2 = threading.Thread(target=sms_email_notification)
            if config.ALERT:
                if (frameCounter >= config.frameLimit):      
                    totalViolations += 1
                    t.start()     
                    #t2.start()
            stopFrameCheck = False
            

        previousFrameViolation = format(len(violate))
        # cv2.putText(frame, "-ALERT: Violations over limit-", (10, frame.shape[0] - 80),
        #     cv2.FONT_HERSHEY_COMPLEX, 0.60, (0, 0, 255), 2)

    else:
        previousFrameViolation = 0
        
    # check to see if the output frame should be displayed to the screen
    if args["display"] > 0:
        # show the output frame
        cv2.imshow("Output", frame)
        key = cv2.waitKey(1) & 0xFF

        # bind the callback function to window
        cv2.setMouseCallback("Output", CallBackFunc)

        # if the 'q' key is pressed, break from the loop
        if key == ord("q"):
            break

        if key == ord("1"):
            if TopLeft_calibrate == False and Calibrate_checker == False:
                TopLeft_calibrate = True
                Calibrate_checker = True
            elif TopLeft_calibrate == True and Calibrate_checker == True:
                TopLeft_calibrate = False
                Calibrate_checker = False
                
        if key == ord("2"):
            if TopRight_calibrate == False and Calibrate_checker == False:
                TopRight_calibrate = True
                Calibrate_checker = True
            elif TopRight_calibrate == True and Calibrate_checker == True:
                TopRight_calibrate = False 
                Calibrate_checker = False

        if key == ord("3"):
            if BottomLeft_calibrate == False and Calibrate_checker == False:
                BottomLeft_calibrate = True
                Calibrate_checker = True
            elif BottomLeft_calibrate == True and Calibrate_checker == True:
                BottomLeft_calibrate = False
                Calibrate_checker = False

        if key == ord("4"):
            if BottomRight_calibrate == False and Calibrate_checker == False:
                BottomRight_calibrate = True
                Calibrate_checker = True
            elif BottomRight_calibrate == True and Calibrate_checker == True:
                BottomRight_calibrate = False
                Calibrate_checker = False

        # if p is pressed, pause
        if key == ord('p'):
            cv2.waitKey(-1) #wait until any key is pressed
    
    # if an output video file path has been supplied and the video writer ahs not been 
    # initialized, do so now
    if args["output"] != "" and writer is None:
        # initialize the video writer
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(args["output"], fourcc, 25, (frame.shape[1], frame.shape[0]), True)

    # if the video writer is not None, write the frame to the output video file
    if writer is not None:
        # print("[INFO] writing stream to output")
        writer.write(frame)

    with open('realtimeData.csv', 'a') as csv_file:
        csv_writer = csv.DictWriter(csv_file, fieldnames=realtimeFields)

        info = {
            "x_value": x_value,
            "config.Human_Data": config.Human_Data,
            "detectedViolators": detectedViolators,
            "totalViolations": totalViolations,
        }

        csv_writer.writerow(info)
        print(x_value, config.Human_Data, detectedViolators, totalViolations)

        x_value += 1
        config.Human_Data = config.Human_Data
        detectedViolators = detectedViolators
        totalViolations = totalViolations

#Clean up, Free memory
cv2.destroyAllWindows

    
    



