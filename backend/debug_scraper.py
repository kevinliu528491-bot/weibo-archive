import requests
import os
import json
import sys

# Quick debug script to see what the API is returning
UID = os.getenv("WEIBO_UID", "1644724561")
COOKIE = os.getenv("WEIBO_COOKIE")
CONTAINER_ID = f"107603{UID}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1",
    "Accept": "application/json, text/plain, */*",
    "MWeibo-Pwa": "1",
    "Referer": "https://m.weibo.cn/",
    "Cookie": COOKIE
}

def check_page_1():
    url = "https://m.weibo.cn/api/container/getIndex"
    params = {
        "type": "uid",
        "value": UID,
        "containerid": CONTAINER_ID,
        "page": 1
    }
    
    print(f"Fetching Page 1 using Cookie: {COOKIE[:20]}...", file=sys.stderr)
    try:
        resp = requests.get(url, params=params, headers=HEADERS)
        print(f"Status: {resp.status_code}", file=sys.stderr)
        data = resp.json()
        
        if data.get("ok") != 1:
            print("API returned not OK", file=sys.stderr)
            print(json.dumps(data, indent=2), file=sys.stderr)
            return

        cards = data.get("data", {}).get("cards", [])
        print(f"Cards found: {len(cards)}", file=sys.stderr)
        
        for i, card in enumerate(cards):
            card_type = card.get("card_type")
            mblog = card.get("mblog", {})
            created_at = mblog.get("created_at", "N/A")
            is_top = mblog.get("isTop", "N/A")
            pid = mblog.get("id", "N/A")
            print(f"[{i}] Type: {card_type}, ID: {pid}, Date: {created_at}, Top: {is_top}", file=sys.stderr)
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        try:
             print(f"Response text start: {resp.text[:500]}", file=sys.stderr)
        except:
             pass

if __name__ == "__main__":
    check_page_1()
