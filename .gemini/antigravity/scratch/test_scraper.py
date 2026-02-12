import sys
print("Test script starting...", file=sys.stderr)
import os
print(f"UID: {os.getenv('WEIBO_UID')}", file=sys.stderr)
try:
    import requests
    print("Requests imported successfully", file=sys.stderr)
except ImportError as e:
    print(f"Import failed: {e}", file=sys.stderr)
