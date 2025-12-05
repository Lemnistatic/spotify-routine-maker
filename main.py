import os
import base64
import requests
import time
from urllib.parse import urlencode
from fastapi import FastAPI, Request
from dotenv import load_dotenv
from fastapi import Body
import threading
import time


routine_thread = None
stop_flag = False
last_playback_state = {
    "context_uri": None,
    "position_ms": None,
    "device_id": None
}

is_paused = False

load_dotenv()

spotify_tokens={
    "access_token": None,
    "refresh_token": None,
    "expires_at": (),
}
app = FastAPI()

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")

SCOPES = " ".join([
    "user-read-private",
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "user-library-read"
])

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/auth/login")
def login():
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "show_dialog": True
    }

    auth_url = "https://accounts.spotify.com/authorize?" + urlencode(params)
    return {"auth_url": auth_url}

@app.get("/callback")
def callback(request: Request):
    code = request.query_params.get("code")

    token_url = "https://accounts.spotify.com/api/token"

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI
    }

    # ✅ Use requests built-in Basic Auth (bypasses all Base64 bugs)
    r = requests.post(
        token_url,
        data=data,
        auth=(CLIENT_ID, CLIENT_SECRET)
    )

    print("TOKEN STATUS:", r.status_code)
    print("TOKEN RESPONSE:", r.text)

    tokens = r.json()

    spotify_tokens["access_token"] = tokens["access_token"]
    spotify_tokens["refresh_token"] = tokens["refresh_token"]
    spotify_tokens["expires_at"] = time.time() + tokens["expires_in"]

    # Use the stored token (not a loose variable)
    me = requests.get(
        "https://api.spotify.com/v1/me",
        headers={"Authorization": f"Bearer {spotify_tokens['access_token']}"}
    ).json()

    return {
        "status": "authenticated",
        "spotify_user": me
    }

# ✅ Get user's active devices
@app.get("/devices")
def get_devices():
    token = refresh_spotify_token_if_needed()
    if not token:
        return {"error": "Not authenticated"}

    r = requests.get(
        "https://api.spotify.com/v1/me/player/devices",
        headers={"Authorization": f"Bearer {token}"}
    )

    return r.json()


# ✅ Start playback
@app.get("/play")
def play_music():
    token = refresh_spotify_token_if_needed()
    if not token:
        return {"error": "Not authenticated"}

    devices = requests.get(
        "https://api.spotify.com/v1/me/player/devices",
        headers={"Authorization": f"Bearer {token}"}
    ).json()

    if not devices.get("devices"):
        return {"error": "No active devices"}

    device_id = devices["devices"][0]["id"]

    r = requests.put(
        f"https://api.spotify.com/v1/me/player/play?device_id={device_id}",
        headers={"Authorization": f"Bearer {token}"}
    )

    return {"status": "playing", "device_id": device_id}



# ✅ Pause playback
@app.get("/pause")
def pause_music():
    token = refresh_spotify_token_if_needed()
    if not token:
        return {"error": "Not authenticated"}

    r = requests.put(
        "https://api.spotify.com/v1/me/player/pause",
        headers={"Authorization": f"Bearer {token}"}
    )

    return {"status": "paused"}

@app.get("/play-playlist/{playlist_id}")
def play_playlist(playlist_id: str):
    token = refresh_spotify_token_if_needed()
    if not token:
        return {"error": "Not authenticated"}

    devices = requests.get(
        "https://api.spotify.com/v1/me/player/devices",
        headers={"Authorization": f"Bearer {token}"}
    ).json()

    if not devices.get("devices"):
        return {"error": "No active devices"}

    device_id = devices["devices"][0]["id"]

    data = {
        "context_uri": f"spotify:playlist:{playlist_id}"
    }

    r = requests.put(
        f"https://api.spotify.com/v1/me/player/play?device_id={device_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json=data
    )

    return {"status": "playing playlist", "playlist_id": playlist_id}

@app.get("/start-block")
def start_block(playlist_id: str, minutes: int):
    token = refresh_spotify_token_if_needed()
    if not token:
        return {"error": "Not authenticated"}

    # 1. Get active device
    devices = requests.get(
        "https://api.spotify.com/v1/me/player/devices",
        headers={"Authorization": f"Bearer {token}"}
    ).json()

    if not devices.get("devices"):
        return {"error": "No active devices"}

    device_id = devices["devices"][0]["id"]

    # 2. Start the playlist
    data = {
        "context_uri": f"spotify:playlist:{playlist_id}"
    }

    requests.put(
        f"https://api.spotify.com/v1/me/player/play?device_id={device_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json=data
    )

    # 3. Run block timer
    duration_seconds = minutes * 60
    time.sleep(duration_seconds)

    # 4. Auto pause after block ends
    requests.put(
        "https://api.spotify.com/v1/me/player/pause",
        headers={"Authorization": f"Bearer {token}"}
    )

    return {
        "status": "block completed",
        "playlist_id": playlist_id,
        "minutes": minutes
    }

@app.get("/start-routine")
def start_routine():
    token = refresh_spotify_token_if_needed()
    if not token:
        return {"error": "Not authenticated"}

    # Example routine (you can customize this later)
    routine = [
        {"playlist_id": "7cK03OlmCoeTJ3Gvxf0RNH?si=da15e7054c9a4026", "minutes": 1},
        {"playlist_id": "0ubQJiaP8qMcUfqyupBfOb?si=7488f38e264f4db0", "minutes": 1},
        {"playlist_id": "7cK03OlmCoeTJ3Gvxf0RNH?si=da15e7054c9a4026", "minutes": 1},
    ]

    devices = requests.get(
        "https://api.spotify.com/v1/me/player/devices",
        headers={"Authorization": f"Bearer {token}"}
    ).json()

    if not devices.get("devices"):
        return {"error": "No active devices"}

    device_id = devices["devices"][0]["id"]

    for block in routine:
        playlist_id = block["playlist_id"]
        minutes = block["minutes"]

        # Start playlist
        requests.put(
            f"https://api.spotify.com/v1/me/player/play?device_id={device_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={"context_uri": f"spotify:playlist:{playlist_id}"}
        )

        # Wait for block duration
        time.sleep(minutes * 60)

    # Pause after routine finishes
    requests.put(
        "https://api.spotify.com/v1/me/player/pause",
        headers={"Authorization": f"Bearer {token}"}
    )

    return {"status": "routine completed"}

from fastapi import Body

@app.post("/start-dynamic-routine")
def start_dynamic_routine(data: dict = Body(...)):
    global routine_thread, stop_flag, last_playback_state

    token = refresh_spotify_token_if_needed()
    if not token:
        return {"error": "Not authenticated"}

    routine = data.get("routine")
    if not routine or not isinstance(routine, list):
        return {"error": "Invalid routine format"}

    stop_flag = False  # reset stop flag

    devices = requests.get(
        "https://api.spotify.com/v1/me/player/devices",
        headers={"Authorization": f"Bearer {token}"}
    ).json()

    if not devices.get("devices"):
        return {"error": "No active devices"}

    device_id = devices["devices"][0]["id"]

    def run_routine():
        global stop_flag, last_playback_state

        for block in routine:
            if stop_flag:
                return

            playlist_id = block["playlist_id"]
            minutes = block["minutes"]

            context_uri = f"spotify:playlist:{playlist_id}"

            # ▶️ PLAY or RESUME
            payload = {
                "context_uri": context_uri
            }

            # Resume if same playlist
            if last_playback_state["context_uri"] == context_uri:
                payload["position_ms"] = last_playback_state["position_ms"]

            requests.put(
                f"https://api.spotify.com/v1/me/player/play?device_id={device_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=payload
            )

            block_seconds = int(minutes * 60)
            elapsed = 0

            start_time = time.time()

            while elapsed < block_seconds:
                    if stop_flag:
                        state = requests.get(
                            "https://api.spotify.com/v1/me/player",
                            headers={"Authorization": f"Bearer {token}"}
                        ).json()

                        if state and state.get("is_playing"):
                            last_playback_state["context_uri"] = state["context"]["uri"]
                            last_playback_state["position_ms"] = state["progress_ms"]
                            last_playback_state["device_id"] = device_id

                        return

                    if is_paused:
                        time.sleep(1)
                        continue

                    time.sleep(1)
                    elapsed += 1

                
        # Auto pause at the end
        requests.put(
            "https://api.spotify.com/v1/me/player/pause",
            headers={"Authorization": f"Bearer {token}"}
        )

        last_playback_state["context_uri"] = None
        last_playback_state["position_ms"] = None
        last_playback_state["device_id"] = None

    routine_thread = threading.Thread(target=run_routine)
    routine_thread.start()

    return {"status": "dynamic routine started"}

@app.post("/stop-routine")
def stop_routine():
    global stop_flag, is_paused

    token = refresh_spotify_token_if_needed()
    if not token:
        return {"error": "Not authenticated"}

    stop_flag = True
    is_paused = False   # ✅ Reset toggle state

    # ✅ Force pause Spotify immediately
    requests.put(
        "https://api.spotify.com/v1/me/player/pause",
        headers={"Authorization": f"Bearer {token}"}
    )

    return {"status": "routine + playback stopped"}


@app.get("/start-preset/default")
def start_default_preset():
    data = {
        "routine": [
            { "playlist_id": "37i9dQZF1EJugUFbzBHKha", "minutes": 1 },  # Deep Work
            { "playlist_id": "7cK03OlmCoeTJ3Gvxf0RNH", "minutes": 1 },   # Break
            { "playlist_id": "0ubQJiaP8qMcUfqyupBfOb", "minutes": 1 }  # Wind Down
        ]
    }

    return start_dynamic_routine(data)

@app.post("/toggle-play-pause")
def toggle_play_pause():
    global is_paused

    token = refresh_spotify_token_if_needed()
    if not token:
        return {"error": "Not authenticated"}

    state = requests.get(
        "https://api.spotify.com/v1/me/player",
        headers={"Authorization": f"Bearer {token}"}
    ).json()

    if state.get("is_playing"):
        # Pause
        requests.put(
            "https://api.spotify.com/v1/me/player/pause",
            headers={"Authorization": f"Bearer {token}"}
        )
        is_paused = True
        return {"status": "paused"}
    else:
        # Resume
        requests.put(
            "https://api.spotify.com/v1/me/player/play",
            headers={"Authorization": f"Bearer {token}"}
        )
        is_paused = False
        return {"status": "playing"}

def refresh_spotify_token_if_needed():
    if time.time() < spotify_tokens["expires_at"] - 60:
        return spotify_tokens["access_token"]

    print("🔁 Refreshing Spotify access token...")

    response = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": spotify_tokens["refresh_token"],
            "client_id": os.getenv("SPOTIFY_CLIENT_ID"),
            "client_secret": os.getenv("SPOTIFY_CLIENT_SECRET")
        }
    )

    new_token_data = response.json()

    spotify_tokens["access_token"] = new_token_data["access_token"]
    spotify_tokens["expires_at"] = time.time() + new_token_data["expires_in"]

    return spotify_tokens["access_token"]
