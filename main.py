import os, requests, time, threading, random, traceback
from urllib.parse import urlencode
from fastapi import FastAPI, Request, Body
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# ── Debug: confirm env vars loaded ───────────────────────────────────────────
_gk = os.getenv("GROQ_API_KEY")
print(f"[ENV] GROQ_API_KEY loaded: {'YES — ' + _gk[:8] + '...' if _gk else 'NO — KEY IS MISSING'}")
print(f"[ENV] SPOTIFY_CLIENT_ID loaded: {'YES' if os.getenv('SPOTIFY_CLIENT_ID') else 'NO'}")

stop_flag = False
is_paused = False
last_playback_state = {"context_uri": None, "position_ms": None, "device_id": None}
spotify_tokens = {"access_token": None, "refresh_token": None, "expires_at": 0}

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI  = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:3000/callback")
GROQ_API_KEY  = os.getenv("GROQ_API_KEY")

SCOPES = " ".join([
    "user-read-private", "user-read-playback-state",
    "user-modify-playback-state", "user-read-currently-playing",
    "playlist-read-private", "user-library-read",
])

MOOD_CONFIG = {
    "focus": {
        "valence": (0.35, 0.65), "energy": (0.5, 0.85), "color": "#3b82f6",
        "queries": [
            "artist:Brian Eno ambient", "genre:lo-fi study",
            "artist:Tycho", "genre:post-rock instrumental",
            "artist:Nils Frahm", "focus flow state instrumental"
        ]
    },
    "chill": {
        "valence": (0.45, 0.75), "energy": (0.2, 0.5), "color": "#06b6d4",
        "queries": [
            "artist:Mac DeMarco", "genre:bedroom pop",
            "artist:Rex Orange County", "genre:indie folk chill",
            "artist:Tame Impala chill", "afternoon slow indie"
        ]
    },
    "moody": {
        "valence": (0.0, 0.32), "energy": (0.2, 0.6), "color": "#8b5cf6",
        "queries": [
            "artist:Lana Del Rey", "artist:The National",
            "genre:dream pop dark", "artist:Bon Iver",
            "artist:Radiohead", "genre:indie folk sad"
        ]
    },
    "hype": {
        "valence": (0.72, 1.0), "energy": (0.8, 1.0), "color": "#f97316",
        "queries": [
            "genre:hip hop hype", "artist:Travis Scott",
            "genre:electronic dance energy", "artist:Kanye West",
            "genre:trap hype", "workout pump up"
        ]
    },
    "late night": {
        "valence": (0.15, 0.45), "energy": (0.2, 0.55), "color": "#6366f1",
        "queries": [
            "artist:Frank Ocean", "genre:r&b slow night",
            "artist:Daniel Caesar", "genre:neo soul late night",
            "artist:SZA", "midnight drive slow"
        ]
    },
}

# ── Serve frontend ────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    with open("routinetunes.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/health")
def health():
    return {"status": "ok"}

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.get("/auth/login")
def login():
    params = {"response_type": "code", "client_id": CLIENT_ID, "scope": SCOPES,
              "redirect_uri": REDIRECT_URI, "show_dialog": True}
    return RedirectResponse(url="https://accounts.spotify.com/authorize?" + urlencode(params))

@app.get("/callback")
def callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        return HTMLResponse("<script>window.close();</script><p>Auth failed. Close this tab.</p>")
    r = requests.post("https://accounts.spotify.com/api/token",
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
        auth=(CLIENT_ID, CLIENT_SECRET))
    tokens = r.json()
    if "access_token" not in tokens:
        return HTMLResponse("<script>window.close();</script><p>Auth failed. Close this tab.</p>")
    spotify_tokens["access_token"] = tokens["access_token"]
    spotify_tokens["refresh_token"] = tokens["refresh_token"]
    spotify_tokens["expires_at"]    = time.time() + tokens["expires_in"]
    # Self-closing success page — main window polls /devices to detect success
    return HTMLResponse("""
<!DOCTYPE html><html><head><title>Connected</title>
<style>body{font-family:sans-serif;background:#0a0a0a;color:#1DB954;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0;flex-direction:column;gap:1rem}
p{font-size:1.1rem}small{color:#555;font-size:0.8rem}</style></head>
<body><p>✓ Spotify connected</p><small>This window will close automatically...</small>
<script>setTimeout(()=>window.close(),1500);</script></body></html>
""")

# ── Devices & playback ────────────────────────────────────────────────────────
@app.get("/devices")
def get_devices():
    t = _token()
    if not t: return {"error": "Not authenticated"}
    return requests.get("https://api.spotify.com/v1/me/player/devices",
                        headers={"Authorization": f"Bearer {t}"}).json()

@app.get("/now-playing")
def now_playing():
    t = _token()
    if not t: return {"is_playing": False}
    r = requests.get("https://api.spotify.com/v1/me/player",
                     headers={"Authorization": f"Bearer {t}"})
    if r.status_code == 204 or not r.text: return {"is_playing": False}
    d = r.json()
    item = d.get("item") or {}
    images = item.get("album", {}).get("images", [])
    return {
        "is_playing":   d.get("is_playing", False),
        "track_name":   item.get("name", ""),
        "artist":       ", ".join(a["name"] for a in item.get("artists", [])),
        "uri":          item.get("uri", ""),
        "progress_ms":  d.get("progress_ms", 0),
        "duration_ms":  item.get("duration_ms", 1),
        "image":        images[1]["url"] if len(images) > 1 else (images[0]["url"] if images else ""),
    }

@app.post("/toggle-play-pause")
def toggle_play_pause():
    global is_paused
    t = _token()
    if not t: return {"error": "Not authenticated"}
    r = requests.get("https://api.spotify.com/v1/me/player", headers={"Authorization": f"Bearer {t}"})
    if r.status_code == 204 or not r.text: return {"error": "Nothing playing"}
    state = r.json()
    if state.get("is_playing"):
        requests.put("https://api.spotify.com/v1/me/player/pause", headers={"Authorization": f"Bearer {t}"})
        is_paused = True; return {"status": "paused"}
    else:
        requests.put("https://api.spotify.com/v1/me/player/play",  headers={"Authorization": f"Bearer {t}"})
        is_paused = False; return {"status": "playing"}

@app.post("/play-track")
def play_track(data: dict = Body(...)):
    t = _token()
    if not t: return {"error": "Not authenticated"}
    devices = requests.get("https://api.spotify.com/v1/me/player/devices",
                           headers={"Authorization": f"Bearer {t}"}).json()
    if not devices.get("devices"): return {"error": "No active devices"}
    device_id = devices["devices"][0]["id"]
    r = requests.put(f"https://api.spotify.com/v1/me/player/play?device_id={device_id}",
        headers={"Authorization": f"Bearer {t}", "Content-Type": "application/json"},
        json={"uris": [data["uri"]]})
    return {"status": "playing", "code": r.status_code}

@app.post("/pause-playback")
def pause_playback():
    t = _token()
    if not t: return {"error": "Not authenticated"}
    requests.put("https://api.spotify.com/v1/me/player/pause",
                 headers={"Authorization": f"Bearer {t}"})
    return {"status": "paused"}

@app.post("/prev-track")
def prev_track():
    t = _token()
    if not t: return {"error": "Not authenticated"}
    requests.post("https://api.spotify.com/v1/me/player/previous",
                  headers={"Authorization": f"Bearer {t}"})
    return {"status": "previous"}

@app.post("/next-track")
def next_track():
    t = _token()
    if not t: return {"error": "Not authenticated"}
    requests.post("https://api.spotify.com/v1/me/player/next",
                  headers={"Authorization": f"Bearer {t}"})
    return {"status": "next"}


@app.post("/queue-track")
def queue_track(data: dict = Body(...)):
    t = _token()
    if not t: return {"error": "Not authenticated"}
    r = requests.post("https://api.spotify.com/v1/me/player/queue",
        params={"uri": data["uri"]},
        headers={"Authorization": f"Bearer {t}"})
    return {"status": "queued", "code": r.status_code}

# ── Mood Mix ──────────────────────────────────────────────────────────────────
@app.get("/suggest-emoji")
def suggest_emoji(name: str):
    if not GROQ_API_KEY:
        return {"emoji": "✨"}
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama3-8b-8192",
                "messages": [
                    {"role": "system", "content": "You are an emoji picker. Reply with ONLY a single emoji character that best represents the given routine name. No text, no punctuation, just one emoji."},
                    {"role": "user", "content": f"Routine name: {name}"}
                ],
                "max_tokens": 5,
                "temperature": 0.8,
            }, timeout=5)
        emoji = r.json()["choices"][0]["message"]["content"].strip()
        # Sanitise — take first character only in case model returns extra text
        return {"emoji": emoji[0] if emoji else "✨"}
    except:
        return {"emoji": "✨"}


@app.get("/mood-mix")
def mood_mix(mood: str, limit: int = 12):
    try:
        mood = mood.lower().strip()
        if mood not in MOOD_CONFIG:
            return {"error": f"Unknown mood. Choose: {', '.join(MOOD_CONFIG)}"}

        t = _token()
        if not t: return {"error": "Not authenticated. Connect Spotify first."}

        cfg = MOOD_CONFIG[mood]
        v_min, v_max = cfg["valence"]
        e_min, e_max = cfg["energy"]

        # Step 1 — search for candidate tracks
        track_ids, track_map = [], {}
        headers = {"Authorization": f"Bearer {t}"}

        for query in cfg["queries"]:
            r = requests.get("https://api.spotify.com/v1/search",
                params={"q": query, "type": "track", "limit": 40, "market": "IN"},
                headers=headers, timeout=10)
            if r.status_code != 200:
                print(f"Search error {r.status_code}: {r.text}")
                continue
            items = r.json().get("tracks", {}).get("items", [])
            for item in items:
                if not item: continue
                tid = item.get("id")
                if not tid or tid in track_map: continue
                album = item.get("album", {})
                images = album.get("images", [])
                track_ids.append(tid)
                track_map[tid] = {
                    "id": tid,
                    "name": item.get("name", ""),
                    "artist": ", ".join(a["name"] for a in item.get("artists", [])),
                    "uri": item.get("uri", ""),
                    "album": album.get("name", ""),
                    "image": images[1]["url"] if len(images) > 1 else (images[0]["url"] if images else ""),
                }

        if not track_ids:
            return {"error": "No tracks found from Spotify search. Check your auth."}

        # Step 2 — try audio features filter (403 on new Spotify apps — soft fallback)
        matched = []
        try:
            for i in range(0, min(len(track_ids), 150), 100):
                batch = track_ids[i:i+100]
                af_r = requests.get("https://api.spotify.com/v1/audio-features",
                    params={"ids": ",".join(batch)},
                    headers=headers, timeout=10)
                if af_r.status_code == 403:
                    print("Audio features blocked (403) — using search-based fallback")
                    break
                if af_r.status_code != 200:
                    print(f"Audio features error {af_r.status_code}")
                    continue
                for af in af_r.json().get("audio_features", []):
                    if not af: continue
                    v = af.get("valence")
                    e = af.get("energy")
                    if v is None or e is None: continue
                    if v_min <= v <= v_max and e_min <= e <= e_max:
                        tid = af.get("id")
                        if tid and tid in track_map:
                            track_map[tid]["valence"] = round(v, 2)
                            track_map[tid]["energy"]  = round(e, 2)
                            matched.append(track_map[tid])
        except Exception as e:
            print(f"Audio features exception: {e}")

        # Fallback: if audio features blocked/empty, use all search results
        # Assign estimated valence based on mood config midpoint so UI shows something
        if not matched:
            mid_v = round((v_min + v_max) / 2, 2)
            mid_e = round((e_min + e_max) / 2, 2)
            matched = [{**v, "valence": mid_v, "energy": mid_e}
                       for v in list(track_map.values())]

        # Step 3 — sort + shuffle
        mid = (v_min + v_max) / 2
        matched.sort(key=lambda x: abs(x.get("valence", 0.5) - mid))
        top = matched[:max(limit, 12)]
        random.shuffle(top)

        # Step 4 — Groq DJ intro
        dj_intro = _groq_dj_intro(mood, top)

        return {
            "mood": mood,
            "color": cfg["color"],
            "dj_intro": dj_intro,
            "tracks": top,
            "valence_range": [v_min, v_max],
        }

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Server error: {str(e)}"}

@app.post("/mood-mix-freetext")
def mood_mix_freetext(data: dict = Body(...)):
    """Takes a freeform text description of a mood, uses Groq to interpret it
    into audio parameters, then fetches matching tracks from Spotify."""
    try:
        text = (data.get("text") or "").strip()
        if not text:
            return {"error": "No text provided"}

        t = _token()
        if not t: return {"error": "Not authenticated. Connect Spotify first."}

        # ── Step 1: Groq interprets the mood ─────────────────────────────────
        groq_params = _groq_interpret_mood(text)
        v_min = groq_params["valence_min"]
        v_max = groq_params["valence_max"]
        e_min = groq_params["energy_min"]
        e_max = groq_params["energy_max"]
        queries = groq_params["queries"]
        color   = groq_params["color"]

        print(f"Groq interpreted '{text}' → valence {v_min}-{v_max}, energy {e_min}-{e_max}, queries: {queries}")

        headers = {"Authorization": f"Bearer {t}"}
        track_ids, track_map = [], {}

        # ── Step 2: Search Spotify ────────────────────────────────────────────
        for query in queries:
            r = requests.get("https://api.spotify.com/v1/search",
                params={"q": query, "type": "track", "limit": 40, "market": "IN"},
                headers=headers, timeout=10)
            if r.status_code != 200: continue
            for item in r.json().get("tracks", {}).get("items", []):
                if not item: continue
                tid = item.get("id")
                if not tid or tid in track_map: continue
                album = item.get("album", {})
                images = album.get("images", [])
                track_ids.append(tid)
                track_map[tid] = {
                    "id": tid,
                    "name": item.get("name", ""),
                    "artist": ", ".join(a["name"] for a in item.get("artists", [])),
                    "uri": item.get("uri", ""),
                    "album": album.get("name", ""),
                    "image": images[1]["url"] if len(images) > 1 else (images[0]["url"] if images else ""),
                }

        if not track_ids:
            return {"error": "No tracks found. Try a different description."}

        # ── Step 3: Audio features filter (with graceful 403 fallback) ───────
        matched = []
        try:
            for i in range(0, min(len(track_ids), 100), 100):
                batch = track_ids[i:i+100]
                af_r = requests.get("https://api.spotify.com/v1/audio-features",
                    params={"ids": ",".join(batch)},
                    headers=headers, timeout=10)
                if af_r.status_code == 403: break
                if af_r.status_code != 200: continue
                for af in af_r.json().get("audio_features", []):
                    if not af: continue
                    v = af.get("valence"); e = af.get("energy")
                    if v is None or e is None: continue
                    if v_min <= v <= v_max and e_min <= e <= e_max:
                        tid = af.get("id")
                        if tid and tid in track_map:
                            track_map[tid]["valence"] = round(v, 2)
                            track_map[tid]["energy"]  = round(e, 2)
                            matched.append(track_map[tid])
        except: pass

        if not matched:
            mid_v = round((v_min + v_max) / 2, 2)
            matched = [{**v, "valence": mid_v, "energy": round((e_min+e_max)/2,2)}
                       for v in list(track_map.values())]

        mid = (v_min + v_max) / 2
        matched.sort(key=lambda x: abs(x.get("valence", 0.5) - mid))
        top = matched[:15]
        random.shuffle(top)

        # ── Step 4: Groq DJ intro ─────────────────────────────────────────────
        dj_intro = _groq_dj_intro_custom(text, groq_params["mood_label"], top)

        return {
            "mood": text,
            "mood_label": groq_params["mood_label"],
            "color": color,
            "dj_intro": dj_intro,
            "tracks": top,
            "valence_range": [v_min, v_max],
            "groq_interpretation": groq_params,
        }

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Server error: {str(e)}"}


# ── Test Groq endpoint ────────────────────────────────────────────────────────
@app.get("/test-groq")
def test_groq():
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return {"status": "error", "message": "GROQ_API_KEY not found in environment"}
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "llama3-8b-8192", "messages": [{"role": "user", "content": "Say hello in 5 words."}], "max_tokens": 20},
            timeout=8
        )
        return {"status": "ok", "http_code": r.status_code, "response": r.json()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _groq_dj_intro(mood: str, tracks: list) -> str:
    """Groq-generated 2-sentence DJ intro for preset mood mixes."""
    key = os.getenv("GROQ_API_KEY")
    print(f"[GROQ] _groq_dj_intro — key present: {bool(key)}, mood: {mood}")
    if not key:
        return f"Your {mood} mix is locked in. {len(tracks)} tracks selected."
    try:
        names = ", ".join(f"{t['name']} by {t['artist']}" for t in tracks[:4])
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "llama3-8b-8192",
                "messages": [
                    {"role": "system", "content": "You are a music DJ. Write exactly 2 punchy sentences as a playlist intro. Be specific to the mood. No hashtags, no emojis, no quotes."},
                    {"role": "user",   "content": f"Mood: {mood}. First tracks: {names}. Write the DJ intro."}
                ],
                "max_tokens": 80, "temperature": 0.85,
            }, timeout=8)
        print(f"[GROQ] dj_intro status: {r.status_code}")
        if r.status_code != 200:
            print(f"[GROQ] dj_intro error body: {r.text}")
            return f"Your {mood} mix is ready. {len(tracks)} tracks curated."
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[GROQ] dj_intro exception: {e}")
        traceback.print_exc()
        return f"Your {mood} frequency is locked in. {len(tracks)} tracks."


def _groq_interpret_mood(text: str) -> dict:
    """Uses Groq to convert freeform mood text into Spotify audio parameters."""
    import json as _json
    t_lower = text.lower()
    # Smart keyword fallback used if Groq fails or key missing
    if any(w in t_lower for w in ["died","death","loss","gone","grief","miss","crying","cry","funeral","depression","depressed","hopeless","heartbroken","broke up","breakup","lonely","alone","empty","dog died","cat died"]):
        default = {"valence_min":0.0,"valence_max":0.2,"energy_min":0.1,"energy_max":0.4,
                   "queries":["grief music emotional","sad piano instrumental","heartbreak indie","melancholic ambient"],"color":"#6366f1","mood_label":"grief"}
    elif any(w in t_lower for w in ["angry","frustrated","rage","pissed","annoyed","mad","furious","vent"]):
        default = {"valence_min":0.1,"valence_max":0.35,"energy_min":0.7,"energy_max":1.0,
                   "queries":["aggressive metal intense","rage playlist","dark electronic heavy"],"color":"#e74c3c","mood_label":"rage"}
    elif any(w in t_lower for w in ["hype","pump","gym","workout","energy","excited","fired up","lets go","let's go"]):
        default = {"valence_min":0.7,"valence_max":1.0,"energy_min":0.8,"energy_max":1.0,
                   "queries":["hype workout hits","pump up energy electronic","high energy pop"],"color":"#f97316","mood_label":"hype"}
    elif any(w in t_lower for w in ["focus","work","study","grind","concentrate","productive","coding","flow","deadline"]):
        default = {"valence_min":0.35,"valence_max":0.6,"energy_min":0.5,"energy_max":0.75,
                   "queries":["deep focus instrumental","study lofi beats","concentration flow state"],"color":"#3b82f6","mood_label":"focus"}
    elif any(w in t_lower for w in ["chill","relax","lazy","calm","slow","sunday","morning","coffee","cozy","easy"]):
        default = {"valence_min":0.45,"valence_max":0.7,"energy_min":0.15,"energy_max":0.45,
                   "queries":["chill lofi afternoon","relaxing indie acoustic","cozy bedroom pop"],"color":"#06b6d4","mood_label":"chill"}
    elif any(w in t_lower for w in ["night","midnight","late","insomnia","dark","melancholic","sad","down","low","blue","gloomy"]):
        default = {"valence_min":0.1,"valence_max":0.35,"energy_min":0.2,"energy_max":0.5,
                   "queries":["late night melancholic indie","dark ambient songs","sad introspective music"],"color":"#8b5cf6","mood_label":"late night"}
    else:
        default = {"valence_min":0.3,"valence_max":0.6,"energy_min":0.3,"energy_max":0.65,
                   "queries":["mood music playlist","emotional indie","atmospheric songs"],"color":"#1DB954","mood_label":text[:20]}

    if not GROQ_API_KEY:
        return default
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama3-8b-8192",
                "messages": [
                    {"role": "system", "content": (
                        "You are a music AI. Convert a mood description into Spotify audio parameters. "
                        "Reply with ONLY a raw JSON object, no markdown, no explanation. "
                        "valence = happiness 0.0(sad) to 1.0(happy). energy = intensity 0.0(calm) to 1.0(loud). "
                        "grief/death/loss: valence 0.0-0.2. anger: valence 0.1-0.3 energy 0.7-1.0. "
                        "happiness/celebration: valence 0.7-1.0. focus/study: valence 0.3-0.6. chill/relax: valence 0.4-0.7 energy 0.1-0.4. "
                        'Format: {"mood_label":"2-3 words","valence_min":0.0,"valence_max":0.0,'
                        '"energy_min":0.0,"energy_max":0.0,"queries":["q1","q2","q3"],"color":"#hex"}'
                    )},
                    {"role": "user", "content": f"Mood: {text}"}
                ],
                "max_tokens": 120,
                "temperature": 0.15,
            }, timeout=8)
        raw = r.json()["choices"][0]["message"]["content"].strip()
        start = raw.find("{"); end = raw.rfind("}") + 1
        if start == -1: raise ValueError("No JSON")
        parsed = _json.loads(raw[start:end])
        for k in ["valence_min","valence_max","energy_min","energy_max"]:
            parsed[k] = max(0.0, min(1.0, float(parsed.get(k, default[k]))))
        if not parsed.get("queries") or not isinstance(parsed["queries"], list):
            parsed["queries"] = default["queries"]
        if not parsed.get("color"): parsed["color"] = default["color"]
        if not parsed.get("mood_label"): parsed["mood_label"] = default["mood_label"]
        print(f"Groq: '{text}' → {parsed['mood_label']} v:{parsed['valence_min']:.2f}-{parsed['valence_max']:.2f}")
        return parsed
    except Exception as e:
        print(f"Groq interpret error: {e} — keyword fallback")
        return default


def _groq_dj_intro_custom(text: str, label: str, tracks: list) -> str:
    if not GROQ_API_KEY:
        return f"Mix crafted for: {text}. {len(tracks)} tracks selected."
    try:
        names = ", ".join(f"{t['name']} by {t['artist']}" for t in tracks[:4])
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama3-8b-8192",
                "messages": [
                    {"role": "system", "content": "You are a music DJ. Write exactly 2 punchy sentences as a mix intro. Reference the specific mood description. No hashtags, no emojis, no quotes."},
                    {"role": "user", "content": f"Someone said: '{text}'. I built them a mix labeled '{label}'. Opening tracks: {names}. Write the DJ intro."}
                ],
                "max_tokens": 90, "temperature": 0.85,
            }, timeout=8)
        return r.json()["choices"][0]["message"]["content"].strip()
    except:
        return f"Built for: {text}. {len(tracks)} tracks, dialled in."


    if not GROQ_API_KEY:
        return f"Your {mood} mix is locked in. {len(tracks)} tracks, filtered by audio valence."
    try:
        names = ", ".join(f"{t['name']} by {t['artist']}" for t in tracks[:4])
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama3-8b-8192",
                "messages": [
                    {"role": "system", "content": "You are a music DJ. Write exactly 2 punchy sentences as a mood mix intro. Be specific to the mood. No hashtags, no emojis, no quotes."},
                    {"role": "user",   "content": f"Mood: {mood}. Opening tracks: {names}. Write the DJ intro now."}
                ],
                "max_tokens": 80, "temperature": 0.85,
            }, timeout=8)
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Groq error: {e}")
        return f"Dialing in your {mood} frequency. {len(tracks)} tracks, handpicked by valence."

# ── Routine ───────────────────────────────────────────────────────────────────
@app.post("/start-dynamic-routine")
def start_dynamic_routine(data: dict = Body(...)):
    global routine_thread, stop_flag, is_paused
    t = _token()
    if not t: return {"error": "Not authenticated"}
    routine = data.get("routine")
    if not routine: return {"error": "Invalid routine"}
    stop_flag = False; is_paused = False
    devices = requests.get("https://api.spotify.com/v1/me/player/devices",
                           headers={"Authorization": f"Bearer {t}"}).json()
    if not devices.get("devices"): return {"error": "No active devices"}
    device_id = devices["devices"][0]["id"]

    def run():
        global stop_flag, is_paused
        for block in routine:
            if stop_flag: return
            uri = f"spotify:playlist:{block['playlist_id']}"
            requests.put(f"https://api.spotify.com/v1/me/player/play?device_id={device_id}",
                headers={"Authorization": f"Bearer {t}", "Content-Type": "application/json"},
                json={"context_uri": uri})
            elapsed = 0; secs = int(block["minutes"] * 60)
            while elapsed < secs:
                if stop_flag: return
                if is_paused: time.sleep(1); continue
                time.sleep(1); elapsed += 1
        requests.put("https://api.spotify.com/v1/me/player/pause",
                     headers={"Authorization": f"Bearer {t}"})

    routine_thread = threading.Thread(target=run, daemon=True)
    routine_thread.start()
    return {"status": "dynamic routine started"}

@app.post("/stop-routine")
def stop_routine():
    global stop_flag, is_paused
    t = _token()
    if not t: return {"error": "Not authenticated"}
    stop_flag = True; is_paused = False
    requests.put("https://api.spotify.com/v1/me/player/pause",
                 headers={"Authorization": f"Bearer {t}"})
    return {"status": "routine + playback stopped"}

# ── Token helper ──────────────────────────────────────────────────────────────
def _token():
    if not spotify_tokens["access_token"]: return None
    if time.time() < spotify_tokens["expires_at"] - 60:
        return spotify_tokens["access_token"]
    r = requests.post("https://accounts.spotify.com/api/token",
        data={"grant_type": "refresh_token", "refresh_token": spotify_tokens["refresh_token"],
              "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET})
    d = r.json()
    if "access_token" not in d: return None
    spotify_tokens["access_token"] = d["access_token"]
    spotify_tokens["expires_at"]   = time.time() + d["expires_in"]
    return spotify_tokens["access_token"]
