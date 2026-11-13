import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
import urllib.error

from datetime import datetime
from zoneinfo import ZoneInfo


# CONFIGURACIÓN
API_KEY = os.environ.get("YOUTUBE_API_KEY")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")

CONFIG_FILE = "config.json"
STATE_FILE = "state.json"

SEARCH_VARIANTS = [
    "alienpito",
    "alien pito",
    "alienpit0",
    "alien pit0",
    "alienpita",
    "alienpitu"
]


def normalize(text):
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return "".join(c for c in text if c.isalnum())


def should_check():
    now = datetime.now(ZoneInfo("UTC"))

    argentina = now.astimezone(
        ZoneInfo("America/Argentina/Buenos_Aires")
    )

    canarias = now.astimezone(
        ZoneInfo("Atlantic/Canary")
    )

    havana = now.astimezone(
        ZoneInfo("America/Havana")
    )

    # No consultar entre medianoche y las 08:00
    # de Argentina O Canarias.
    if argentina.hour < 8 or canarias.hour < 8:
        print("Horario nocturno: no se consulta YouTube.")
        return False

    # Lunes: vigilancia intensiva de 11 a 15,
    # hora de La Habana.
    intensivo = (
        havana.weekday() == 0
        and 11 <= havana.hour < 15
    )

    minute = now.minute

    if intensivo:
        return minute % 10 < 5

    return minute % 30 < 5


def api_get(endpoint, params):
    params["key"] = API_KEY

    url = (
        "https://www.googleapis.com/youtube/v3/"
        + endpoint
        + "?"
        + urllib.parse.urlencode(params)
    )

    request = urllib.request.Request(url)

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as error:
        print("Error de YouTube API:", error.code)
        print(error.read().decode("utf-8")[:500])
        raise


def get_channel_ids(channels):
    ids = set()

    for channel in channels:
        handle = channel["handle"]

        data = api_get(
            "channels",
            {
                "part": "id",
                "forHandle": handle
            }
        )

        items = data.get("items", [])

        if items:
            channel_id = items[0]["id"]
            ids.add(channel_id)
            print("Canal encontrado:", channel["name"])
        else:
            print("No se encontró:", handle)

    return ids


def search_live_streams():
    terms = []

    for variant in SEARCH_VARIANTS:
        if " " in variant:
            terms.append(f'"{variant}"')
        else:
            terms.append(variant)

    query = "|".join(terms)

    data = api_get(
        "search",
        {
            "part": "snippet",
            "q": query,
            "type": "video",
            "eventType": "live",
            "maxResults": 50
        }
    )

    return data.get("items", [])


def load_state():
    if not os.path.exists(STATE_FILE):
        return set()

    with open(STATE_FILE, "r", encoding="utf-8") as file:
        data = json.load(file)

    return set(data.get("seen", []))


def save_state(seen):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(
            {"seen": list(seen)[-200:]},
            file,
            indent=2
        )


def send_notification(title, video_url):
    payload = {
        "topic": NTFY_TOPIC,
        "title": title,
        "message": video_url,
        "click": video_url,
        "priority": 4,
        "tags": ["tv"]
    }

    request = urllib.request.Request(
        "https://ntfy.sh/",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        print("Notificación enviada:", response.status)


def main():
    if not API_KEY:
        raise RuntimeError("Falta YOUTUBE_API_KEY")

    if not NTFY_TOPIC:
        raise RuntimeError("Falta NTFY_TOPIC")

    if not should_check():
        return

    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        config = json.load(file)

    channel_ids = get_channel_ids(config["channels"])

    if not channel_ids:
        print("No se encontraron canales.")
        return

    videos = search_live_streams()
    seen = load_state()

    for video in videos:
        snippet = video["snippet"]
        video_id = video["id"]["videoId"]

        if snippet["channelId"] not in channel_ids:
            continue

        title = snippet["title"]
        normalized_title = normalize(title)

        if not any(
            normalize(term) in normalized_title
            for term in SEARCH_VARIANTS
        ):
            continue

        if video_id in seen:
            continue

        video_url = (
            "https://www.youtube.com/watch?v=" + video_id
        )

        send_notification(title, video_url)

        seen.add(video_id)
        save_state(seen)

    print("Revisión terminada.")


if __name__ == "__main__":
    main()