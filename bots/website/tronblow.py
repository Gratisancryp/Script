#!/usr/bin/env python3
"""
TRONBLOW AUTO CLAIM v6 - Universal Edition
- Headers generic
- ASCII-safe (bisa di-encrypt)
- Auto-diagnose kalau CSRF gagal
- CSRF fallback dari cookie
- Siap dipakai siapa saja
"""

import requests
import re
import time
import random
import os
import sys
import json


# ==================== WARNA ====================
class Colors:
    HEADER  = '\033[95m'
    BLUE    = '\033[94m'
    CYAN    = '\033[96m'
    GREEN   = '\033[92m'
    YELLOW  = '\033[93m'
    RED     = '\033[91m'
    BOLD    = '\033[1m'
    DIM     = '\033[2m'
    END     = '\033[0m'

    @staticmethod
    def ok(text):   return Colors.GREEN + str(text) + Colors.END
    @staticmethod
    def fail(text): return Colors.RED + str(text) + Colors.END
    @staticmethod
    def warn(text): return Colors.YELLOW + str(text) + Colors.END
    @staticmethod
    def info(text): return Colors.CYAN + str(text) + Colors.END
    @staticmethod
    def bold(text): return Colors.BOLD + str(text) + Colors.END
    @staticmethod
    def dim(text):  return Colors.DIM + str(text) + Colors.END


# ==================== KONFIG ====================
CONFIG_FILE = "tronblow_email.txt"
DEBUG_FILE  = "tronblow_debug.html"
RESP_FILE   = "tronblow_response.html"

# Headers generic - tidak terikat device user manapun
GENERIC_UA = (
    "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


# ==================== TRONBLOW BOT ====================
class TronBlow:
    def __init__(self):
        self.base = "https://tronblow.site"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': GENERIC_UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': 'https://tronblow.site',
            'Referer': 'https://tronblow.site/',
            'Upgrade-Insecure-Requests': '1',
        })
        self.email = None
        self.stats = {'claims': 0, 'total_reward': 0, 'start_time': None}
        self.last_html = None  # cache HTML untuk debug

    # ==================== SESSION ====================
    def init_session(self):
        try:
            r = self.session.get(self.base, timeout=15)
            if r.status_code == 200:
                print(Colors.ok("[+] Session initialized"))
                return True
            print(Colors.fail("[-] Server responded HTTP " + str(r.status_code)))
            return False
        except Exception as e:
            print(Colors.fail("[-] Gagal connect: " + str(e)))
            return False

    # ==================== EMAIL CONFIG ====================
    def save_email(self, email):
        try:
            with open(CONFIG_FILE, 'w') as f:
                f.write(email)
            return True
        except Exception:
            return False

    def load_email(self):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return f.read().strip()
        except Exception:
            return None

    # ==================== GET PAGE ====================
    def get_page(self, debug=False):
        """Ambil HTML utama + auto-detect masalah."""
        try:
            r = self.session.get(self.base, timeout=15)
            if r.status_code != 200:
                print(Colors.fail("[-] HTTP " + str(r.status_code)))
                return None

            html = r.text
            self.last_html = html

            # Debug: simpan HTML
            if debug:
                try:
                    with open(DEBUG_FILE, 'w', encoding='utf-8') as f:
                        f.write(html)
                    print(Colors.dim("[*] HTML saved: " + DEBUG_FILE + " (" + str(len(html)) + " bytes)"))
                except Exception:
                    pass

            # Deteksi masalah umum
            if "Just a moment" in html or "cf-browser-verification" in html or "challenge-platform" in html:
                print(Colors.warn("[!] Cloudflare challenge terdeteksi"))
                return None
            if "Access Denied" in html or "403 Forbidden" in html:
                print(Colors.fail("[-] IP diblokir server"))
                return None

            return html
        except Exception as e:
            print(Colors.fail("[-] Error: " + str(e)))
            return None

    # ==================== CSRF EXTRACTOR (ROBUST) ====================
    def extract_csrf(self, html):
        """Cari CSRF token dengan banyak pattern + fallback cookie."""
        patterns = [
            # Standard hidden input (attribute name first)
            r'name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)["\']',
            # Reversed attribute order
            r'value=["\']([^"\']+)["\'][^>]*name=["\']csrf_token["\']',
            # JavaScript variable (camelCase, snake_case, etc)
            r'csrf[_-]?token\s*[:=]\s*["\']([a-zA-Z0-9+/=]+)["\']',
            # Generic 64-char hex
            r'value=["\']([a-f0-9]{64})["\']',
            # Generic 32-char hex (MD5)
            r'value=["\']([a-f0-9]{32})["\']',
            # Meta tag
            r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']',
            # data-csrf attribute
            r'data-csrf=["\']([^"\']+)["\']',
        ]

        for i, pattern in enumerate(patterns):
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                token = match.group(1)
                print(Colors.dim("[*] CSRF via pattern #" + str(i + 1)))
                return token

        # Fallback: cek cookie session
        for cookie in self.session.cookies:
            name = cookie.name.lower()
            if "csrf" in name or "token" in name or "nonce" in name:
                print(Colors.dim("[*] CSRF from cookie: " + cookie.name))
                return cookie.value

        return None

    # ==================== MATH EXTRACTOR ====================
    def extract_math(self, html):
        """Extract soal matematika + hitung jawaban."""
        # Pattern utama
        match = re.search(r'<div class="captcha-q">([^<]+)</div>', html)
        if match:
            question = match.group(1).strip()
            print(Colors.info("[?] Question: " + question))

            math_match = re.search(r'(\d+)\s*([\+\-\*/xX])\s*(\d+)', question)
            if math_match:
                a = int(math_match.group(1))
                op = math_match.group(2)
                b = int(math_match.group(3))

                if op == '+':
                    ans = a + b
                elif op == '-':
                    ans = a - b
                elif op == '*' or op.lower() == 'x':
                    ans = a * b
                elif op == '/':
                    ans = a // b if b != 0 else 0
                else:
                    ans = None

                if ans is not None:
                    print(Colors.info("[*] Math: " + str(a) + " " + op + " " + str(b) + " = " + str(ans)))
                    return ans

        # Fallback: cari 2 angka di captcha-q
        match = re.search(r'captcha-q[^>]*>([^<]+)<', html)
        if match:
            text = match.group(1)
            nums = re.findall(r'(\d+)', text)
            if len(nums) >= 2:
                a, b = int(nums[0]), int(nums[1])
                if '+' in text: return a + b
                if '-' in text: return a - b
                if '*' in text or 'x' in text.lower(): return a * b
                if '/' in text: return a // b if b != 0 else 0
                return a + b

        return None

    # ==================== DIAGNOSE ====================
    def diagnose(self):
        """Diagnosa halaman TronBlow kalau ada masalah."""
        print(Colors.info("\n[*] Diagnosa halaman..."))
        try:
            r = self.session.get(self.base, timeout=15)
            html = r.text
        except Exception as e:
            print(Colors.fail("[-] Koneksi gagal: " + str(e)))
            return

        print(Colors.dim("[*] Status  : " + str(r.status_code)))
        print(Colors.dim("[*] Length  : " + str(len(html))))
        print(Colors.dim("[*] Cookies : " + str([c.name for c in self.session.cookies])))

        checks = {
            "CSRF token"    : "csrf_token" in html,
            "Claim form"    : ('action="claim"' in html or "action='claim'" in html or 'name="math_answer"' in html),
            "Cooldown"      : ("countdown-box" in html or "Next claim available" in html),
            "Math captcha"  : "captcha-q" in html,
            "Cloudflare"    : ("Just a moment" in html or "cf-browser-verification" in html),
            "Access Denied" : ("Access Denied" in html or "403 Forbidden" in html),
            "Register form" : ("register" in html.lower() and "password" in html.lower()),
        }

        print(Colors.info("\n[*] Hasil diagnosa:"))
        for k, v in checks.items():
            mark = Colors.ok("[+]") if v else Colors.fail("[-]")
            print("   " + mark + " " + k)

        # Simpan HTML
        try:
            with open(DEBUG_FILE, "w", encoding="utf-8") as f:
                f.write(html)
            print(Colors.dim("\n[*] HTML saved: " + DEBUG_FILE))
            print(Colors.dim("[*] Kirim file ini ke developer kalau masih error"))
        except Exception:
            pass

    # ==================== CLAIM ====================
    def claim(self, debug=False):
        print(Colors.info("\n[*] Claiming..."))

        html = self.get_page(debug=debug)
        if not html:
            return False

        # Cek cooldown
        if 'Next claim available' in html or 'countdown-box' in html:
            time_match = re.search(
                r'id="cdH">(\d+)</div>.*?id="cdM">(\d+)</div>.*?id="cdS">(\d+)</div>',
                html, re.DOTALL
            )
            if time_match:
                h = int(time_match.group(1))
                m = int(time_match.group(2))
                s = int(time_match.group(3))
                total = h * 3600 + m * 60 + s
                if total > 0:
                    print(Colors.warn("[~] Cooldown: " + str(h).zfill(2) + ":" + str(m).zfill(2) + ":" + str(s).zfill(2)))
                    return total

        # CSRF
        csrf = self.extract_csrf(html)
        if not csrf:
            print(Colors.fail("[-] CSRF token tidak ditemukan"))
            print(Colors.warn("[!] Coba jalankan menu 'Diagnosa' untuk cek"))
            if debug:
                try:
                    with open(DEBUG_FILE, 'w', encoding='utf-8') as f:
                        f.write(html)
                    print(Colors.dim("[*] HTML saved: " + DEBUG_FILE))
                except Exception:
                    pass
            return False
        print(Colors.info("[*] CSRF: " + csrf[:20] + "..."))

        # Math
        math_answer = self.extract_math(html)
        if math_answer is None:
            print(Colors.fail("[-] Math tidak bisa dihitung"))
            if debug:
                try:
                    with open(DEBUG_FILE, 'w', encoding='utf-8') as f:
                        f.write(html)
                except Exception:
                    pass
            return False
        print(Colors.info("[+] Answer: " + str(math_answer)))

        # Kirim claim
        data = {
            'action': 'claim',
            'csrf_token': csrf,
            'website': '',
            'email': self.email,
            'math_answer': str(math_answer),
        }

        try:
            response = self.session.post(self.base, data=data, timeout=30)

            if response.status_code != 200:
                print(Colors.fail("[-] HTTP " + str(response.status_code)))
                return False

            html_result = response.text

            # Sukses?
            if 'Success!' in html_result or 'sent to your' in html_result:
                payout_match = re.search(r'Payout #(\d+)', html_result)
                payout = payout_match.group(1) if payout_match else 'N/A'
                self.stats['claims'] += 1
                self.stats['total_reward'] += 1000
                print(Colors.ok("[+] Claim success! +1000 Satoshi (Payout #" + str(payout) + ")"))
                return True

            # Error message?
            error_match = re.search(r'alert-error[^>]*>([^<]+)<', html_result)
            if error_match:
                error_msg = error_match.group(1).strip()
                print(Colors.fail("[-] Error: " + error_msg))
                if debug:
                    try:
                        with open(RESP_FILE, 'w', encoding='utf-8') as f:
                            f.write(html_result)
                        print(Colors.dim("[*] Response saved: " + RESP_FILE))
                    except Exception:
                        pass
                return False

            # Cooldown lagi?
            if 'Next claim available' in html_result or 'countdown-box' in html_result:
                print(Colors.ok("[+] Claim processed!"))
                return True

            print(Colors.warn("[!] Response tidak dikenal"))
            if debug:
                try:
                    with open(RESP_FILE, 'w', encoding='utf-8') as f:
                        f.write(html_result)
                except Exception:
                    pass
            return False
        except Exception as e:
            print(Colors.fail("[-] Error: " + str(e)))
            return False

    # ==================== AUTO CLAIM ====================
    def auto_claim(self, max_claims=100):
        print(Colors.bold("\n[*] AUTO CLAIM START"))
        print("=" * 60)
        print(Colors.info("[i] Email  : " + str(self.email)))
        print(Colors.info("[i] Target : " + str(max_claims) + " claims"))
        print("=" * 60)

        self.stats['start_time'] = time.time()
        count = 0
        fails = 0

        while count < max_claims:
            result = self.claim()

            if result is True:
                count += 1
                fails = 0
                wait = 65
                self._countdown(wait)
            elif isinstance(result, int):
                wait = result + 5
                self._countdown(wait)
            else:
                fails += 1
                print(Colors.warn("[!] Failed (" + str(fails) + "/3)"))
                if fails >= 3:
                    print(Colors.warn("[!] Terlalu banyak gagal, stop"))
                    print(Colors.info("[i] Tip: jalankan menu 3 (Diagnosa) untuk cek masalah"))
                    break
                time.sleep(5)

        self.show_summary()

    def _countdown(self, seconds):
        print(Colors.info("[~] Waiting " + str(seconds) + "s..."))
        for i in range(seconds):
            time.sleep(1)
            remaining = seconds - i - 1
            sys.stdout.write("\r" + Colors.YELLOW + "[~] Next claim in " + str(remaining) + "s..." + Colors.END)
            sys.stdout.flush()
        print()

    # ==================== SUMMARY ====================
    def show_summary(self):
        elapsed = int(time.time() - self.stats['start_time']) if self.stats['start_time'] else 0
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60

        print("\n" + "=" * 60)
        print(Colors.HEADER + "[*] SUMMARY" + Colors.END)
        print("=" * 60)
        print("[~] Duration    : " + str(h) + "h " + str(m) + "m " + str(s) + "s")
        print("[+] Claims      : " + str(self.stats['claims']))
        print("[$] Total Reward: " + str(self.stats['total_reward']) + " Satoshi")
        print("=" * 60)


# ==================== BANNER ====================
def print_banner():
    print()
    print(Colors.CYAN + "+" + "-" * 58 + "+" + Colors.END)
    print(Colors.CYAN + "|" + " " * 58 + "|" + Colors.END)
    print(Colors.CYAN + "|" + Colors.BOLD + "   TRONBLOW AUTO CLAIM v6" + Colors.END + Colors.CYAN + " " * 33 + "|" + Colors.END)
    print(Colors.CYAN + "|" + Colors.YELLOW + "  By: @Samdekdck" + Colors.END + Colors.CYAN + " " * 38 + "|" + Colors.END)
    print(Colors.CYAN + "|" + " " * 58 + "|" + Colors.END)
    print(Colors.CYAN + "+" + "-" * 58 + "+" + Colors.END)
    print()


# ==================== MAIN ====================
def main():
    clear_screen()
    print_banner()

    tb = TronBlow()

    # ===== 1. INPUT EMAIL =====
    saved_email = tb.load_email()

    if saved_email:
        print(Colors.ok("[+] Email tersimpan: " + saved_email))
        try:
            use_saved = input(Colors.YELLOW + "? Gunakan email ini? (y/n): " + Colors.END).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if use_saved == 'y':
            tb.email = saved_email
        else:
            saved_email = None

    if not tb.email:
        print(Colors.info("\n[*] Masukkan email FaucetPay:"))
        try:
            email = input(Colors.GREEN + "? Email: " + Colors.END).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not email or '@' not in email:
            print(Colors.fail("[-] Email tidak valid!"))
            return

        tb.email = email
        tb.save_email(email)
        print(Colors.ok("[+] Email saved: " + email))

    # ===== 2. INIT SESSION =====
    print(Colors.info("\n[*] Initialize session..."))
    if not tb.init_session():
        print(Colors.fail("[-] Gagal init. Cek koneksi internet."))
        return

    # ===== 3. TEST CONNECT =====
    print(Colors.info("[*] Testing..."))
    html = tb.get_page()

    if not html:
        print(Colors.fail("[-] Gagal connect"))
        return

    print(Colors.ok("[+] Connected!"))
    if 'countdown-box' in html or 'Next claim available' in html:
        print(Colors.warn("[~] Masih cooldown"))
    else:
        print(Colors.ok("[+] Siap claim!"))

    # ===== 4. MENU =====
    print("\n" + "=" * 60)
    print(Colors.bold("PILIH MODE:"))
    print("  1. " + Colors.GREEN + "Auto Claim" + Colors.END)
    print("  2. " + Colors.CYAN + "Test 1 Claim (debug)" + Colors.END)
    print("  3. " + Colors.YELLOW + "Diagnosa (kalau ada error)" + Colors.END)
    print("  0. " + Colors.RED + "Keluar" + Colors.END)
    print("=" * 60)

    try:
        choice = input("\n" + Colors.YELLOW + "? Pilih (0-3): " + Colors.END).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if choice == "1":
        try:
            max_input = input(Colors.YELLOW + "? Jumlah claim (default 100): " + Colors.END).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        tb.auto_claim(int(max_input) if max_input.isdigit() else 100)

    elif choice == "2":
        tb.stats['start_time'] = time.time()
        result = tb.claim(debug=True)
        if result is True:
            tb.stats['claims'] = 1
            tb.stats['total_reward'] = 1000
        tb.show_summary()

    elif choice == "3":
        tb.diagnose()

    elif choice == "0":
        print(Colors.info("[*] Bye!"))
        return
    else:
        print(Colors.fail("[-] Pilihan tidak valid"))


# ==================== ENTRY ====================
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(Colors.warn("\n[!] STOP"))
    except Exception as e:
        print(Colors.fail("\n[-] Error: " + str(e)))
