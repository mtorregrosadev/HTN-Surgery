# ADR 0002: Relative Z for the standalone browser tracker

## Status

Accepted for the browser tracking experiment. This does not define the
controller or API's metric calibration method.

## Decision

The browser tracker uses a guided three-step flow: start a video source, hold
one detected marker still for eight stable frames, then move it toward or away
from the camera. Its Z readout is the percentage change from that starting
camera distance, computed as `100 × (starting apparent marker size / current
apparent marker size − 1)`. Positive is farther from the camera. The synthetic
demo stays still until calibration succeeds and then changes its apparent size.

The browser must label this value as relative and must not send it as
`positionMm.z` in the normalized tool-sample contract.

## Why

The participant wants calibration without measuring a physical distance or
marker side length. With one ordinary camera and an unknown-size marker on a
phone, the image supplies a scale ratio but no absolute millimetre scale.
Holding the marker still supplies a replaceable starting reference without
claiming metric 3D tracking.

Existing code for metric Z is available when the necessary inputs exist:

- [OpenCV ArUco pose estimation](https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html)
  uses known marker side length plus camera intrinsics and distortion to return
  a translation vector in the chosen length unit.
- [js-aruco POSIT](https://github.com/jcmellado/js-aruco#3d-pose-estimation)
  uses marker size and focal length; `js-aruco2`, already installed here,
  includes `posit2.js`.
- [Luxonis Spatial Location Calculator](https://docs.luxonis.com/software-v3/depthai/examples/spatial_location_calculator/spatial_location_calculator/)
  reads stereo depth and reports spatial Z in millimetres on supported OAK
  hardware.

## Consequences

- The browser can demonstrate toward/away motion with no measurement input.
- Tilting a marker changes its apparent size and can distort the relative Z
  estimate. It remains a browser experiment, not calibrated tool-tip pose.
- The controller's eventual metric tracking should use calibrated marker size
  and camera intrinsics, or the OAK-D stereo depth path, before emitting
  `positionMm` to the API.
