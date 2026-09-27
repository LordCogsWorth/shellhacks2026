# Guide Dog Robot Demo

Dashboard and Raspberry Pi bridge for the SunFounder Zeus car. The dashboard shows live phone camera/GPS, robot telemetry, saved object and place icons, route previews, and supervised manual controls. This prototype is not validated as a mobility aid.

## Quick start on Raspberry Pi

1. Put the Pi and iPhone on the same Wi-Fi hotspot. Connect the Zeus Arduino USB cable to the Pi.
2. From this repo on your Mac, run `./deploy-from-mac.sh pi@pi.local` (or pass `pi@<address>`). The installer creates the service and HTTPS certificate.
3. Configure provider keys on the Pi (see below).
4. On the iPhone, open `https://pi.local:8443/phone.html`, install and trust the project CA certificate as prompted, then start GPS and camera.
5. On the dashboard computer, open `http://pi.local:8000/`.

If `pi.local` does not resolve, use the Pi's Wi-Fi address. `deploy-from-mac.sh` assumes SSH access and requests sudo interactively during installation.

## Provider keys

Keys are private files on the Pi and are excluded from Git. Run this from your Mac:

```sh
ssh -t pi@pi.local 'cd ~/guide-dog-live/pi && cp -n navigation.env.example navigation.env && chmod 600 navigation.env && nano navigation.env'
```

Paste `OPENAI_API_KEY`, a server Google key in `GOOGLE_MAPS_API_KEY`, and a separately restricted browser key in `GOOGLE_MAPS_BROWSER_KEY`. Enable OpenAI Responses API access and Google Places, Routes, and Maps JavaScript APIs as used. Restrict Google keys to the needed APIs; restrict the browser key by dashboard referrer. Save and exit nano. Keys are read per request. Never commit actual keys.

For local development, install `pi/requirements.txt`, copy `pi/navigation.env.example` to `pi/navigation.env`, then run `cd pi && python bridge.py`.

## Object and place demo

In dashboard chat, say `add moster as one of my things` or `add water bottle to my things`. These create saved map icons at the current phone GPS position. Say `I moved my monster`, then `update monster here` at its new position. For camera rediscovery, print labels from `/object-tags.html`, attach a label, set a camera zone in chat, and say `scan my objects`. Say `set the FIU publix as my local grocery store` to search Places and choose the exact match. See [OBJECT_DEMO.md](OBJECT_DEMO.md).

Chat-saved object positions are phone-reported; attached tag scans add camera sightings. GPS does not locate objects precisely indoors. Google place search needs Places API. Walking paths also need saved destinations, OpenAI and Google Routes access.

## Firmware

Firmware source is under `firmware/guide_dog_firmware/`. `upload-from-mac.sh` targets the Arduino IDE avrdude installation configured in that script. It reads flash and EEPROM backups before writing. Keep wheels raised and the shield on UPLOAD. Backups stay local and are ignored by Git.

## Checks and limits

Run `python -m unittest discover -s tests -v`, `node tests/manual-controls.cjs`, and `node tests/object-tags.cjs`. Manual controls are capped and require a clear front sensor for forward motion. Route previews never command autonomous driving. See [NAVIGATION_SETUP.md](NAVIGATION_SETUP.md) and [PROJECT_GUIDE.md](PROJECT_GUIDE.md).
