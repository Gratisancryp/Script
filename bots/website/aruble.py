#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARUBLE AUTO FAUCET CLAIM — Python port of aruble_faucet.js with a
FautePay-style live banner (rich).

Flow:
  1. login            (captcha -> POST /api/auth/login)
  2. bot-check gate   (math + captcha + mouse signals -> POST /bot-check/verify)
  3. claim loop       (captcha -> POST /faucet/claim, 5min cooldown)

Auto-recovery: redo bot-check when the server asks (403 bot-check),
re-login on session expiry, wait out temp-bans and cooldowns.
Network errors (ConnectionError / Timeout / ProtocolError) are retried
automatically — penting untuk Termux/Android yang sering putus socket.

Solver image_slide (puzzle geser) menggunakan template matching
(OpenCV jika tersedia, fallback numpy NCC). Format jawaban yang berhasil
disimpan ke aruble.json agar tidak perlu coba-coba lagi di sesi berikutnya.

Usage:
    python3 arublee.py [email] [password] [N|all] [-q] [--ipv4] [--no-keepalive]

    - Tanpa argumen N  -> claim sampai limit harian (default, max 70)
    - N (angka)        -> claim tepat N kali (dibatasi sisa slot harian)
    - all/today/max    -> claim sampai limit harian
    - -q               -> quiet mode (tanpa dashboard rich)
    - --ipv4           -> paksa IPv4 (workaround bug IPv6 di Android)
    - --no-keepalive   -> kirim "Connection: close" tiap request

Examples:
    python3 arublee.py
    python3 arublee.py 10
    python3 arublee.py all
    python3 arublee.py --ipv4
    python3 arublee.py -q user@mail.com pass123 20
"""

import base64
import io
import json
import os
import random
import re
import secrets
import sys
import time
from collections import Counter
from datetime import datetime

# ---- opsional: paksa IPv4 SEBELUM import requests/urllib3 ----
if "--ipv4" in sys.argv:
    import socket
    import urllib3.util.connection as urllib3_cn

    def _allowed_gai_family():
        return socket.AF_INET  # paksa IPv4 saja

    urllib3_cn.allowed_gai_family = _allowed_gai_family

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3.exceptions import ProtocolError

# ---- image processing (untuk captcha image_slide) ----
try:
    import numpy as np
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False
    np = None
    Image = None

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

# ------------------- CONFIG -------------------
BASE = "https://aruble.net"
COOLDOWN_SECONDS = 300
DEFAULT_HOLD_MS = 1000
MAX_ATTEMPTS = 6
TEMP_BAN_WAIT = 65
DAILY_CLAIM_MAX = 70
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aruble.json")

# Network retry settings
NET_TIMEOUT = (10, 30)          # (connect, read) detik
NET_MAX_ATTEMPTS = 3            # retry manual di _request()
NET_BACKOFF_BASE = 2.0          # 2s, 4s, 8s...
REAUTH_MAX_RETRIES = 3

# Kandidat format jawaban image_slide (urutan fallback)
IMAGE_SLIDE_FORMATS = [
    "json_x_int",
    "plain_int",
    "json_x_float",
    "json_xy",
    "comma_xy",
    "target_pct",
]
# ---------------------------------------------

UA = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36")

DEV_PROFILE = {
    "userAgent": UA,
    "language": "en-GB",
    "screen": "412x915",
    "colorDepth": 24,
    "tzOffset": -330,
    "hwConcurrency": 8,
    "platform": "Linux armv8l",
}

stop_flag = False

# Network exception tuple untuk dipakai berulang
NET_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
    ProtocolError,
)


def now_str():
    return datetime.now().strftime("%H:%M:%S")


def log(msg):
    print(f"[{now_str()}] {msg}", flush=True)


def rnd(a, b):
    return a + (b - a) * random.random()


def cls():
    """Clear the terminal screen (cls on Windows, clear on Unix)."""
    os.system("cls" if os.name == "nt" else "clear")


clear = cls


# ---------------- config (aruble.json) ----------------
def load_config():
    """Load seluruh config dari aruble.json."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(cfg):
    """Simpan config ke aruble.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        log(f"warning: could not save {CONFIG_FILE}: {e}")
        return False


def load_credentials():
    cfg = load_config()
    return cfg.get("email") or "", cfg.get("password") or ""


def save_credentials(email, password):
    cfg = load_config()
    cfg["email"] = email
    cfg["password"] = password
    return save_config(cfg)


def ask_credentials(cli_email, cli_pass):
    """Resolve credentials: CLI > config file > interactive prompt.
    Saves whatever is used into aruble.json."""
    cfg_email, cfg_pass = load_credentials()
    email = cli_email or cfg_email
    password = cli_pass or cfg_pass

    if not email:
        email = input("Email: ").strip()
    if not password:
        try:
            import getpass
            password = getpass.getpass("Password: ")
        except Exception:
            password = input("Password: ").strip()
    if not email:
        raise RuntimeError("email required")
    if not password:
        raise RuntimeError("password required")

    save_credentials(email, password)
    if cli_email or cli_pass:
        log(f"credentials saved to {CONFIG_FILE}")
    return email, password


# ---------------- fingerprint (faucet.js port) ----------------
def get_fingerprint(profile=DEV_PROFILE):
    data = "|".join([
        profile["userAgent"], profile["language"], profile["screen"],
        str(profile["colorDepth"]), str(profile["tzOffset"]),
        str(profile["hwConcurrency"]), profile["platform"],
    ])
    h = 0
    for ch in data:
        h = ((h << 5) - h) + ord(ch)
        h &= 0xFFFFFFFF  # 32-bit wrap
    if h >= 0x80000000:  # JS `|0` is signed 32-bit
        h -= 0x100000000
    return "%08x" % abs(h)


# ---------------- math (bot-check port) ----------------
def eval_math(q):
    m = re.search(r"(-?\d+)\s*([+\-*x×÷/])\s*(-?\d+)", q)
    if not m:
        raise RuntimeError(f"cannot parse math question: {q}")
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    if op == "+":
        return str(a + b)
    if op == "-":
        return str(a - b)
    if op in ("*", "x", "×"):
        return str(a * b)
    if op in ("/", "÷"):
        if b == 0:
            return "0"
        return str(int(a / b))
    raise RuntimeError(f"unknown op {op}")


class SessionExpired(RuntimeError):
    pass


# ============================================================
# IMAGE SLIDE SOLVER HELPERS
# ============================================================

def _decode_data_url(data_url):
    """Decode 'data:image/png;base64,...' -> RGB numpy array."""
    if not _HAS_PIL:
        raise RuntimeError("PIL tidak terinstall — jalankan: pip install pillow numpy")
    if "," in data_url:
        _, b64 = data_url.split(",", 1)
    else:
        b64 = data_url
    raw = base64.b64decode(b64)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    return np.array(img)


def _to_gray(arr):
    """RGB -> grayscale float32."""
    return (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1]
            + 0.114 * arr[:, :, 2]).astype(np.float32)


def _match_cv2(bg_crop, piece):
    """Template matching dengan OpenCV (edge-based). Return (x, score)."""
    bg_gray = cv2.cvtColor(bg_crop, cv2.COLOR_RGB2GRAY)
    pc_gray = cv2.cvtColor(piece, cv2.COLOR_RGB2GRAY)
    bg_edge = cv2.Canny(bg_gray, 100, 200)
    pc_edge = cv2.Canny(pc_gray, 100, 200)
    if (pc_edge.shape[0] > bg_edge.shape[0]
            or pc_edge.shape[1] > bg_edge.shape[1]):
        return 0, -1.0
    res = cv2.matchTemplate(bg_edge, pc_edge, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    return int(max_loc[0]), float(max_val)


def _match_numpy(bg_crop, piece):
    """Fallback NCC (normalized cross-correlation) pakai numpy."""
    bg_g = _to_gray(bg_crop)
    pc_g = _to_gray(piece)
    p_h, p_w = pc_g.shape
    bg_h, bg_w = bg_g.shape

    pc_c = pc_g - pc_g.mean()
    pc_norm = float(np.sqrt((pc_c ** 2).sum()))
    if pc_norm < 1e-6:
        pc_norm = 1.0

    best_x, best_score = 0, -1.0
    for x in range(0, bg_w - p_w + 1):
        win = bg_g[:p_h, x:x + p_w]
        if win.shape != (p_h, p_w):
            continue
        win_c = win - win.mean()
        win_norm = float(np.sqrt((win_c ** 2).sum()))
        if win_norm < 1e-6:
            continue
        score = float((win_c * pc_c).sum() / (win_norm * pc_norm))
        if score > best_score:
            best_score = score
            best_x = x
    return best_x, best_score


# ---------------- http client ----------------
class ArubleClient:
    def __init__(self, verbose=True, dash=None, no_keepalive=False):
        self.verbose = verbose
        self.dash = dash
        self.no_keepalive = no_keepalive
        self.s = requests.Session()

        # Retry adapter untuk network error transient
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "POST"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry,
                              pool_connections=4, pool_maxsize=4)
        self.s.mount("https://", adapter)
        self.s.mount("http://", adapter)

        hdrs = {
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": BASE,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        if no_keepalive:
            hdrs["Connection"] = "close"
        self.s.headers.update(hdrs)
        self.csrf = None

        # Format image_slide yang sudah terbukti (dari config)
        cfg = load_config()
        saved = cfg.get("image_slide_format")
        if saved in IMAGE_SLIDE_FORMATS:
            self._image_slide_format = saved
        else:
            self._image_slide_format = None

    def log(self, msg):
        if not self.verbose:
            return
        if self.dash is not None:
            self.dash.log(msg)
        else:
            log(msg)

    # ---------- internal request with manual retry ----------
    def _request(self, method, url, headers=None, data=None,
                 max_attempts=NET_MAX_ATTEMPTS):
        last_err = None
        for attempt in range(1, max_attempts + 1):
            try:
                if method == "GET":
                    return self.s.get(url, headers=headers, timeout=NET_TIMEOUT)
                else:
                    return self.s.post(url, data=data, headers=headers,
                                       timeout=NET_TIMEOUT)
            except NET_ERRORS as e:
                last_err = e
                if attempt < max_attempts:
                    wait = (NET_BACKOFF_BASE ** attempt) + rnd(0.3, 1.5)
                    self.log(f"  [net] {type(e).__name__}: {str(e)[:60]} "
                             f"— retry {attempt}/{max_attempts - 1} in {wait:.1f}s")
                    time.sleep(wait)
                else:
                    self.log(f"  [net] {type(e).__name__} — giving up after "
                             f"{max_attempts} attempts")
        raise last_err

    def _get(self, path, referer=None):
        h = {}
        if referer:
            h["Referer"] = referer
        return self._request("GET", BASE + path, headers=h)

    def _post_form(self, path, data, referer=None):
        h = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        if referer:
            h["Referer"] = referer
        return self._request("POST", BASE + path, data=data, headers=h)

    @staticmethod
    def _json(resp, what):
        try:
            return resp.json()
        except Exception:
            raise RuntimeError(f"{what}: HTTP {resp.status_code}, "
                               f"not JSON: {resp.text[:200]!r}")

    # ----- session / csrf -----
    def init_session(self):
        r = self._get("/", referer=BASE + "/")
        if r.status_code != 200:
            raise RuntimeError(f"login page: HTTP {r.status_code}")
        m = re.search(r'csrf-token"[\s>]+content="([^"]+)"', r.text)
        if not m:
            raise RuntimeError("no csrf token in login page")
        self.csrf = m.group(1)
        self.log(f"[init] session ok, csrf={self.csrf[:16]}...")

    # ----- captcha solver -----
    def fetch_challenge(self):
        j = self._json(self._get("/captcha/challenge", referer=BASE + "/"), "challenge")
        if j.get("banned"):
            self.log("  challenge: banned")
        elif j.get("gate_required"):
            self.log(f"  challenge: gate ({j.get('hold_ms', DEFAULT_HOLD_MS)}ms hold)")
        else:
            self.log(f"  challenge: {j['type']}")
        return j

    def gate_start(self):
        return self._json(self._post_form("/captcha/gate/start",
                                          {"_csrf_token": self.csrf}), "gate/start")

    def gate_complete(self, gate_key, moves):
        return self._json(self._post_form("/captcha/gate/complete",
                                          {"gate_key": gate_key, "moves": moves,
                                           "_csrf_token": self.csrf}), "gate/complete")

    def verify(self, key, answer):
        return self._json(self._post_form("/captcha/verify",
                                          {"key": key, "answer": answer,
                                           "_csrf_token": self.csrf}), "verify")

    def pass_gate(self):
        gs = self.gate_start()
        if not gs.get("success"):
            raise RuntimeError(f"gate/start failed: {gs}")
        hold_ms = int(gs.get("hold_ms", DEFAULT_HOLD_MS))
        self.log(f"  gate started (hold={hold_ms}ms)")
        time.sleep(hold_ms / 1000.0 + rnd(0.05, 0.35))
        moves = max(3, int(hold_ms / 1000.0 * rnd(12, 40)))
        gc = self.gate_complete(gs["gate_key"], moves)
        if not gc.get("success"):
            raise RuntimeError(f"gate/complete failed: {gc}")
        self.log(f"  gate passed (moves={moves})")

    # ---------- IMAGE SLIDE SOLVER ----------
    def solve_image_slide(self, ch):
        """
        Selesaikan captcha 'image_slide' (puzzle geser).
        Return X center potongan dalam px (int).
        """
        bg = _decode_data_url(ch["bg"])
        piece = _decode_data_url(ch["piece"])
        piece_y = int(ch.get("piece_y", 0))
        p_h, p_w = piece.shape[:2]
        bg_h, bg_w = bg.shape[:2]

        # Crop bg di area Y piece (kurangi search space)
        y0 = max(0, min(piece_y, bg_h - p_h))
        y1 = y0 + p_h
        bg_crop = bg[y0:y1, :, :]

        engine = "cv2" if _HAS_CV2 else "numpy"
        if _HAS_CV2:
            best_x, score = _match_cv2(bg_crop, piece)
        else:
            best_x, score = _match_numpy(bg_crop, piece)

        center_x = int(best_x + p_w // 2)
        self.log(f"  [slide] image_slide: x_center={center_x}px "
                 f"(engine={engine}, score={score:.3f})")
        return center_x

    # ---------- BUILD ANSWER ----------
    def build_answer(self, ch):
        t = ch["type"]
        if t == "slide":
            return str(ch["target_pct"])
        if t == "image_slide":
            # jarang dipakai — biasanya lewat _solve_image_slide_with_fallbacks
            x = self.solve_image_slide(ch)
            return json.dumps({"x": int(x)}, separators=(",", ":"))
        if t == "icon_order":
            idmap = {it["icon"]: it["id"] for it in ch["display"]}
            seq = [idmap[icon] for icon in ch["prompt"]]
            return json.dumps(seq, separators=(",", ":"))
        if t == "least_repeat":
            counts = Counter(it["icon"] for it in ch["grid"])
            least = min(counts.values())
            return str(next(it["id"] for it in ch["grid"] if counts[it["icon"]] == least))
        if t == "drag_dot":
            return json.dumps({"x": round(ch["target_x"]), "y": round(ch["target_y"])},
                              separators=(",", ":"))
        raise RuntimeError(f"unknown challenge type: {t}")

    # ---------- IMAGE SLIDE: FALLBACK FORMATS ----------
    def _build_slide_answer(self, name, x, ch):
        """Bangun string jawaban image_slide berdasarkan nama format."""
        x = int(x)
        y = int(ch.get("piece_y", 0))
        w = max(1, int(ch.get("w", 320)))
        if name == "json_x_int":
            return json.dumps({"x": x}, separators=(",", ":"))
        if name == "plain_int":
            return str(x)
        if name == "json_x_float":
            return json.dumps({"x": float(x)}, separators=(",", ":"))
        if name == "json_xy":
            return json.dumps({"x": x, "y": y}, separators=(",", ":"))
        if name == "comma_xy":
            return f"{x},{y}"
        if name == "target_pct":
            return str(round(x / w * 100, 2))
        raise RuntimeError(f"unknown slide format: {name}")

    def _persist_slide_format(self, name):
        """Simpan format yang berhasil ke aruble.json biar persist."""
        self._image_slide_format = name
        cfg = load_config()
        if cfg.get("image_slide_format") != name:
            cfg["image_slide_format"] = name
            save_config(cfg)
            self.log(f"  [slide] format '{name}' disimpan ke aruble.json")

    def _drop_slide_format(self, name):
        """Hapus format tersimpan (karena gagal)."""
        if self._image_slide_format == name:
            self._image_slide_format = None
            cfg = load_config()
            if cfg.pop("image_slide_format", None) is not None:
                save_config(cfg)
                self.log(f"  [slide] saved format '{name}' gagal -> hapus dari config")

    def _solve_image_slide_with_fallbacks(self, ch):
        """
        Coba format image_slide:
          - Kalau sudah ada format tersimpan -> coba itu dulu.
          - Kalau berhasil -> selesai.
          - Kalau gagal -> coba format lain (fallback).
        Return token jika sukses, None jika challenge expired.
        """
        x = self.solve_image_slide(ch)
        time.sleep(rnd(0.8, 2.2))

        saved = self._image_slide_format
        if saved and saved in IMAGE_SLIDE_FORMATS:
            order = [saved] + [c for c in IMAGE_SLIDE_FORMATS if c != saved]
        else:
            order = list(IMAGE_SLIDE_FORMATS)

        for idx, name in enumerate(order, 1):
            answer = self._build_slide_answer(name, x, ch)
            marker = " (saved)" if name == saved else f" ({idx}/{len(order)})"
            self.log(f"  [slide] try '{name}'{marker}: {answer[:60]}")

            res = self.verify(ch["key"], answer)

            if res.get("success"):
                self.log(f"  [slide] format '{name}' WORKS!")
                self._persist_slide_format(name)
                return res.get("token", "")

            if res.get("banned"):
                raise RuntimeError(f"temp-banned at verify: {res.get('message', '')} "
                                   f"(retry in {res.get('remaining_seconds', 0)}s)")

            if res.get("expired"):
                self.log(f"  [slide] format '{name}' -> key expired, stop")
                # kalau format tersimpan yang gagal, hapus
                if name == saved:
                    self._drop_slide_format(name)
                return None

            # format salah, lanjut coba berikutnya
            self.log(f"  [slide] format '{name}' -> ditolak")

        return None

    # ---------- SOLVE ONE ----------
    def solve_one(self):
        for attempt in range(MAX_ATTEMPTS):
            ch = self.fetch_challenge()
            if ch.get("banned"):
                raise RuntimeError(f"temp-banned: {ch.get('message', '')} "
                                   f"(retry in {ch.get('remaining_seconds', 0)}s)")
            if ch.get("gate_required"):
                self.pass_gate()
                continue

            # Khusus image_slide -> pakai fallback format
            if ch["type"] == "image_slide":
                token = self._solve_image_slide_with_fallbacks(ch)
                if token is not None:
                    return token
                # semua format gagal -> challenge baru
                self.log("  [slide] semua format gagal -> challenge baru")
                time.sleep(1.2)
                continue

            answer = self.build_answer(ch)
            time.sleep(rnd(0.8, 2.2))
            res = self.verify(ch["key"], answer)
            if res.get("success"):
                self.log("  captcha verified")
                return res.get("token", "")
            if res.get("banned"):
                raise RuntimeError(f"temp-banned at verify: {res.get('message', '')} "
                                   f"(retry in {res.get('remaining_seconds', 0)}s)")
            if res.get("expired"):
                self.log("  wrong answer / expired -> fresh challenge")
                time.sleep(1.2)
                continue
            raise RuntimeError(f"verify failed: {res}")
        raise RuntimeError("too many attempts without a verifiable challenge")

    # ----- login -----
    def login(self, email, password):
        token = self.solve_one()
        device_fp = secrets.token_hex(16)
        res = self._post_form("/api/auth/login", {
            "_csrf_token": self.csrf, "email": email, "password": password,
            "captcha_token": token, "remember_me": "1",
            "device_fingerprint": device_fp,
        }, referer=BASE + "/")
        try:
            data = res.json()
        except Exception:
            raise RuntimeError(f"login failed: HTTP {res.status_code}, "
                               f"{res.text[:200]!r}")
        ok = res.status_code == 200 and data.get("success")
        self.log(f"  login {'ok' if ok else 'failed'} (http {res.status_code})")
        if not ok:
            raise RuntimeError(f"login failed: {res.text[:200]}")
        return True

    # ----- bot-check -----
    def bot_check(self, return_to="/faucet"):
        page = self._get(f"/bot-check?return_to={requests.utils.quote(return_to)}",
                         referer=BASE + "/")
        if page.status_code != 200:
            raise RuntimeError(f"bot-check page: HTTP {page.status_code}")
        token = re.search(r'name="token"\s+value="([^"]+)"', page.text)
        question = re.search(r'botcheck-question">([^<]+)<', page.text)
        math_field = re.search(r'name="(q_[a-f0-9]+)"\s+id="mathAnswer"', page.text)
        time_field = re.search(r"fieldTime:\s*'([^']+)'", page.text)
        start_ms = re.search(r"challengeStartMs:\s*(\d+)", page.text)
        if not all([token, question, math_field, time_field, start_ms]):
            raise RuntimeError("bot-check page fields not found")
        token, question, math_field, time_field = (token.group(1), question.group(1),
                                                   math_field.group(1), time_field.group(1))
        start_ms = int(start_ms.group(1))
        answer = eval_math(question)
        self.log(f"  bot-check: math {question} = {answer}")

        captcha_token = self.solve_one()
        self.log("  bot-check captcha ok")

        solve_time = max(3000, int(time.time() * 1000) - start_ms)
        seconds = solve_time / 1000.0
        mouse_moves = int(seconds * rnd(5, 14))
        linear_count = int(mouse_moves * rnd(0.1, 0.35))

        data = {
            "token": token,
            "captcha_token": captcha_token,
            "website": "",
            math_field: answer,
            time_field: solve_time,
            "mouse_moves": mouse_moves,
            "mouse_linear": linear_count,
            "integrity_signals": "",
        }
        res = self._post_form("/bot-check/verify", data, referer=BASE + "/bot-check")
        try:
            j = res.json()
        except Exception:
            raise RuntimeError(f"bot-check failed: HTTP {res.status_code}, "
                               f"{res.text[:200]!r}")
        if not j.get("success"):
            raise RuntimeError(f"bot-check failed: {res.text[:200]}")
        self.log("  bot-check passed")
        return j

    # ----- faucet page info -----
    def read_faucet(self):
        page = self._get("/faucet", referer=BASE + "/")
        if page.status_code != 200:
            return None
        m = re.search(r"var FAUCET_DATA = (\{[\s\S]*?\n\});", page.text)
        data = {}
        if m:
            try:
                data = json.loads(m.group(1))
            except Exception:
                data = {}
        ct = re.search(r'id="statClaims">(\d+)<', page.text)
        if not ct:
            ct = re.search(r'claimsToday["\']?\s*[:=]\s*(\d+)', page.text)
        claims_today = int(ct.group(1)) if ct else None
        return {
            "acc_balance": data.get("accBalance"),
            "coin_reward": data.get("coinReward"),
            "coin_symbol": data.get("coinSymbol"),
            "cooldown": int(data.get("cooldownSeconds", COOLDOWN_SECONDS)),
            "multiplier": data.get("multiplier"),
            "claims_today": claims_today,
        }

    def faucet_status(self):
        r = self._get("/api/earn-badges", referer=BASE + "/faucet")
        j = self._json(r, "earn-badges")
        f = j.get("faucet", {}) if j else {}
        return {
            "available": bool(f.get("available")),
            "enabled": bool(f.get("enabled", True)),
            "cooldown": int(f.get("cooldown", 0)),
        }

    # ----- faucet claim -----
    def claim_once(self, fp):
        time.sleep(rnd(0.6, 1.5))
        page = self._get("/faucet", referer=BASE + "/")
        if page.status_code == 401:
            raise SessionExpired("session expired")
        if page.status_code != 200:
            raise RuntimeError(f"faucet page: HTTP {page.status_code}")

        captcha_token = self.solve_one()
        self.log("  claim captcha ok")
        res = self._post_form("/faucet/claim", {
            "dest": "account", "wc_id": 0, "captcha_token": captcha_token,
            "fp": fp, "_csrf_token": self.csrf,
        }, referer=BASE + "/faucet")
        j = self._json(res, "claim")
        if j.get("success"):
            self.log(f"  claimed +{j['amount']} {j['symbol']} "
                     f"(balance {j['balance_after']})")
        return j


# ---------------- cooldown parsing ----------------
def cooldown_seconds(msg):
    m = re.search(r"(\d+)m\s*(\d+)s", msg or "")
    if m:
        return int(m.group(1)) * 60 + int(m.group(2)) + 3
    m = re.search(r"in (\d+)s", msg or "")
    if m:
        return int(m.group(1)) + 3
    return 320


def re_auth(client, email, password, max_retries=REAUTH_MAX_RETRIES):
    """Re-auth dengan retry untuk network error transient."""
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            client.init_session()
            client.login(email, password)
            client.bot_check("/faucet")
            client.log("re-authenticated (login + bot-check)")
            return
        except NET_ERRORS as e:
            last_err = e
            if attempt < max_retries:
                wait = 5 * attempt + rnd(0.5, 2.0)
                client.log(f"re-auth net error ({type(e).__name__}) — "
                           f"retry {attempt}/{max_retries} in {wait:.1f}s")
                time.sleep(wait)
            else:
                client.log(f"re-auth gave up after {max_retries} attempts")
                raise
    if last_err:
        raise last_err


# ---------------- dashboard (rich live card) ----------------

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text

    _RICH = True
except Exception:
    _RICH = False


def _fmt_dur(secs):
    secs = int(max(0, secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s"


def _claim_history_panel(history):
    rows = history[-8:] if history else []
    t = Table.grid(padding=(0, 2), expand=True)
    t.add_column(justify="left", ratio=2)
    t.add_column(justify="left", ratio=1)
    t.add_column(justify="right", ratio=1)
    if not rows:
        t.add_row("[dim]no claims this session yet[/]")
    for r in rows:
        t.add_row(r["time"], f"[dim]balance[/] {r['balance']}",
                  f"[bold green]+{r['amount']} {r['symbol']}[/]")
    return t


def _progress_bar(fraction, width=30):
    filled = int(round(max(0.0, min(1.0, fraction)) * width))
    return "[" + ("█" * filled) + ("░" * (width - filled)) + "]"


class Dashboard:
    def __init__(self):
        self.logs = []
        self.is_tty = sys.stdout.isatty()
        self.live = None
        self.console = Console() if _RICH else None

    def clear(self):
        pass

    def log(self, msg):
        line = f"[{now_str()}] {msg}"
        if self.is_tty and _RICH:
            self.logs.append(line)
            if len(self.logs) > 8:
                self.logs.pop(0)
        else:
            print(line, flush=True)

    def _panel(self, stats):
        now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        bal = f"{stats['balance']:.2f}" if stats.get("balance") is not None else "?"
        frac = stats["done"] / stats["max"] if stats.get("max") else 0
        pct = frac * 100
        bar = _progress_bar(frac)

        table = Table.grid(padding=(0, 2), expand=True)
        table.add_column(justify="left", ratio=1)
        table.add_column(justify="left", ratio=3)
        table.add_row("[bold cyan]Worker[/]", "ARUBLE AUTO FAUCET (Python)")
        table.add_row("[bold]Account[/]", stats.get("account", "?"))
        table.add_row("[bold]Target[/]",
                      f"{stats.get('done', 0)}/{stats.get('max', 0)} claims"
                      f"{' — ALL remaining today' if stats.get('all') else ''}")
        table.add_row("[bold]Claims today[/]",
                      f"{stats.get('today', 0)}/{stats.get('today_max', 0)} | "
                      f"[bold yellow]{stats.get('remaining', 0)}[/] remaining")
        table.add_row("[bold]Device time[/]", now_local)
        table.add_row("[bold]Balance[/]", f"[bold green]{bal}[/] COINS")
        table.add_row("[bold]Cooldown[/]",
                      f"{_fmt_dur(stats.get('cooldown', 0))}"
                      + (f" | faucet [red]off[/]" if stats.get("enabled") is False else ""))
        table.add_row("[bold]Progress[/]", f"{bar} {stats['done']}/{stats['max']} ({pct:.1f}%)")
        table.add_row("[bold]Stats[/]",
                      f"success [green]{stats['success']}[/] | "
                      f"blocked [yellow]{stats['blocked']}[/] | "
                      f"bans [red]{stats['bans']}[/] | "
                      f"net-errs [magenta]{stats.get('neterrs', 0)}[/] | "
                      f"earned [green]+{stats.get('earned', 0):.2f}[/]")
        table.add_row("[bold]Session[/]",
                      f"bot-checks {stats['botchecks']} | re-logins {stats['relogins']}")

        hist = Table.grid(expand=True)
        hist.add_column(justify="center")
        hist.add_row("[bold]Claim History[/]")
        hist.add_row(_claim_history_panel(stats.get("history", [])))

        body = [table, Rule(style="dim"), hist]
        for line in self.logs[-4:]:
            body.append(Text(line, style="dim"))
        return Panel(Group(*body), border_style="cyan",
                     title=f"[bold]Device {now_local}[/]", title_align="left",
                     subtitle="[dim]COINS[/]")

    def render(self, stats):
        if not (self.is_tty and _RICH):
            return
        panel = self._panel(stats)
        if self.live is None:
            self.live = Live(panel, console=self.console,
                             refresh_per_second=4, transient=True)
            self.live.start()
        else:
            self.live.update(panel)

    def stop(self):
        if self.live is not None:
            try:
                self.live.stop()
            except Exception:
                pass
            self.live = None


def countdown(dash, stats, seconds):
    seconds = int(max(0, seconds))
    for i in range(seconds):
        if stop_flag:
            break
        stats["cooldown"] = seconds - i
        dash.render(stats)
        time.sleep(1)
    stats["cooldown"] = 0
    dash.render(stats)


# ---------------- main ----------------

def _refresh_today(stats, client, msg=None):
    try:
        info = client.read_faucet()
    except NET_ERRORS as e:
        stats["neterrs"] = stats.get("neterrs", 0) + 1
        dash_ref = stats.get("_dash")
        if dash_ref:
            dash_ref.log(f"_refresh_today net error: {type(e).__name__}")
        return
    if info:
        try:
            stats["balance"] = float(info["acc_balance"])
        except (TypeError, ValueError):
            pass
        if info.get("claims_today") is not None:
            stats["today"] = info["claims_today"]
    stats["remaining"] = max(stats["today_max"] - stats["today"], 0)
    if msg:
        dash_ref = stats.get("_dash")
        if dash_ref:
            dash_ref.log(msg)


def parse_args(argv):
    """
    Returns (email, password, max_claims, all_mode, quiet, no_keepalive)
    """
    keywords = {"all", "today", "max"}
    pos = [a for a in argv if not a.startswith("-")]
    quiet = "-q" in argv
    no_keepalive = "--no-keepalive" in argv

    non_num = [a for a in pos
               if not re.fullmatch(r"[0-9]+", a) and a.lower() not in keywords]
    num_token = next((a for a in pos if re.fullmatch(r"[0-9]+", a)), None)
    has_keyword = any(a.lower() in keywords for a in pos)

    if has_keyword:
        all_mode = True
        numeric = None
    elif num_token is not None:
        all_mode = False
        numeric = int(num_token)
    else:
        all_mode = True
        numeric = None

    cli_email = non_num[0] if non_num and "@" in non_num[0] else ""
    cli_pass = non_num[1] if len(non_num) > 1 and "@" not in non_num[1] else ""

    max_claims = None if all_mode else numeric
    return cli_email, cli_pass, max_claims, all_mode, quiet, no_keepalive


def main():
    global stop_flag

    (cli_email, cli_pass, max_claims, all_mode,
     quiet, no_keepalive) = parse_args(sys.argv[1:])

    email, password = ask_credentials(cli_email, cli_pass)

    dash = Dashboard()
    client = ArubleClient(verbose=not quiet, dash=dash, no_keepalive=no_keepalive)
    stats = {"balance": None, "done": 0, "max": 0, "cooldown": 0,
             "success": 0, "blocked": 0, "bans": 0, "botchecks": 1, "relogins": 0,
             "account": email, "history": [],
             "today": 0, "today_max": DAILY_CLAIM_MAX, "remaining": 0,
             "all": all_mode, "enabled": True, "earned": 0.0,
             "neterrs": 0, "_dash": dash}

    target = 0
    try:
        re_auth(client, email, password)
        fp = get_fingerprint()

        info = client.read_faucet()
        if info:
            try:
                stats["balance"] = float(info["acc_balance"])
            except (TypeError, ValueError):
                pass
            if info.get("claims_today") is not None:
                stats["today"] = info["claims_today"]
            dash.log(f"balance {info['acc_balance']} {info['coin_symbol']} | "
                     f"reward {info['coin_reward']} x{info['multiplier']} | "
                     f"claims today {info['claims_today']}/{DAILY_CLAIM_MAX}")

        st = client.faucet_status()
        stats["enabled"] = st["enabled"]
        if not st["enabled"]:
            dash.log("faucet is disabled on the site — exiting")
        stats["remaining"] = max(stats["today_max"] - stats["today"], 0)

        if max_claims is None:
            target = stats["remaining"]
        else:
            target = min(max_claims, stats["remaining"]) if stats["remaining"] > 0 else 0
        stats["max"] = target

        if target <= 0:
            dash.log(f"nothing to claim — today {stats['today']}/{stats['today_max']} "
                     f"({stats['remaining']} left)")
            if sys.stdout.isatty():
                clear()
            dash.render(stats)
            if dash.live is not None:
                time.sleep(1.5)
            return

        # info format image_slide yang tersimpan
        if client._image_slide_format:
            dash.log(f"image_slide format tersimpan: {client._image_slide_format}")

        dash.log(f"fp={fp} | target {target} claim(s) "
                 f"({'all remaining today' if all_mode else 'fixed count'})")
        if sys.stdout.isatty():
            clear()
        dash.render(stats)

        while stats["done"] < target:
            if stop_flag:
                break
            if all_mode:
                try:
                    st = client.faucet_status()
                    stats["enabled"] = st["enabled"]
                    if not st["enabled"]:
                        dash.log("faucet disabled by site — stopping")
                        break
                except NET_ERRORS as e:
                    stats["neterrs"] += 1
                    dash.log(f"faucet_status net error: {type(e).__name__} — wait 20s")
                    countdown(dash, stats, 20)
                    continue

            try:
                res = client.claim_once(fp)
            except SessionExpired:
                stats["relogins"] += 1
                dash.log("session expired -> re-auth")
                try:
                    re_auth(client, email, password)
                except NET_ERRORS as e:
                    stats["neterrs"] += 1
                    dash.log(f"re-auth net error: {type(e).__name__} — waiting 30s")
                    stats["blocked"] += 1
                    countdown(dash, stats, 30)
                    continue
                except Exception as e:
                    dash.log(f"re-auth failed: {e} — waiting 60s")
                    stats["blocked"] += 1
                    countdown(dash, stats, 60)
                    continue
                _refresh_today(stats, client)
                dash.render(stats)
                continue
            except NET_ERRORS as e:
                stats["neterrs"] += 1
                stats["blocked"] += 1
                dash.log(f"claim net error: {type(e).__name__} — waiting 20s")
                countdown(dash, stats, 20)
                continue
            except RuntimeError as e:
                if "temp-banned" in str(e):
                    stats["bans"] += 1
                    dash.log(f"[banned] waiting {TEMP_BAN_WAIT}s")
                    stats["cooldown"] = TEMP_BAN_WAIT
                    dash.render(stats)
                    countdown(dash, stats, TEMP_BAN_WAIT)
                    continue
                raise

            if res.get("success"):
                stats["done"] += 1
                stats["success"] += 1
                try:
                    stats["balance"] = float(res.get("balance_after"))
                    stats["earned"] += float(res.get("amount", 0))
                except (TypeError, ValueError):
                    pass
                stats["today"] = int(res.get("claims_today", stats["today"]))
                stats["today_max"] = int(res.get("claims_max", stats["today_max"]))
                stats["remaining"] = max(stats["today_max"] - stats["today"], 0)
                if not all_mode:
                    stats["max"] = target
                stats["history"].append({
                    "time": now_str(),
                    "amount": res["amount"],
                    "symbol": res["symbol"],
                    "balance": res["balance_after"],
                })
                if len(stats["history"]) > 8:
                    stats["history"].pop(0)
                dash.log(f"CLAIMED +{res['amount']} {res['symbol']} "
                         f"(balance: {res['balance_after']}) "
                         f"[{stats['today']}/{stats['today_max']}] "
                         f"{stats['done']}/{target}")
                dash.render(stats)
                if all_mode and stats["today"] >= stats["today_max"]:
                    dash.log(f"daily cap reached ({stats['today']}/{stats['today_max']}) — done")
                    dash.render(stats)
                    break
                if stats["done"] < target:
                    wait = int(res.get("next_claim_in", COOLDOWN_SECONDS) + rnd(3, 12))
                    countdown(dash, stats, wait)
                continue

            msg = str(res.get("message", ""))
            redirect = str(res.get("redirect", ""))
            if "bot-check" in msg or "security check" in msg or "bot-check" in redirect:
                stats["blocked"] += 1
                stats["botchecks"] += 1
                dash.log("bot-check re-required -> redoing")
                try:
                    client.bot_check("/faucet")
                except NET_ERRORS as e:
                    stats["neterrs"] += 1
                    dash.log(f"bot_check net error: {type(e).__name__} — wait 20s")
                    countdown(dash, stats, 20)
                    continue
                time.sleep(rnd(1.5, 2.5))
                dash.render(stats)
                continue
            if "login" in msg:
                stats["relogins"] += 1
                dash.log("claim says not logged in -> re-auth")
                try:
                    re_auth(client, email, password)
                except NET_ERRORS as e:
                    stats["neterrs"] += 1
                    dash.log(f"re-auth net error: {type(e).__name__} — wait 30s")
                    countdown(dash, stats, 30)
                    continue
                except Exception as e:
                    dash.log(f"re-auth failed: {e} — wait 60s")
                    countdown(dash, stats, 60)
                    continue
                dash.render(stats)
                continue
            if re.search(r"\d+m\s*\d+s|in \d+s", msg):
                wait = cooldown_seconds(msg)
                stats["blocked"] += 1
                dash.log(f"cooldown: {msg if len(msg) < 80 else msg[:77] + '...'}")
                _refresh_today(stats, client)
                dash.render(stats)
                countdown(dash, stats, wait)
                continue
            dash.log(f"unknown claim response: {json.dumps(res)} — retry in 60s")
            countdown(dash, stats, 60)

    except KeyboardInterrupt:
        stop_flag = True
        dash.log("Interrupted by user")
    except Exception as e:
        stop_flag = True
        dash.log(f"FATAL: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        stats.pop("_dash", None)
        dash.stop()
        log(f"Exited. claimed {stats['done']}/{target or 0} "
            f"today {stats['today']}/{stats['today_max']} "
            f"| earned +{stats['earned']:.2f} COINS | success {stats['success']} | "
            f"blocked {stats['blocked']} | bans {stats['bans']} | "
            f"net-errs {stats.get('neterrs', 0)}")


if __name__ == "__main__":
    main()
