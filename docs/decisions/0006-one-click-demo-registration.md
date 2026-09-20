# One-click demo registration

The physical tracker supports an explicit `one-click-demo` registration for a live prototype demonstration when a desk AprilTag or successful pivot calibration is unavailable.

The learner places the tracked blade tip at the intended virtual origin and presses Space. The tracker records that camera point as the desk origin, retains the nominal desk orientation, records a 15 mm registration uncertainty, and marks samples with `inputMode: demo-registration`.

The tracker HUD labels this mode as `DEMO` with its approximate uncertainty. It is not a measured calibration and must not be represented as one. Pivot, desk-tag, and probe calibration remain the measured paths and retain their 3 mm acceptance limit.
