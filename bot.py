"""
Cricbuzz News -> Telegram Channel Bot
- Cricbuzz se latest news uthata hai
- Gemini (free) se headline + summary apne shabdon mein likhwata hai
- Photo ke saath channel mein post karta hai (koi source link nahi)
- Jo news post ho chuki, dobara nahi jaati (posted.json)
"""

import html
import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

# ---------------- CONFIG ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

LANGUAGE = os.getenv("LANGUAGE", "").strip() or "Hinglish"
CHANNEL_TAG = os.getenv("CHANNEL_TAG", "").strip()          # e.g. "🦁 @mychannel"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip()
USE_PHOTO = (os.getenv("USE_PHOTO", "").strip() or "true").lower() == "true"

MAX_POSTS_PER_RUN = int(os.getenv("MAX_POSTS_PER_RUN", "") or 5)
FIRST_RUN_POSTS = int(os.getenv("FIRST_RUN_POSTS", "") or 2)

NEWS_URL = "https://www.cricbuzz.com/cricket-news"
BASE_URL = "https://www.cricbuzz.com"
STATE_FILE = "posted.json"
KEEP_IDS = 500

# Model try order: agar ek band/unavailable ho to agla try hoga
MODELS = [m for m in [GEMINI_MODEL, "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash"] if m]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

ARTICLE_RE = re.compile(r"/cricket-news/(\d+)/([a-z0-9\-]+)", re.I)
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)


def log(msg):
    print(msg, flush=True)


# ---------------- STATE ----------------
def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_state(ids):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(ids[-KEEP_IDS:], f, indent=1)


# ---------------- SCRAPING ----------------
def get(url):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                return r.text
            log(f"GET {url} -> {r.status_code}")
        except requests.RequestException as e:
            log(f"GET {url} error: {e}")
        time.sleep(3 * (attempt + 1))
    return None


def fetch_news_list():
    """Latest news ki list (newest first): [(id, url), ...]"""
    page = get(NEWS_URL)
    if not page:
        return []
    seen, items = set(), []
    for m in ARTICLE_RE.finditer(page):
        nid, slug = m.group(1), m.group(2)
        if nid in seen:
            continue
        seen.add(nid)
        items.append((nid, f"{BASE_URL}/cricket-news/{nid}/{slug}"))
    return items


def meta(soup, prop):
    tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    return tag.get("content", "").strip() if tag else ""


def fetch_article(url):
    page = get(url)
    if not page:
        return None
    soup = BeautifulSoup(page, "html.parser")

    title = meta(soup, "og:title") or (soup.title.get_text(strip=True) if soup.title else "")
    title = re.sub(r"\s*\|\s*Cricbuzz.*$", "", title, flags=re.I).strip()
    desc = meta(soup, "og:description") or meta(soup, "description")
    image = meta(soup, "og:image")

    paras = []
    for p in soup.find_all("p"):
        t = p.get_text(" ", strip=True)
        if len(t) > 40 and "cricbuzz" not in t.lower():
            paras.append(t)
    body = " ".join(paras)[:4000]

    if not title:
        return None
    return {"title": title, "desc": desc, "body": body or desc, "image": image}


# ---------------- GEMINI ----------------
def rewrite(article):
    """Gemini se headline + summary apne shabdon mein. Fail ho to None."""
    if not GEMINI_API_KEY:
        return None

    prompt = f"""You are the editor of a cricket news Telegram channel.
Read the news below and write it fully in YOUR OWN WORDS (do not copy sentences).

Rules:
- Language: {LANGUAGE}
- "headline": short, catchy, max 12 words, 1 relevant emoji at start
- "summary": 2-3 short sentences, simple and engaging, facts must stay correct
- Do NOT mention Cricbuzz or any website/source name, and do NOT include any links
- Return ONLY JSON: {{"headline": "...", "summary": "..."}}

NEWS TITLE: {article['title']}
NEWS DESCRIPTION: {article['desc']}
NEWS TEXT: {article['body']}
"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "responseMimeType": "application/json"},
    }

    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(3):
            try:
                r = requests.post(
                    url,
                    headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
                    json=payload,
                    timeout=60,
                )
            except requests.RequestException as e:
                log(f"Gemini error ({model}): {e}")
                time.sleep(5)
                continue

            if r.status_code in (429, 500, 503):  # rate limit / overload -> thoda ruko
                wait = 15 * (attempt + 1)
                log(f"Gemini busy ({model}) [{r.status_code}], {wait}s baad retry...")
                time.sleep(wait)
                continue
            if r.status_code in (404, 400) and "not found" in r.text.lower():
                log(f"Model {model} available nahi, next try...")
                break
            if r.status_code != 200:
                log(f"Gemini {model} -> {r.status_code}: {r.text[:300]}")
                time.sleep(5)
                continue

            try:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                text = text.strip().strip("`")
                text = re.sub(r"^json\s*", "", text, flags=re.I)
                data = json.loads(text)
                headline = clean(data.get("headline", ""))
                summary = clean(data.get("summary", ""))
                if headline and summary:
                    return {"headline": headline, "summary": summary}
            except (KeyError, IndexError, ValueError) as e:
                log(f"Gemini parse error ({model}): {e}")
            time.sleep(3)
    return None


def clean(text):
    text = URL_RE.sub("", str(text))
    text = re.sub(r"(?i)\(?\s*(via|source:?)?\s*cricbuzz\s*\)?", "", text)
    return re.sub(r"\s{2,}", " ", text).strip()


# ---------------- TELEGRAM ----------------
def build_caption(headline, summary):
    parts = [f"<b>{html.escape(headline)}</b>", "", html.escape(summary)]
    if CHANNEL_TAG:
        parts += ["", html.escape(CHANNEL_TAG)]
    caption = "\n".join(parts)
    return caption[:1020]  # Telegram photo caption limit 1024


def send(caption, image):
    api = f"https://api.telegram.org/bot{BOT_TOKEN}"
    if USE_PHOTO and image:
        r = requests.post(
            f"{api}/sendPhoto",
            data={"chat_id": CHANNEL_ID, "photo": image, "caption": caption, "parse_mode": "HTML"},
            timeout=30,
        )
        if r.ok:
            return True
        log(f"sendPhoto failed: {r.text[:300]} -> text post try kar rahe hain")

    r = requests.post(
        f"{api}/sendMessage",
        data={
            "chat_id": CHANNEL_ID,
            "text": caption,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
        timeout=30,
    )
    if not r.ok:
        log(f"sendMessage failed: {r.text[:300]}")
    return r.ok


# ---------------- MAIN ----------------
def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        log("BOT_TOKEN / CHANNEL_ID secret missing hai.")
        sys.exit(1)
    if not GEMINI_API_KEY:
        log("GEMINI_API_KEY missing hai - sirf headline post hogi.")

    posted = load_state()
    first_run = len(posted) == 0

    news = fetch_news_list()
    log(f"Cricbuzz se {len(news)} news mili")
    if not news:
        return

    new_items = [(nid, url) for nid, url in news if nid not in posted]

    # Pehli baar: channel flood na ho, sirf latest kuch post karo, baaki mark kar do
    if first_run:
        skip = new_items[FIRST_RUN_POSTS:]
        posted.extend(nid for nid, _ in skip)
        new_items = new_items[:FIRST_RUN_POSTS]
        log(f"First run: {len(skip)} purani news skip, {len(new_items)} post hongi")

    new_items = new_items[:MAX_POSTS_PER_RUN]
    new_items.reverse()  # purani pehle, latest last

    count = 0
    for nid, url in new_items:
        art = fetch_article(url)
        if not art:
            log(f"Article load nahi hua: {nid}")
            continue

        rw = rewrite(art)
        if rw:
            caption = build_caption(rw["headline"], rw["summary"])
        elif GEMINI_API_KEY:
            # Gemini abhi down hai: ye news post nahi karenge, agle run mein dobara try hogi
            log("Gemini fail - baaki news agle run mein try hongi")
            break
        else:
            # Gemini key hi nahi hai: sirf headline
            caption = build_caption("🏏 " + clean(art["title"]), "")
            caption = caption.replace("\n\n\n", "\n\n")

        if send(caption, art["image"]):
            posted.append(nid)
            count += 1
            log(f"Posted: {nid}")
            save_state(posted)
            time.sleep(4)

    save_state(posted)
    log(f"Done. {count} news post hui.")


if __name__ == "__main__":
    main()
