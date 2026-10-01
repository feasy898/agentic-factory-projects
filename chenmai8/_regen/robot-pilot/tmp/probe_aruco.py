"""探测：OpenCV 5.0 ArUco 对 tests/_place_marker 合成场景（灰底 90、无白留白）的检出行为。"""

import cv2
import numpy as np


def place(scene, marker_id, side, x, y):
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    tile = cv2.aruco.generateImageMarker(dictionary, marker_id, side)
    scene[y : y + side, x : x + side] = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)


scene = np.full((480, 640, 3), 90, np.uint8)
place(scene, 0, 80, 60, 60)
place(scene, 1, 120, 220, 200)
place(scene, 2, 100, 420, 90)
place(scene, 5, 150, 100, 100)  # 未登记
place(scene, 0, 14, 560, 400)  # 过小

gray = cv2.cvtColor(scene, cv2.COLOR_BGR2GRAY)
dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)

for label, params in [
    ("default", cv2.aruco.DetectorParameters()),
]:
    det = cv2.aruco.ArucoDetector(dictionary, params)
    corners, ids, rejected = det.detectMarkers(gray)
    got = sorted(int(np.ravel(i)[0]) for i in ids) if ids is not None else []
    sizes = {}
    if ids is not None:
        for c, i in zip(corners, ids):
            pts = c[0]
            s = sum(float(np.linalg.norm(pts[k] - pts[(k + 1) % 4])) for k in range(4)) / 4.0
            sizes[int(np.ravel(i)[0])] = round(s, 1)
    print(f"{label}: ids={got} sides={sizes} rejected={len(rejected)}")
