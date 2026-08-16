# Atjautība — a Latvian Quiplash-style party game

A self-hosted, phone-controlled party game. One big screen (laptop/TV) shows
prompts and results; everyone else joins on their phones with a room code,
types funny answers, and votes. 3–8 players, 3 rounds.

Everything is in **Python** (Flask + Socket.IO) so you can read and tweak it.
The only JavaScript is the browser side, which you rarely need to touch.

```
quiplash/
├── server.py            # game server + all game logic (Python)
├── prompts.py           # the Latvian prompts — edit/add your own here
├── templates/
│   ├── host.html        # the big shared screen
│   └── player.html      # the phone controller
├── requirements.txt
├── Procfile             # tells the host how to run it
└── README.md
```

---

## 1. Try it locally first (same WiFi)

```bash
pip install -r requirements.txt
python server.py
```

- On the computer you ran it on, open **http://localhost:5000** — that's the big screen.
- On phones connected to the **same WiFi**, open `http://<computer-ip>:5000/play`
  (find the IP with `ipconfig` on Windows or `ifconfig`/`ip a` on Mac/Linux —
  something like `http://192.168.1.42:5000/play`).
- Enter the 4-letter room code shown on the big screen, pick a name, play.

This is perfect for testing. To play with friends who **aren't** in your room,
deploy it to the internet (next section).

---

## 2. Put it online for remote friends

Your friends are remote, so you need a host. The honest 2026 picture:

- **Render (free, no credit card)** — easiest. Free web service, 750 hrs/month.
  Note: the app **sleeps after ~15 min idle** and takes ~30–50s to wake on the
  first visit — just open the page a minute before game night. This app uses
  Socket.IO's polling transport, so it works on Render's free tier fine.
- **Railway** — dead simple and supports WebSockets on all plans, but only gives
  a small trial credit (~a few euros) that burns over a week or two. Great for a
  one-off game night, not for leaving it running forever.
- **Fly.io** — now requires a credit card, so skip it for a free setup.

### Deploy to Render (recommended)

1. Put this folder in a **GitHub repo** (create one, push these files).
2. Go to <https://render.com>, sign up, **New → Web Service**, connect the repo.
3. Render auto-detects Python. Set:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn --workers 1 --threads 100 --timeout 120 --bind 0.0.0.0:$PORT server:app`
4. Pick the **Free** instance type, create the service.
5. You'll get a URL like `https://atjautiba.onrender.com`. That's your big screen.
   Friends open `https://atjautiba.onrender.com/play` on their phones. Done.

> ⚠️ **Keep 1 worker.** The game state lives in memory in a single process, so
> `--workers 1` is required. `--threads 100` handles many phones at once.

Railway is even simpler — it reads the `Procfile` automatically. Same idea:
push to GitHub, "New Project → Deploy from repo", open the generated URL.

---

## 3. Make it yours

- **Add prompts:** open `prompts.py` and add lines to the `PROMPTS` list.
  More prompts = more variety across games (needs at least as many as players
  per round; you have 60, plenty for 8 players × 3 rounds).
- **Change round count:** `NUM_ROUNDS` near the top of `server.py`.
- **Change scoring:** see `reveal_matchup()` — points scale by round, with a
  bonus "Atjautība!" for sweeping every vote.
- **Player limits:** `MIN_PLAYERS` / `MAX_PLAYERS` in `server.py`.

## How a round works (for when you tweak the code)

1. **Answering** — each player gets exactly 2 prompts. Every prompt goes to
   exactly 2 players (a "circle" pairing, `build_matchups()`), so each prompt
   becomes a head-to-head.
2. **Voting** — each matchup shows on the big screen; everyone *except* the two
   authors votes on their phone.
3. **Scoring** — points split by vote share, revealed on screen, then the host
   taps *Tālāk* for the next matchup. After all matchups, standings show and the
   host taps *Nākamais raunds*.

Have fun! 🎉
