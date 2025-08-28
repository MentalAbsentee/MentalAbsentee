import streamlit as st
import requests
import json
import time
import pandas as pd
from datetime import datetime

# Configuration
WALLET_ADDRESS = ""
RPC_URL = "https://api.mainnet-beta.solana.com"
OUTPUT_FILE = "wallet_history.txt"
CHECK_INTERVAL = 60
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

def api_request(payload, retries=2):
    for attempt in range(retries + 1):
        try:
            response = requests.post(RPC_URL, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            st.warning(f"Request failed (attempt {attempt + 1}): {e}")
            if attempt < retries:
                time.sleep(5)
    return None

def get_balance(address):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [address]
    }
    data = api_request(payload)
    if data and 'result' in data:
        return data['result']['value'] / 1_000_000_000
    return None

def get_token_accounts(address):
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
    data = api_request(payload)
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
        if amount > 0:
            balances.append({"mint": mint, "amount": amount, "decimals": decimals})
        if decimals == 0 and amount == 1:
            nfts.append({"mint": mint})
    return balances, nfts

def get_recent_transactions(address, limit=10):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [address, {"limit": limit}]
    }
    data = api_request(payload)
    if data and 'result' in data:
        return data['result']
    return []

def parse_transaction(signature, wallet_address):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
    }
    data = api_request(payload)
    if not data or 'result' not in data or not data['result']:
        return None

    tx = data['result']
    timestamp = tx['blockTime']
    date = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S") if timestamp else "N/A"
    
    transfer_info = {"type": "Unknown", "amount": 0, "recipient": "N/A"}
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
        f.write("Transactions:\n")
        for idx, tx in enumerate(txs_data, 1):
            f.write(f"  {idx}. {tx['date']}: {tx['type']}, Amount: {tx['amount']}, To: {tx['recipient']}\n")
        f.write("\n")

# Streamlit UI
st.title("🐶 Solana Wallet Tracker (Beagle Edition)")
st.write("Track SOL, tokens, NFTs, and transactions. Enter a wallet below!")

wallet_input = st.text_input("Wallet Address", value=WALLET_ADDRESS, placeholder="Enter Solana wallet address")
if wallet_input and len(wallet_input) not in [32, 44]:
    st.error("Invalid Solana wallet address (should be ~44 characters).")

if st.button("Check Wallet Details", disabled=not wallet_input):
    with st.spinner("Fetching data..."):
        balance = get_balance(wallet_input)
        token_accounts = get_token_accounts(wallet_input)
        token_balances, nfts = get_token_balances(token_accounts)
        txs = get_recent_transactions(wallet_input)
        
        if balance is not None:
            st.success(f"**SOL Balance:** {balance:.9f} SOL")
        
        if token_balances:
            st.subheader("Token Balances (Non-Zero):")
            tb_df = pd.DataFrame(token_balances)
            st.table(tb_df)
        
        if nfts:
            st.subheader("NFTs:")
            nft_df = pd.DataFrame(nfts)
            st.table(nft_df)
        
        txs_data = []
        tx_placeholder = st.empty()
        if txs:
            st.subheader("Recent Transactions (Last 10):")
            for i, tx in enumerate(txs):
                parsed = parse_transaction(tx['signature'], wallet_input)
                if parsed and parsed['amount'] > 0:
                    txs_data.append(parsed)
                time.sleep(5)  # Increased delay
                tx_placeholder.table(pd.DataFrame(txs_data).assign(number=range(1, len(txs_data)+1)))
        
        save_to_file(balance if balance is not None else "N/A", token_balances, nfts, txs_data, wallet_input)

if st.checkbox("Auto-refresh every 60s", disabled=not wallet_input):
    placeholder = st.empty()
    while True:
        with placeholder.container():
            balance = get_balance(wallet_input)
            token_accounts = get_token_accounts(wallet_input)
            token_balances, nfts = get_token_balances(token_accounts)
            txs = get_recent_transactions(wallet_input)
            
            if balance is not None:
                st.metric("SOL Balance", f"{balance:.9f}")
            
            if token_balances:
                tb_df = pd.DataFrame(token_balances)
                st.table(tb_df)
            
            if nfts:
                nft_df = pd.DataFrame(nfts)
                st.table(nft_df)
            
            txs_data = []
            if txs:
                txs_data = [parse_transaction(tx['signature'], wallet_input) for tx in txs if parse_transaction(tx['signature'], wallet_input) and parse_transaction(tx['signature'], wallet_input)['amount'] > 0]
                if txs_data:
                    df = pd.DataFrame(txs_data).assign(number=range(1, len(txs_data)+1))
                    st.table(df[["number", "date", "type", "amount", "recipient"]])
                save_to_file(balance if balance is not None else "N/A", token_balances, nfts, txs_data, wallet_input)
        time.sleep(CHECK_INTERVAL)
        st.rerun()

st.info("💡 Results saved to wallet_history.txt. Built for #BeagleLife! 🚀")
