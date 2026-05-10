#!/usr/bin/env python3
"""
auto_cookie.py - 自动从 Microsoft Edge 浏览器提取微博 Cookie。

工作原理：
  1. 读取 Edge 浏览器本地的 Cookies SQLite 数据库
  2. 用 macOS Keychain 中的密钥解密 Cookie 值
  3. 筛选出微博相关的 Cookie，拼成 scraper 需要的格式
  4. 保存到 cookie.txt，供定时备份脚本使用

前提条件：
  - 你在 Edge 中保持登录 m.weibo.cn
  - macOS Keychain 处于解锁状态（用户已登录系统即可）
"""

import os
import sys
import sqlite3
import shutil
import tempfile
import subprocess
from pathlib import Path

# Edge cookie 数据库路径（按优先级搜索多个 Profile）
EDGE_COOKIE_PATHS = [
    "~/Library/Application Support/Microsoft Edge/Default/Cookies",
    "~/Library/Application Support/Microsoft Edge/Profile 1/Cookies",
    "~/Library/Application Support/Microsoft Edge/Profile 2/Cookies",
]

# 要提取的域名
WEIBO_DOMAINS = ['.weibo.cn', '.weibo.com', '.m.weibo.cn']

# 缓存 Keychain 密钥（解决 cron 环境可能无法访问 Keychain 的问题）
KEY_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".edge_key_cache")

# cookie.txt 路径
COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookie.txt")


def _log(msg):
    print(f"[auto_cookie] {msg}", file=sys.stderr)


def get_edge_encryption_key():
    """从 macOS Keychain 获取 Edge 的加密密钥，并缓存到本地文件。"""
    # 先尝试 Keychain
    try:
        password = subprocess.check_output(
            ['security', 'find-generic-password',
             '-w', '-s', 'Microsoft Edge Safe Storage',
             '-a', 'Microsoft Edge'],
            stderr=subprocess.DEVNULL
        ).strip()

        # 缓存密钥，供 cron 环境使用
        with open(KEY_CACHE_FILE, 'wb') as f:
            f.write(password)
        _log("Got encryption key from Keychain (cached for cron).")
        return password
    except (subprocess.CalledProcessError, Exception) as e:
        _log(f"Keychain access failed: {e}")

    # 降级：使用缓存的密钥
    if os.path.exists(KEY_CACHE_FILE):
        with open(KEY_CACHE_FILE, 'rb') as f:
            _log("Using cached encryption key.")
            return f.read()

    _log("ERROR: No encryption key available.")
    return None


def derive_aes_key(password):
    """用 PBKDF2 从 Keychain 密码派生 AES 密钥。"""
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=16,
        salt=b'saltysalt',
        iterations=1003,
    )
    return kdf.derive(password)


def decrypt_cookie_value(encrypted_value, aes_key):
    """解密 Chromium 加密的 Cookie 值。
    
    Chromium v10 加密后，解密结果前面会带有随机字节前缀，
    真正的 Cookie 值是其中最长的可打印 ASCII 段。
    """
    import re
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if not encrypted_value:
        return ""

    # Chromium 在加密值前加 'v10' 或 'v11' 前缀
    if len(encrypted_value) >= 3 and encrypted_value[:3] in (b'v10', b'v11'):
        encrypted_data = encrypted_value[3:]
        iv = b' ' * 16

        try:
            cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
            decryptor = cipher.decryptor()
            decrypted = decryptor.update(encrypted_data) + decryptor.finalize()

            # 移除 PKCS7 填充
            padding_len = decrypted[-1]
            if isinstance(padding_len, int) and 1 <= padding_len <= 16:
                decrypted = decrypted[:-padding_len]

            # 先用 latin-1 解码（不会丢字节），再提取最长可打印 ASCII 段
            raw_str = decrypted.decode('latin-1', errors='ignore')
            
            # 匹配可打印 ASCII 字符的连续段（空格到 ~，即 0x20-0x7e）
            matches = re.findall(r'[\x20-\x7e]+', raw_str)
            if matches:
                # 取最长的那段作为 Cookie 值
                return max(matches, key=len)
            return ""
        except Exception as e:
            _log(f"Decryption error: {e}")
            return ""

    # 未加密（明文）
    return encrypted_value.decode('utf-8', errors='ignore')


def find_edge_cookies_db():
    """查找 Edge 的 Cookies 数据库文件。"""
    for path_template in EDGE_COOKIE_PATHS:
        path = os.path.expanduser(path_template)
        if os.path.exists(path):
            _log(f"Found Edge Cookies DB: {path}")
            return path
    return None


def extract_weibo_cookies():
    """从 Edge 提取微博 Cookie，返回格式化的 cookie 字符串。"""
    db_path = find_edge_cookies_db()
    if not db_path:
        _log("ERROR: Edge Cookies database not found.")
        return None

    password = get_edge_encryption_key()
    if not password:
        return None

    aes_key = derive_aes_key(password)

    # 复制数据库文件，避免锁冲突（Edge 可能正在使用）
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.db')
    os.close(tmp_fd)
    shutil.copy2(db_path, tmp_path)

    # 同时复制 WAL 和 SHM 文件（如果存在）
    for suffix in ['-wal', '-shm']:
        src = db_path + suffix
        if os.path.exists(src):
            shutil.copy2(src, tmp_path + suffix)

    cookies = {}
    try:
        conn = sqlite3.connect(tmp_path)
        c = conn.cursor()

        # 构建查询条件
        conditions = " OR ".join(
            f"host_key LIKE '%{d}'" for d in WEIBO_DOMAINS
        )
        c.execute(f"""
            SELECT name, encrypted_value, host_key
            FROM cookies
            WHERE {conditions}
            ORDER BY host_key
        """)

        for name, enc_val, host in c.fetchall():
            val = decrypt_cookie_value(enc_val, aes_key)
            if val:
                # 如果同名 Cookie 出现在多个域名下，优先 .weibo.cn
                if name not in cookies or '.weibo.cn' in host:
                    cookies[name] = val

        conn.close()
    except Exception as e:
        _log(f"Database error: {e}")
    finally:
        # 清理临时文件
        for suffix in ['', '-wal', '-shm']:
            p = tmp_path + suffix
            if os.path.exists(p):
                os.unlink(p)

    if not cookies:
        _log("WARNING: No Weibo cookies found in Edge.")
        return None

    # 过滤掉包含非 ASCII 字符的 Cookie 值（HTTP header 不支持）
    clean_cookies = {}
    for name, val in cookies.items():
        try:
            # HTTP headers 使用 latin-1 编码，Cookie 值必须可编码
            val.encode('latin-1')
            clean_cookies[name] = val
        except UnicodeEncodeError:
            _log(f"Skipping cookie '{name}' (contains non-ASCII chars)")

    if not clean_cookies:
        _log("WARNING: No valid Weibo cookies after filtering.")
        return None

    # 检查关键 Cookie
    if 'SUB' not in clean_cookies:
        _log("WARNING: SUB cookie not found - session may be expired in Edge!")
    else:
        _log(f"SUB cookie found (length={len(clean_cookies['SUB'])})")

    cookie_str = "; ".join(f"{k}={v}" for k, v in clean_cookies.items())
    _log(f"Extracted {len(clean_cookies)} valid Weibo cookies from Edge.")
    return cookie_str


def refresh_cookie_file():
    """
    从 Edge 提取 Cookie 并保存到 cookie.txt。
    返回 cookie 字符串，失败返回 None。
    """
    cookie_str = extract_weibo_cookies()
    if cookie_str:
        with open(COOKIE_FILE, 'w') as f:
            f.write(cookie_str)
        _log(f"Saved fresh cookies to {COOKIE_FILE}")
        return cookie_str

    _log("Failed to extract cookies from Edge.")
    return None


if __name__ == "__main__":
    result = refresh_cookie_file()
    if result:
        print(f"\n✅ Cookie 刷新成功！提取到 {len(result.split(';'))} 个 Cookie。")
        print(f"   已保存到: {COOKIE_FILE}")
        print(f"   预览: {result[:100]}...")
    else:
        print("\n❌ Cookie 刷新失败。请确认：")
        print("   1. Edge 浏览器已安装")
        print("   2. 你已在 Edge 中登录 m.weibo.cn")
        sys.exit(1)
