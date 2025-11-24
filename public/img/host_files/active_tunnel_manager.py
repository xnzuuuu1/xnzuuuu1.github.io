#!/usr/bin/env python3
"""
Sidecar Tunnel Manager
1. Reads /shared_logs/cloudflared.log (from the Tunnel container)
2. Extracts the current trycloudflare.com URL
3. Updates docker-compose.yml if the URL has changed
"""

import time
import os
import json
import re
import urllib.request
from datetime import datetime

# --- CONFIGURATION ---
TUNNEL_LOG_PATH = "/shared_logs/cloudflared.log"
DOCKER_COMPOSE_PATH = "/home/node/host_files/docker-compose.yml"
SCRIPT_LOG_FILE = "/home/node/sidecar-monitor.log"

def log_message(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    entry = f"[{timestamp}] {message}"
    print(entry, flush=True)
    try:
        with open(SCRIPT_LOG_FILE, 'a') as f:
            f.write(entry + '\n')
    except: pass

def get_tunnel_url():
    # Try 5 times to find a valid URL
    for attempt in range(5):
        if not os.path.exists(TUNNEL_LOG_PATH):
            time.sleep(2)
            continue

        try:
            with open(TUNNEL_LOG_PATH, 'r') as f:
                content = f.read()
            
            # Regex for URL
            url_pattern = r'https://[a-zA-Z0-9_-]+\.trycloudflare\.com'
            matches = re.findall(url_pattern, content)
            
            if matches:
                return matches[-1]
        except Exception as e:
            pass
        
        # If we didn't find it, wait 2 seconds and look again
        time.sleep(2)

    log_message("Error: Could not find URL in logs after 5 attempts.")
    return None

def check_url_health(url):
    """Verifies the URL is actually active"""
    try:
        req = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.getcode() in [200, 302, 404, 503]
    except:
        return False

def update_docker_compose(new_url):
    """Updates the WEBHOOK_URL in the YAML file"""
    if not os.path.exists(DOCKER_COMPOSE_PATH):
        log_message("Error: docker-compose.yml not found")
        return False

    if not new_url.endswith('/'): new_url += '/'

    with open(DOCKER_COMPOSE_PATH, 'r') as f:
        content = f.read()

    # Regex to find 'WEBHOOK_URL=...'
    pattern = r'(WEBHOOK_URL=)(.*)'
    
    match = re.search(pattern, content)
    if match:
        current_in_file = match.group(2)
        if current_in_file.strip().rstrip('/') == new_url.strip().rstrip('/'):
            # log_message("URL in docker-compose.yml is already correct. No update needed.")
            return False 
        
        # Apply Change
        log_message(f"Updating WEBHOOK_URL to {new_url}")
        new_content = re.sub(pattern, f'\\1{new_url}', content)
        with open(DOCKER_COMPOSE_PATH, 'w') as f:
            f.write(new_content)
        return True
    
    return False

def main():
    log_message("=== Sidecar Monitor Started ===")
    
    # 1. Get URL from shared logs
    url = get_tunnel_url()
    
    if not url:
        log_message("No Tunnel URL found yet.")
        print(json.dumps({"success": False, "error": "No URL found"}))
        return

    # 2. Check if it works
    if check_url_health(url):
        # 3. Update File (if needed)
        changed = update_docker_compose(url)
        
        if changed:
            log_message("File updated! Mac Watcher should trigger restart soon.")
            print(json.dumps({"success": True, "action": "update", "url": url}))
        else:
            print(json.dumps({"success": True, "action": "noChange", "url": url}))
            
    else:
        # If URL is found in logs but unreachable, we assume the tunnel container 
        # is dead/restarting or Mac just woke up.
        # We DO NOT start a process. We report failure and wait for Docker to auto-restart the tunnel.
        log_message(f"URL found ({url}) but it is not reachable.")
        print(json.dumps({"success": False, "error": "URL Unreachable - Waiting for Docker/Network"}))
    
    log_message("=== Sidecar Monitor Ended ===")

if __name__ == "__main__":
    main()
