#!/usr/bin/env python3
import time
import os
import json
import re
import sys
import shutil
import tempfile
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

# --- CONFIGURATION ---
TUNNEL_LOG_PATH = "/shared_logs/cloudflared.log"
DOCKER_COMPOSE_PATH = "/home/node/host_files/docker-compose.yml"
SCRIPT_LOG_FILE = "/home/node/sidecar-monitor.log"
TRIGGER_FILE_PATH = "/home/node/host_files/n8n_restart.txt"
TRIGGER2_FILE_PATH = "/home/node/host_files/tunnel_restart.txt"

def log_stderr(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {message}", file=sys.stderr, flush=True)

def get_latest_url():
    # Use tail to read only the last 100 lines (Efficient)
    if not os.path.exists(TUNNEL_LOG_PATH): return None
    try:
        logs = subprocess.check_output(['tail', '-n', '2000', TUNNEL_LOG_PATH], stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore')
        matches = re.findall(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', logs)
        log_stderr(f"matches: {matches}")
        if matches: return matches[-1]
    except: pass
    return None

def check_url_health(url):
    try:
        # 3s timeout is enough for a local check
        req = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.getcode() < 400
    except: return False

def atomic_update_compose(new_url):
    if not os.path.exists(DOCKER_COMPOSE_PATH): return False
    if not new_url.endswith('/'): new_url += '/'

    try:
        with open(DOCKER_COMPOSE_PATH, 'r') as f: content = f.read()
        
        pattern = r'(WEBHOOK_URL=)(.*)'
        match = re.search(pattern, content)
        
        if match:
            current_url = match.group(2).strip().strip('"').strip("'").rstrip('/')
            if current_url == new_url.strip().rstrip('/'):
                return False # No change, do NOT touch files

            # Update Content
            new_content = re.sub(pattern, f'\\1{new_url}', content)
            
            # Atomic Write
            with tempfile.NamedTemporaryFile('w', dir=os.path.dirname(DOCKER_COMPOSE_PATH), delete=False) as tmp:
                tmp.write(new_content)
                temp_name = tmp.name
            shutil.move(temp_name, DOCKER_COMPOSE_PATH)
            
            # TOUCH TRIGGER FILE (This signals 'entr' to restart n8n)
            try:
                #Path(TRIGGER_FILE_PATH).touch()
                #os.chmod(TRIGGER_FILE_PATH, 0o644)
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                with tempfile.NamedTemporaryFile('w', dir=os.path.dirname(TRIGGER_FILE_PATH), delete=False) as tmp:
                    tmp.write(timestamp)
                    temp_name = tmp.name
                shutil.move(temp_name, TRIGGER_FILE_PATH)
            except: pass
            
            return True
    except Exception as e:
        log_stderr(f"Update failed: {e}")
        return False
    return False

def main():
    result = {"action": "error", "url": None}
    
    url = get_latest_url()
    
    if not url:
        result["error"] = "No URL found"
    # Note: We skip check_url_health here because if the tunnel is new, 
    # it might take a second to be reachable from outside. 
    # We trust the log file if it's new.
    elif not check_url_health(url):
        # TOUCH TRIGGER2 FILE (This signals 'entr' to restart tunnel by force)
        try:
            #Path(TRIGGER2_FILE_PATH).touch()
            #os.chmod(TRIGGER2_FILE_PATH, 0o644)
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with tempfile.NamedTemporaryFile('w', dir=os.path.dirname(TRIGGER2_FILE_PATH), delete=False) as tmp:
                tmp.write(timestamp)
                temp_name = tmp.name
            shutil.move(temp_name, TRIGGER2_FILE_PATH)
            result["error"] = "Unhealthy URL found"
        except: pass
    elif atomic_update_compose(url):
        result["action"] = "update"
        result["url"] = url
    else:
        result["action"] = "noChange"
        result["url"] = url

    print(json.dumps(result))

if __name__ == "__main__":
    main()
