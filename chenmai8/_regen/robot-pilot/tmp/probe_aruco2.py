"""探测 2：预二值化（非黑→白）+ 自适应窗口扩展，对测试合成场景的检出行为。"""

import cv2
import numpy as np


def place(scene, marker_id, side, x, y):
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    tile = cv2.aruco.generateImageMarker(dictionary, marker_id, side)
    scene[y : y + side, x : x + side] = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)


def scene3():
    s = np.full((480, 640, 3), 90, np.uint8)
    place(s, 0, 80, 60, 60)
    place(s, 1, 120, 220, 200)
    place(s, 2, 100, 420, 90)
    return s


def report(label, gray, dictionary):
    params = cv2.aruco.DetectorParameters()
    params.adaptiveThreshWinSizeMin = 13
    params.adaptiveThreshWinSizeMax = 151
    params.adaptiveThreshWinSizeStep = 10
    params.minMarkerPerimeterRate = 0.02
    params.perspectiveRemovePixelPerCell = 8
    det = cv2.aruco.ArucoDetector(dictionary, params)
    corners, ids, _ = det.detectMarkers(gray)
    out = {}
    if ids is not None:
        for c, i in zip(corners, ids):
            pts = c[0]
            side = sum(float(np.linalg.norm(pts[k] - pts[(k + 1) % 4])) for k in range(4)) / 4.0
            out[int(np.ravel(i)[0])] = round(side, 1)
    print(f"{label}: {out}")


dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
BIN_THR = 45

s = scene3()
report("raw    ", cv2.cvtColor(s, cv2.COLOR_BGR2GRAY), dictionary)
bina = cv2.threshold(cv2.cvtColor(s, cv2.COLOR_BGR2GRAY), BIN_THR, 255, cv2.THRESH_BINARY)[1]
report("binariz", bina, dictionary)

# 灰度输入、空场景、未登记码、过小码
g = cv2.cvtColor(scene3(), cv2.COLOR_BGR2GRAY)
report("gray-in", cv2.threshold(g, BIN_THR, 255, cv2.THRESH_BINARY)[1], dictionary)

empty = np.full((480, 640, 3), 90, np.uint8)
report("empty  ", cv2.threshold(cv2.cvtColor(empty, cv2.COLOR_BGR2GRAY), BIN_THR, 255, cv2.THRESH_BINARY)[1], dictionary)

unreg = np.full((480, 640, 3), 90, np.uint8)
place(unreg, 5, 150, 100, 100)
report("id5@150", cv2.threshold(cv2.cvtColor(unreg, cv2.COLOR_BGR2GRAY), BIN_THR, 255, cv2.THRESH_BINARY)[1], dictionary)

small = np.full((480, 640, 3), 90, np.uint8)
place(small, 0, 14, 100, 100)
report("id0@14 ", cv2.threshold(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), BIN_THR, 255, cv2.THRESH_BINARY)[1], dictionary)
