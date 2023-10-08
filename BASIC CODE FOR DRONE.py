import sys, time
import argparse
sys.path.insert(1, 'modules')

import cv2
import collections

import lidar
import detector_mobilenet as detector
import vision
import control 
import keyboard

parser = argparse.ArgumentParser(description='Drive autonomous')
parser.add_argument('--debug_path', type=str, default="debug/run1", help='debug message name')
parser.add_argument('--mode', type=str, default='flight', help='Switches between flight record and flight visualisation')
parser.add_argument('--control', type=str, default='PID', help='Use PID or P controller' )
args = parser.parse_args()

MAX_FOLLOW_DIST = 2
MAX_ALT =  2.5
MAX_MA_X_LEN = 5
MAX_MA_Z_LEN = 5
MA_X = collections.deque(maxlen=MAX_MA_X_LEN)
MA_Z = collections.deque(maxlen=MAX_MA_Z_LEN)
STATE = "takeoff"
# end config

def setup():
    print("connecting lidar")
    lidar.connect_lidar("/dev/ttyTHS1")

    print("setting up detector")
    detector.initialize_detector()

    print("connecting to drone")
    if args.mode == "flight":
        print("MODE = flight")
        control.connect_drone('/dev/ttyACM0')
    else:
        print("MODE = test")
        control.connect_drone('127.0.0.1:14551')
    
    control.set_flight_altitude(MAX_ALT)

setup()

image_width, image_height = detector.get_image_size()
image_center = (image_width / 2, image_height / 2)
debug_image_writer = cv2.VideoWriter(args.debug_path + ".avi",cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'), 25.0,(image_width,image_height))

control.configure_PID(args.control)
control.initialize_debug_logs(args.debug_path)

def track():
    print("State is TRACKING -> " + STATE)
    while True:

        if keyboard.is_pressed('q'):
            print("Closing due to manual interruption")
            land()

        detections, fps, image = detector.get_detections()

        if len(detections) > 0:
            person_to_track = detections[0]
            
            print(person_to_track)

            person_center = person_to_track.Center

            x_delta = vision.get_single_axis_delta(image_center[0],person_center[0])
            y_delta = vision.get_single_axis_delta(image_center[1],person_center[1])

            lidar_on_target = vision.point_in_rectangle(image_center,person_to_track.Left, person_to_track.Right, person_to_track.Top, person_to_track.Bottom) #check if lidar is pointed on target

            lidar_dist = lidar.read_lidar_distance()[0]
            
            MA_Z.append(lidar_dist)
            MA_X.append(x_delta)

            velocity_z_command = 0
            if lidar_dist > 0 and lidar_on_target and len(MA_Z) > 0:
                
                z_delta_MA = calculate_ma(MA_Z) 
                z_delta_MA = z_delta_MA - MAX_FOLLOW_DIST
                control.setZDelta(z_delta_MA)
                velocity_z_command = control.getMovementVelocityXCommand()

            yaw_command = 0
            if len(MA_X) > 0:
                x_delta_MA = calculate_ma(MA_X)
                control.setXdelta(x_delta_MA)
                yaw_command = control.getMovementYawAngle()

            control.control_drone()
            #draw lidar distance
            prepare_visualisation(lidar_dist, person_center, person_to_track, image, yaw_command, x_delta, y_delta, fps,velocity_z_command, lidar_on_target)
        else:
            return "search"

def search():
    print("State is SEARCH -> " + STATE)
    start = time.time()
    
    control.stop_drone()
    while time.time() - start < 40:
        if keyboard.is_pressed('q'):
            print("Closing due to manual interruption")
            land()

        detections, fps, image = detector.get_detections()
        print("searching: " + str(len(detections)))
        if len(detections) > 0:
            return "track"
        if "test" == args.mode:
            cv2.putText(image, "searching target. Time left: " + str(40 - (time.time() - start)), (50, 50), cv2.FONT_HERSHEY_SIMPLEX , 1, (0, 0, 255), 3, cv2.LINE_AA) 
            visualize(image)

    return "land"

def takeoff():
    control.print_drone_report()
    print("State = TAKEOFF -> " + STATE)
    control.arm_and_takeoff(MAX_ALT)
    return "search"

def land():
    print("State = LAND -> " + STATE)
    control.land()
    detector.close_camera()
    sys.exit(0)

def visualize(img):
    if "flight" == args.mode:
        debug_image_writer.write(img)
    else:
        cv2.imshow("out", img)
        cv2.waitKey(1)
    return

def prepare_visualisation(lidar_distance, person_center, person_to_track, image, yaw_command, x_delta, y_delta, fps,velocity_x_command, lidar_on_target):
    lidar_vis_x = image_width - 50
    lidar_vis_y = image_height - 50
    lidar_vis_y2 = int(image_height - lidar_distance * 200)
    cv2.line(image, (lidar_vis_x,lidar_vis_y), (lidar_vis_x, lidar_vis_y2), (0, 255, 0), thickness=10, lineType=8, shift=0)
    cv2.putText(image, "distance: " + str(round(lidar_distance,2)), (image_width - 300, 200), cv2.FONT_HERSHEY_SIMPLEX , 1, (0, 0, 255), 3, cv2.LINE_AA) 

    cv2.line(image, (int(image_center[0]), int(image_center[1])), (int(person_center[0]), int(person_center[1])), (255, 0, 0), thickness=10, lineType=8, shift=0)

    cv2.rectangle(image,(int(person_to_track.Left),int(person_to_track.Bottom)), (int(person_to_track.Right),int(person_to_track.Top)), (0,0,255), thickness=10)

    cv2.circle(image, (int(image_center[0]), int(image_center[1])), 20, (0, 255, 0), thickness=-1, lineType=8, shift=0)

    cv2.circle(image, (int(person_center[0]), int(person_center[1])), 20, (0, 0, 255), thickness=-1, lineType=8, shift=0)

    cv2.putText(image, "fps: " + str(round(fps,2)) + " yaw: " + str(round(yaw_command,2)) + " forward: " + str(round(velocity_x_command,2)) , (50, 50), cv2.FONT_HERSHEY_SIMPLEX , 1, (0, 0, 255), 3, cv2.LINE_AA) 
    cv2.putText(image, "lidar_on_target: " + str(lidar_on_target), (50, 100), cv2.FONT_HERSHEY_SIMPLEX , 1, (0, 0, 255), 3, cv2.LINE_AA) 
    cv2.putText(image, "x_delta: " + str(round(x_delta,2)) + " y_delta: " + str(round(y_delta,2)), (50, 150), cv2.FONT_HERSHEY_SIMPLEX , 1, (0, 0, 255), 3, cv2.LINE_AA) 

    visualize(image)

def calculate_ma(ma_array):
    sum_ma = 0
    for i in ma_array:
        sum_ma = sum_ma + i

    return sum_ma / len(ma_array)

while True:

    if STATE == "track":
        control.set_system_state("track")
        STATE = track()

    elif STATE == "search":
        control.set_system_state("search")
        STATE = search()
    
    elif STATE == "takeoff":
        STATE = takeoff()

    elif STATE == "land":
        STATE = land()
