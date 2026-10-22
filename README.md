# Cricket News Channel Bot

Cricbuzz se nayi news uthata hai → Gemini (free) se headline + summary apne shabdon mein likhwata hai → photo ke saath Telegram channel mein post karta hai. Source link nahi jaata. Har 15 min GitHub Actions par chalta hai.

## Files
```
bot.py
requirements.txt
posted.json
.github/workflows/news.yml
```

## Setup

1. **Gemini key:** aistudio.google.com → Get API key → Create API key
2. **Bot:** @BotFather → `/newbot` → token lo. Bot ko naye channel mein **Admin** banao (Post Messages ON)
3. **Repo:** naya GitHub repo banao, ye saari files upload karo (`.github/workflows/news.yml` same folder path mein)
4. **Secrets:** Settings → Secrets and variables → Actions → **Secrets** tab:
   - `BOT_TOKEN`
   - `CHANNEL_ID` → `@channel_username`
   - `GEMINI_API_KEY`
5. **Variables (optional):** same jagah **Variables** tab:
   - `LANGUAGE` → `Hinglish` (default) / `Hindi` / `English`
   - `CHANNEL_TAG` → jaise `🦁 @channel_username` (har post ke end mein)
   - `USE_PHOTO` → `false` karo agar photo nahi chahiye
6. **Start:** Actions tab → workflow enable → **Run workflow**

## Note
- Pehli run mein sirf latest 2 news post hongi, baaki skip (channel flood na ho)
- Ek run mein max 5 news
- Gemini fail ho to sirf headline + photo jaayega
- GitHub ka cron kabhi-kabhi 5-10 min late chalta hai, normal hai
