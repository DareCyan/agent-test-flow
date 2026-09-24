import json, urllib.request, sys

REPO = "sst/opencode"

def get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "opencode-bundle/1.0",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)

rel = get(f"https://api.github.com/repos/{REPO}/releases/latest")
print("TAG:", rel["tag_name"])
print("NAME:", rel.get("name"))
print("PUBLISHED:", rel.get("published_at"))
print("ASSETS:", len(rel["assets"]))
print("-" * 70)
for a in sorted(rel["assets"], key=lambda x: x["name"]):
    print(f"{a['name']:<55} {a['size']:>12,}  {a['browser_download_url']}")
