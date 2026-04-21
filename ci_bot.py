#!/usr/bin/env python3
import os
import sys
import time
import argparse
import subprocess
import requests
import re
import json
from datetime import datetime

YELLOW = "\033[33m"
BOLD = "\033[1m"
RESET = "\033[0m"
BOLD_GREEN = "\033[1;32m"
RED = "\033[31m"
CYAN = "\033[36m"

ROOT_DIRECTORY = os.getcwd()
REMOTE_USER = "zenin"
REMOTE_HOST = "zenin1504.dpdns.org"

def get_ts():
    return f"[{datetime.now().strftime('%H:%M:%S')}]"

try:
    ROM_NAME = os.path.basename(ROOT_DIRECTORY)
except:
    ROM_NAME = "Unknown"

def load_env(file_path):
    config = {}
    if not os.path.exists(file_path):
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
        self.base_url = f"https://api.telegram.org/bot{config['BOT_TOKEN']}"
        self.message_id = None
        self.config = config

    def send_message(self, text, chat_id=None, reply_markup=None):
        target_chat = chat_id if chat_id else self.config['CHAT_ID']
        url = f"{self.base_url}/sendMessage"
        data = {"chat_id": target_chat, "text": text, "parse_mode": "html", "disable_web_page_preview": True}
        if reply_markup: data["reply_markup"] = json.dumps(reply_markup)
        try:
            r = requests.post(url, data=data)
            res = r.json()
            if res.get("ok"): return res["result"]["message_id"]
        except: return None

    def edit_message(self, text, message_id=None, chat_id=None, reply_markup=None):
        msg_id = message_id if message_id else self.message_id
        target_chat = chat_id if chat_id else self.config['CHAT_ID']
        if not msg_id: return
        url = f"{self.base_url}/editMessageText"
        data = {"chat_id": target_chat, "message_id": msg_id, "text": text, "parse_mode": "html", "disable_web_page_preview": True}
        if reply_markup: data["reply_markup"] = json.dumps(reply_markup)
        try: requests.post(url, data=data)
        except: pass

    def send_document(self, file_path, chat_id=None):
        target_chat = chat_id if chat_id else self.config['CHAT_ID']
        try:
            with open(file_path, 'rb') as f:
                requests.post(f"{self.base_url}/sendDocument", data={"chat_id": target_chat}, files={"document": f})
        except: pass

def remote_deploy(file_paths, target_path):
    try:
        ssh_opts = ["-o", "PasswordAuthentication=no", "-o", "StrictHostKeyChecking=no"]
        subprocess.run(["ssh"] + ssh_opts + [f"{REMOTE_USER}@{REMOTE_HOST}", f"mkdir -p {target_path}"], check=True)
        for fp in file_paths:
            if os.path.exists(fp):
                subprocess.run(["scp"] + ssh_opts + [fp, f"{REMOTE_USER}@{REMOTE_HOST}:{target_path}/"], check=True)
        return True
    except: return False

def fetch_progress(log_file):
    try:
        if not os.path.exists(log_file): return None, "Building"
        status = "Building"
        progress = None
        with open(log_file, "r") as f:
            lines = f.readlines()
            content = "".join(lines[-50:])
            if "Fetching" in content or "Syncing" in content: status = "Syncing Source"
            elif "ninja" in content or "target" in content: status = "Compiling"
            for line in reversed(lines):
                match = re.search(r'(\d+%)[\s\(\[]*(\d+/\d+)', line)
                if match:
                    progress = f"{match.group(1)} ({match.group(2)})"
                    break
        return progress, status
    except: return None, "Building"

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

    print(f"\n{BOLD_GREEN}Syncing Selection:{RESET}")
    print(f"{BOLD_GREEN}1. repo sync -> m clean -> m yaap{RESET}")
    print(f"{BOLD_GREEN}2. repo sync -> m installclean -> m yaap{RESET}")
    print(f"{BOLD_GREEN}3. repo sync -> m yaap{RESET}")
    choice = input(f"\n{get_ts()} {BOLD}Select build option (1-3): {RESET}").strip()

    print(f"\n{BOLD_GREEN}GApps Selection:{RESET}")
    print(f"1. GApps")
    print(f"2. MicroG")
    gapps_choice = input(f"{get_ts()} {BOLD}Select GApps option (1-2): {RESET}").strip()

    print(f"\n{BOLD_GREEN}Variant Selection:{RESET}")
    print(f"1. user")
    print(f"2. userdebug")
    print(f"3. eng")
    var_choice = input(f"{get_ts()} {BOLD}Select variant (1-3): {RESET}").strip()

    if var_choice == '1': variant = "user"
    elif var_choice == '3': variant = "eng"
    else: variant = "userdebug"

    if gapps_choice == '1':
        gapps_export = "export TARGET_BUILD_GAPPS=true"
        gapps_label = "GApps"
        remote_path = "/var/www/roms/peridot/yaap-gapps"
        base_url = "https://zenin1504.dpdns.org/peridot/yaap-gapps/"
    else:
        gapps_export = "export TARGET_BUILD_GAPPS=false"
        gapps_label = "MicroG"
        remote_path = "/var/www/roms/peridot/yaap"
        base_url = "https://zenin1504.dpdns.org/peridot/yaap/"

    sync_cmd = "repo sync -j$(nproc --all) --no-tags --no-clone-bundle --current-branch --force-sync"
    setup_env = f"source build/envsetup.sh && lunch yaap_{CONFIG['DEVICE']}-{variant}"
    build_cmd = "m yaap"
    if args.pick: build_cmd = f"repopick {' '.join(args.pick)} && {build_cmd}"
    
    if choice == '1':
        mode_cmd = "m clean"
        mode_label = "Sync & Clean Build"
    elif choice == '2':
        mode_cmd = "m installclean"
        mode_label = "Sync & Installclean"
    else:
        mode_cmd = "true"
        mode_label = "Sync & Build"

    full_cmd_chain = f"{gapps_export} && {sync_cmd} && {setup_env} && {mode_cmd} && {build_cmd}"
    log_file = "build.log"
    error_log = "out/error.log"
    if os.path.exists(log_file): os.remove(log_file)
    start_time_stamp = time.time()
    
    info_text = (f"<b>ROM:</b> {ROM_NAME}\n"
                 f"<b>Device:</b> <code>{CONFIG['DEVICE']}</code>\n"
                 f"<b>Variant:</b> <code>{variant}</code>\n"
                 f"<b>Build Type:</b> <code>{gapps_label}</code>\n"
                 f"<b>Mode:</b> <code>{mode_label}</code>")

    bot.message_id = bot.send_message(f"<b>Build Status: Starting</b>\n{info_text}")
    process = subprocess.Popen(f"bash -c '{full_cmd_chain} 2>&1 | tee {log_file}'", shell=True)
    
    prev_prog, prev_status = "", ""
    while process.poll() is None:
        curr_prog, curr_status = fetch_progress(log_file)
        if (curr_prog and curr_prog != prev_prog) or (curr_status != prev_status):
            duration = format_duration(time.time() - start_time_stamp)
            bot.edit_message(f"<b>Build Status: {curr_status}</b>\n{info_text}\n<b>Time Elapsed:</b> <code>{duration}</code>\n<b>Progress:</b> <code>{curr_prog if curr_prog else 'Initializing...'}</code>")
            prev_prog, prev_status = curr_prog, curr_status
        time.sleep(30)
    
    out_dir = f"out/target/product/{CONFIG['DEVICE']}"
    build_success = False
    rom_zip = None
    if os.path.exists(out_dir):
        all_zips = [os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith(".zip") and CONFIG['DEVICE'] in f and "ota" not in f.lower()]
        if all_zips:
            latest_zip = max(all_zips, key=os.path.getmtime)
            if os.path.getmtime(latest_zip) > start_time_stamp:
                build_success = True
                rom_zip = latest_zip
    
    if build_success:
        duration_final = format_duration(time.time() - start_time_stamp)
        rom_url = f"{base_url}{os.path.basename(rom_zip)}"
        bot.edit_message(f"<b>Build Status: Success ✅</b>\n{info_text}\n<b>Total Duration:</b> <code>{duration_final}</code>\n\n<i>Uploading ROM & Checksums...</i>")
        
        sha256_file = f"{rom_zip}.sha256sum"
        files_to_deploy = [rom_zip]
        sha256_val = "Not Found"
        if os.path.exists(sha256_file):
            files_to_deploy.append(sha256_file)
            with open(sha256_file, 'r') as f:
                sha256_val = f.read().split()[0]
        
        remote_deploy(files_to_deploy, remote_path)
        md5 = subprocess.check_output(f"md5sum {rom_zip} | awk '{{print $1}}'", shell=True).decode().strip()
        size = subprocess.check_output(f"ls -sh {rom_zip} | awk '{{print $1}}'", shell=True).decode().strip()
        markup = {"inline_keyboard": [[{"text": "🚀 Download ROM", "url": rom_url}]]}
        
        private_msg = (f"<b>New Build Ready!</b>\n\n"
                       f"<b>File:</b> <code>{os.path.basename(rom_zip)}</code>\n"
                       f"<b>Type:</b> <code>{gapps_label}</code>\n"
                       f"<b>Variant:</b> <code>{variant}</code>\n"
                       f"<b>Size:</b> <code>{size}</code>\n"
                       f"<b>MD5:</b> <code>{md5}</code>\n"
                       f"<b>SHA256:</b> <code>{sha256_val}</code>\n"
                       f"<b>Duration:</b> <code>{duration_final}</code>")
        bot.send_message(private_msg, chat_id="6500816373", reply_markup=markup)
    else:
        duration_fail = format_duration(time.time() - start_time_stamp)
        bot.edit_message(f"<b>Build Status: Failed ❌</b>\n{info_text}\n<b>Time Elapsed:</b> <code>{duration_fail}</code>")
        if os.path.exists(error_log): bot.send_document(error_log)
        elif os.path.exists(log_file): bot.send_document(log_file)

if __name__ == "__main__":
    main()
