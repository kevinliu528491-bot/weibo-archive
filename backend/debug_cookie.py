import requests
import os

UID = "1644724561"
# using the cookie from run.sh
COOKIE = "SUB=_2A25Ef4PcDeRhGeBM6lIV8CbPzz6IHXVn9JkUrDV6PUJbktANLWmskW1NRQVR60_LzY0morLXZTBHxI9QKJZ9frqq"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1",
    "Accept": "application/json, text/plain, */*",
    "MWeibo-Pwa": "1",
    "Referer": "https://m.weibo.cn/",
    "Cookie": COOKIE
}

url = "https://m.weibo.cn/api/container/getIndex"
params = {
    "type": "uid",
    "value": UID,
    "containerid": f"107603{UID}",
    "page": 1
}

try:
    print(f"Testing connectivity with cookie...")
    response = requests.get(url, params=params, headers=HEADERS)
    print(f"Status Code: {response.status_code}")
    print(f"Response Content URL: {response.url}")
    # Print first 500 chars
    print(f"Response Body: {response.text[:500]}")
except Exception as e:
    print(f"Error: {e}")
