#!/usr/bin/env python3
import os
import sys
import time
import argparse
import subprocess
import requests
import re
import json

YELLOW = "\033[33m"
BOLD = "\033[1m"
RESET = "\033[0m"
BOLD_GREEN = "\033[1;32m"
RED = "\033[31m"
CYAN = "\033[36m"

def load_env(file_path):
    config = {}
    if not os.path.exists(file_path):
        print(f"{RED}Error: Config file '{file_path}' not found.{RESET}")
        sys.exit(1)
    with open(file_path, 'r') as f:
        for line in f:
            if not line.strip() or line.strip().startswith('#'): continue
            if '=' in line:
                key, value = line.split('=', 1)
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if value.lower() == 'true': value = True
                elif value.lower() == 'false': value = False
                config[key] = value
    return config

class CIBot:
    def __init__(self, config):
        self.config = config
        self.base_url = f"https://api.telegram.org/bot{config['BOT_TOKEN']}"
        self.message_id = None

    def send_message(self, text, chat_id=None, reply_markup=None):
        target_chat = chat_id if chat_id else self.config['CHAT_ID']
        url = f"{self.base_url}/sendMessage"
        data = {"chat_id": target_chat, "text": text, "parse_mode": "html", "disable_web_page_preview": True}
        if reply_markup: data["reply_markup"] = json.dumps(reply_markup)
        try:
            r = requests.post(url, data=data)
            return r.json().get("result", {}).get("message_id")
        except: return None

    def edit_message(self, text):
        if not self.message_id: return
        url = f"{self.base_url}/editMessageText"
        data = {"chat_id": self.config['CHAT_ID'], "message_id": self.message_id, "text": text, "parse_mode": "html", "disable_web_page_preview": True}
        try: requests.post(url, data=data)
        except: pass

    def send_document(self, file_path):
        try:
            with open(file_path, 'rb') as f:
                requests.post(f"{self.base_url}/sendDocument", data={"chat_id": self.config['CHAT_ID']}, files={"document": f})
        except: pass

def upload_gofile(file_path, token=None):
    try:
        server_res = requests.get("https://api.gofile.io/servers").json()
        if server_res["status"] != "ok": return None
        server = server_res["data"]["servers"][0]["name"]
        url = f"https://{server}.gofile.io/contents/uploadfile"
        data = {"token": token} if token else {}
        with open(file_path, 'rb') as f:
            res = requests.post(url, files={"file": f}, data=data, timeout=None).json()
        return res["data"]["downloadPage"] if res["status"] == "ok" else None
    except: return None

def fetch_progress(log_file):
    try:
        if not os.path.exists(log_file): return None
        with open(log_file, "r") as f:
            lines = f.readlines()
            for line in reversed(lines):
                match = re.search(r'(\d+%) (\d+/\d+)', line)
                if match: return f"{match.group(1)} ({match.group(2)})"
    except: pass
    return None

def format_duration(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s" if h > 0 else f"{m}m {s}s"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, default="config.env")
    parser.add_argument('-p', '--pick', nargs='+', help='Cherry-pick IDs')
    args = parser.parse_args()
    CONFIG = load_env(args.config)
    bot = CIBot(CONFIG)

    rom_name = CONFIG.get('ROM_NAME', 'YAAP')
    print(f"{BOLD_GREEN}1. repo sync -> source build -> lunch -> m clean -> m yaap{RESET}")
    print(f"{BOLD_GREEN}2. repo sync -> source build -> lunch -> m installclean -> m yaap{RESET}")
    print(f"{BOLD_GREEN}3. repo sync -> source build -> lunch -> m yaap{RESET}")
    
    choice = input(f"\n{BOLD}Select option (1-3): {RESET}").strip()
    
    gms_env = f"export WITH_GMS={CONFIG.get('WITH_GMS', False)} && "
    setup_env = f"source build/envsetup.sh && lunch yaap_{CONFIG['DEVICE']}-{CONFIG['VARIANT']}"
    sync_cmd = "repo sync -j$(nproc --all) --no-tags --no-clone-bundle --current-branch"
    build_cmd = "m yaap"
    if args.pick: build_cmd = f"repopick {' '.join(args.pick)} && m yaap"

    log_file = "build.log"
    error_log = "out/error.log"
    if os.path.exists(log_file): os.remove(log_file)
    start_time = time.time()
    
    mode_map = {"1": "Sync & Clean Build", "2": "Sync & Installclean", "3": "Sync & Build"}
    mode_label = mode_map.get(choice, "Unknown")
    info_text = f"<b>ROM:</b> <code>{rom_name}</code>\n<b>Device:</b> <code>{CONFIG['DEVICE']}</code>\n<b>Variant:</b> <code>{CONFIG['VARIANT']}</code>\n<b>GMS:</b> <code>{CONFIG.get('WITH_GMS', False)}</code>\n<b>Mode:</b> <code>{mode_label}</code>"

    bot.message_id = bot.send_message(f"<b>Build Status: Starting</b>\n{info_text}")

    if choice in ['1', '2', '3']:
        bot.edit_message(f"<b>Build Status: Syncing Source...</b>\n{info_text}")
        subprocess.run(f"bash -c '{sync_cmd}' | tee -a {log_file}", shell=True)

    full_build_chain = f"{gms_env}{setup_env} && m clean && {build_cmd}" if choice == '1' else \
                       f"{gms_env}{setup_env} && m installclean && {build_cmd}" if choice == '2' else \
                       f"{gms_env}{setup_env} && {build_cmd}" if choice == '3' else sys.exit(1)

    bot.edit_message(f"<b>Build Status: Compiling...</b>\n{info_text}\n<b>Progress:</b> <code>Initializing</code>")
    compile_proc = subprocess.Popen(f"bash -c '{full_build_chain} 2>&1 | tee -a {log_file}'", shell=True)

    prev_prog = ""
    while compile_proc.poll() is None:
        curr_prog = fetch_progress(log_file)
        if curr_prog and curr_prog != prev_prog:
            bot.edit_message(f"<b>Build Status: Compiling</b>\n{info_text}\n<b>Progress:</b> <code>{curr_prog}</code>")
            prev_prog = curr_prog
        time.sleep(30)

    out_dir = f"out/target/product/{CONFIG['DEVICE']}"
    build_success = False
    rom_zip = None
    if os.path.exists(out_dir):
        zips = [os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith(".zip") and CONFIG['DEVICE'] in f and "ota" not in f.lower()]
        if zips:
            rom_zip = max(zips, key=os.path.getmtime)
            if os.path.getmtime(rom_zip) > start_time: build_success = True

    if build_success:
        bot.edit_message(f"<b>Build Status: Uploading...</b>\n{info_text}")
        gofile_link = upload_gofile(rom_zip, CONFIG.get('GOFILE_TOKEN'))
        md5 = subprocess.check_output(f"md5sum {rom_zip} | awk '{{print $1}}'", shell=True).decode().strip()
        size = subprocess.check_output(f"ls -sh {rom_zip} | awk '{{print $1}}'", shell=True).decode().strip()
        
        bot.edit_message(f"<b>Build Status: Success ✅</b>\n{info_text}\n<i>Sent to owner.</i>")
        
        markup = {"inline_keyboard": [[{"text": "🚀 Download ROM", "url": gofile_link if gofile_link else "https://gofile.io"}]]}
        success_msg = (
            f"<b>New {rom_name} Build Ready!</b>\n\n"
            f"<b>Device:</b> <code>{CONFIG['DEVICE']}</code>\n"
            f"<b>File:</b> <code>{os.path.basename(rom_zip)}</code>\n"
            f"<b>Size:</b> <code>{size}</code>\n"
            f"<b>MD5:</b> <code>{md5}</code>\n"
            f"<b>Duration:</b> <code>{format_duration(time.time()-start_time)}</code>"
        )
        bot.send_message(success_msg, chat_id="6500816373", reply_markup=markup)
    else:
        bot.edit_message(f"<b>Build Status: Failed ❌</b>\n{info_text}")
        bot.send_document(error_log) if os.path.exists(error_log) else bot.send_document(log_file) if os.path.exists(log_file) else None

if __name__ == "__main__":
    main()
