#!/usr/bin/env python3
import os
import sys
import time
import argparse
import subprocess
import requests
import re
import json
import psutil
from datetime import datetime

YELLOW = "\033[33m"
BOLD = "\033[1m"
RESET = "\033[0m"
BOLD_GREEN = "\033[1;32m"

def load_env(file_path):
    config = {}
    if not os.path.exists(file_path):
        sys.exit(1)
    with open(file_path, 'r') as f:
        for line in f:
            if '=' in line and not line.strip().startswith('#'):
                key, value = line.split('=', 1)
                config[key.strip()] = value.strip().strip('"').strip("'")
    return config

def get_progress_bar(percentage, width=25):
    filled_len = int(width * percentage // 100)
    bar = '#' * filled_len + '-' * (width - filled_len)
    return f"[{bar}]"

def get_corefreq_data():
    stats = {"max": 0.0, "min": 0.0, "avg": 0.0, "temp": 0, "pwr": 0}
    try:
        raw = subprocess.check_output(["corefreq-cli", "-s"], text=True, timeout=2)
        freqs = re.findall(r'([\d\.]+)\s+MHz', raw)
        if freqs:
            ghz_list = [float(f)/1000 for f in freqs]
            stats["max"] = max(ghz_list)
            stats["min"] = min(ghz_list)
            stats["avg"] = sum(ghz_list) / len(ghz_list)
        temp_match = re.search(r'(?:Package|Core)\s+Temperature\s+(\d+)', raw)
        if temp_match: stats["temp"] = int(temp_match.group(1))
        pwr_match = re.search(r'(?:Total|Package|Energy)\s+([\d\.]+)\s+Watts', raw)
        if pwr_match: stats["pwr"] = int(float(pwr_match.group(1)))
    except: pass
    return stats

def get_ccache_stats():
    try:
        res = subprocess.check_output(["ccache", "-s"], text=True)
        size_match = re.search(r'cache size\s+([\d\.]+\s\w+)\s/\s+([\d\.]+\s\w+)', res)
        file_match = re.search(r'files in cache\s+(\d+)', res)
        size_str = f"{size_match.group(1)} / {size_match.group(2)}" if size_match else "0.0 / 0.0 GB"
        files_str = f"{file_match.group(1)} files" if file_match else "0 files"
        return size_str, files_str
    except: return "0.0 / 0.0 GB", "0 files"

def format_duration(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"

class CIBot:
    def __init__(self, config):
        self.token = config['BOT_TOKEN']
        self.chat_id = config['CHAT_ID']
        self.msg_id = None

    def update_status(self, text, reply_markup=None):
        if not self.msg_id:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
            if reply_markup: payload["reply_markup"] = json.dumps(reply_markup)
            r = requests.post(url, json=payload).json()
            if r.get("ok"): self.msg_id = r["result"]["message_id"]
        else:
            url = f"https://api.telegram.org/bot{self.token}/editMessageText"
            payload = {"chat_id": self.chat_id, "message_id": self.msg_id, "text": text, "parse_mode": "HTML"}
            if reply_markup: payload["reply_markup"] = json.dumps(reply_markup)
            requests.post(url, json=payload)

    def send_document(self, file_path, caption=None):
        url = f"https://api.telegram.org/bot{self.token}/sendDocument"
        try:
            with open(file_path, 'rb') as f:
                payload = {"chat_id": self.chat_id, "caption": caption, "parse_mode": "HTML"}
                requests.post(url, data=payload, files={"document": f})
        except: pass

    def pin_message(self):
        if self.msg_id:
            url = f"https://api.telegram.org/bot{self.token}/pinChatMessage"
            payload = {"chat_id": self.chat_id, "message_id": self.msg_id}
            requests.post(url, json=payload)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, default="config.env")
    args = parser.parse_args()
    CONF = load_env(args.config)
    bot = CIBot(CONF)
    device = CONF.get('DEVICE', 'onyx')
    variant = CONF.get('VARIANT', 'user')

    print(f"\n{BOLD_GREEN}--- VoltageOS Build Menu ---{RESET}")
    print(f"1. Sync + Clean Build (m clobber)")
    print(f"2. Sync + Installclean (m installclean)")
    print(f"3. Sync + Standard Build")
    choice = input(f"\n{YELLOW}{BOLD}Select option (1-3): {RESET}").strip()

    sync_cmd = "repo sync -c -j$(nproc --all) --force-sync --no-clone-bundle --no-tags --optimized-fetch"
    setup_env = f"source build/envsetup.sh && breakfast {device} {variant}"
    build_target = "m bacon"

    if choice == '1':
        full_cmd = f"{sync_cmd} && {setup_env} && m clobber && {build_target}"
        mode_label = "Sync & Clean"
    elif choice == '2':
        full_cmd = f"{sync_cmd} && {setup_env} && m installclean && {build_target}"
        mode_label = "Sync & Installclean"
    elif choice == '3':
        full_cmd = f"{sync_cmd} && {setup_env} && {build_target}"
        mode_label = "Standard Build"
    else:
        sys.exit(1)

    log_file = "build.log"
    if os.path.exists(log_file): os.remove(log_file)
    
    start_time = time.time()
    process = subprocess.Popen(f"bash -c '{full_cmd} 2>&1 | tee {log_file}'", shell=True)
    
    try:
        while process.poll() is None:
            targets, pct = "0/0", 0
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    content = f.read()
                    match = re.findall(r'\[\s*(\d+)%\s+(\d+/\d+)\]', content)
                    if match:
                        pct = int(match[-1][0])
                        targets = match[-1][1]
            
            core = get_corefreq_data()
            cpu_usage = psutil.cpu_percent()
            ram = psutil.virtual_memory()
            cc_size, cc_files = get_ccache_stats()
            
            msg = (
                f"<b>Build started for {device}</b>\n"
                f"Mode: <code>{mode_label}</code>\n\n"
                f"<code>[{targets}] targets ; {pct}%</code>\n"
                f"<code>{get_progress_bar(pct)}</code>\n"
                f"Time running: {format_duration(time.time() - start_time)} (mm:ss)\n\n"
                f"CPU: {cpu_usage}% {core['temp']}°C {core['pwr']}W\n"
                f"<code>{get_progress_bar(cpu_usage)}</code>\n"
                f"GHz: ↑{core['max']:.2f} ↓{core['min']:.2f} ⨏{core['avg']:.2f}\n\n"
                f"RAM: {ram.percent}% ({int(ram.used/1024**2)}/{int(ram.total/1024**2)} MiB)\n"
                f"<code>{get_progress_bar(ram.percent)}</code>\n\n"
                f"ccache: {cc_size}\n"
                f"{cc_files}"
            )
            bot.update_status(msg)
            time.sleep(5)

        if process.returncode == 0:
            out_dir = f"out/target/product/{device}"
            zips = [os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith(".zip") and device in f and "ota" not in f.lower()]
            if zips:
                rom_path = max(zips, key=os.path.getmtime)
                filename = os.path.basename(rom_path)
                bot.update_status(f"<b>Build Success!</b>\nUploading <code>{filename}</code>...")
                
                user = CONF.get('REMOTE_USER')
                host = CONF.get('REMOTE_HOST')
                path = CONF.get('REMOTE_PATH').rstrip('/')
                base_url = CONF.get('DOWNLOAD_URL').rstrip('/')
                
                try:
                    subprocess.run(["scp", rom_path, f"{user}@{host}:{path}/"], check=True)
                    download_url = f"{base_url}/{filename}"
                    markup = {"inline_keyboard": [[{"text": "🚀 Download ROM", "url": download_url}]]}
                    bot.update_status(f"<b>Build Success ✅</b>\n\nDevice: <code>{device}</code>\nMode: <code>{mode_label}</code>\nFile: <code>{filename}</code>", reply_markup=markup)
                    bot.pin_message()
                except Exception as e:
                    bot.update_status(f"<b>Build Success ✅</b>\nBut upload failed: <code>{str(e)}</code>")
            else:
                bot.update_status(f"<b>Build Success ✅</b>\nBut ZIP file was not found.")
        else:
            bot.update_status(f"<b>Build for {device} finished: Failed ❌</b>\nCC: @zenin1504")
            error_log = "out/error.log"
            if os.path.exists(error_log):
                bot.send_document(error_log, caption="Build failed error log. CC: @zenin1504")
            
    except KeyboardInterrupt:
        process.terminate()

if __name__ == "__main__":
    main()
