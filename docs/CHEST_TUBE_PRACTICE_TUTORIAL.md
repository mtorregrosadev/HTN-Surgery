# Chest-tube access: practice tutorial

A step-by-step guide for practising chest-tube access on the Surge Prep trainer, using the AprilTag +
FSR scalpel (`hardware/`) or the WASD keyboard fallback.

> **Training prototype only.** This is not a medical device. It never replaces qualified instruction, supervised
> simulation, or clinical judgment. Use it only on the synthetic surface and virtual anatomy. Never attach the
> electronics to a real clinical instrument and never use it on a person. The exercise definition
> (`models/exercises/chest-tube-access-demo.json`) is marked *draft, instructor review required*: have an instructor
> check the landmarks and technique against your local guideline before relying on this tutorial.

---

## Contents

1. [What you will learn](#1-what-you-will-learn)
2. [Before you start: setup checklist](#2-before-you-start-setup-checklist)
3. [Know the anatomy](#3-know-the-anatomy)
4. [Know the equipment](#4-know-the-equipment)
5. [Calibrate your hand: force to depth](#5-calibrate-your-hand-force-to-depth)
6. [Warm-up drills](#6-warm-up-drills)
7. [The procedure, stage by stage](#7-the-procedure-stage-by-stage)
8. [Common mistakes and how to fix them](#8-common-mistakes-and-how-to-fix-them)
9. [How you are scored](#9-how-you-are-scored)
10. [Practice plan: from first session to fluent](#10-practice-plan-from-first-session-to-fluent)
11. [Troubleshooting the rig](#11-troubleshooting-the-rig)
12. [Glossary](#12-glossary)
13. [References](#13-references)

---

## 1. What you will learn

By the end of this tutorial you should be able to:

- Find a safe entry point on the lateral chest wall and keep the scalpel aligned to it.
- Make a controlled skin incision of the right length, in the right place, at the right depth.
- Open the soft-tissue tract with blunt dissection without cutting where you should be spreading.
- Recognise each tissue layer by its depth and by how much pressure it takes to go through.
- Enter the pleural layer deliberately, and only after the tract above it is open.
- Place the chest tube through the tract you made.
- Read your scorecard and know which habit to change next.

The goal is **controlled, repeatable technique**, not speed.

## 2. Before you start: setup checklist

| Check | How to confirm |
| --- | --- |
| SOFA backend is running | HUD shows **SOFA NATIVE** (green). **SOFA OFFLINE** means start `scripts/start-showcase.sh`. |
| Scene was rebuilt | `Surge Prep -> Build Chest-Tube Showcase` was run once after pulling the latest code. |
| ESP32-C3 is sending force | Arduino Serial Monitor (115200 baud) shows `F,<number>` rising as you press the FSR. Close it before running the bridge. |
| Bridge is running | `python hardware/tag_fsr_bridge.py --port COM3` shows `tags=3` while the scalpel is in view. |
| Tags 1, 2, 3 are visible | Green outlines and IDs on all three tags in the bridge window. |
| Origin is set | Rest the scalpel over the middle of the practice area and press `z` in the bridge window. |
| FSR is zeroed | With nothing pressed, press `c` in the bridge window. |
| HUD status | Should read *LIVE - AprilTag position, FSR cut depth*. If it says WASD fallback, Unity is not receiving the bridge. |

No hardware? Run `python hardware/tag_fsr_bridge.py --simulate` (mouse moves the scalpel, hold the left button to press)
or use WASD in Unity: `W/A/S/D` or arrows move, `Q`/`E` raise and lower, `1`/`2`/`3` switch tools, `R` twice resets.

**Good lighting matters.** AprilTags need even, glare-free light and a flat, unwrinkled print. If tracking flickers,
fix the lighting before anything else.

## 3. Know the anatomy

You are practising **lateral chest-wall access**, the way a chest drain is normally placed for a collapsed lung or
fluid around the lung. The simulated chest wall is a layered slab, 32 mm deep in total:

```text
 depth below skin surface
   0 mm  ──────────────  Skin                       (0 to 3 mm)      cut with the scalpel
   3 mm  ──────────────  Subcutaneous fat            (3 to 15 mm)    open with blunt dissection
  15 mm  ──────────────  Intercostal muscle          (15 to 25 mm)   open with blunt dissection
  25 mm  ──────────────  Pleura                      (25 to 32 mm)   enter deliberately, once
  32 mm  ──────────────  pleural floor (fixed - you cannot go past it)
```

### Landmarks

Chest drains are conventionally placed in the **"safe triangle"** on the side of the chest. Have your instructor
confirm the landmarks for your local guideline. The commonly taught boundaries are:

- **Front edge:** the lateral border of the pectoralis major muscle.
- **Back edge:** the anterior border of the latissimus dorsi muscle.
- **Bottom edge:** a horizontal line at the level of the nipple (roughly the 5th intercostal space).
- **Top edge:** the base of the axilla (armpit).

In the simulator, the practice target is the highlighted window on the lateral chest. It is marked as illustrative:
it is *not* the centre or front of the chest.

### Why the rib matters

Each rib has a **neurovascular bundle** (vein, artery, nerve) running along its **lower edge**. That is why the tract
goes in **just above the top of the lower rib**, never along the underside of the rib above. In the simulator the
ribs are protected geometry: the blade cannot pass through them, so if it stops on a rib, reposition above it.

### Practice-field limits

- The whole patch is 80 x 72 mm, but only the inner ellipse (about 30 mm left/right, 22 mm up/down from the target)
  can be cut. Cuts outside it are ignored to keep the fixed boundary stable.
- The intended incision corridor is 36 mm long and 12 mm wide (6 mm either side of the centre line).

## 4. Know the equipment

Press `1`, `2`, `3` on the keyboard to change tool, in the order you use them:

| Key | Tool | What it does | Used for |
| --- | --- | --- | --- |
| `1` | **Scalpel** | Cuts. Position comes from the AprilTags, depth from the FSR. | Skin incision |
| `2` | **Blunt dissector** | Spreads tissue without cutting it. | Opening fat and muscle, then the pleura |
| `3` | **Chest tube** | The drain itself. | Final placement through the open tract |

### How the hardware maps to the virtual scalpel

- **Where the scalpel is** over the skin comes from the centroid of AprilTags 1, 2 and 3. Move the handle left,
  right, up or down and the virtual scalpel follows. Losing the tags holds the last position and lifts the blade.
- **How deep it goes** comes from the FSR. Light pressure = shallow. Harder pressure = deeper. Releasing the pressure
  lifts the blade back above the skin.

Nothing in Unity decides the cut. Unity sends a pose and force through the controller and API, and SOFA decides contact
and carving.

## 5. Calibrate your hand: force to depth

With the default settings (`hoverMm = 6`, `maxDepthMm = 32`, `deadband = 0.08`), the FSR reading (0 = untouched,
1 = your hardest press, after `--fsr-max` scaling) maps to depth like this:

| Target | Depth reached | Approx. FSR reading (0 to 1) | How it should feel |
| --- | --- | --- | --- |
| Hovering | 6 mm above skin | below 0.08 | Fingers resting on the handle, no press |
| Touching skin | 0 mm | about 0.15 | The lightest press that registers |
| Through skin | 3 mm | about 0.30 | Light, deliberate press |
| Through fat | 15 mm | about 0.59 | Moderate press |
| Through muscle | 25 mm | about 0.83 | Firm press |
| Pleural floor | 32 mm | 1.00 | Full press: this is the limit, not a target |

**Do this once per session:** in the HUD, slowly increase pressure over the practice patch and note where each layer
opens. If your layers open earlier or later than the table, adjust `--fsr-max` on the bridge (raise it if you reach
full depth too easily, lower it if you cannot get deep enough) or `maxDepthMm` / `deadband` in the `TagFsrInput`
inspector.

**The most important habit in this whole tutorial:** *the FSR is a depth control, not a "cut harder" control.* You
choose a depth and hold it. Pressing harder than you meant sends the blade into the layer below.

## 6. Warm-up drills

Do these before the full procedure. Each takes a few minutes. Press `R` twice to reset between drills.

### Drill A: Hover and land

1. Hold the scalpel over the centre of the window, pressing nothing.
2. Press until the HUD shows first contact, then release completely.
3. Repeat 10 times. Aim for contact with **no** cut through the skin.

*Pass:* 10 touches, 0 unintended cuts.

### Drill B: Depth ladder

1. Press to skin depth (about 3 mm) and hold for 2 seconds. Release.
2. Press to about 8 mm (into fat) and hold for 2 seconds. Release.
3. Press to about 15 mm and hold. Release.

*Pass:* You can hit each depth within about 2 mm three times in a row. Watch the tool depth, not your hand.

### Drill C: The straight line

1. Press to skin depth and hold steady.
2. Move the scalpel along the highlighted corridor, left to right, without changing pressure.
3. Lift off at the end.

*Pass:* The line stays inside the corridor and the cut depth stays constant from start to end.

### Drill D: Lift and reposition

1. Cut a short line, then **release fully** before moving.
2. Reposition and cut a second line.

*Pass:* The two cuts stay separate. Dragging while still pressing carves a connecting groove, which is the classic
beginner mistake.

## 7. The procedure, stage by stage

The HUD shows your current stage and an instruction. The stages are, in order:

`Approach` -> `Skin incision` -> `Blunt dissection` -> `Pleural entry` -> `Tube placement` -> `Complete`

### Stage 1: Approach and landmark alignment

**Goal:** get the scalpel over the right spot without touching anything you shouldn't.

1. Start with the scalpel (`1`), hovering above the skin.
2. Move over the highlighted lateral intercostal window.
3. Check your position relative to the target guide before you descend.
4. Confirm you are above the **top of the lower rib** and away from protected rib geometry.

**Do:** slow, small movements. Pause and check. **Avoid:** descending while still moving.

*You are done when:* the scalpel is aligned over the corridor start and the HUD shows **Approach** or
**Landmark alignment**.

### Stage 2: Controlled skin incision

**Goal:** a clean cut through the skin only, along the corridor.

1. Lower slowly until the skin deforms. This is first contact.
2. Increase pressure to skin depth (about 3 mm, FSR about 0.30). **Stop there.**
3. Travel along the corridor at a slow, steady speed. Aim for the full 36 mm without leaving the 12 mm-wide
   corridor.
4. Lift off completely at the end.

**What good looks like:** one continuous, even line, in the corridor, through skin only. The skin edges gape and curl
slightly, and pink tissue is visible below.

**Depth check:** if you can see yellow (fat) along the whole line, you went too deep. Reset and lighten your press.

### Stage 3: Blunt dissection (fat, then muscle)

**Goal:** open the tract *without cutting*. Spreading tissue apart, not slicing it.

1. Press `2` to switch to the **blunt dissector**.
2. Enter the incision. Press gently into the fat layer (to about 15 mm).
3. Work the tract open along the corridor with small, controlled movements.
4. Continue down through the intercostal muscle (to about 25 mm). Stay above the rib.
5. Stop once the muscle layer is open along the tract. **Do not go into the pleura yet.**

**Why blunt?** Blunt spreading keeps the vessels and nerve running along the rib's lower border intact. Cutting them
is what you are training yourself *not* to do.

**Layer discipline:** the simulator tracks which layer you are in. Opening a layer out of order counts as a **layer
violation**.

### Stage 4: Controlled pleural entry

**Goal:** enter the pleural layer once, deliberately, at a controlled speed.

1. Confirm the soft-tissue tract above is open. The pleura only opens **after** the layers above it.
2. Press slowly through the last few millimetres (25 to 32 mm, FSR about 0.83 to 1.0).
3. Stop as soon as the pleura opens. Do not push to the floor.
4. Release and withdraw smoothly.

**Warning sign:** a sudden lunge is the failure this stage trains against. In real practice, uncontrolled entry
risks injuring the lung and the structures beneath it. Here it costs you controlled-force points.

### Stage 5: Tube placement

**Goal:** pass the chest tube through the tract you made.

1. Press `3` to select the **chest tube**.
2. Line the tube up with the open tract.
3. Guide it through skin, fat, muscle and pleura in one smooth motion.
4. Stop when the HUD shows the tube is in place.

### Stage 6: Completion and scorecard

The stage becomes **Complete** and the HUD shows your scorecard. Read it (section 9), then reset with `R` twice and
go again.

## 8. Common mistakes and how to fix them

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Skin opens, but fat shows along the whole line | Pressed too hard for the skin step | Lighter press; practise Drill B |
| Cut wanders out of the corridor | Moving too fast, or looking at your hand not the screen | Slow down; follow the guide; practise Drill C |
| A long groove between two cuts | Dragging while still pressing | Release fully before repositioning; Drill D |
| Blade jumps sideways mid-cut | Tags briefly lost, or glare on the printed tags | Fix lighting; keep all three tags in view |
| Blade sits above the skin however hard you press | FSR not zeroed, or `--fsr-max` too high | Press `c` in the bridge; lower `--fsr-max` |
| Blade dives into deep tissue with a light press | `--fsr-max` too low, or FSR baseline drifted | Raise `--fsr-max`; press `c` |
| Touched a rib | Too far down, or under the upper rib | Re-check landmarks; stay over the top of the lower rib |
| Pleura opens before the layers above it | Went straight down instead of dissecting | Work layer by layer; do not skip the dissection stage |
| Scalpel moves the wrong way | Camera axis vs skin axis | Tick `invertX` / `invertZ` on `TagFsrInput` |
| Cut position is offset from where you aim | Origin not set | Rest over the centre and press `z` in the bridge |

## 9. How you are scored

The scorecard is **training telemetry, not a clinical score.** It comes from deterministic metrics recorded during
your attempt, and is stored so it can be replayed. The current illustrative weighting is:

| Component | Weight | What it rewards |
| --- | --- | --- |
| Targeting | 22% | Being over the intended target window |
| Controlled force | 16% | Force staying in the 0.3 to 1.2 N range |
| Incision geometry | 12% | An even, correctly sized incision |
| Instrument angle | 10% | Holding the scalpel at a sensible angle |
| Force consistency | 10% | Steady pressure, not spikes |
| Staying in the corridor | 10% | Not cutting outside the marked corridor |
| Layer discipline | 10% | Opening layers in the right order |
| Completion time | 5% | Finishing in reasonable time (lowest weight on purpose) |
| Tube placement | 5% | The tube passing through the tract |

Notice that **time is only 5%.** Accuracy, control and layer discipline are 90%. Going slowly is not penalised.

To improve, find your lowest component and go back to the matching drill:

- Low **force consistency** or **controlled force**: Drill B, then Drill C.
- Low **corridor** or **incision geometry**: Drill C.
- Low **layer discipline**: repeat stage 3 slowly, one layer at a time.
- Low **targeting**: spend more time on stage 1 before you descend.

## 10. Practice plan: from first session to fluent

| Session | Focus | Target |
| --- | --- | --- |
| 1 | Setup, calibration (section 5), Drills A and B | Hit each depth within about 2 mm |
| 2 | Drills C and D, then stages 1 and 2 only | Clean skin incision inside the corridor |
| 3 | Full run using the HUD instructions, no time pressure | Finish the whole procedure once |
| 4 | Full runs, focus on layer discipline | No layer violations in 3 runs in a row |
| 5 | Full runs, focus on force consistency | Force stays in range for the whole run |
| 6+ | Timed full runs | Repeat the same quality faster, then compare scorecards |

Keep a simple log: date, run number, total score, and your lowest component. If the lowest component is the same
three sessions in a row, that is the drill to spend your time on.

**A note on habit.** Repetition only helps if you repeat *good* technique. If a run goes badly, reset and slow down,
rather than rushing through several more.

## 11. Troubleshooting the rig

| Problem | What to check |
| --- | --- |
| **SOFA OFFLINE** in the HUD | Start the showcase backend (`scripts/start-showcase.sh`). |
| HUD says WASD fallback | Bridge not running, wrong UDP port (default 5005), or a firewall is blocking it. |
| Bridge says `tags=0` | Tags out of frame, too small, glare, or the wrong family. Try `--family 16h5`, `25h9` or `36h10`. |
| Bridge cannot open the camera | Another app is using it. Try `--camera 1`. |
| No COM port for the ESP32-C3 | Use a data USB cable; set **USB CDC On Boot: Enabled**; if still missing, hold `9`, tap `RST`, release `9`, and re-upload. |
| Force reads 0 whatever you press | Check the FSR wiring: 3V3 to FSR to GPIO3, plus a 10k resistor from GPIO3 to GND. |
| Force is noisy | Keep the FSR cable still and away from motor or mains cables; raise `deadband` slightly. |
| Position drifts over time | Camera or handle moved; press `z` to reset the origin. |
| Blade jitter | Increase smoothing by lowering the camera frame rate load, or improve lighting. |

## 12. Glossary

- **Chest tube / chest drain:** a tube placed between the chest wall and the lung to remove air or fluid.
- **Pleura:** the thin lining around the lung and inside the chest wall. Entering it opens the pleural space.
- **Intercostal:** between the ribs. Intercostal muscles fill the gaps.
- **Neurovascular bundle:** the vein, artery and nerve that run along the lower border of each rib.
- **Blunt dissection:** separating tissue by spreading it apart rather than cutting it.
- **Safe triangle:** the conventionally taught region on the side of the chest used for drain insertion.
- **AprilTag:** a printed square marker that a camera can identify and locate. Tags 1, 2 and 3 are on the scalpel.
- **FSR:** force-sensitive resistor. Its resistance drops as you press harder.
- **Deadband:** the small FSR reading below which pressure is ignored, so sensor noise does not cause cuts.
- **SOFA:** the physics engine that decides contact, deformation and carving.

## 13. References

Also listed in the exercise definition; read these before instructor sign-off:

- NHS South East Scotland Major Trauma Guidelines: chest drain insertion
  (https://www.rightdecisions.scot.nhs.uk/south-east-scotland-major-trauma-guidelines/cardiothoracics/chest-drain-insertion/)
- Royal Cornwall Hospitals Trust: insertion and management of chest drains clinical guideline
  (https://doclibrary-rcht.cornwall.nhs.uk/DocumentsLibrary/RoyalCornwallHospitalsTrust/Clinical/Respiratory/InsertionAndManagementOfChestDrainsClinicalGuideline.pdf)

Related project files: `models/exercises/chest-tube-access-demo.json`, `hardware/README.md`,
`docs/decisions/0005-visible-incision-and-chest-depth.md`.
