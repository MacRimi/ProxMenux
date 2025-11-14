import requests, json
from pathlib import Path

# GitHub API URL to fetch all .json files describing scripts
API_URL = "https://api.github.com/repos/community-scripts/ProxmoxVE/contents/frontend/public/json"

# Base path to build the full URL for the installable scripts
SCRIPT_BASE = "https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main"

# Output file where the consolidated helper scripts cache will be stored
OUTPUT_FILE = Path("json/helpers_cache.json")
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

res = requests.get(API_URL)
data = res.json()
cache = []

# Loop over each file in the JSON directory
for item in data:
    url = item.get("download_url")
    if not url or not url.endswith(".json"):
        continue
    try:
        raw = requests.get(url).json()
        if not isinstance(raw, dict):
            continue
    except:
        continue

    # Extract fields required to identify a valid helper script
    name = raw.get("name", "")
    slug = raw.get("slug")
    type_ = raw.get("type", "")
    script = raw.get("install_methods", [{}])[0].get("script", "")
    if not slug or not script:
        continue  # Skip if it's not a valid script

    desc = raw.get("description", "")
    categories = raw.get("categories", [])
    notes = [note.get("text", "") for note in raw.get("notes", []) if isinstance(note, dict)]
    full_script_url = f"{SCRIPT_BASE}/{script}"


    credentials = raw.get("default_credentials", {})
    cred_username = credentials.get("username")
    cred_password = credentials.get("password")
 
    add_credentials = (
        (cred_username is not None and str(cred_username).strip() != "") or
        (cred_password is not None and str(cred_password).strip() != "")
    )

    entry = {
        "name": name,
        "slug": slug,
        "desc": desc,
        "script": script,
        "script_url": full_script_url,
        "categories": categories,
        "notes": notes,
        "type": type_
    }
    if add_credentials:
        entry["default_credentials"] = {
            "username": cred_username,
            "password": cred_password
        }

    cache.append(entry)


# Write the JSON cache to disk
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(cache, f, indent=2)

print(f"✅ helpers_cache.json created at {OUTPUT_FILE} with {len(cache)} valid scripts.")
