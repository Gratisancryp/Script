import os
import sys
import time
import json
import random
import base64
import io
from datetime import datetime
import requests
import PIL.Image
import numpy as np

# Fix UTF-8 encoding for Windows / Termux CLI
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Terminal ANSI Styling
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    G = Fore.GREEN + Style.BRIGHT
    Y = Fore.YELLOW + Style.BRIGHT
    R = Fore.RED + Style.BRIGHT
    C = Fore.CYAN + Style.BRIGHT
    M = Fore.MAGENTA + Style.BRIGHT
    W = Fore.WHITE + Style.BRIGHT
    D = Fore.BLACK + Style.BRIGHT
    DIM = Style.DIM
    RESET = Style.RESET_ALL
except ImportError:
    G = Y = R = C = M = W = D = DIM = RESET = ""

SITE = "https://limefaucet.com"
CFG = "lime.json"
REF_CODE = "GepJAncOGVlPFZdj"
REF_URL = f"{SITE}/ref/{REF_CODE}"
UA = "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Mobile Safari/537.36"

# Cooldown & Session Defaults
DEFAULT_SESSION_DURATION  = 60 * 60   # 1 hour
BASE_CLAIM_COOLDOWN       = 5 * 60    # 5 minutes base
DEFAULT_EXTRA_CLAIM_MIN   = 0         # 0 seconds
DEFAULT_EXTRA_CLAIM_MAX   = 30        # 30 seconds
DEFAULT_SESSION_BREAK_MIN = 30 * 60   # 30 minutes
DEFAULT_SESSION_BREAK_MAX = 45 * 60   # 45 minutes

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_banner():
    print(f"{C}╔{'═'*48}╗{RESET}")
    print(f"{C}║{W}{'LIMEFAUCET AUTOPILOT BOT 24/7':^48}{C}║{RESET}")
    print(f"{C}║{DIM}{'Pure HTTP Engine · Termux & CLI Ready':^48}{RESET}{C}║{RESET}")
    print(f"{C}╚{'═'*48}╝{RESET}\n")

def print_dashboard(email, coin, balance_usd, session_start, session_duration, ok_count, fail_count, total_earned, last_claim, current_status="Ready"):
    elapsed = int(time.time() - session_start)
    left = max(0, session_duration - elapsed)
    el_m, el_s = divmod(elapsed, 60)
    lf_m, lf_s = divmod(left, 60)
    sess_str = f"{el_m}m {el_s:02d}s (Break in: {lf_m}m {lf_s:02d}s)"

    acc_str = email if len(email) <= 35 else email[:32] + "..."
    bal_str = f"{coin} · ${balance_usd:.8f}"
    stats_str = f"{ok_count} Won / {fail_count} Failed (+${total_earned:.6f})"

    if last_claim:
        roll = last_claim.get("roll", "-")
        crypto = last_claim.get("crypto", 0.0)
        curr = last_claim.get("currency", coin)
        roll_str = f"#{roll} (+{crypto:.8f} {curr})"
    else:
        roll_str = "No claims yet"

    st_str = current_status if len(current_status) <= 35 else current_status[:32] + "..."

    print(f"{C}┌{'─'*48}┐{RESET}")
    print(f"{C}│ {W}{'Account':<9}: {G}{acc_str:<35}{RESET}{C}│{RESET}")
    print(f"{C}│ {W}{'Balance':<9}: {Y}{bal_str:<35}{RESET}{C}│{RESET}")
    print(f"{C}│ {W}{'Session':<9}: {C}{sess_str:<35}{RESET}{C}│{RESET}")
    print(f"{C}│ {W}{'Stats':<9}: {M}{stats_str:<35}{RESET}{C}│{RESET}")
    print(f"{C}│ {W}{'Last Roll':<9}: {G}{roll_str:<35}{RESET}{C}│{RESET}")
    print(f"{C}│ {W}{'Status':<9}: {W}{st_str:<35}{RESET}{C}│{RESET}")
    print(f"{C}└{'─'*48}┘{RESET}\n")

class LimeBot:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Content-Type": "application/json",
            "Origin": SITE,
            "Referer": REF_URL
        })
        self.email = None
        self.coin = "USDT"
        self.balance_usd = 0.0
        self.last = None

        self.session_duration = DEFAULT_SESSION_DURATION
        self.extra_claim_min = DEFAULT_EXTRA_CLAIM_MIN
        self.extra_claim_max = DEFAULT_EXTRA_CLAIM_MAX
        self.session_break_min = DEFAULT_SESSION_BREAK_MIN
        self.session_break_max = DEFAULT_SESSION_BREAK_MAX

        self.session_start = time.time()
        self.ok_count = 0
        self.fail_count = 0
        self.total_earned = 0.0
        self.logs = []
        self.current_status = "Initializing..."

        self.load()

    def render_view(self, live_line=None):
        clear()
        print_banner()
        print_dashboard(
            email=self.email or "-",
            coin=self.coin,
            balance_usd=self.balance_usd,
            session_start=self.session_start,
            session_duration=self.session_duration,
            ok_count=self.ok_count,
            fail_count=self.fail_count,
            total_earned=self.total_earned,
            last_claim=self.last,
            current_status=self.current_status
        )
        print(f"{C}┌── Recent Activity ─────────────────────────────┐{RESET}")
        display_logs = self.logs[-8:] if self.logs else [f" {DIM}No activity recorded yet.{RESET}"]
        for log in display_logs:
            print(log)
        print(f"{C}└────────────────────────────────────────────────┘{RESET}")
        if live_line:
            print(f"\n {live_line}")

    def add_log(self, level, msg):
        icons = {
            'ok':    G + '✓' + RESET,
            'err':   R + '✗' + RESET,
            'info':  C + '•' + RESET,
            'wait':  Y + '⏳' + RESET,
            'warn':  Y + '!' + RESET,
            'money': G + '💰' + RESET,
            'star':  M + '★' + RESET,
        }
        icon = icons.get(level, C + '·' + RESET)
        self.logs.append(f" {icon} {W}{msg}{RESET}")
        self.render_view()

    def live_cooldown(self, seconds, label="Cooldown"):
        end_time = time.time() + seconds
        try:
            while True:
                remain = int(end_time - time.time())
                if remain <= 0:
                    break
                m, s = divmod(remain, 60)
                h, m = divmod(m, 60)
                if h > 0:
                    time_str = f"{h:02d}:{m:02d}:{s:02d}"
                else:
                    time_str = f"{m:02d}:{s:02d}"
                self.current_status = f"{label}: {time_str} ({remain}s)"
                live_msg = f"{Y}⏳{RESET} {label}: {Y}{time_str}{RESET} ({remain}s remaining)..."
                self.render_view(live_line=live_msg)
                time.sleep(1)
            self.current_status = "Ready to claim"
            self.render_view(live_line=f"{G}✓{RESET} {label} finished! Resuming claims...")
            time.sleep(1)
        except KeyboardInterrupt:
            raise

    def load(self):
        cfg_data = {}
        for fn in [CFG, "config.json"]:
            if os.path.exists(fn):
                try:
                    with open(fn, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            cfg_data.update(data)
                except Exception:
                    pass

        self.email = cfg_data.get("email")
        self.coin = cfg_data.get("coin", "USDT")
        if "session_duration_minutes" in cfg_data:
            self.session_duration = int(cfg_data["session_duration_minutes"]) * 60
        if "session_break_min_minutes" in cfg_data:
            self.session_break_min = int(cfg_data["session_break_min_minutes"]) * 60
        if "session_break_max_minutes" in cfg_data:
            self.session_break_max = int(cfg_data["session_break_max_minutes"]) * 60
        if "extra_claim_cooldown_min_seconds" in cfg_data:
            self.extra_claim_min = int(cfg_data["extra_claim_cooldown_min_seconds"])
        if "extra_claim_cooldown_max_seconds" in cfg_data:
            self.extra_claim_max = int(cfg_data["extra_claim_cooldown_max_seconds"])

    def save(self):
        data = {
            "email": self.email,
            "coin": self.coin,
            "session_duration_minutes": self.session_duration // 60,
            "session_break_min_minutes": self.session_break_min // 60,
            "session_break_max_minutes": self.session_break_max // 60,
            "extra_claim_cooldown_min_seconds": self.extra_claim_min,
            "extra_claim_cooldown_max_seconds": self.extra_claim_max
        }
        for fn in [CFG, "config.json"]:
            try:
                with open(fn, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass

    def login(self, force=False):
        """Login / re-login. Clears old cookies if force=True or token missing."""
        try:
            if force or "lf_token" not in self.s.cookies:
                self.s.cookies.clear()
            self.s.get(REF_URL, timeout=15)
        except Exception:
            pass

        try:
            payload = {"email": self.email, "referral_code": REF_CODE}
            r = self.s.post(f"{SITE}/api/auth/login", json=payload, timeout=30)
            if r.status_code == 200 and "lf_token" in self.s.cookies:
                data = r.json()
                u = data.get("user", {})
                self.balance_usd = float(u.get("balance_usd", 0.0))
                self.coin = u.get("preferred_currency", self.coin)
                self.save()
                self.add_log('ok', f"Logged in as {self.email}" + (" (re-auth)" if force else ""))
                return True
            self.add_log('err', f"Login failed: {r.text[:80]}")
        except Exception as e:
            self.add_log('err', f"Login error: {e}")
        return False

    def solve_captcha(self, retry_count=0):
        if retry_count > 3:
            self.add_log('err', "Max challenge reload attempts reached.")
            return None

        try:
            r = self.s.post(f"{SITE}/api/faucet/ac-captcha/challenge", timeout=20)
        except Exception as e:
            self.add_log('err', f"Challenge request error: {e}")
            return None

        try:
            ch = r.json()
        except Exception:
            ch = {}

        if r.status_code == 429 or ch.get("blocked") or ch.get("error") == "locked":
            locked_until = ch.get("locked_until")
            wait_s = 600
            if locked_until:
                now_ms = int(time.time() * 1000)
                wait_s = max(5, int((locked_until - now_ms) / 1000) + 2)
            self.add_log('warn', f"Captcha rate-limited (HTTP 429). Pausing for {wait_s}s...")
            self.live_cooldown(wait_s, label="Captcha Rate-Limit")
            return None

        if r.status_code != 200 or "session_id" not in ch or "challenge" not in ch:
            self.add_log('warn', f"Failed to acquire challenge ({r.status_code}).")
            if r.status_code in (401, 403) or (isinstance(ch, dict) and any(k in str(ch).lower() for k in ("token", "auth", "unauthorized", "login"))):
                self.add_log('warn', "Auth error on challenge. Forcing re-login...")
                self.login(force=True)
            return None

        sid = ch["session_id"]
        raw_img = ch["challenge"].get("image", "")
        if not raw_img.startswith("data:image/"):
            self.add_log('err', "Invalid captcha image payload format.")
            return None

        try:
            self.add_log('info', "Loading animated captcha & analyzing motion vectors...")
            img_b64 = raw_img.split(",", 1)[1]
            img_bytes = base64.b64decode(img_b64)
            im = PIL.Image.open(io.BytesIO(img_bytes))

            frames = []
            n_frames = getattr(im, "n_frames", 1)
            for i in range(n_frames):
                im.seek(i)
                frames.append(np.array(im.convert("RGBA")))

            # 1. Extract reference motion trajectory (y: 0..80)
            ref_pts = []
            for f in frames:
                crop = f[0:80, :, 3]
                ys, xs = np.where(crop > 50)
                if len(xs) > 0:
                    ref_pts.append((np.mean(xs), np.mean(ys)))
                else:
                    ref_pts.append((0, 0))
            ref_pts = np.array(ref_pts)
            ref_motion = ref_pts - np.mean(ref_pts, axis=0)

            # 2. Extract 9 grid candidate motion trajectories
            scores = []
            for idx in range(9):
                row = idx // 3
                col = idx % 3
                y1 = 80 + int(row * (193.0 / 3))
                y2 = 80 + int((row + 1) * (193.0 / 3))
                x1 = int(col * (387.0 / 3))
                x2 = int((col + 1) * (387.0 / 3))

                cand_pts = []
                for f in frames:
                    crop = f[y1:y2, x1:x2, 3]
                    ys, xs = np.where(crop > 50)
                    if len(xs) > 0:
                        cand_pts.append((np.mean(xs), np.mean(ys)))
                    else:
                        cand_pts.append((0, 0))
                cand_pts = np.array(cand_pts)
                cand_motion = cand_pts - np.mean(cand_pts, axis=0)

                diff = np.mean(np.linalg.norm(ref_motion - cand_motion, axis=1))
                scores.append(diff)

            best_index = int(np.argmin(scores))
            min_diff = scores[best_index]

            if min_diff > 0.4:
                self.add_log('warn', f"Motion diff ({min_diff:.4f}) uncertain. Reloading fresh challenge...")
                time.sleep(1)
                return self.solve_captcha(retry_count + 1)

            self.add_log('info', f"Target icon detected: Option #{best_index + 1:02d} (diff: {min_diff:.4f})")

            # Human-like verification delay (1.5 - 2.5s)
            time.sleep(random.uniform(1.5, 2.5))

            v_res = self.s.post(
                f"{SITE}/api/faucet/ac-captcha/verify",
                json={"session_id": sid, "candidate_index": best_index},
                timeout=20
            )

            if v_res.status_code == 200:
                v_data = v_res.json()
                if v_data.get("ok") and v_data.get("token"):
                    self.add_log('ok', "Captcha verified successfully! Token acquired.")
                    return v_data["token"]
                self.add_log('err', f"Verification response not ok: {v_data}")
            elif v_res.status_code == 429:
                v_data = v_res.json()
                locked_until = v_data.get("locked_until")
                wait_s = 600
                if locked_until:
                    now_ms = int(time.time() * 1000)
                    wait_s = max(5, int((locked_until - now_ms) / 1000) + 2)
                self.add_log('warn', f"Captcha rate-limited (HTTP 429). Pausing for {wait_s}s...")
                self.live_cooldown(wait_s, label="Captcha Rate-Limit")
            else:
                self.add_log('err', f"Verification failed (HTTP {v_res.status_code}): {v_res.text[:80]}")

        except Exception as e:
            self.add_log('err', f"Error processing captcha: {e}")

        return None

    def claim(self):
        try:
            info_res = self.s.get(f"{SITE}/api/faucet/info", timeout=20)
            if info_res.status_code == 200:
                info = info_res.json()
                remain = info.get("time_remaining_seconds", 0)
                if remain > 0:
                    self.add_log('wait', f"Server cooldown active ({remain//60}m {remain%60:02d}s). Waiting...")
                    self.live_cooldown(remain, label="Server Cooldown")
                    time.sleep(1)
        except Exception as e:
            self.add_log('err', f"Faucet info error: {e}")

        self.current_status = f"Claiming {self.coin}..."
        self.add_log('info', f"Initiating claim cycle for {self.coin}...")

        token = self.solve_captcha()
        if not token:
            self.add_log('warn', "Captcha solve failed. Retrying in 15 seconds...")
            time.sleep(15)
            return False

        # Natural pause before clicking ROLL NOW
        time.sleep(random.uniform(1.2, 2.0))
        self.add_log('info', "Triggering ROLL NOW...")

        try:
            r = self.s.post(f"{SITE}/api/faucet/claim", json={"captcha_token": token}, timeout=25)
            if r.status_code == 200:
                d = r.json()
                if d.get("reward_crypto") is not None:
                    roll = d.get("roll_number", "00000")
                    crypto = float(d.get("reward_crypto", 0))
                    usd = float(d.get("reward_usd", 0))
                    currency = d.get("currency", self.coin)
                    payout_status = d.get("payout_status", "success")

                    self.last = {
                        "crypto": crypto,
                        "usd": usd,
                        "currency": currency,
                        "roll": roll,
                        "payout_status": payout_status
                    }
                    self.balance_usd += usd

                    payout_note = "Sent to FaucetPay!" if payout_status == "success" else payout_status
                    self.add_log('money', f"Won +{crypto:.8f} {currency} (${usd:.6f})! Roll #{roll} · {payout_note}")
                    return True
                err_msg = str(d.get('error', 'unknown')).lower()
                self.add_log('err', f"Claim response error: {d.get('error', 'unknown')}")
                # Detect auth / token related failures
                if any(k in err_msg for k in ("token", "auth", "login", "session", "unauthorized", "invalid captcha", "captcha")):
                    self.add_log('warn', "Possible expired token detected. Will re-login on next cycle.")
            elif r.status_code in (401, 403):
                self.add_log('err', f"Claim auth failed (HTTP {r.status_code}). Token likely expired.")
                self.login(force=True)
            else:
                self.add_log('err', f"Claim failed (HTTP {r.status_code}): {r.text[:80]}")
        except Exception as e:
            self.add_log('err', f"Claim exception: {e}")

        return False

    def run(self):
        if not self.email:
            clear()
            print_banner()
            self.email = input(f" {W}Enter your LimeFaucet email: {G}").strip()
            print(RESET, end="")
            if not self.email:
                print(f"\n {R}Email cannot be empty. Exiting.{RESET}\n")
                return
            self.save()

        if not self.login():
            print(f"\n {R}Authentication failed. Please check your credentials.{RESET}\n")
            return

        self.current_status = "Running Autopilot"
        self.render_view()

        while True:
            try:
                if self.claim():
                    self.ok_count += 1
                    self.total_earned += self.last["usd"]

                    # Base claim cooldown (5m) + random extra (0-30s)
                    extra_claim = random.randint(self.extra_claim_min, self.extra_claim_max)
                    claim_wait = BASE_CLAIM_COOLDOWN + extra_claim

                    # Check if 1-hour session duration has been reached
                    elapsed_session = time.time() - self.session_start
                    if elapsed_session >= self.session_duration:
                        extra_break = random.randint(self.session_break_min, self.session_break_max)
                        total_wait = claim_wait + extra_break

                        e_m, e_s = divmod(extra_break, 60)
                        self.add_log('star', f"1-Hour run session completed! Starting long break ({e_m}m)...")
                        self.live_cooldown(total_wait, label="Session Break Cooldown")
                        self.session_start = time.time()
                        # CRITICAL FIX: Re-login after long break.
                        # lf_token (JWT) typically expires ~1 hour. After 30-45m idle
                        # the token is invalid → captcha/claim always fails until restart.
                        self.add_log('info', "Re-authenticating after session break (token refresh)...")
                        if not self.login(force=True):
                            self.add_log('err', "Re-login failed after break. Retrying in 30s...")
                            time.sleep(30)
                            if not self.login(force=True):
                                self.add_log('err', "Re-login still failing. Waiting 60s then retry...")
                                time.sleep(60)
                        self.add_log('ok', f"Break complete! Starting new {self.session_duration // 60}m session.")
                    else:
                        self.live_cooldown(claim_wait, label="Claim Cooldown")
                else:
                    self.fail_count += 1
                    # On repeated failures, try re-login in case token expired mid-session
                    if self.fail_count % 3 == 0:
                        self.add_log('warn', "Multiple failures detected. Attempting re-login...")
                        self.login(force=True)
                    self.add_log('warn', "Claim cycle incomplete. Retrying in 15 seconds...")
                    time.sleep(15)

            except KeyboardInterrupt:
                clear()
                print(f"\n {Y}Bot stopped by user.{RESET}")
                print(f" Total Claims: {G}{self.ok_count}{RESET} | Earned: {G}${self.total_earned:.8f}{RESET}\n")
                break
            except Exception as e:
                self.add_log('err', f"Main loop exception: {e}")
                time.sleep(15)

def main():
    bot = LimeBot()
    bot.run()

if __name__ == "__main__":
    main()
