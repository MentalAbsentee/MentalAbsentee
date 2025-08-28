import streamlit as st
import requests
import json
import time
import random
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup

# Configuration
WALLET_ADDRESS = ""  # No default wallet; user inputs via UI
RPC_URL = "https://api.mainnet-beta.solana.com"
PROXY_LIST_URL = "https://free-proxy-list.net/"  # Free proxy source
OUTPUT_FILE = "wallet_history.txt"  # Log file
CHECK_INTERVAL = 60  # Seconds between checks

def fetch_proxy_list():
    try:
        response = requests.get(PROXY_LIST_URL, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table', id='proxylisttable')
        proxies = []
        if table:
            rows = table.find_all('tr')
            for row in rows[1:]:  # Skip header
                tds = row.find_all('td')
                if len(tds) > 4:
                    ip = tds[0].text.strip()
                    port = tds[1].text.strip()
                    anonymity = tds[4].text.strip().lower()
                    if "elite proxy" in anonymity or "anonymous" in anonymity:
                        proxies.append(f"{ip}:{port}")
        return proxies[:10]
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to fetch proxies: {e}")
        return []

def get_proxies(proxy):
    """Format proxy for requests library."""
    if proxy:
        return {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    return None

def api_request(payload, proxies_list, retries=2):
    """Make an RPC request with proxy rotation."""
    for attempt in range(retries + 1):
        if proxies_list:
            proxy = random.choice(proxies_list)
            proxies = get_proxies(proxy)
            st.info(f"Trying proxy: {proxy}")
        else:
            proxies = None
        try:
            response = requests.post(RPC_URL, json=payload, proxies=proxies, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            st.warning(f"Request failed (attempt {attempt + 1}): {e}")
            if attempt < retries:
                time.sleep(2)
    return None

def get_balance(address, proxies_list):
    """Fetch wallet balance in SOL."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [address]
    }
    data = api_request(payload, proxies_list)
    if data and 'result' in data:
        return data['result']['value'] / 1_000_000_000
    return None

def get_recent_transactions(address, proxies_list, limit=5):
    """Fetch recent transaction signatures."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [address, {"limit": limit}]
    }
    data = api_request(payload, proxies_list)
    if data and 'result' in data:
        return data['result']
    return []

def parse_transaction(signature, proxies_list):
    """Parse a transaction to detect SOL/token transfers."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
    }
    data = api_request(payload, proxies_list)
    if not data or 'result' not in data or not data['result']:
        return None

    tx = data['result']
    timestamp = tx['blockTime']
    date = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S") if timestamp else "N/A"
    
    transfer_info = {"type": "Unknown", "amount": 0, "recipient": "N/A"}
    accounts = tx['transaction']['message']['accountKeys']
    instructions = tx['transaction']['message']['instructions']

    for instr in instructions:
        if 'parsed' in instr and instr['parsed']['type'] == 'transfer':
            info = instr['parsed']['info']
            if 'lamports' in info:
                transfer_info = {
                    "type": "SOL Transfer",
                    "amount": info['lamports'] / 1_000_000_000,
                    "recipient": info['destination']
                }
            elif 'amount' in info and 'mint' in info:
                transfer_info = {
                    "type": f"Token Transfer ({info['mint'][:8]}...)",
                    "amount": int(info['amount']) / (10 ** info.get('decimals', 9)),
                    "recipient": info['destination']
                }
            break
    
    return {"date": date, "signature": signature, **transfer_info}

def save_to
