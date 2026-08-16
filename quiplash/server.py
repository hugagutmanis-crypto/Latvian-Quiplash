# -*- coding: utf-8 -*-
"""
Latviešu "Quiplash" tipa spēle — serveris.

Palaišana lokāli:
    pip install -r requirements.txt
    python server.py
    -> atver http://localhost:5000  (lielais ekrāns / host)
    -> telefonā atver to pašu adresi un pievienojies ar istabas kodu

Spēles gaita:
    LOBBY -> (3 raundi: ANSWERING -> VOTING -> ROUND_RESULTS) -> GAME_OVER
"""

import random
import string
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

from prompts import PROMPTS

app = Flask(__name__)
app.config["SECRET_KEY"] = "nomaini-so-uz-jebko-slepenu"
# threading async mode = mazāk atkarību, strādā uz jebkura hosta.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

NUM_ROUNDS = 3
MIN_PLAYERS = 3
MAX_PLAYERS = 8

# Visas aktīvās istabas: kods -> Room objekts
rooms = {}


class Player:
    def __init__(self, sid, name):
        self.sid = sid              # socket ID
        self.name = name
        self.score = 0
        self.connected = True


class Room:
    def __init__(self, code):
        self.code = code
        self.players = {}           # sid -> Player
        self.host_sid = None        # lielā ekrāna socket
        self.phase = "LOBBY"
        self.round = 0
        self.matchups = []          # šī raunda pāri
        self.matchup_index = 0
        self.used_prompts = set()   # lai neatkārtotos vienā spēlē

    # ---- palīgfunkcijas ----
    def player_list(self):
        return [
            {"name": p.name, "score": p.score, "connected": p.connected}
            for p in self.players.values()
        ]

    def active_players(self):
        return [p for p in self.players.values() if p.connected]

    def fresh_prompts(self, n):
        pool = [p for p in PROMPTS if p not in self.used_prompts]
        random.shuffle(pool)
        chosen = pool[:n]
        self.used_prompts.update(chosen)
        return chosen

    def build_matchups(self):
        """
        'Apļa' metode: sakārto spēlētājus aplī, uzvedni j saņem
        spēlētājs j un j+1. Tā katrs saņem tieši 2 uzvednes un
        katru uzvedni atbild tieši 2 spēlētāji.
        """
        players = self.active_players()
        random.shuffle(players)
        n = len(players)
        prompts = self.fresh_prompts(n)
        matchups = []
        for j in range(n):
            a = players[j]
            b = players[(j + 1) % n]
            matchups.append({
                "id": j,
                "prompt": prompts[j],
                "player_a": a.sid,
                "player_b": b.sid,
                "answer_a": None,
                "answer_b": None,
                "votes": {},        # voter_sid -> "a" | "b"
                "revealed": False,
            })
        return matchups

    def prompts_for(self, sid):
        """Atgriež uzvednes, kas jāatbild dotajam spēlētājam."""
        out = []
        for m in self.matchups:
            if m["player_a"] == sid:
                out.append({"id": m["id"], "prompt": m["prompt"], "slot": "a"})
            elif m["player_b"] == sid:
                out.append({"id": m["id"], "prompt": m["prompt"], "slot": "b"})
        return out

    def all_answers_in(self):
        for m in self.matchups:
            if m["answer_a"] is None or m["answer_b"] is None:
                return False
        return True

    def current_matchup(self):
        if 0 <= self.matchup_index < len(self.matchups):
            return self.matchups[self.matchup_index]
        return None


def make_code():
    while True:
        code = "".join(random.choices(string.ascii_uppercase, k=4))
        if code not in rooms:
            return code


# ---------------- HTTP maršruti ----------------

@app.route("/")
def host_screen():
    return render_template("host.html")


@app.route("/play")
def player_screen():
    return render_template("player.html")


# ---------------- Socket notikumi ----------------

@socketio.on("create_room")
def on_create_room():
    """Lielais ekrāns izveido jaunu istabu."""
    code = make_code()
    room = Room(code)
    room.host_sid = request.sid
    rooms[code] = room
    join_room(code)
    emit("room_created", {"code": code})


@socketio.on("join_room_as_player")
def on_join(data):
    code = (data.get("code") or "").strip().upper()
    name = (data.get("name") or "").strip()[:20]
    room = rooms.get(code)

    if not room:
        emit("join_error", {"message": "Tāda istaba neeksistē."})
        return
    if room.phase != "LOBBY":
        emit("join_error", {"message": "Spēle jau ir sākusies."})
        return
    if not name:
        emit("join_error", {"message": "Ieraksti vārdu."})
        return
    if any(p.name.lower() == name.lower() for p in room.players.values()):
        emit("join_error", {"message": "Šāds vārds jau ir aizņemts."})
        return
    if len(room.players) >= MAX_PLAYERS:
        emit("join_error", {"message": "Istaba ir pilna."})
        return

    room.players[request.sid] = Player(request.sid, name)
    join_room(code)
    emit("join_ok", {"code": code, "name": name})
    socketio.emit("lobby_update", {"players": room.player_list()}, room=code)


@socketio.on("start_game")
def on_start(data):
    code = (data.get("code") or "").strip().upper()
    room = rooms.get(code)
    if not room or request.sid != room.host_sid:
        return
    if len(room.active_players()) < MIN_PLAYERS:
        emit("host_error", {"message": f"Vajag vismaz {MIN_PLAYERS} spēlētājus."})
        return
    room.round = 0
    start_round(room)


def start_round(room):
    room.round += 1
    room.phase = "ANSWERING"
    room.matchups = room.build_matchups()
    room.matchup_index = 0

    # Katram spēlētājam nosūti viņa uzvednes
    for p in room.active_players():
        socketio.emit("your_prompts",
                      {"prompts": room.prompts_for(p.sid), "round": room.round},
                      room=p.sid)

    socketio.emit("phase_answering",
                  {"round": room.round, "total_rounds": NUM_ROUNDS,
                   "answered": 0, "total": len(room.matchups) * 2},
                  room=room.code)


@socketio.on("submit_answer")
def on_answer(data):
    code = (data.get("code") or "").strip().upper()
    room = rooms.get(code)
    if not room or room.phase != "ANSWERING":
        return
    mid = data.get("id")
    slot = data.get("slot")
    text = (data.get("text") or "").strip()[:80]
    if not text:
        return

    for m in room.matchups:
        if m["id"] == mid:
            if slot == "a" and m["player_a"] == request.sid:
                m["answer_a"] = text
            elif slot == "b" and m["player_b"] == request.sid:
                m["answer_b"] = text
            break

    # Cik atbilžu jau saņemtas?
    answered = sum(
        (1 if m["answer_a"] else 0) + (1 if m["answer_b"] else 0)
        for m in room.matchups
    )
    emit("answer_received", {"id": mid, "slot": slot})
    socketio.emit("answering_progress",
                  {"answered": answered, "total": len(room.matchups) * 2},
                  room=room.code)

    if room.all_answers_in():
        start_voting(room)


def start_voting(room):
    room.phase = "VOTING"
    room.matchup_index = 0
    send_current_matchup(room)


def send_current_matchup(room):
    m = room.current_matchup()
    if m is None:
        end_round(room)
        return

    a = room.players[m["player_a"]]
    b = room.players[m["player_b"]]

    # Lielais ekrāns rāda abas atbildes
    socketio.emit("show_matchup", {
        "id": m["id"],
        "prompt": m["prompt"],
        "answer_a": m["answer_a"],
        "answer_b": m["answer_b"],
        "index": room.matchup_index + 1,
        "total": len(room.matchups),
    }, room=room.code)

    # Katram spēlētājam pasaki, vai viņš var balsot
    for p in room.active_players():
        can_vote = p.sid != m["player_a"] and p.sid != m["player_b"]
        socketio.emit("vote_prompt", {
            "id": m["id"],
            "prompt": m["prompt"],
            "answer_a": m["answer_a"] if can_vote else None,
            "answer_b": m["answer_b"] if can_vote else None,
            "can_vote": can_vote,
        }, room=p.sid)


@socketio.on("submit_vote")
def on_vote(data):
    code = (data.get("code") or "").strip().upper()
    room = rooms.get(code)
    if not room or room.phase != "VOTING":
        return
    m = room.current_matchup()
    if not m or m["id"] != data.get("id"):
        return
    voter = request.sid
    # Nevar balsot par savu atbildi un tikai vienreiz
    if voter in (m["player_a"], m["player_b"]):
        return
    choice = data.get("choice")
    if choice not in ("a", "b"):
        return
    m["votes"][voter] = choice

    votes_a = sum(1 for c in m["votes"].values() if c == "a")
    votes_b = sum(1 for c in m["votes"].values() if c == "b")
    socketio.emit("vote_progress", {"votes_a": votes_a, "votes_b": votes_b},
                  room=room.code)

    # Vai visi, kas drīkst, ir nobalsojuši?
    eligible = [p for p in room.active_players()
                if p.sid not in (m["player_a"], m["player_b"])]
    if len(m["votes"]) >= len(eligible) and len(eligible) > 0:
        reveal_matchup(room)


def reveal_matchup(room):
    m = room.current_matchup()
    if not m:
        return
    votes_a = sum(1 for c in m["votes"].values() if c == "a")
    votes_b = sum(1 for c in m["votes"].values() if c == "b")
    total = votes_a + votes_b

    # Punkti: līdzīgi oriģinālam — līdz 1000 x raunda numurs.
    max_points = 1000 * room.round
    pts_a = round((votes_a / total) * max_points) if total else 0
    pts_b = round((votes_b / total) * max_points) if total else 0

    # "Quiplash" bonuss, ja iegūti visi balsojumi
    quiplash_a = total > 0 and votes_a == total and votes_b == 0
    quiplash_b = total > 0 and votes_b == total and votes_a == 0
    if quiplash_a:
        pts_a += 250 * room.round
    if quiplash_b:
        pts_b += 250 * room.round

    room.players[m["player_a"]].score += pts_a
    room.players[m["player_b"]].score += pts_b
    m["revealed"] = True

    socketio.emit("matchup_result", {
        "id": m["id"],
        "prompt": m["prompt"],
        "answer_a": m["answer_a"],
        "answer_b": m["answer_b"],
        "name_a": room.players[m["player_a"]].name,
        "name_b": room.players[m["player_b"]].name,
        "votes_a": votes_a,
        "votes_b": votes_b,
        "pts_a": pts_a,
        "pts_b": pts_b,
        "quiplash_a": quiplash_a,
        "quiplash_b": quiplash_b,
    }, room=room.code)


@socketio.on("next_matchup")
def on_next(data):
    """Host nospiež 'Tālāk' pēc rezultāta parādīšanas."""
    code = (data.get("code") or "").strip().upper()
    room = rooms.get(code)
    if not room or request.sid != room.host_sid or room.phase != "VOTING":
        return
    room.matchup_index += 1
    send_current_matchup(room)


def end_round(room):
    room.phase = "ROUND_RESULTS"
    standings = sorted(room.player_list(), key=lambda x: -x["score"])
    is_final = room.round >= NUM_ROUNDS
    socketio.emit("round_over", {
        "round": room.round,
        "standings": standings,
        "is_final": is_final,
    }, room=room.code)
    if is_final:
        room.phase = "GAME_OVER"


@socketio.on("next_round")
def on_next_round(data):
    code = (data.get("code") or "").strip().upper()
    room = rooms.get(code)
    if not room or request.sid != room.host_sid:
        return
    if room.round < NUM_ROUNDS:
        start_round(room)


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    for room in list(rooms.values()):
        if room.host_sid == sid:
            # Host aizgāja — paziņo un aizver istabu
            socketio.emit("host_left", {}, room=room.code)
            rooms.pop(room.code, None)
            return
        if sid in room.players:
            room.players[sid].connected = False
            socketio.emit("lobby_update", {"players": room.player_list()},
                          room=room.code)
            return


if __name__ == "__main__":
    # host="0.0.0.0" -> pieejams arī citiem ierīcēm tavā WiFi tīklā
    socketio.run(app, host="0.0.0.0", port=5000, debug=True,
                 allow_unsafe_werkzeug=True)
