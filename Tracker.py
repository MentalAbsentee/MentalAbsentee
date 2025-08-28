import streamlit as st
import requests
import json
import time
import random
import pandas as pd
from datetime import datetime

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
        proxies = []
        for line in response.text.splitlines():
            if "elite proxy" in line or "anonymous" in line:
                parts = line.split()
                for part in parts:
                    if ":" in part and part.replace(".", "").replace(":", "").isdigit():
                        proxies.append(part)
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

def save_to_file(balance, txs_data, wallet):
    """Append balance and parsed transactions to a text file."""
    with open(OUTPUT_FILE, 'a') as f:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{timestamp}] Wallet: {wallet}\n")
        f.write(f"Balance: {balance} SOL\n")
        f.write("Parsed Transactions:\n")
        for tx in txs_data:
            f.write(f"  - {tx['date']}: {tx['type']}, Amount: {tx['amount']}, To: {tx['recipient']}\n")
        f.write("\n")

# Streamlit UI
st.title("🐶 Solana Wallet Tracker (Beagle Edition)")
st.write("Track SOL balances and token transfers with IP masking. Enter a wallet below!")

# Input for wallet
wallet_input = st.text_input("Wallet Address", value=WALLET_ADDRESS, placeholder="Enter Solana wallet address")
if wallet_input and len(wallet_input) not in [32, 44]:
    st.error("Invalid Solana wallet address (should be ~44 characters).")

# Fetch proxies once
if 'proxies_list' not in st.session_state:
    with st.spinner("Fetching proxies..."):
        st.session_state.proxies_list = fetch_proxy_list()
    if not st.session_state.proxies_list:
        st.warning("No proxies available—running direct (no IP masking)")

# Button to fetch and display data
if st.button("Check Balance & Transactions", disabled=not wallet_input):
    with st.spinner("Fetching data..."):
        balance = get_balance(wallet_input, st.session_state.proxies_list)
        txs = get_recent_transactions(wallet_input, st.session_state.proxies_list)
        
        if balance is not None:
            st.success(f"**Balance:** {balance:.9f} SOL")
        else:
            st.error("Failed to fetch balance")
        
        if txs:
            st.subheader("Recent Transactions:")
            txs_data = []
            for tx in txs:
                parsed = parse_transaction(tx['signature'], st.session_state.proxies_list)
                if parsed:
                    txs_data.append(parsed)
            
            if txs_data:
                df = pd.DataFrame(txs_data, columns=["date", "type", "amount", "recipient", "signature"])
                st.table(df[["date", "type", "amount", "recipient"]])
                save_to_file(balance if balance is not None else "N/A", txs_data, wallet_input)
            else:
                st.error("Failed to parse transactions")
        else:
            st.error("Failed to fetch transactions")

# Auto-refresh option
if st.checkbox("Auto-refresh every 60s", disabled=not wallet_input):
    placeholder = st.empty()
    while True:
        with placeholder.container():
            balance = get_balance(wallet_input, st.session_state.proxies_list)
            txs = get_recent_transactions(wallet_input, st.session_state.proxies_list)
            if balance is not None:
                st.metric("Balance (SOL)", f"{balance:.9f}")
            if txs:
                txs_data = [parse_transaction(tx['signature'], st.session_state.proxies_list) for tx in txs]
                txs_data = [tx for tx in txs_data if tx]
                if txs_data:
                    df = pd.DataFrame(txs_data, columns=["date", "type", "amount", "recipient", "signature"])
                    st.table(df[["date", "type", "amount", "recipient"]])
                    save_to_file(balance if balance is not None else "N/A", txs_data, wallet_input)
                else:
                    st.text("No transactions parsed")
        time.sleep(CHECK_INTERVAL)
        st.rerun()

st.info("💡 Proxies rotate for privacy. Results saved to wallet_history.txt. Built for #BeagleLife! 🚀")
