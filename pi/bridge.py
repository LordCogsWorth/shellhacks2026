"""
bridge.py — the Raspberry Pi "brain" for the Guide-Dog robot.

What it does:
  * Talks to the Zeus Car's Arduino over USB serial (drive commands out, sensor telemetry in)
  * Gets GPS from an iPhone: the phone opens https://<pi>:8443/phone.html and streams
    its location over a WebSocket (or, optionally, an NMEA app like GPS2IP over TCP)
  * Streams the Pi Camera as MJPEG at /video.mjpg
  * Serves your dashboard (the shellhacks2026 repo) at http://<pi>:8000/
  * One WebSocket at /ws that the dashboard uses for everything
  * Follows a GPS route (list of waypoints the dashboard sends)
  * Barks (plays a sound + flashes red) when it sees something on the "dislike" list

Run:
    source ~/dogenv/bin/activate
    python bridge.py            # then open http://<pi-ip>:8000 on your laptop

Environment overrides (optional):
    ARDUINO_PORT=/dev/serial/by-id/...   GPS_TCP=172.20.10.1:11123  (NMEA app fallback)
    DASHBOARD_DIR=~/guide-dog/dashboard  BARK_SOUND=~/guide-dog/pi/bark.wav
"""

import asyncio
import uuid
import sqlite3
from collections import OrderedDict
import io
import json
import socket
import math
import os
import subprocess
import threading
import time
import urllib.request
import shutil
from pathlib import Path

from saved_places import SavedPlaces
from object_memory import ObjectMemory
from manual_control import manual_command
from navigation import Navigator, NavigationError, config as navigation_config, presets, WALK_WARNING

import serial
import serial.tools.list_ports
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

try:
    import pynmea2
except ImportError:
    pynmea2 = None

# ---------------------------------------------------------------- settings
MAX_POWER = 60                 # % motor power cap (walking pace for a small car)
DEADMAN_S = 0.4                # stop if dashboard stops sending drive msgs
BARK_COOLDOWN_S = 6
WAYPOINT_RADIUS_M = 4          # "arrived at this waypoint" distance (GPS is ~2-5 m accurate)
GPS_MAX_ACCURACY_M = 25        # ignore phone fixes worse than this (indoors, cold start)
GPS_STALE_S = 15                # treat GPS as lost if no update for this long
CERT_DIR = Path(__file__).with_name("certs")   # made by make_certs.sh — needed for iPhone GPS
MAG_DECLINATION = -7.0         # degrees; Miami ≈ -7°. Look yours up at ngdc.noaa.gov
DASHBOARD_DIR = Path(os.path.expanduser(os.getenv("DASHBOARD_DIR", str(Path(__file__).resolve().parent.parent / "dashboard"))))
BARK_SOUND = os.path.expanduser(os.getenv("BARK_SOUND", str(Path(__file__).with_name("bark.wav"))))


# ---------------------------------------------------------------- helpers
def find_port(env_name, hints):
    """Use the env var if set, otherwise guess by USB description."""
    if os.getenv(env_name):
        return os.getenv(env_name)
    for p in serial.tools.list_ports.comports():
        text = f"{p.description} {p.manufacturer} {p.product}".lower()
        if any(h in text for h in hints):
            return p.device
    return None


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def say(text):
    """Speak out loud on the robot's speaker (needs: sudo apt install espeak-ng)."""
    if not shutil.which("espeak-ng"):
        return
    subprocess.Popen(["espeak-ng", "-s", "160", text],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- shared state
state = {
    "dist": None, "ir": 0, "heading": None,
    "gps": None,                  # {"lat","lon","fix","acc","src","ts"}
    "mode": "idle",               # idle | manual | route
    "route": [], "wp_index": 0,
    "alerts": [],
}
dislike = {"cat", "dog", "bicycle", "skateboard", "motorcycle"}
last_bark = 0.0
last_drive_msg = 0.0
drive_cmd = (0, 0, 0)             # (angle, power, rot)
state_lock = threading.Lock()


# ---------------------------------------------------------------- Arduino link
class Arduino:
    """Reconnect independently so the GPS/web server survives USB failures."""
    def __init__(self):
        self.ser = None
        self.lock = threading.Lock()
        self.last_telemetry = 0.0
        threading.Thread(target=self._reader, daemon=True).start()

    @property
    def connected(self):
        return self.ser is not None and time.monotonic() - self.last_telemetry < 2

    def send(self, line):
        with self.lock:
            if self.ser is not None:
                try:
                    self.ser.write((line + "\n").encode())
                except (serial.SerialException, OSError):
                    pass  # reader reconnects; firmware watchdog stops motors

    def move(self, angle, power, rot):
        if self.connected:
            self.send(f"M {int(angle)} {int(power)} {int(rot)}")

    def stop(self):
        self.send("S")

    def led(self, r, g, b):
        self.send(f"L {int(r)} {int(g)} {int(b)}")

    def _reader(self):
        while True:
            port = find_port("ARDUINO_PORT", ["ch340", "arduino", "usb serial", "wch", "16u2"])
            if not port:
                time.sleep(3)
                continue
            try:
                with serial.Serial(port, 115200, timeout=0.2, write_timeout=0.5) as link:
                    time.sleep(2)
                    link.reset_input_buffer()
                    link.write(b"S\n")
                    with state_lock:
                        state["mode"] = "idle"
                    with self.lock:
                        self.ser = link
                    print(f"[arduino] connected {port}", flush=True)
                    while True:
                        raw = link.readline().decode(errors="replace").strip()
                        parts = raw.split()
                        if not parts:
                            continue
                        try:
                            if parts[0] == "T" and len(parts) == 4:
                                dist, ir, heading = float(parts[1]), int(parts[2]), int(parts[3])
                                if not math.isfinite(dist):
                                    continue
                                with state_lock:
                                    state.update(dist=dist, ir=ir, heading=heading)
                                self.last_telemetry = time.monotonic()
                            elif parts[0] == "E":
                                with state_lock:
                                    state["alerts"].append(raw)
                                    state["mode"] = "idle"
                        except ValueError:
                            continue
            except (serial.SerialException, OSError) as exc:
                print(f"[arduino] unavailable: {exc}", flush=True)
            finally:
                with self.lock:
                    self.ser = None
                self.last_telemetry = 0
                with state_lock:
                    state.update(mode="idle", dist=None, heading=None)
            time.sleep(3)


# ---------------------------------------------------------------- GPS (iPhone)
def set_gps(lat, lon, acc, src):
    lat, lon = float(lat), float(lon)
    acc = float(acc) if acc is not None else None
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Invalid GPS coordinates")
    if acc is not None and (not math.isfinite(acc) or acc < 0):
        raise ValueError("Invalid GPS accuracy")
    with state_lock:
        state["gps"] = {"lat": lat, "lon": lon, "acc": acc, "src": src,
                        "fix": acc is None or acc <= GPS_MAX_ACCURACY_M, "ts": time.time()}


def gps_fix():
    """Current GPS if it is good and fresh, else None."""
    g = state["gps"]
    if not g or not g["fix"] or time.time() - g["ts"] > GPS_STALE_S:
        return None
    return g


def nmea_tcp_reader():
    """Optional fallback: an iPhone app that streams NMEA over TCP (e.g. GPS2IP).
    Main path is phone.html, which needs no extra app."""
    target = os.getenv("GPS_TCP")
    if not target:
        return
    if not pynmea2:
        print("[gps] GPS_TCP set but pynmea2 not installed")
        return
    host, port = target.rsplit(":", 1)
    while True:
        try:
            with socket.create_connection((host, int(port)), timeout=10) as sock:
                print(f"[gps] NMEA stream from {target}")
                for line in sock.makefile("r", errors="ignore"):
                    line = line.strip()
                    if not line.startswith(("$GPGGA", "$GNGGA")):
                        continue
                    try:
                        msg = pynmea2.parse(line)
                    except pynmea2.ParseError:
                        continue
                    if int(msg.gps_qual or 0) > 0:
                        hdop = float(msg.horizontal_dil or 5)
                        set_gps(msg.latitude, msg.longitude, hdop * 5, "nmea")  # rough metres
        except OSError as e:
            print(f"[gps] {target} unavailable ({e}); retrying in 3 s")
            time.sleep(3)


# ---------------------------------------------------------------- camera (MJPEG)
class FrameBuffer(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.cond = threading.Condition()

    def write(self, buf):
        with self.cond:
            self.frame = bytes(buf)
            self.updated = time.monotonic()
            self.cond.notify_all()


frames = FrameBuffer()
frames.updated = 0.0
camera_error = "Camera has not delivered a frame"
CAMERA_URL = os.getenv("CAMERA_URL", "")
CAMERA_SOURCE = os.getenv("CAMERA_SOURCE", "network")


def network_camera_reader():
    """One upstream MJPEG connection shared by all dashboard viewers."""
    global camera_error
    while True:
        try:
            request = urllib.request.Request(CAMERA_URL, headers={"User-Agent": "GuideDog/1.0"})
            with urllib.request.urlopen(request, timeout=8) as response:
                if "multipart/" not in response.headers.get("Content-Type", "").lower():
                    raise ValueError("Camera URL did not return an MJPEG stream")
                pending = bytearray()
                while True:
                    chunk = response.read1(16384)
                    if not chunk:
                        raise OSError("Camera stream ended")
                    pending.extend(chunk)
                    while True:
                        start = pending.find(b"\xff\xd8")
                        if start < 0:
                            pending[:] = pending[-1:]
                            break
                        end = pending.find(b"\xff\xd9", start + 2)
                        if end < 0:
                            del pending[:start]
                            break
                        frame = bytes(pending[start:end + 2])
                        del pending[:end + 2]
                        frames.write(frame)
                        camera_error = None
                    if len(pending) > 4 * 1024 * 1024:
                        raise ValueError("Camera frame exceeds 4 MB")
        except Exception as exc:
            camera_error = str(exc)
            print(f"[camera] {exc}; retrying", flush=True)
            time.sleep(3)


def start_camera():
    global camera_error, cam
    if CAMERA_SOURCE == "phone":
        camera_error = "Waiting for iPhone camera sharing"
        return
    if CAMERA_URL:
        if not CAMERA_URL.startswith(("http://", "https://")):
            camera_error = "CAMERA_URL must be an HTTP(S) MJPEG URL"
            return
        threading.Thread(target=network_camera_reader, daemon=True).start()
        return
    try:
        from picamera2 import Picamera2
        from picamera2.encoders import JpegEncoder
        from picamera2.outputs import FileOutput
        cam = Picamera2()
        cam.configure(cam.create_video_configuration(main={"size": (640, 480)}))
        cam.start_recording(JpegEncoder(), FileOutput(frames))
        camera_error = None
    except Exception as exc:
        camera_error = "Set CAMERA_URL for the Zeus ESP32 camera. " + str(exc)
        print(f"[camera] {camera_error}", flush=True)


# ---------------------------------------------------------------- behaviours
def maybe_bark(labels, arduino):
    global last_bark
    hits = [l for l in labels if l.lower() in dislike]
    if not hits or time.time() - last_bark < BARK_COOLDOWN_S:
        return None
    last_bark = time.time()
    if os.path.exists(BARK_SOUND):
        subprocess.Popen(["aplay", "-q", BARK_SOUND])
    arduino.led(255, 0, 0)                     # flash red...
    threading.Timer(1.0, lambda: arduino.led(0, 255, 0)).start()   # ...then back to green
    return hits[0]


def route_step():
    """One tick of the GPS route follower. Returns (angle, power, rot)."""
    with state_lock:
        gps, heading = gps_fix(), state["heading"]
        route, i = state["route"], state["wp_index"]
    if not gps or heading is None or i >= len(route):
        return (0, 0, 0)
    lat, lon = route[i]
    if haversine_m(gps["lat"], gps["lon"], lat, lon) < WAYPOINT_RADIUS_M:
        with state_lock:
            state["wp_index"] += 1
            done = state["wp_index"] >= len(route)
            if done:
                state["mode"] = "idle"
        say("You have arrived." if done else "Next turn.")
        return (0, 0, 0)
    true_heading = (heading + MAG_DECLINATION) % 360
    err = (bearing_deg(gps["lat"], gps["lon"], lat, lon) - true_heading + 540) % 360 - 180
    if abs(err) > 35:                               # way off: turn in place first
        return (0, 0, 40 if err > 0 else -40)
    return (0, MAX_POWER * 0.7, max(-30, min(30, err)))   # drive + gentle correction


# ---------------------------------------------------------------- web app
app = FastAPI()
arduino = None
clients = set()
started = False
navigator = Navigator()
manual_owner = None
manual_feedback = "Manual controls off"
object_store = None
place_store = None
scan_frames = OrderedDict()


def memory():
    global object_store
    if object_store is None:
        object_store = ObjectMemory(Path(__file__).parent / 'data' / 'objects.sqlite3')
    return object_store


def places():
    global place_store
    if place_store is None or place_store.memory is not memory():
        place_store = SavedPlaces(memory())
    return place_store


@app.on_event("startup")
async def startup():
    global arduino, started
    if started:                  # two servers (http + https) share this app; start once
        return
    started = True
    arduino = Arduino()
    start_camera()
    threading.Thread(target=nmea_tcp_reader, daemon=True).start()
    asyncio.create_task(control_loop())
    asyncio.create_task(telemetry_loop())


async def control_loop():
    """10 Hz: decide what the motors should do and send it (this is also the Arduino heartbeat)."""
    while True:
        mode = state["mode"]
        if state['dist'] is not None and 0 < state['dist'] < 20 and gps_fix():
            if navigator.observe(['obstacle'], gps_fix()):
                state['mode'] = mode = 'idle'
                state['alerts'].append('E OBSTACLE: hazard review required')
                arduino.stop()
                asyncio.create_task(navigator.replan(gps_fix()))
        if navigator.hold and mode != "manual":
            state['mode'] = mode = 'idle'
        if mode == "manual" and time.time() - last_drive_msg < DEADMAN_S:
            angle, power, rot = drive_cmd
            if power > 0 and angle == 0 and (state['dist'] is None or state['dist'] <= 0 or state['dist'] < 25):
                arduino.stop()
            else:
                arduino.move(angle, power, rot)
        elif mode == "route":
            arduino.move(*route_step())
        else:
            arduino.stop()
        await asyncio.sleep(0.1)


async def telemetry_loop():
    while True:
        with state_lock:
            msg = {k: state[k] for k in ("dist", "ir", "heading", "gps", "mode", "wp_index")}
            msg["manual_feedback"] = manual_feedback
            msg["gps_ok"] = gps_fix() is not None
            msg["arduino_connected"] = arduino.connected
            msg["camera_connected"] = time.monotonic() - frames.updated < 10
            msg["alerts"], state["alerts"] = state["alerts"], []
        await broadcast({"type": "telemetry", **msg})
        await asyncio.sleep(0.2)


async def broadcast(obj):
    data = json.dumps(obj)
    for ws in list(clients):
        try:
            await ws.send_text(data)
        except Exception:
            clients.discard(ws)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    global last_drive_msg, drive_cmd, dislike, manual_owner, manual_feedback
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            m = json.loads(await ws.receive_text())
            t = m.get("type")
            if t == 'manual':
                enabled = m.get('enabled') is True and arduino.connected
                if enabled or manual_owner is ws:
                    state['mode'] = 'idle'
                    arduino.stop()
                    if manual_owner is not None and manual_owner is not ws:
                        try:
                            await manual_owner.send_json({'type':'manual_status','enabled':False,'message':'Another dashboard took manual control.'})
                        except Exception:
                            pass
                    manual_owner = ws if enabled else None
                manual_feedback = 'Manual ready · 40% maximum motor output' if enabled else ('Arduino offline · check USB and car power' if m.get('enabled') is True else 'Manual off')
                await ws.send_json({'type':'manual_status','enabled':enabled,'message':manual_feedback})
            elif t == 'manual_stop':
                if manual_owner is ws:
                    state['mode'] = 'idle'
                    arduino.stop()
                    manual_feedback = 'Stopped · release complete'
            elif t == 'drive':
                if manual_owner is not ws:
                    continue
                command, error = manual_command(m, state['dist'], arduino.connected)
                if error:
                    state['mode'] = 'idle'
                    arduino.stop()
                    manual_feedback = error
                    continue
                drive_cmd = command
                last_drive_msg = time.time()
                state['mode'] = 'manual'
                manual_feedback = 'Driving · release arrows to stop'
            elif t == 'estop':
                state['mode'] = 'idle'
                manual_owner = None
                manual_feedback = 'Emergency stop · turn manual on to resume'
                arduino.stop()
                arduino.led(255, 0, 0)
                await broadcast({'type':'manual_status','enabled':False,'message':manual_feedback})
            elif t == "route":
                state['mode'] = 'idle'
                arduino.stop()
                await ws.send_json({'type': 'error', 'message': 'Autonomous street navigation is disabled. Use chat to preview a walking route.'})
            elif t == "detections":      # {labels: ["person", "dog", ...]}
                labels = m.get('labels', [])
                if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels) or len(labels) > 50:
                    continue
                if time.monotonic() - frames.updated > 3:
                    continue
                if navigator.observe(labels, gps_fix()):
                    state['alerts'].append('E OBSTACLE: hazard review required')
                    state['mode'] = 'idle'
                    arduino.stop()
                    asyncio.create_task(navigator.replan(gps_fix()))
                barked = maybe_bark(labels, arduino)
                if barked:
                    await broadcast({"type": "bark", "label": barked})
            elif t == "dislike":         # {labels: [...]}
                dislike = {l.lower() for l in m.get("labels", [])}
            elif t == "phone_gps":       # from phone.html: {lat, lon, acc}
                try:
                    set_gps(m["lat"], m["lon"], m.get("acc"), "iphone")
                    await ws.send_json({"type": "gps_ack", "gps_ok": gps_fix() is not None})
                except (KeyError, TypeError, ValueError):
                    await ws.send_json({"type": "error", "message": "Invalid GPS fix"})
            elif t == "say":
                say(m.get("text", ""))
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)
        if manual_owner is ws:
            manual_owner = None
            state['mode'] = 'idle'
            arduino.stop()
            manual_feedback = 'Manual stopped · dashboard disconnected'


@app.get('/memory')
async def map_memory():
    return {**memory().snapshot(), 'places': await places().snapshot()}


@app.post('/places/confirm')
async def confirm_place(request: Request):
    try:
        payload = await request.json()
        return places().confirm(payload.get('token'))
    except (ValueError, TypeError, AttributeError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


@app.get('/objects')
async def objects_list():
    return memory().snapshot()


@app.post('/objects')
async def objects_add(request: Request):
    try:
        payload = await request.json()
        return memory().add(payload.get('name'))
    except (ValueError, TypeError, AttributeError, sqlite3.IntegrityError):
        return JSONResponse({'error': 'Use a unique object name of 1–80 characters (maximum 50 objects).'}, status_code=400)


@app.post('/objects/context')
async def objects_context(request: Request):
    try:
        payload = await request.json()
        return {'zone': memory().set_zone(payload.get('zone'))}
    except (ValueError, TypeError, AttributeError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


@app.post('/objects/{object_id}/moved')
async def objects_moved(object_id: str):
    try:
        memory().mark_moved(object_id)
        return memory().snapshot()
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


@app.get('/objects/{object_id}/photo')
async def objects_photo(object_id: str):
    frame = memory().photo(object_id)
    if not frame:
        return JSONResponse({'error': 'No observation image yet'}, status_code=404)
    return Response(frame, media_type='image/jpeg', headers={'Cache-Control':'no-store'})


@app.get('/camera/snapshot.jpg')
async def camera_snapshot():
    if not frames.frame or time.monotonic() - frames.updated > 3:
        return JSONResponse({'error': 'Phone camera is not streaming. Open the phone page and Start camera.'}, status_code=503)
    token = uuid.uuid4().hex
    frame = frames.frame
    scan_frames[token] = (frame, time.monotonic(), time.time())
    while len(scan_frames) > 24:
        scan_frames.popitem(last=False)
    return Response(frame, media_type='image/jpeg', headers={'Cache-Control':'no-store','X-Frame-Id':token})


@app.post('/objects/observe')
async def objects_observe(request: Request):
    try:
        payload = await request.json()
        evidence = scan_frames.pop(payload.get('frame_id'), None)
        if not evidence or time.monotonic()-evidence[1] > 5:
            return JSONResponse({'error': 'Camera frame expired. Scan again.'}, status_code=409)
        zone = payload.get('zone') or memory().snapshot()['zone']
        if not zone:
            if not gps_fix():
                return JSONResponse({'error':'Start GPS or set a camera zone in chat before scanning.'}, status_code=409)
            zone = memory().set_zone('Current phone position')
        result = memory().observe(payload.get('tag'), zone, evidence[0], gps_fix(), observed_at=evidence[2])
        if result['changed']:
            await broadcast({'type':'object_event', **result})
        return result
    except (ValueError, TypeError, AttributeError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


@app.get('/navigation')
def navigation_status():
    cfg = navigation_config()
    try:
        destinations = presets()
        error = None
    except NavigationError as exc:
        destinations, error = [], str(exc)
    return {**navigator.snapshot(), 'destinations': destinations, 'configuration_error': error,
            'configured': {'openai': bool(cfg.get('OPENAI_API_KEY')), 'google_routes': bool(cfg.get('GOOGLE_MAPS_API_KEY'))},
            'google_maps_browser_key': cfg.get('GOOGLE_MAPS_BROWSER_KEY', ''), 'warning': WALK_WARNING}


@app.post('/chat')
async def navigation_chat(request: Request):
    try:
        body = await request.body()
        if len(body) > 4096:
            return JSONResponse({'error': 'Message too long.'}, status_code=413)
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError()
        # Route planning always begins at rest; never starts the motors.
        state['mode'] = 'idle'
        arduino.stop()
        message = payload.get('message')
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 1000:
            raise ValueError('Enter a message of 1–1000 characters.')
        place_reply = await places().chat(message, gps_fix())
        if place_reply:
            return place_reply
        frame = frames.frame if time.monotonic()-frames.updated < 3 else None
        object_reply = memory().chat(message, gps_fix(), frame)
        if object_reply:
            return object_reply
        return await navigator.plan_message(message, gps_fix(), extra_destinations=await places().destinations())
    except NavigationError as exc:
        return JSONResponse({'error': str(exc)}, status_code=409)
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)
    except TypeError:
        return JSONResponse({'error': 'Invalid chat request.'}, status_code=400)


@app.post('/navigation/acknowledge')
async def navigation_acknowledge():
    if not arduino.connected or state['dist'] is None or state['dist'] <= 0 or state['dist'] < 40:
        return JSONResponse({'error': 'Cannot clear stop: Arduino must be online and front distance at least 40 cm.'}, status_code=409)
    if any(time.time() - h['last_seen'] < 5 for h in navigator.hazards):
        return JSONResponse({'error': 'Hazard is still being observed. Keep stopped.'}, status_code=409)
    navigator.hold = False
    navigator.reason = 'Reviewed by operator. Manual control available; autonomous navigation remains disabled.'
    navigator.revision += 1
    return navigator.snapshot()


@app.post("/camera/frame")
async def phone_camera_frame(request: Request):
    global camera_error
    if CAMERA_SOURCE != "phone":
        return JSONResponse({"error": "Phone camera is not enabled"}, status_code=409)
    if request.headers.get("content-type", "").split(";")[0] != "image/jpeg":
        return JSONResponse({"error": "JPEG required"}, status_code=415)
    frame = bytearray()
    async for chunk in request.stream():
        frame.extend(chunk)
        if len(frame) > 512 * 1024:
            return JSONResponse({"error": "Frame too large"}, status_code=413)
    if len(frame) < 4 or not frame.startswith(b"\xff\xd8") or not frame.endswith(b"\xff\xd9"):
        return JSONResponse({"error": "Invalid JPEG"}, status_code=400)
    frames.write(frame)
    camera_error = None
    return {"received": True}


@app.get("/video.mjpg")
def video():
    def gen():
        while True:
            with frames.cond:
                frames.cond.wait(timeout=5)
                frame = frames.frame
                if frame is None or time.monotonic() - frames.updated > 10:
                    continue
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/health")
def health():
    return {
        "bridge": "online",
        "arduino_connected": bool(arduino and arduino.connected),
        "camera_connected": time.monotonic() - frames.updated < 10,
        "camera_error": camera_error if time.monotonic() - frames.updated < 10 else (camera_error or "Camera frames stopped"),
        "camera_source": CAMERA_SOURCE,
        "gps_received": state["gps"] is not None,
        "gps_ok": gps_fix() is not None,
        "https_configured": (CERT_DIR / "guidedog.crt").exists(),
    }


@app.get("/setup/ca.crt")
def download_ca():
    cert = CERT_DIR / "guidedog-ca.crt"
    if not cert.exists():
        return JSONResponse({"error": "Run make_certs.sh on the Pi first"}, status_code=503)
    return FileResponse(cert, media_type="application/x-x509-ca-cert", filename="guidedog-ca.crt")


if DASHBOARD_DIR.exists():
    app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")

async def main():
    import uvicorn
    servers = [uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8000, timeout_graceful_shutdown=3))]  # laptop dashboard
    cert, key = CERT_DIR / "guidedog.crt", CERT_DIR / "guidedog.key"
    if cert.exists() and key.exists():
        # iPhone Safari only shares location with HTTPS pages, so the phone uses port 8443
        servers.append(uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8443, timeout_graceful_shutdown=3,
                                                     ssl_certfile=str(cert), ssl_keyfile=str(key))))
        print("[https] iPhone GPS page: https://guidedog.local:8443/phone.html")
    else:
        print("[https] no certs — run ./make_certs.sh so the iPhone can send GPS")
    await asyncio.gather(*(srv.serve() for srv in servers))


if __name__ == "__main__":
    asyncio.run(main())
