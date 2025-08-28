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
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

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
    if proxy:
        return {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    return None

def api_request(payload, proxies_list, retries=2):
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

def get_token_accounts(address, proxies_list):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            address,
            {"programId": TOKEN_PROGRAM_ID},
            {"encoding": "jsonParsed"}
        ]
    }
    data = api_request(payload, proxies_list)
    if data and 'result' in data:
        return data['result']['value']
    return []

def get_token_balances(token_accounts):
    balances = []
    nfts = []
    for account in token_accounts:
        info = account['account']['data']['parsed']['info']
        mint = info['mint']
        amount = info['tokenAmount']['uiAmount']
        decimals = info['tokenAmount']['decimals']
        balances.append({"mint": mint, "amount": amount, "decimals": decimals})
        if decimals == 0 and amount == 1:
            nfts.append({"mint": mint})
    return balances, nfts

def get_recent_transactions(address, proxies_list, limit=5):
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
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
    }
    data = api_request(payload, proxies_list)
    if not data or 'result' in data or not data['result']:
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

def save_to_file(balance, token_balances, nfts, txs_data, wallet):
    with open(OUTPUT_FILE, 'a') as f:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{timestamp}] Wallet: {wallet}\n")
        f.write(f"SOL Balance: {balance} SOL\n")
        f.write("Token Balances:\n")
        for tb in token_balances:
            f.write(f"  - Mint: {tb['mint']}, Amount: {tb['amount']}\n")
        f.write("NFTs:\n")
        for nft in nfts:
            f.write(f"  - Mint: {nft['mint']}\n")
        f.write("Parsed Transactions:\n")
        for tx in txs_data:
            f.write(f"  - {tx['date']}: {tx['type']}, Amount: {tx['amount']}, To: {tx['recipient']}\n")
        f.write("\n")

# Streamlit UI
st.title("🐶 Solana Wallet Tracker (Beagle Edition)")
st.write("Track SOL, tokens, NFTs, and transactions with IP masking. Enter a wallet below!")

wallet_input = st.text_input("Wallet Address", value=WALLET_ADDRESS, placeholder="Enter Solana wallet address")
if wallet_input and len(wallet_input) not in [32, 44]:
    st.error("Invalid Solana wallet address (should be ~44 characters).")

if 'proxies_list' not in st.session_state:
    with st.spinner("Fetching proxies..."):
        st.session_state.proxies_list = fetch_proxy_list()
    if not st.session_state.proxies_list:
        st.warning("No proxies available—running direct (no IP masking)")

if st.button("Check Wallet Details", disabled=not wallet_input):
    with st.spinner("Fetching data..."):
        balance = get_balance(wallet_input, st.session_state.proxies_list)
        token_accounts = get_token_accounts(wallet_input, st.session_state.proxies_list)
        token_balances, nfts = get_token_balances(token_accounts)
        txs = get_recent_transactions(wallet_input, st.session_state.proxies_list)
        
        if balance is not None:
            st.success(f"**SOL Balance:** {balance:.9f} SOL")
        
        if token_balances:
            st.subheader("Token Balances:")
            tb_df = pd.DataFrame(token_balances)
            st.table(tb_df)
        
        if nfts:
            st.subheader("NFTs:")
            nft_df = pd.DataFrame(nfts)
            st.table(nft_df)
        
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
        
        save_to_file(balance if balance is not None else "N/A", token_balances, nfts, txs_data, wallet_input)

if st.checkbox("Auto-refresh every 60s", disabled=not wallet_input):
    placeholder = st.empty()
    while True:
        with placeholder.container():
            balance = get_balance(wallet_input, st.session_state.proxies_list)
            token_accounts = get_token_accounts(wallet_input, st.session_state.proxies_list)
            token_balances, nfts = get_token_balances(token_accounts)
            txs = get_recent_transactions(wallet_input, st.session_state.proxies_list)
            
            if balance is not None:
                st.metric("SOL Balance", f"{balance:.9f}")
            
            if token_balances:
                tb_df = pd.DataFrame(token_balances)
                st.table(tb_df)
            
            if nfts:
                nft_df = pd.DataFrame(nfts)
                st.table(nft_df)
            
            if txs:
                txs_data = [parse_transaction(tx['signature'], st.session_state.proxies_list) for tx in txs]
                txs_data = [tx for tx in txs_data if tx]
                if txs_data:
                    df = pd.DataFrame(txs_data, columns=["date", "type", "amount", "recipient", "signature"])
                    st.table(df[["date", "type", "amount", "recipient"]])
                save_to_file(balance if balance is not None else "N/A", token_balances, nfts, txs_data, wallet_input)
        time.sleep(CHECK_INTERVAL)
        st.rerun()

st.info("💡 Proxies rotate for privacy. Results saved to wallet_history.txt. Built for #BeagleLife! 🚀")
