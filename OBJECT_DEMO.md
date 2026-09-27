# Chat and map demo

Open http://pi.local:8000/ and keep the phone camera/GPS page active.

1. Place the phone next to the Monster Energy can. Chat: **add moster as one of my things**. A green can icon saves the current phone position.
2. Beside the water bottle: **add water bottle to my things**. A blue bottle icon appears. Click icons for saved time, accuracy, and camera frame if available.
3. **Where is my monster?** highlights its icon.
4. **I moved my monster** marks its previous pin amber and unconfirmed. Move it, then **update monster here** beside the object to record the new phone position.
5. For camera rediscovery, print `/object-tags.html` after adding objects and attach each label to its matching prop. Chat **set camera zone to Kitchen table**, then **scan my objects**. Hold the label steady for two frames. A confirmed scan updates its stored position and photo. **Stop scanning** ends scanning.
6. **set here as my home** saves the current phone position as a fixed place.
7. **set the FIU publix as my local grocery store** searches Google Places and asks you to choose the exact match. Requires the server Google key with Places API (New) enabled. Google-derived pins require the browser Google Maps key. Stored aliases join route destinations; walking route chat additionally requires configured OpenAI and Google Routes access.

Objects and places persist locally. No demo objects are automatically added. Earlier Cane/Walker seeds are archived with history preserved. Coordinates describe phone position and accuracy, not precise indoor object position. Initial saves are user reports; attached-label scans are camera observations. Untagged brand recognition and autonomous indoor guidance are not implemented.
