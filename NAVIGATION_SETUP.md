# Chat walking paths

## Implemented

- Dashboard chat calls the Pi's `/chat` endpoint.
- OpenAI Responses API selects an ID from your preset destination list using a strict JSON schema. The model never supplies arbitrary coordinates.
- The Pi resolves that ID to operator-verified coordinates and calls Google Routes with `travelMode=WALK` and alternative routes enabled.
- Google route geometry appears only on a Google map. Without a browser key the local observation map still works, but Google routes are not drawn on it.
- Route requests stop motion and create a preview. They never engage autonomous motors. The old map-click straight-line driving fallback is removed, including server acceptance of raw route commands.
- Repeated camera observations add category icons and an uncertainty circle at the phone's observation position. This is **not** the measured position of the object. COCO-SSD supports stop signs and generic traffic lights, but does not reliably read pedestrian signals, signs, crosswalk state, or arbitrary obstacles.
- New observations stop motion and trigger a rate-limited request for alternative routes if a plan exists. Candidates intersecting known observation areas are rejected. If all alternatives intersect, the plan is blocked and motion stays stopped. Google does not accept these local hazard polygons as an avoidance constraint; we filter the alternatives it returns. No local detour is fabricated.
- A hazard near the current position can block every route. A sighted operator must inspect and reposition the robot; GPS and monocular imagery cannot resolve a safe maneuver around it.
- Observations persist in memory until bridge restart, up to 100 records. They are not automatically declared safe when no longer detected. The operator acknowledgement unlocks manual control only after the front sensor reads at least 40 cm and no recorded hazard has been observed in the last 5 seconds. This check does not establish that the surrounding environment is safe.

## Private configuration

On the Pi, copy `pi/navigation.env.example` to `pi/navigation.env`, set mode 600, and edit it privately:

```bash
ssh -t pi@pi.local 'cd ~/guide-dog-live/pi && cp -n navigation.env.example navigation.env && chmod 600 navigation.env && nano navigation.env'
```

Set:

- `OPENAI_API_KEY`: server-only OpenAI API key.
- `OPENAI_MODEL`: defaults to `gpt-4.1-mini`; choose a Responses model that supports structured outputs and is available to your API account.
- `GOOGLE_MAPS_API_KEY`: server-only Google key with Routes API enabled and billing configured. Restrict to that API and appropriate server restrictions.
- `GOOGLE_MAPS_BROWSER_KEY`: a separate browser key with Maps JavaScript API enabled. This key is intentionally public; restrict HTTP referrers to your dashboard URLs, including port, and restrict the allowed API.

Keys are read on each request; no service restart is needed. Never paste secret keys into chat, JavaScript files, or the public dashboard directory. Each request can incur provider charges. Provider failures leave the robot stopped and show a readable error.

## Preset destinations

Edit `/home/pi/guide-dog-live/pi/destinations.json`. It currently contains an empty array because no real destinations have been supplied. Example **format only**, using operator-provided real coordinates in place of the placeholders:

```json
[
  {
    "id": "grocery_store",
    "name": "Grocery store",
    "aliases": ["groceries", "supermarket"],
    "lat": "REPLACE_WITH_NUMERIC_LATITUDE",
    "lon": "REPLACE_WITH_NUMERIC_LONGITUDE"
  }
]
```

Coordinates must be finite numeric values in latitude/longitude range, and IDs must be unique. Confirm the accessible pedestrian entrance; a store's geographic center is not necessarily its entrance. The model receives names and aliases, not your GPS coordinates. Google receives route origin and destination coordinates. Destination names and coordinates are visible to clients on the trusted local hotspot.

## Use

1. Keep the iPhone's HTTPS page open; start GPS and camera. Mount the camera facing forward.
2. Reload the dashboard and enter “take me to the grocery store”, or click a configured preset.
3. Review the Google walking route, directions, provider warnings, and observed hazard icons.
4. A detection can stop manual movement; inspect it before using the operator acknowledgement. Street autonomy remains disabled.

The map and provider calls need internet access. Route planning alone does not make this robot suitable for guiding blind people through traffic. Independent navigation would require validated pedestrian-signal perception, localization, obstacle geometry, fail-safe control, and supervised hardware testing.

## Verification

Run with Python dependencies from the bridge plus `httpx`:

```bash
python -m unittest discover -s tests -v
node --check dashboard/navigation.js
node --check dashboard/dog.js
node --check dashboard/app.js
```

21 tests cover provider request formatting, destination allowlisting, refusals, ambiguous requests, stale GPS, invalid geometry, alternate-route filtering, no-route behavior, observation deduplication, in-flight hazard changes, secret isolation, and motor-command rejection. Provider responses in these tests are mocked; they do not establish live API access, map authorization, or field safety.

## Sources

- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Google computeRoutes](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes)
- [Google route options and walking warning](https://developers.google.com/maps/documentation/routes/route-opt)
- [Google map display and attribution policy](https://developers.google.com/maps/documentation/routes/policies)

The dashboard includes a local privacy/terms page. Before public distribution, publish operator-specific terms and privacy notices at publicly accessible URLs.
