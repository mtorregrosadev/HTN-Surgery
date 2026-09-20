# Surge Prep: the complete, slow-paced tutorial

### From an empty laptop to a live demo, with MongoDB Atlas for the Hack the North 2026 prize track

This guide walks through **everything**, one small step at a time. Nothing is skipped and nothing is assumed.
If a step is easy, read it quickly and move on. If a step is confusing, there is a **"What you should see"**
box after it so you can check yourself, and a **"If it does not work"** box for the common failures.

> **Safety first.** Surge Prep is a **training prototype**. It is *not* a medical device. It never replaces qualified
> teachers, supervised simulation, or clinical judgment. Use it only on the synthetic surface and virtual anatomy.
> Never attach the electronics to a real clinical instrument. Never use it on a person.

---

## How to read this guide

- Each **Part** is one topic. Each **Step** inside it is one small action.
- Do the steps **in order**. Later steps depend on earlier ones.
- Lines in `grey code boxes` are things to type or paste.
- "**Checkpoint**" means: stop, and confirm before you continue.
- "**Why?**" boxes explain the reason, so you can defend your choices to a judge.
- Words in **bold** the first time they appear are defined in the [glossary](#part-16-glossary).

### Table of contents

| Part | What it covers |
| --- | --- |
| [0](#part-0-the-clock-and-the-plan) | The clock, and what "done" means |
| [1](#part-1-what-you-are-building) | What Surge Prep is, in plain words |
| [2](#part-2-the-prize-track-mlh-best-use-of-mongodb-atlas) | The MongoDB Atlas prize, and how you qualify |
| [3](#part-3-the-big-picture-how-the-pieces-talk) | The architecture, one arrow at a time |
| [4](#part-4-set-up-your-computer) | Tools to install |
| [5](#part-5-get-the-code) | Cloning the repo and the `test` branch |
| [6](#part-6-create-your-mongodb-atlas-database) | Atlas account, cluster, user, network, connection string |
| [7](#part-7-connect-the-backend-to-atlas) | Pointing the API at Atlas and proving it works |
| [8](#part-8-understand-what-is-stored-in-mongodb) | Every collection, every field |
| [9](#part-9-build-the-hardware) | AprilTags, ESP32-C3, FSR sensor |
| [10](#part-10-run-the-bridge-and-calibrate) | Camera bridge and calibration |
| [11](#part-11-set-up-unity) | Unity project, package, scene |
| [12](#part-12-your-first-full-practice-run) | One complete run, start to finish |
| [13](#part-13-watch-your-run-appear-in-mongodb) | Seeing your data in Atlas, plus queries |
| [14](#part-14-make-the-mongodb-story-shine) | Aggregations, Charts, and honest extras |
| [15](#part-15-the-demo-and-the-devpost-submission) | The live demo script and the submission |
| [16](#part-16-glossary) | Glossary |
| [17](#part-17-troubleshooting-everything) | Troubleshooting table |
| [18](#part-18-cheat-sheet) | One-page cheat sheet |

---

# Part 0: The clock and the plan

## Step 0.1: Know your deadline

From the Hack the North 2026 Devpost page:

| Fact | Value |
| --- | --- |
| Submission deadline | **Sunday, Sep 20, 2026 at 8:00 AM EDT** |
| Where | University of Waterloo, E5/PSE |
| Prize selection cutoff | **Before 2:00 PM EDT on Saturday** (Sep 19) |
| Submission needs | Source code link, every teammate's badge ID, prizes you want, and optionally a demo video |

> **Check this right now.** The listing says sponsor prizes must be *selected before 2:00 PM EDT on Saturday*.
> Saturday is Sep 19. If that time has already passed, **tell an organizer at the help desk immediately** and ask what
> can still be done. Do not assume it is fine.

## Step 0.2: Decide what "done" means

You are **done** when all of these are true. Print this list or keep it open.

- [ ] The project runs on your laptop from a cold start.
- [ ] A practice run creates data in **MongoDB Atlas** (not just on your laptop).
- [ ] You can open Atlas and show a session, its samples, and its replay data.
- [ ] You can do a **live demo** in about 2 to 3 minutes (judges want a live demo, not slides).
- [ ] The code is pushed to a public repo with a clear README.
- [ ] The Devpost submission lists the MongoDB Atlas prize, every teammate's badge ID, and the repo link.
- [ ] You have a backup plan if Wi-Fi, the camera, or the sensor fails.

## Step 0.3: A realistic plan for a short window

If you have about 10 hours left, spend them like this. Adjust the numbers, but keep the order.

| Block | Time | Goal |
| --- | --- | --- |
| A | 1 h | Parts 4 to 7: Atlas connected, data proven |
| B | 1.5 h | Parts 9 to 11: hardware and Unity working (or fall back to the keyboard) |
| C | 1 h | Parts 12 to 13: one full run visible in Atlas |
| D | 1.5 h | Part 14: one strong MongoDB feature for judges |
| E | 1 h | Part 15: demo rehearsal x3, record a backup video |
| F | 30 min | Part 15: Devpost submission, **well before 8:00 AM** |
| G | rest | **Sleep.** A rested demo beats a half-finished feature. |

**Rule:** submit at least 45 minutes early. Devpost can be slow at the deadline, and a submission that is not
finished is not a submission.

---

# Part 1: What you are building

## Step 1.1: The one-sentence version

> **Surge Prep** lets a learner practise a chest-tube procedure with a real hand-held tool, while a virtual body
> reacts with real physics, and every attempt is saved so it can be replayed and scored.

## Step 1.2: The same thing, slower

Picture a student at a table.

1. On the table is a flat practice surface, and a hand-held tool with **three printed square markers** on it. Those
   markers are **AprilTags**.
2. A camera watches the tool. The computer works out *where* the tool is.
3. The tool has a small pressure sensor (an **FSR**). It measures *how hard* the student presses.
4. On the screen, in **Unity**, a virtual chest appears with layers: skin, fat, muscle, and pleura.
5. Where the student moves the tool, the virtual scalpel moves. How hard they press decides **how deep** it cuts.
6. A physics engine called **SOFA** decides what really happens: does the tissue deform, does it tear, how much force
   pushes back.
7. Every position, every force, and every result is saved in a **database**, so the attempt can be **replayed** and
   **scored** later.

## Step 1.3: Why it is a good hackathon project

Judges score four things (from the Devpost page):

| Judging criterion | How Surge Prep answers it |
| --- | --- |
| **WOW factor** | A physical tool controlling a live tearing-tissue simulation |
| **Technical ability** | Computer vision + embedded sensor + physics engine + game engine + database, all live |
| **Originality** | Training surgical *skill* with real touch, not just watching a video |
| **Design** | Step-by-step on-screen guidance, layers you can see, a scorecard, and a replay |

## Step 1.4: What you are *not* claiming

Be honest with judges. This builds trust.

- It is an **illustrative training prototype**, not a validated model of human tissue.
- The scorecard is **training telemetry**, not a clinical grade.
- Tissue numbers are illustrative, not measured from real people.

Saying this yourself makes you look careful, not weak.

---

# Part 2: The prize track (MLH: Best Use of MongoDB Atlas)

## Step 2.1: What the prize says

The listing for **MLH: Best Use of MongoDB Atlas** (1 winner) says, in summary:

- MongoDB Atlas is the modern database in the cloud.
- You can start with a **$50 student credit** (`https://mlh.link/mongodb`) or the **free forever tier**
  (`https://mlh.link/mongodb-free`, no credit card needed).
- **MongoDB University** has free learning resources (`https://mlh.link/mongodb-university`).
- The task: **build a hack using MongoDB Atlas.**
- The prize: an **M5Stack IoT Kit for you and each member of your group.**

## Step 2.2: What the listing does *not* say

The listing gives **no detailed scoring rubric** for this prize beyond "build a hack using MongoDB Atlas". So do not
guess a hidden rubric. Instead, make it **obvious and impressive** that Atlas is doing real work:

1. It stores **live, high-frequency data** (the tool's position and force, many times per second).
2. It stores **derived results** (simulation snapshots, sessions).
3. It powers **replay** (read the recorded attempt back and play it again).
4. You can **query and summarise** it (progress over time, comparisons).

That story is clear, visual, and easy to demo. Part 14 shows how to make it even stronger.

## Step 2.3: How to choose your prizes on Devpost

You pick prizes on the submission form. Guidance:

1. **Hack the North 2026: Finalists**: the main award. Everyone is considered; select it.
2. **MLH: Best Use of MongoDB Atlas**: select it, because the project genuinely uses Atlas.
3. **Aramco Americas: Best Beginner Hack**: only if **every** teammate has attended **one or fewer** hackathons before
   Hack the North 2026. Read the rule on the page and be honest.
4. Do **not** select sponsor prizes you cannot truthfully explain. Judges ask.

> Only select prizes where you can say, in one sentence, *exactly how your project uses that sponsor's product*.
> A shorter, honest list beats a long, weak one.

---

# Part 3: The big picture (how the pieces talk)

## Step 3.1: The map

```text
                      ┌───────────────────────────┐
   webcam ──────────► │                           │
   (AprilTags 1,2,3)  │   hardware/               │        UDP :5005
                      │   tag_fsr_bridge.py       │ ─────────────────────┐
   ESP32-C3 + FSR ──► │   (Python)                │                      │
   (USB serial)       └───────────────────────────┘                      ▼
                                                           ┌──────────────────────┐
                                                           │ Unity                │
                                                           │  TagFsrInput.cs      │
                                                           │  UnityManualDemo-    │
                                                           │  Client.cs           │
                                                           └──────────┬───────────┘
                                                                      │ WebSocket
                                                                      ▼
                                                           ┌──────────────────────┐
                                                           │ Scalpel controller   │
                                                           │ (FastAPI, port 8100) │
                                                           └──────────┬───────────┘
                                                                      │ HTTP
                                                                      ▼
                                                           ┌──────────────────────┐
                                                           │ API (FastAPI, 8000)  │──► SOFA physics
                                                           └──────────┬───────────┘
                                                                      │
                                                                      ▼
                                                           ┌──────────────────────┐
                                                           │  MongoDB Atlas       │
                                                           └──────────────────────┘
```

## Step 3.2: Read the arrows, one at a time

| Arrow | What travels | Why |
| --- | --- | --- |
| webcam → bridge | Camera frames | Find where AprilTags 1, 2, 3 are |
| ESP32 → bridge | `F,<number>` lines over USB | How hard the sensor is pressed |
| bridge → Unity | A small JSON packet over UDP, ~30 times a second | Position, pressure, how many tags are visible |
| Unity → controller | A "tool sample" (position, force, contact) over WebSocket | The official input format for the system |
| controller → API | The same sample over HTTP | The API owns the simulation and the database |
| API → SOFA | The pose | SOFA decides contact, deformation, tearing |
| API → MongoDB Atlas | Samples, snapshots, sessions | Permanent storage, replay, scoring |
| API → controller → Unity | A "snapshot" of the simulated world | Unity draws what SOFA computed |

## Step 3.3: Two rules that keep it honest

1. **Only the API talks to MongoDB.** Unity and the camera bridge never touch the database directly. This is a hard
   rule of the project's architecture.
2. **SOFA decides what happens.** Unity only draws. The hardware only sends a pose and a force.

## Step 3.4: How pressure becomes depth (in one picture)

```text
FSR pressure ──►  tool height above/below the skin  ──►  SOFA measures how far below the skin the tip is
   none               +6 mm  (hovering)                    no contact
   light               0 mm  (touching)                    first contact
   moderate         -3 to -15 mm                           skin, then fat
   firm             -15 to -25 mm                          muscle
   full             -32 mm                                 pleura (the floor)
```

The backend itself works out contact from *how far below the skin the tip is*. So pressing harder literally lowers
the virtual blade.

---

# Part 4: Set up your computer

> **Important, honest note about operating systems.** The repo's full physics showcase (`scripts/start-showcase.sh`)
> is written and tested for **macOS on Apple Silicon**, with the **macOS build of SOFA 26.06**. Your machine runs
> **Windows**. So there are **two paths**:
>
> - **Path A: Full physics.** Run the showcase on a Mac (yours or a teammate's). Everything in this guide applies.
> - **Path B: Windows, no native SOFA.** Run the API in its **memory-simulator** mode with **real MongoDB Atlas**.
>   You can prove the whole data pipeline and the hardware, but the physics is **not** real SOFA. The README states
>   that this mode must **never be presented as the physics demo.** If you use Path B, say so out loud in your demo.
>
> Pick a path now and write it here: **Path ____**.

## Step 4.1: Install Git

1. Download Git from https://git-scm.com/downloads and install with the defaults.
2. Open a terminal and type:

```bash
git --version
```

**What you should see:** a version number such as `git version 2.46.2`.

## Step 4.2: Install Python 3.12

1. Download Python 3.12 from https://www.python.org/downloads/ (or use the Microsoft Store version).
2. Check it:

```bash
py -3.12 --version
```

**What you should see:** `Python 3.12.x`.

> **Why 3.12?** The project targets Python 3.12 and the SOFA Python bindings match it. OpenCV and pyserial are
> already installed for 3.12 on your machine.

## Step 4.3: Install Docker Desktop (Path A, and optional for Path B)

Docker runs a local MongoDB for practice and the memory-dev stack.

```bash
docker compose version
```

**What you should see:** a version line. If the command is not found, install Docker Desktop and start it.

## Step 4.4: Install the Arduino IDE

1. Download from https://www.arduino.cc/en/software.
2. Open **Boards Manager**, search **esp32**, and install **"esp32 by Espressif Systems"**.

## Step 4.5: Install Unity (Path A, and for any Unity work)

1. Install **Unity Hub**.
2. In Unity Hub, install the editor version the README names: **6000.6.2f1**.
3. You will create the project in [Part 11](#part-11-set-up-unity).

## Step 4.6: Install the Python libraries for the hardware bridge

```bash
py -3.12 -m pip install opencv-python numpy pyserial
```

**What you should see:** lines ending in "Successfully installed" or "Requirement already satisfied".

## Step 4.7: Install `mongosh` (optional but very useful)

`mongosh` is a command-line tool for looking inside a MongoDB database. Download it from the MongoDB website
(search "MongoDB Shell download"). You can also use the **Atlas web interface** instead. Both work; the shell is
faster once you know it.

**Checkpoint 4:** git, Python 3.12, and the Python libraries work. You know whether you are on Path A or Path B.

---

# Part 5: Get the code

## Step 5.1: Clone the repository

Use a **short folder path** on Windows. Very long paths make git fail with "Filename too long".

```bash
cd C:\Users\hasin
git -c core.longpaths=true clone https://github.com/mtorregrosadev/HTN-Surgery.git
cd HTN-Surgery
```

## Step 5.2: Switch to the working branch

The hardware work lives on the `test` branch (built on top of `apriltags`).

```bash
git switch test
```

If `test` does not exist on your copy yet, it is only on the machine where it was created. In that case use the
clone in `C:\Users\hasin\HTN-Surgery`, which already has it.

## Step 5.3: Look around

```bash
git log --oneline -5
```

**What you should see:** commits including *"Add chest-tube practice tutorial…"* and *"Drive the scalpel from
AprilTags and an FSR sensor"*.

## Step 5.4: The folders that matter

| Folder / file | What is in it |
| --- | --- |
| `backend/` | The Python API, the database code (`store.py`), the simulator interface |
| `controller/` | The controller between Unity/hardware and the API |
| `simulation/` | The SOFA scene |
| `client/unity/Packages/com.surgeprep.runtime/` | The Unity package (scene builder, scalpel, HUD, `TagFsrInput.cs`) |
| `hardware/` | The camera + FSR bridge and the ESP32-C3 firmware |
| `bodyparts3d_highres/` | The 3D anatomy models |
| `contracts/` | JSON schemas that define the data format |
| `models/exercises/` | The exercise definition (stages, layers, scoring weights) |
| `docs/` | This tutorial, the practice tutorial, and design decisions |
| `compose.yaml` | Docker: local MongoDB (and the memory-dev stack) |

**Checkpoint 5:** the repo is cloned and you are on `test`.

---

# Part 6: Create your MongoDB Atlas database

> Atlas is a website. Button names and screen layouts change from time to time, so the labels below are a guide.
> The **ideas** stay the same: account → cluster → database user → network access → connection string.

## Step 6.1: Create an account

1. Go to https://mlh.link/mongodb-free (free forever tier, no credit card needed) or https://mlh.link/mongodb
   (the $50 student credit).
2. Sign up **yourself**, with your own email and password. (An assistant cannot and should not create the account or
   type passwords for you.)
3. Verify your email if asked.

## Step 6.2: Create a project

Atlas groups clusters into **projects**. Name yours something clear, for example `surge-prep`.

## Step 6.3: Create a cluster

1. Choose **Create a cluster** / **Build a database**.
2. Choose the **free (M0 / Free)** option.
3. Pick a cloud provider and a **region close to you**. Waterloo is in Ontario, Canada, so a Canadian or
   nearby US-East region has the lowest delay.
4. Name it, for example `surge-prep-cluster`, and create it.

**What you should see:** a cluster that takes a minute or two to become ready.

> **Why the free tier is enough:** a practice run stores a few thousand small documents. That is tiny.

## Step 6.4: Create a database user

This is the username and password **your API** will use. It is *not* your Atlas login.

1. Open **Database Access** (under Security).
2. Choose **Add New Database User**.
3. Use **Password** authentication. Pick a username such as `surgeprep_api`.
4. Use a **long, random password**. Let Atlas generate one.
5. **Copy the password somewhere private right now.** You cannot read it again later.
6. Give the user the **Read and write to any database** role (or, better, only your `surge_prep` database).

> **Never** paste this password into the chat with anyone, into a GitHub file, into Devpost, or into a screenshot.

## Step 6.5: Allow your network

Atlas blocks unknown computers by default. You must allow yours.

1. Open **Network Access** (under Security).
2. Choose **Add IP Address**.
3. Choose **Add Current IP Address** and confirm.

**Hackathon Wi-Fi warning:** your IP address can **change** when you move rooms or reconnect. If the database
suddenly refuses connections, come back here first.

A tempting shortcut is `0.0.0.0/0` ("allow anywhere"). It works, but it means **anyone with your password can connect
from anywhere**. If you use it for the weekend:

- Use a strong password.
- **Delete that entry after the event.**

## Step 6.6: Get the connection string

1. Go to your cluster and choose **Connect**.
2. Choose **Drivers** (or "Connect your application").
3. Copy the connection string. It looks like this:

```text
mongodb+srv://surgeprep_api:<password>@surge-prep-cluster.abcde.mongodb.net/?retryWrites=true&w=majority
```

4. Replace `<password>` with the real password.

> If the password contains special characters such as `@`, `:`, `/`, or `?`, they must be **URL-encoded**
> (for example `@` becomes `%40`). The simplest fix: generate a password with **letters and numbers only**.

## Step 6.7: Store it safely

The repo's `.gitignore` already ignores `.env`. Create a file called `backend/.env` (it will **not** be committed):

```text
SURGE_PREP_MONGODB_URI=mongodb+srv://surgeprep_api:YOURPASSWORD@surge-prep-cluster.abcde.mongodb.net/?retryWrites=true&w=majority
SURGE_PREP_MONGODB_DATABASE=surge_prep
```

Then verify git ignores it:

```bash
git status
```

**What you should see:** `backend/.env` does **not** appear in the list. If it does, stop and fix `.gitignore`
before doing anything else.

**Checkpoint 6:** you have an Atlas cluster, a database user, your IP allowed, and a private `backend/.env`.

---

# Part 7: Connect the backend to Atlas

## Step 7.1: How the backend chooses a database

The API reads two environment variables (see `backend/src/surge_prep/config.py`):

| Variable | Meaning | Default |
| --- | --- | --- |
| `SURGE_PREP_MONGODB_URI` | The MongoDB connection string | unset |
| `SURGE_PREP_MONGODB_DATABASE` | The database name | `surge_prep` |

**If the URI is unset**, the API uses an **in-memory store** and forgets everything on restart. **If it is set**, the
API uses **MongoDB**. So pointing at Atlas is *only* a matter of setting one variable. No code change.

## Step 7.2: Install the backend (Path B, Windows)

```bash
cd C:\Users\hasin\HTN-Surgery
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e "./backend[dev]" -e "./controller[dev]"
```

If you later see an error mentioning **`dnspython`** or **`mongodb+srv`**, run:

```bash
.venv\Scripts\python -m pip install "pymongo[srv]"
```

## Step 7.3: Set the environment variables for this terminal session

In **PowerShell** (replace the URI with yours):

```powershell
$env:SURGE_PREP_MONGODB_URI = "mongodb+srv://surgeprep_api:YOURPASSWORD@surge-prep-cluster.abcde.mongodb.net/?retryWrites=true&w=majority"
$env:SURGE_PREP_MONGODB_DATABASE = "surge_prep"
$env:SURGE_PREP_SIMULATION_BACKEND = "memory"
```

> `memory` here means the **simulator** is the development stand-in. It does **not** mean the database is in
> memory. The database is Atlas. (Path A on a Mac uses `sofa` instead.)

## Step 7.4: Start the API

```powershell
.venv\Scripts\python -m uvicorn surge_prep.app:app --app-dir backend/src --host 127.0.0.1 --port 8000
```

**What you should see:** uvicorn says it is running on `http://127.0.0.1:8000`, and no error mentioning a
connection or authentication failure.

## Step 7.5: Prove the API sees Atlas

Open a **second** terminal and run:

```bash
curl http://127.0.0.1:8000/health
```

**What you should see:** JSON similar to:

```json
{"status":"ok","persistence":"mongodb","simulation":"memory-development-only"}
```

The important word is **`"persistence":"mongodb"`**. If it says `memory`, the URI variable was not set in the terminal
that started the API.

## Step 7.6: Start the controller

In a third terminal:

```powershell
$env:SURGE_PREP_API_URL = "http://127.0.0.1:8000"
.venv\Scripts\python -m uvicorn scalpel_controller.app:app --app-dir controller/src --host 127.0.0.1 --port 8100
```

```bash
curl http://127.0.0.1:8100/health
```

**What you should see:** `"status":"ok"` and the API health nested inside.

## Step 7.7: Prove data really reaches Atlas (before Unity)

You can test the whole database path with **no Unity, no camera, and no sensor**, using the API docs page.

1. Open `http://127.0.0.1:8000/docs` in a browser.
2. Use **POST /v1/calibrations** with an example body such as:

```json
{
  "deviceId": "manual-test",
  "transform": [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1],
  "rmsErrorMm": 0.1
}
```

3. Copy the returned `calibrationId`.
4. Use **POST /v1/sessions**:

```json
{
  "exerciseId": "chest-tube-access-demo",
  "calibrationId": "PASTE-THE-ID-HERE",
  "toolId": "scalpel",
  "deviceId": "manual-test"
}
```

5. Now open **Atlas → Database → Browse Collections**. You should see the `surge_prep` database with
   `calibrations` and `sessions` collections, and your new documents inside.

**Checkpoint 7 (the big one):** you can see a document you created **appear in Atlas**. If yes, your MongoDB
integration is proven. Take a screenshot; it is great for Devpost.

---

# Part 8: Understand what is stored in MongoDB

This part is short and important. When a judge asks "what is in your database?", you should answer instantly.

## Step 8.1: The four collections

| Collection | One document is… | Written when |
| --- | --- | --- |
| `calibrations` | A saved alignment between the tool's coordinate system and the virtual world | A session starts |
| `sessions` | One practice attempt (status, who/what/when) | Start, every sample, and completion |
| `samples` | One measurement from the tool (position, orientation, force, contact) | Every ~33 ms while practising |
| `snapshots` | One frame of the simulated world returned by the physics | Every sample |

## Step 8.2: An example `sessions` document

```json
{
  "sessionId": "…",
  "exerciseId": "chest-tube-access-demo",
  "calibrationId": "…",
  "toolId": "scalpel",
  "deviceId": "unity-manual-demo",
  "status": "active",
  "createdAt": "2026-09-19T20:00:00Z",
  "completedAt": null,
  "lastSequence": 412
}
```

`status` is one of `active`, `completed`, or `aborted`. When the practice ends, the API sets `completed` and fills in
`completedAt`.

## Step 8.3: An example `samples` document

```json
{
  "contractVersion": "1.1",
  "sessionId": "…",
  "toolId": "scalpel",
  "deviceId": "unity-manual-demo",
  "calibrationId": "…",
  "sequence": 412,
  "timestampMs": 13560,
  "positionMm": { "x": 4.2, "y": -3.1, "z": 1.0 },
  "orientation": { "qx": 0.342, "qy": 0, "qz": 0, "qw": 0.939 },
  "forceN": 0.8,
  "contact": true,
  "quality": 1,
  "sourceHealthy": true,
  "inputMode": "calibrated-hardware",
  "forceMeasurementValid": true
}
```

Read it slowly:

- `sequence` counts samples in order, starting at 0.
- `positionMm.y` is the tool's **height**. A **negative** number means it is **below the skin**. That is the depth.
- `forceN` is the measured force. `inputMode: "calibrated-hardware"` means it came from your camera + sensor, not the
  keyboard (keyboard samples say `pose-only`).

## Step 8.4: What `snapshots` add

A snapshot holds what the **physics** said happened at that moment:

- `tick` and `simulationTimeMs`: when.
- `procedureStage`: `approach`, `skin-incision`, `blunt-dissection`, `pleural-entry`, `tube-placement`, `complete`.
- `tool`: contact, penetration, reaction force.
- `tissue` and `deformableMeshes`: how the tissue currently looks.
- `events`: things like `first-contact`, `contact-start`, `contact-end`.

## Step 8.5: The indexes

When the API connects, it creates two **unique indexes** automatically:

| Collection | Index | Why |
| --- | --- | --- |
| `samples` | `sessionId` + `sequence` (unique) | Fast "give me this session in order", and no duplicate samples |
| `snapshots` | `sessionId` + `tick` (unique) | Same idea, for replay |

**Why?** Replay is just "read all snapshots for this session, sorted by tick". With that index, the database does it
quickly without scanning everything. This is a good design detail to mention to a judge.

## Step 8.6: Why the scorecard is not stored (and why that is fine)

Today the **scorecard is calculated on demand**: when the session completes, the API reads the stored samples and
snapshots, computes the metrics, and returns them. Because the raw data is in MongoDB, **any attempt can be
re-scored or replayed later**. The database is the **source of truth**. In [Part 14](#part-14-make-the-mongodb-story-shine)
there is an optional upgrade that also stores the result.

**Checkpoint 8:** you can name the four collections and say what each holds.

---

# Part 9: Build the hardware

## Step 9.1: What you need

| Item | Notes |
| --- | --- |
| A webcam | Built-in or USB |
| Three printed **AprilTags**, IDs **1, 2, 3**, family **36h11** | Print flat, matte paper, large, on white margins |
| ESP32-C3 Mini | USB-C cable **that carries data** |
| An FSR (force-sensitive resistor) | The pressure sensor |
| A **10 kΩ resistor** | For the voltage divider |
| Breadboard and jumper wires | |
| The practice tool | A blunt training tool only. **Never a real scalpel.** |

## Step 9.2: Print the AprilTags

1. Search for an AprilTag **36h11** generator (or generate them with OpenCV).
2. You need IDs **1, 2, and 3**.
3. Print them on **matte** paper, **at least 3 cm** wide, with a **white border** all around.
4. Stick them flat on the tool handle, all facing the camera. **No wrinkles, no glare.**

Optional: generate them with Python.

```python
import cv2
d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
for i in (1, 2, 3):
    cv2.imwrite(f"tag_{i}.png", cv2.aruco.generateImageMarker(d, i, 600))
```

## Step 9.3: Wire the FSR

Build a **voltage divider**:

```text
3V3 ───[ FSR ]───┬─── GPIO3
                 │
               [10 kΩ]
                 │
                GND
```

Go slowly:

1. Connect one FSR leg to the **3V3** pin.
2. Connect the other FSR leg to **GPIO3**.
3. Connect the 10 kΩ resistor from **GPIO3** to **GND**.

> **Why GPIO3?** On the ESP32-C3, only GPIO0 to GPIO4 are on the ADC1 converter. GPIO2 is a boot-strap pin, so avoid
> it. GPIO34 does not exist on this chip.

## Step 9.4: Flash the firmware

1. Open `hardware/esp32c3_fsr/esp32c3_fsr.ino` in the Arduino IDE.
2. **Tools → Board →** choose **ESP32C3 Dev Module** (or **LOLIN C3 Mini** if that matches yours).
3. **Tools → USB CDC On Boot → Enabled.** *(This is essential. Without it, nothing prints and no port appears.)*
4. **Tools → Port →** choose the new COM port.
5. Click **Upload**.

**If the port never appears:** hold the **9** button, tap **RST**, release **9**, then upload again. Tap **RST** once
more after uploading.

## Step 9.5: Test the sensor

1. Open **Tools → Serial Monitor**, set **115200 baud**.

**What you should see:** lines like `F,12`, `F,13`, `F,12`. Press the FSR. The number should **rise**, for example to
`F,1800`.

2. **Close the Serial Monitor.** Only one program can hold the port. The bridge needs it next.

## Step 9.5b: Find the port name

```bash
py -3.12 -m serial.tools.list_ports -v
```

**What you should see:** a port such as `COM3`. Write it here: **COM____**.

**Checkpoint 9:** the tags are printed and stuck on, the FSR is wired, and you saw `F,<number>` change when pressed.

---

# Part 10: Run the bridge and calibrate

The **bridge** (`hardware/tag_fsr_bridge.py`) combines the camera and the sensor and sends one small packet to Unity.

## Step 10.1: Try it with no hardware first

```bash
cd C:\Users\hasin\HTN-Surgery
py -3.12 hardware/tag_fsr_bridge.py --simulate
```

A small window opens. Move the mouse and **hold the left button**.

**What you should see:** the text `tags=3 force=… pos=(…)` change as you move and press. Press **q** to quit.

## Step 10.2: Run it with the camera and the sensor

```bash
py -3.12 hardware/tag_fsr_bridge.py --port COM3 --fsr-max 3000
```

(Use **your** port.)

**What you should see:** the camera image with **green outlines and IDs** on the tags, and `tags=3` in the text.

## Step 10.3: If tags are not found

Work down this list, in order:

1. **Light:** even light, no glare on the print.
2. **Size:** move the tool closer, or print bigger tags.
3. **Flat:** unwrinkled paper.
4. **Family:** try `--family 16h5`, `25h9`, or `36h10`.
5. **Camera:** try `--camera 1`.

## Step 10.4: Set the origin

1. Hold the tool over the **middle** of your practice area.
2. Press **z** in the bridge window.

Now that spot is the centre `(0, 0)` of the virtual practice patch.

## Step 10.5: Zero the sensor

1. Take your hand **off** the FSR.
2. Press **c** in the bridge window.

This records the "no pressure" reading, so noise is not mistaken for a press.

## Step 10.6: Calibrate the full-press value

1. Press as hard as you would ever press. Watch the `force=` number.
2. If it maxes out at 1.00 too easily, **raise** `--fsr-max` (for example `3500`).
3. If you can never reach 1.00, **lower** it (for example `2500`).

Restart the bridge with the new value.

## Step 10.7: Tune how far the tool travels (`--span`)

`--span 0.5` means: half the camera's width covers the full practice patch. A **smaller** span makes small hand
movements travel far; a **larger** span makes the tool move less. Try `0.4` to `0.8`.

**Checkpoint 10:** `tags=3`, the origin is set, the sensor is zeroed, and pressing changes `force=`.

---

# Part 11: Set up Unity

> Requires Unity (Path A). If you are on Windows Path B and cannot run Unity with SOFA, skip to Part 13 using the API
> docs page or the `--simulate` bridge to generate data, and be clear about it in the demo.

## Step 11.1: Create the project

1. In Unity Hub choose **New project**.
2. Choose the **Universal 3D** template, editor **6000.6.2f1**.
3. Save it **outside** the repo, for example `C:\Users\hasin\SurgePrepXR`.

## Step 11.2: Link the package from the repo

1. **Window → Package Management → Package Manager.**
2. Click **+ → Install package from disk.**
3. Pick this file inside your clone:

```text
C:\Users\hasin\HTN-Surgery\client\unity\Packages\com.surgeprep.runtime\package.json
```

4. Wait for Unity to finish compiling.

**What you should see:** a new **Surge Prep** menu at the top.

> **Do not copy the package elsewhere.** The scene builder finds the anatomy by looking relative to the linked
> package inside the repo.

## Step 11.3: Build the scene

1. Make sure you are **not** in Play mode.
2. **Surge Prep → Build Chest-Tube Showcase.**
3. Wait. It imports the 3D anatomy, which can take a few minutes.

**What you should see:** Unity opens `Assets/SurgePrepShowcase/Scenes/ChestTubeShowcase.unity`.

> Rebuild the scene after every `git pull`. The builder is what adds the `TagFsrInput` component that connects the
> hardware.

## Step 11.4: Tune the hardware component

1. In the **Hierarchy**, select `RegistrationAnchor_SimulationPatch`.
2. In the **Inspector**, find **Tag Fsr Input**.

| Setting | Default | When to change it |
| --- | --- | --- |
| `port` | 5005 | Only if that port is busy |
| `xRangeMm` / `zRangeMm` | 30 / 22 | The carvable field is about this big |
| `invertX` / `invertZ` | off | Tick if the tool moves the wrong way |
| `hoverMm` | 6 | Height above skin with no pressure |
| `maxDepthMm` | 32 | Depth at full pressure (reaches the pleura) |
| `deadband` | 0.08 | Raise if sensor noise makes it cut by itself |

**Checkpoint 11:** the scene exists and you can find the **Tag Fsr Input** settings.

---

# Part 12: Your first full practice run

## Step 12.1: Start everything, in this order

The order matters. Think of it as turning on a stack from the bottom up.

1. **Atlas** is already running (it is in the cloud).
2. **API** (Part 7.4).
3. **Controller** (Part 7.6).
4. **Bridge** (Part 10.2).
5. **Unity → Play.**

Path A (Mac, real physics) can use the one-line starter instead of steps 2 and 3:

```bash
./scripts/start-showcase.sh
```

To make that script use **Atlas**, set the URI first, in the same terminal:

```bash
export SURGE_PREP_MONGODB_URI="mongodb+srv://…"
export SURGE_PREP_MONGODB_DATABASE=surge_prep
./scripts/start-showcase.sh
```

(The script still starts a local Docker MongoDB, which is harmless. The API uses whichever URI you set.)

## Step 12.2: Confirm the health line in Unity

Click once inside the **Game** view. Look at the top-left guidance panel.

| It says | Meaning |
| --- | --- |
| **SOFA NATIVE** (green) | Real physics is running |
| **SOFA OFFLINE** | Physics is not connected. On Path B this is expected. Do **not** present it as real physics |
| *LIVE, AprilTag position, FSR cut depth* | The hardware is driving the tool |
| *…WASD fallback…* | The bridge is not reaching Unity |

## Step 12.3: Follow the practice tutorial

Open `docs/CHEST_TUBE_PRACTICE_TUTORIAL.md` and follow its stages:

1. **Approach**: hover over the highlighted window.
2. **Skin incision**: press lightly, travel along the corridor, lift off.
3. **Blunt dissection**: press `2`, open fat and muscle.
4. **Pleural entry**: enter once, slowly.
5. **Tube placement**: press `3`, pass the tube.
6. **Complete**: read the scorecard.

## Step 12.4: End the session properly

Leave Play mode. Unity tells the API to **complete** the session. That step:

1. reads all the stored samples and snapshots,
2. sets the session `status` to `completed` and fills `completedAt`,
3. calculates the metrics.

**Checkpoint 12:** you finished one run and left Play mode cleanly.

---

# Part 13: Watch your run appear in MongoDB

## Step 13.1: Look in the Atlas web page

1. **Atlas → Database → Browse Collections → `surge_prep`.**
2. Click `sessions`. You should see your session with `status: "completed"`.
3. Click `samples`. You should see **hundreds or thousands** of documents, one per ~33 ms of practice.
4. Click `snapshots`. Similar count.

**Screenshot this.** It is proof, and it makes a great Devpost image.

## Step 13.2: Query with `mongosh`

Connect (replace with your string; mongosh will ask for the password if you leave it out):

```bash
mongosh "mongodb+srv://surge-prep-cluster.abcde.mongodb.net/surge_prep" --username surgeprep_api
```

Then, one line at a time:

```javascript
// which database, which collections?
db.getCollectionNames()

// how many of each?
db.sessions.countDocuments()
db.samples.countDocuments()
db.snapshots.countDocuments()

// your most recent sessions
db.sessions.find({}, { _id: 0 }).sort({ createdAt: -1 }).limit(3)
```

## Step 13.3: Pick one session and inspect it

```javascript
const s = db.sessions.findOne({ status: "completed" }, { _id: 0 })
s

// how many samples in this session?
db.samples.countDocuments({ sessionId: s.sessionId })

// the first 3 samples, in order
db.samples.find({ sessionId: s.sessionId }, { _id: 0 }).sort({ sequence: 1 }).limit(3)
```

## Step 13.4: Ask real questions

```javascript
// deepest the tool ever went (most negative y = deepest)
db.samples.find({ sessionId: s.sessionId }, { _id: 0, "positionMm.y": 1 })
  .sort({ "positionMm.y": 1 }).limit(1)

// how many samples were real hardware (not keyboard)?
db.samples.countDocuments({ sessionId: s.sessionId, inputMode: "calibrated-hardware" })

// how many samples had contact?
db.samples.countDocuments({ sessionId: s.sessionId, contact: true })
```

## Step 13.5: See the stages you went through

```javascript
db.snapshots.aggregate([
  { $match: { sessionId: s.sessionId } },
  { $group: { _id: "$procedureStage", frames: { $sum: 1 }, firstTick: { $min: "$tick" } } },
  { $sort: { firstTick: 1 } }
])
```

**What you should see:** a list like `approach`, `skin-incision`, `blunt-dissection`, `pleural-entry`,
`tube-placement`, each with how many frames you spent there. That is your whole procedure, summarised by the
database.

**Checkpoint 13:** you queried your own session and got sensible answers.

---

# Part 14: Make the MongoDB story shine

Everything up to here is **built and works**. This part offers **extras that make the prize stronger**. Each one is
labelled honestly: **built** vs **idea (not built yet)**. Do them in order of value per hour.

## 14.1 (built): Live proof during the demo

Keep an Atlas browser tab open on `samples`. During the demo, **refresh** it and show the count climbing. That alone
proves the data is live and real. Cost: 0 minutes.

## 14.2 (built): Force over time, per session

Copy into `mongosh`. It averages force in 1-second buckets for one session.

```javascript
db.samples.aggregate([
  { $match: { sessionId: s.sessionId, contact: true } },
  { $group: {
      _id: { $floor: { $divide: ["$timestampMs", 1000] } },
      avgForceN: { $avg: "$forceN" },
      peakForceN: { $max: "$forceN" },
      samples: { $sum: 1 }
  } },
  { $sort: { _id: 1 } }
])
```

## 14.3 (built): Depth over time

```javascript
db.samples.aggregate([
  { $match: { sessionId: s.sessionId } },
  { $group: {
      _id: { $floor: { $divide: ["$timestampMs", 1000] } },
      deepestMm: { $min: "$positionMm.y" }
  } },
  { $sort: { _id: 1 } }
])
```

## 14.4 (built): Compare two attempts

```javascript
db.samples.aggregate([
  { $match: { contact: true } },
  { $group: {
      _id: "$sessionId",
      meanForceN: { $avg: "$forceN" },
      peakForceN: { $max: "$forceN" },
      contactSamples: { $sum: 1 }
  } },
  { $sort: { meanForceN: 1 } }
])
```

**Why judges like it:** it shows the database turning raw sensor data into *insight about a learner*.

## 14.4b (built): Which session is the newest and how long was it?

```javascript
db.sessions.aggregate([
  { $match: { status: "completed" } },
  { $project: {
      _id: 0, sessionId: 1,
      minutes: { $round: [{ $divide: [{ $subtract: ["$completedAt", "$createdAt"] }, 60000] }, 2] }
  } },
  { $sort: { minutes: 1 } }
])
```

> This works if `createdAt` and `completedAt` are stored as real dates. If it returns nothing or an error, they are
> probably stored as text; skip this one rather than spending time on it.

## 14.5 (built, in Atlas): A chart in five minutes

Atlas has a **Charts** feature. Open it from the Atlas menu, add your `surge_prep` data source, and create a **line
chart** from `samples` with:

- X axis: `timestampMs`
- Y axis: `forceN`
- Filter: `sessionId` = your session

You get a shareable force curve with no code. (Menu names may differ slightly; search the Atlas docs for "Charts".)

## 14.6 (idea, not built): Store the scorecard in a `results` collection

Right now, the metrics are computed and returned but **not saved**. A small change would save them, so a learner's
progress could be charted across many sessions.

The shape could be:

```json
{
  "sessionId": "…",
  "completedAt": "…",
  "illustrativeScorePercent": 71.5,
  "peakForceN": 1.9,
  "layerViolations": 0,
  "tubePlacementComplete": true
}
```

Where it goes: in `backend/src/surge_prep/service.py`, inside `complete_session`, after the metrics are calculated,
write the result through the `Store` interface (`store.py`), adding a `save_result` method to both `MemoryStore` and
`MongoStore`. **This is not built.** Ask for it if you want it, and it needs a test in `backend/tests/`.

## 14.7 (idea, not built): A progress dashboard for the learner

With `results` stored, a one-page dashboard could show: score per attempt, the weakest component, and a "next drill"
suggestion pulled from the practice tutorial. This is the best story for **Design** and **WOW**.

## 14.8 (idea, not built): Atlas Vector Search for a "similar attempts" coach

Store an embedding of each attempt's force/depth curve and find the **most similar expert attempt**. This is real
Atlas functionality, but it needs an embedding step and an index. **Do this only if everything else is finished.**

## 14.9 What to say about it

Keep the claim exactly as large as what is real:

> "Every sensor sample and every physics frame is stored in **MongoDB Atlas**, indexed by session and time. That
> lets us replay any attempt exactly, re-score it later, and compare attempts, all from one database."

---

# Part 15: The demo and the Devpost submission

## Step 15.1: The live demo (about 2.5 minutes)

Judges want a **live demo, not slides.** Rehearse this three times.

| Time | Do | Say |
| --- | --- | --- |
| 0:00 | Hold up the tool | "Surgeons practise on plastic and cadavers. We built a tool that gives instant, objective feedback." |
| 0:15 | Show the bridge window with 3 tags | "A camera tracks three AprilTags for position, and a pressure sensor tells us depth." |
| 0:30 | Hover, then press lightly on the surface | "Watch the virtual scalpel follow my hand. Light pressure, shallow cut." |
| 0:50 | Cut through skin, then press harder | "Pressing harder goes through fat and muscle. The physics is real, not animated." |
| 1:20 | Press `2`, open the tract | "Blunt dissection spreads tissue instead of cutting it." |
| 1:40 | Show Atlas, refresh the `samples` count | "Every sample and physics frame is stored in **MongoDB Atlas**, so any attempt can be replayed." |
| 2:00 | Show one aggregation or chart | "Here is my force over time. We can compare attempts and see improvement." |
| 2:20 | Show the scorecard | "It is training telemetry, not a clinical score. It tells the learner which habit to fix." |

## Step 15.2: Your backup plan

Things fail on stage. Prepare for it:

| If this fails | Do this |
| --- | --- |
| Camera cannot see tags | Use `--simulate` (mouse) and say so honestly |
| Sensor is dead | Use WASD in Unity and say so honestly |
| Wi-Fi drops | Keep the local Docker MongoDB ready (Part 7 uses the same code) and a recorded video |
| Unity crashes | Show the recorded video, then explain the architecture slide-free using the map in Part 3 |

**Record a 60 to 90 second video of a good run tonight.** It is optional on Devpost but strongly recommended, and it is
your safety net.

## Step 15.3: Prepare the repository

1. Make sure no secret is committed:

```bash
git grep -n "mongodb+srv"
```

**What you should see:** only placeholders (like `YOURPASSWORD`), never a real password. If a real one appears,
**rotate the Atlas password immediately** and remove it from the history.

2. Make sure the README explains, in the first screen: what it is, how to run it, and the safety note.
3. Push your work. **You need a GitHub account and a fork or repo you can push to.** Pushing is your action; if git
   asks you to sign in, do that yourself.
4. The repo link on Devpost must be **public and open**. Test it in a private browser window.

## Step 15.4: The Devpost submission, step by step

1. Go to the Hack the North 2026 page on Devpost, choose **Create project** (or **Edit project** if it exists).
2. **Project name and tagline:** short and clear, for example *"Surge Prep: hands-on chest-tube practice with real
   physics"*.
3. **Description:** use the template below.
4. **Built with:** Python, OpenCV, AprilTags, ESP32-C3, Arduino, Unity, SOFA, FastAPI, **MongoDB Atlas**.
5. **Links:** the public repo. Add the demo video link if you made one.
6. **Team:** add every teammate and enter each **badge ID exactly as printed under the QR code** on their badge.
7. **Prizes:** select the ones from Step 2.3 that you can honestly justify.
8. **Images:** add your Atlas screenshot, the map from Part 3, and a photo of the rig.
9. **Submit.** Then open the public project page and check it displays correctly.

## Step 15.5: Description template

> **Inspiration.** Practising invasive procedures is hard: cadavers and mannequins are scarce, and feedback is
> subjective. We wanted a safe way to build the *feel* of controlled pressure and depth.
>
> **What it does.** A hand-held training tool with AprilTags and a force sensor controls a virtual scalpel. Position
> comes from a camera, pressure sets cut depth, and a physics engine (SOFA) simulates skin, fat, muscle, and pleura.
> A guided on-screen tutorial and a scorecard coach the learner.
>
> **How we built it.** OpenCV finds AprilTags 1 to 3; an ESP32-C3 reads an FSR; a Python bridge streams both to
> Unity; Unity sends samples through a controller and API to SOFA. **MongoDB Atlas** stores every sample and physics
> snapshot, indexed by session and time, powering replay, re-scoring, and per-attempt analytics.
>
> **Challenges.** Mapping sensor pressure to physical depth, keeping tracking stable under real lighting, and keeping
> the database, controller, and physics in one consistent contract.
>
> **What we learned.** Designing around a single source of truth (the database), and being honest about what is
> illustrative.
>
> **What's next.** Store scorecards for progress charts, iPhone/Cardboard VR, and instructor-reviewed exercises.
>
> **Safety.** Training prototype only. Not a medical device. Never for use on people.

## Step 15.6: Final checks (do these at least 45 minutes before 8:00 AM)

- [ ] The project page opens while logged out.
- [ ] The repo link opens while logged out, and no password is visible anywhere.
- [ ] Every teammate is listed with the correct badge ID.
- [ ] MongoDB Atlas (and any other honest prize) is selected.
- [ ] The video plays.
- [ ] You pressed the actual **Submit** button, and the status is not "draft".

---

# Part 16: Glossary

| Word | Meaning |
| --- | --- |
| **AprilTag** | A printed square barcode-like marker a camera can find and locate |
| **FSR** | Force-sensitive resistor; its resistance drops as you press harder |
| **ESP32-C3** | A small, cheap microcontroller board with USB and Wi-Fi |
| **Voltage divider** | Two resistors that split a voltage; here the FSR and a 10 kΩ resistor |
| **ADC** | Analog-to-digital converter; turns a voltage into a number |
| **Bridge** | The Python program joining the camera and sensor and sending to Unity |
| **UDP** | A fast, simple network message format (no connection needed) |
| **Unity** | The game engine that draws the virtual room and scalpel |
| **SOFA** | The physics engine that simulates soft tissue and cutting |
| **Controller** | The service between Unity/hardware and the API |
| **API** | The service that owns the simulation and the database |
| **MongoDB** | A document database; stores JSON-like documents |
| **Atlas** | MongoDB's cloud service |
| **Cluster** | A running MongoDB in Atlas |
| **Collection** | A group of documents, like a table |
| **Document** | One JSON-like record |
| **Index** | A lookup structure that makes queries fast |
| **Aggregation** | A pipeline that groups and summarises documents |
| **Connection string** | The address + login used to reach the database |
| **Session** | One practice attempt |
| **Sample** | One measurement of the tool at one instant |
| **Snapshot** | One frame of the simulated world |
| **Replay** | Playing a stored attempt back from its snapshots |
| **Pleura** | The lining around the lung |
| **Blunt dissection** | Separating tissue by spreading, not cutting |
| **Deadband** | A small range of sensor values that is ignored as noise |
| **Origin** | The reference point you call `(0, 0)` |

---

# Part 17: Troubleshooting everything

| Symptom | Most likely cause | Fix |
| --- | --- | --- |
| Health says `"persistence":"memory"` | The URI variable was not set in that terminal | Set `SURGE_PREP_MONGODB_URI` and restart the API |
| API fails with an authentication error | Wrong username or password | Recheck the database user; regenerate the password if needed |
| API fails with a timeout or server-selection error | Your IP is not allowed | Atlas → Network Access → add your current IP |
| It worked, then stopped | Your IP changed on Wi-Fi | Add the new IP |
| Error mentioning `dnspython` or `+srv` | Missing DNS support | `pip install "pymongo[srv]"` |
| Password contains `@` or `/` and it fails | Not URL-encoded | Use a letters-and-numbers password |
| `git clone` says "Filename too long" | Windows path length | Clone to a short path and use `-c core.longpaths=true` |
| No COM port for the ESP32-C3 | Charge-only cable, or CDC off | Use a data cable, enable **USB CDC On Boot**, try the `9`+`RST` trick |
| Serial Monitor shows nothing | CDC off, or wrong baud | Enable CDC On Boot; use 115200 |
| Bridge cannot open the serial port | Serial Monitor still open | Close it |
| Bridge says `tags=0` | Light, size, or wrong family | Part 10.3 |
| Tool moves the wrong direction | Camera vs surface axes | Tick `invertX` / `invertZ` |
| Blade never reaches the skin | Sensor not zeroed, or `--fsr-max` too high | Press `c`; lower `--fsr-max` |
| Blade dives with a light touch | `--fsr-max` too low, or drifted baseline | Raise it; press `c` |
| Cut happens with no pressure | Deadband too small | Raise `deadband` |
| HUD says WASD fallback | Bridge not running or port mismatch | Start the bridge; keep both on port 5005 |
| HUD says SOFA OFFLINE | Physics not connected | Path A: run the showcase script. Path B: expected. Say so |
| **Surge Prep** menu missing | Package not linked | Reinstall it from disk (Step 11.2) |
| Scene looks stale after a pull | Scene not rebuilt | **Surge Prep → Build Chest-Tube Showcase** |
| Port 8000 / 8100 / 27017 busy | Something else is using it | Stop the old process, or change the port |
| An aggregation returns nothing | Field name typo, or wrong session | Check field names in Part 8; `countDocuments` first |
| Atlas shows no collections | The API has not written yet | Do Step 7.7, or complete a run |

---

# Part 18: Cheat sheet

**Start order:** Atlas → API → controller → bridge → Unity Play.

```powershell
# terminal 1: API (Path B)
$env:SURGE_PREP_MONGODB_URI = "mongodb+srv://…"
$env:SURGE_PREP_MONGODB_DATABASE = "surge_prep"
$env:SURGE_PREP_SIMULATION_BACKEND = "memory"
.venv\Scripts\python -m uvicorn surge_prep.app:app --app-dir backend/src --host 127.0.0.1 --port 8000

# terminal 2: controller
$env:SURGE_PREP_API_URL = "http://127.0.0.1:8000"
.venv\Scripts\python -m uvicorn scalpel_controller.app:app --app-dir controller/src --host 127.0.0.1 --port 8100

# terminal 3: bridge
py -3.12 hardware/tag_fsr_bridge.py --port COM3 --fsr-max 3000
```

**Bridge keys:** `z` set origin · `c` zero sensor · `q` quit.
**Unity keys:** `1/2/3` tools · `R` twice reset · `Tab` guidance · `F/C/O` cameras · `H` head close-up · `B` overhead · `T` 360 turntable · `K` cutaway.
**Health checks:** `curl http://127.0.0.1:8000/health` and `curl http://127.0.0.1:8100/health`.
**Pressure to depth:** hover +6 mm · skin 0 to −3 · fat −3 to −15 · muscle −15 to −25 · pleura −25 to −32.
**Deadline:** Sunday Sep 20, 2026, **8:00 AM EDT**. Submit early.
**Honesty line for judges:** "This is an illustrative training prototype, not a medical device."

---

*Related files:* `docs/CHEST_TUBE_PRACTICE_TUTORIAL.md` (the hands-on practice guide), `hardware/README.md`,
`README.md`, `docs/decisions/0005-visible-incision-and-chest-depth.md`.
