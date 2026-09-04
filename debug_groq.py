import os
import urllib.request
import urllib.error

def load_env_file(path):
    if not os.path.exists(path):
        print(f"(.env not found at {path})")
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

# adjust this if your .env lives somewhere else relative to this script
load_env_file(os.path.join(os.path.dirname(__file__), ".env"))

api_key = os.environ.get("GROQ_API_KEY")
print("GROQ_API_KEY present:", bool(api_key))
if api_key:
    print("key length:", len(api_key), "  starts with:", api_key[:6], "  ends with:", api_key[-4:])

# 1. Cheapest possible call - list models. If this 403s, it's purely an auth problem.
req = urllib.request.Request(
    "https://api.groq.com/openai/v1/models",
    headers={
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (compatible; recon-agent/1.0)",
    },
)
try:
    with urllib.request.urlopen(req) as resp:
        print("\n/models call: SUCCESS", resp.status)
except urllib.error.HTTPError as e:
    print(f"\n/models call FAILED: {e.code}")
    print("Body:", e.read().decode("utf-8"))