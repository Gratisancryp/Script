import os
import sys
import subprocess

# ============================================================
# ===== AUTO-INSTALL DEPENDENCY (JALAN SEBELUM IMPORT) =======
# ============================================================
def auto_install_packages():
    """Cek & install package yang dibutuhin tanpa user harus pip install manual."""
    required = {
        "colorama": "colorama",
    }
    
    missing = []
    for import_name, pip_name in required.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)
    
    if missing:
        print(f"[*] Installing: {', '.join(missing)}...")
        for pkg in missing:
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except:
                # Fallback kalau pip gak ada
                subprocess.check_call(
                    [sys.executable, "-m", "ensurepip", "--default-pip"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
        print(f"[OK] Selesai install.\n")

# Install dulu sebelum import colorama
auto_install_packages()

# Baru import
import time
import json
import ssl
import platform
import shutil
import urllib.request
from colorama import init, Fore, Style

init(autoreset=True)

# ============================================================
# ============ KONFIGURASI GITHUB ============================
# ============================================================
GITHUB_USER = "Gratisancryp"
GITHUB_REPO = "Script"
GITHUB_BRANCH = "main"
RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}"

BOT_FILES = {
    "bots/website/bot_contoh.py": "bots/website/bot_contoh.py",
    # tambahin bot lain di sini
}
# ============================================================


def input_tty(prompt=""):
    try:
        with open('/dev/tty', 'r') as tty:
            sys.stdout.write(prompt)
            sys.stdout.flush()
            line = tty.readline()
            if not line:
                raise EOFError
            return line.rstrip('\n')
    except (OSError, IOError):
        return input(prompt)


class FaucetPanel:
    def __init__(self):
        self.clear_screen()
        self.php_path = None
        self.php_version = None
        self.detect_php()
        self.auto_download_bots()
        self.full_reset_and_cleanup()
        self.init_structure()
        self.load_bot_status()
        self.load_cookies()

    def auto_download_bots(self):
        bot_folder = "bots/website"
        os.makedirs(bot_folder, exist_ok=True)

        existing = [
            f for f in os.listdir(bot_folder)
            if not f.startswith('__') and not f.endswith('.pyc')
        ]
        if existing:
            return
        if not BOT_FILES:
            return

        print(Fore.YELLOW + "\n[*] Setup pertama kali, download bot dari GitHub...\n")

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        success, fail = 0, 0
        for github_path, local_path in BOT_FILES.items():
            url = f"{RAW_BASE}/{github_path}"
            os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)

            for attempt in range(3):
                try:
                    print(Fore.CYAN + f"    [{attempt+1}/3] {github_path}")
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
                        with open(local_path, 'wb') as f:
                            f.write(r.read())
                    print(Fore.GREEN + f"    [OK] Berhasil")
                    success += 1
                    break
                except Exception as e:
                    if attempt == 2:
                        print(Fore.RED + f"    [FAIL] {e}")
                        fail += 1
                    else:
                        time.sleep(2)

        print(Fore.GREEN + f"\n[OK] Download selesai: {success} sukses, {fail} gagal\n")
        time.sleep(2)

    def full_reset_and_cleanup(self):
        protected_files = ["main.py", "main.pyw", "requirements.txt", "README.md", ".gitignore"]

        for item in os.listdir("."):
            item_path = os.path.join(".", item)
            if os.path.isdir(item_path):
                continue
            if item in protected_files:
                continue
            try:
                os.remove(item_path)
            except:
                pass

        for folder in ["config", "logs", "data"]:
            if os.path.exists(folder):
                for item in os.listdir(folder):
                    item_path = os.path.join(folder, item)
                    try:
                        if os.path.isfile(item_path):
                            os.remove(item_path)
                        elif os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                    except:
                        pass
            else:
                os.makedirs(folder, exist_ok=True)

        os.makedirs("bots/website", exist_ok=True)

        bot_folder = "bots/website"
        for item in os.listdir(bot_folder):
            item_path = os.path.join(bot_folder, item)
            if item.endswith(".pyc") or item.endswith(".pyo"):
                try:
                    os.remove(item_path)
                except:
                    pass
            elif item == "__pycache__":
                try:
                    shutil.rmtree(item_path)
                except:
                    pass

    def load_cookies(self):
        self.cookies = {"accounts": []}
        cookies_file = "config/cookies.json"
        if os.path.exists(cookies_file):
            try:
                with open(cookies_file, 'r') as f:
                    self.cookies = json.load(f)
            except:
                self.cookies = {"accounts": []}

    def save_cookies(self):
        os.makedirs("config", exist_ok=True)
        with open("config/cookies.json", 'w') as f:
            json.dump(self.cookies, f, indent=4)

    def init_structure(self):
        self.bot_scripts = {
            "website": {
                "name": "WEBSITE",
                "bots": [{"id": 0, "name": "KEMBALI", "script": "back", "type": "back"}]
            }
        }

    def load_bot_status(self):
        self.bot_status = {}
        status_file = "config/bot_status.json"
        if os.path.exists(status_file):
            try:
                with open(status_file, 'r') as f:
                    self.bot_status = json.load(f)
            except:
                self.bot_status = {}

    def save_bot_status(self):
        os.makedirs("config", exist_ok=True)
        with open("config/bot_status.json", 'w') as f:
            json.dump(self.bot_status, f, indent=4)

    def detect_php(self):
        if platform.system() == "Windows":
            php_paths = ["php", "php.exe", "C:\\xampp\\php\\php.exe",
                         "C:\\xampp8\\php\\php.exe", "C:\\xampp7\\php\\php.exe",
                         "C:\\wamp64\\bin\\php\\php.exe", "C:\\wamp\\bin\\php\\php.exe",
                         "C:\\laragon\\bin\\php\\php.exe", "C:\\php\\php.exe"]
        else:
            php_paths = ["php", "/usr/bin/php", "/usr/local/bin/php",
                         "/opt/lampp/bin/php", "/data/data/com.termux/files/usr/bin/php",
                         "/usr/bin/php7.4", "/usr/bin/php8.0", "/usr/bin/php8.1",
                         "/usr/bin/php8.2", "/usr/bin/php8.3"]

        for path in php_paths:
            try:
                if os.path.exists(path) or path in ["php", "php.exe"]:
                    result = subprocess.run(
                        [path, "-v"], capture_output=True, text=True, timeout=3,
                        shell=True if platform.system() == "Windows" else False
                    )
                    if result.returncode == 0:
                        self.php_path = path
                        version_line = result.stdout.split('\n')[0] if result.stdout else result.stderr.split('\n')[0]
                        self.php_version = version_line.replace('PHP', '').strip()
                        break
            except:
                continue

    def clear_screen(self):
        os.system('cls' if os.name == 'nt' else 'clear')

    def print_banner(self):
        banner = r'''
 ██████╗ ██████╗  █████╗ ████████╗██╗███████╗ █████╗ ███╗   ██╗
██╔════╝ ██╔══██╗██╔══██╗╚══██╔══╝██║██╔════╝██╔══██╗████╗  ██║
██║  ███╗██████╔╝███████║   ██║   ██║███████╗███████║██╔██╗ ██║
██║   ██║██╔══██╗██╔══██║   ██║   ██║╚════██║██╔══██║██║╚██╗██║
╚██████╔╝██║  ██║██║  ██║   ██║   ██║███████║██║  ██║██║ ╚████║
 ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝
                        https://t.me/gratisancryp
'''
        print(Fore.GREEN + banner)
        print(Fore.GREEN + "  " + "=" * 56)
        print(Fore.GREEN + "  " + " " * 15 + "WELCOME TO GRATISANCRYP BOT" + " " * 15)
        print(Fore.GREEN + "  " + "=" * 56)
        print()

    def print_banner_small(self):
        banner = r'''
 ██████╗ ██████╗  █████╗ ████████╗██╗███████╗ █████╗ ███╗   ██╗
██╔════╝ ██╔══██╗██╔══██╗╚══██╔══╝██║██╔════╝██╔══██╗████╗  ██║
██║  ███╗██████╔╝███████║   ██║   ██║███████╗███████║██╔██╗ ██║
██║   ██║██╔══██╗██╔══██║   ██║   ██║╚════██║██╔══██║██║╚██╗██║
╚██████╔╝██║  ██║██║  ██║   ██║   ██║███████║██║  ██║██║ ╚████║
 ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝
                        https://t.me/gratisancryp
'''
        print(Fore.GREEN + banner)
        print(Fore.GREEN + "=" * 60)
        print(Fore.GREEN + "            GRATISANCRYP BOT PANEL")
        print(Fore.GREEN + "=" * 60)
        print()

    def main_menu(self):
        while True:
            self.clear_screen()
            self.print_banner()
            print(Fore.WHITE + "  PILIH MENU")
            print(Fore.CYAN + "  " + "-" * 56)
            print(Fore.GREEN + "  [1] " + Fore.WHITE + "JALANKAN BOT")
            print(Fore.RED + "  [2] " + Fore.WHITE + "EXIT / KELUAR")
            print(Fore.CYAN + "  " + "-" * 56)
            print()

            choice = input_tty(Fore.GREEN + "  Pilih menu [1-2]: " + Fore.WHITE).strip()

            if choice == "1":
                self.show_bot_list("website")
            elif choice == "2":
                print(Fore.YELLOW + "\n  Terima kasih telah menggunakan panel ini!")
                print(Fore.GREEN + "  Happy Farming! 🚀")
                sys.exit()
            else:
                print(Fore.RED + "  Pilihan tidak valid!")
                time.sleep(1)

    def scan_bot_scripts_silent(self):
        bot_folder = "bots/website"
        os.makedirs(bot_folder, exist_ok=True)

        self.bot_scripts["website"]["bots"] = [{"id": 0, "name": "KEMBALI", "script": "back", "type": "back"}]

        if os.path.exists(bot_folder):
            files = os.listdir(bot_folder)
            bot_id = 1
            for file in sorted(files):
                file_path = os.path.join(bot_folder, file)
                if os.path.isfile(file_path):
                    if file.endswith('.py') or file.endswith('.php'):
                        bot_name = os.path.splitext(file)[0].replace('_', ' ').title()
                        self.bot_scripts["website"]["bots"].append({
                            "id": bot_id,
                            "name": bot_name,
                            "script": file_path,
                            "type": "python" if file.endswith('.py') else "php"
                        })
                        bot_id += 1

    def show_bot_list(self, category):
        self.scan_bot_scripts_silent()

        while True:
            self.clear_screen()
            self.print_banner_small()

            category_data = self.bot_scripts.get(category)
            if not category_data:
                print(Fore.RED + "Kategori tidak ditemukan!")
                time.sleep(1)
                return

            bots = category_data["bots"]

            print(Fore.WHITE + "  DAFTAR BOT")
            print(Fore.CYAN + "  " + "-" * 56)

            bot_list = [b for b in bots if b.get("type") != "back"]
            back_bot = [b for b in bots if b.get("type") == "back"]

            if not bot_list:
                print(Fore.YELLOW + "  Belum ada script bot di folder bots/website/")
                print(Fore.YELLOW + "  Taruh script .py atau .php di folder tersebut")
                print()
            else:
                for i in range(0, len(bot_list), 2):
                    line = "  "
                    for j in range(2):
                        if i + j < len(bot_list):
                            bot = bot_list[i + j]
                            bot_id = f"[{bot['id']:2}]"
                            bot_name = bot['name'][:25]
                            col = f"{Fore.YELLOW}{bot_id} {Fore.WHITE}{bot_name:<25}"
                            line += col.ljust(30)
                        else:
                            line += " " * 30
                    print(line)

            print(Fore.CYAN + "  " + "-" * 56)
            if back_bot:
                bot = back_bot[0]
                print(Fore.YELLOW + f"  [{bot['id']:2}] " + Fore.WHITE + bot['name'])
            print(Fore.CYAN + "  " + "-" * 56)
            print()

            choice = input_tty(Fore.GREEN + "  Pilih bot [0-{0}]: ".format(len(bots)-1) + Fore.WHITE).strip()

            try:
                choice_int = int(choice)
                if choice_int == 0:
                    return

                selected_bot = None
                for bot in bots:
                    if bot["id"] == choice_int:
                        selected_bot = bot
                        break

                if selected_bot:
                    if selected_bot["script"] == "back":
                        return

                    if not os.path.exists(selected_bot["script"]):
                        print(Fore.RED + f"\n  [ERROR] File tidak ditemukan!")
                        input_tty("\n" + Fore.WHITE + "  Press Enter to continue...")
                        continue

                    if selected_bot.get("type") == "php" and not self.php_path:
                        print(Fore.RED + "\n  [ERROR] PHP tidak ditemukan!")
                        print(Fore.YELLOW + "  Bot PHP tidak bisa dijalankan.")
                        input_tty("\n" + Fore.WHITE + "  Press Enter to continue...")
                        continue

                    self.run_bot_script(selected_bot["name"], selected_bot["script"], selected_bot.get("type", "python"))
                else:
                    print(Fore.RED + "  Pilihan tidak valid!")
                    time.sleep(1)
            except ValueError:
                print(Fore.RED + "  Input tidak valid! Masukkan angka.")
                time.sleep(1)

    def run_bot_script(self, bot_name, script_file, script_type="python"):
        self.clear_screen()
        self.print_banner_small()
        print(Fore.GREEN + f"  Menjalankan: {bot_name}")
        print(Fore.CYAN + "  " + "-" * 56)
        print()

        if not os.path.exists(script_file):
            print(Fore.RED + f"  File script tidak ditemukan!")
            input_tty("\n" + Fore.WHITE + "  Press Enter to continue...")
            return

        print(Fore.WHITE + f"  Bot : {Fore.GREEN}{bot_name}")
        print(Fore.WHITE + f"  File: {Fore.YELLOW}{script_file}")
        print()

        confirm = input_tty(Fore.YELLOW + "  Lanjutkan? (y/n): " + Fore.WHITE).lower().strip()

        if confirm != 'y':
            print(Fore.YELLOW + "  Dibatalkan.")
            time.sleep(1)
            return

        try:
            print(Fore.CYAN + "\n  " + "=" * 56)
            print(Fore.GREEN + f"  >> Menjalankan {bot_name}...")
            print(Fore.CYAN + "  " + "=" * 56 + "\n")

            if script_type == "php":
                if not self.php_path:
                    print(Fore.RED + "  PHP not found! Cannot run PHP script.")
                    input_tty("\n  Press Enter to continue...")
                    return
                result = subprocess.run([self.php_path, script_file], capture_output=False, text=True)
            else:
                result = subprocess.run([sys.executable, script_file], capture_output=False, text=True)

            print(Fore.CYAN + "\n  " + "=" * 56)
            if result.returncode == 0:
                print(Fore.GREEN + "  [OK] Bot selesai dijalankan!")
            else:
                print(Fore.RED + "  [ERROR] Bot mengalami error! (Exit code: " + str(result.returncode) + ")")
            print(Fore.CYAN + "  " + "=" * 56)
        except KeyboardInterrupt:
            print(Fore.YELLOW + "\n\n  [STOP] Bot dihentikan oleh user.")
        except Exception as e:
            print(Fore.RED + f"  [ERROR] {str(e)}")

        input_tty("\n" + Fore.WHITE + "  Press Enter to continue...")


def main():
    try:
        panel = FaucetPanel()
        panel.main_menu()
    except KeyboardInterrupt:
        print(Fore.YELLOW + "\n\nPanel dihentikan oleh user.")
        sys.exit(0)
    except Exception as e:
        print(Fore.RED + f"Error: {e}")
        input_tty("\nPress Enter to exit...")
        sys.exit(1)


if __name__ == "__main__":
    main()
