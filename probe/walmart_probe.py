"""Dump the Apify Home Depot actor's input schema and pricing."""
import json, os, urllib.request
H = {"Authorization": "Bearer " + os.environ["APIFY_TOKEN"].strip()}
def get(u): return json.loads(urllib.request.urlopen(urllib.request.Request("https://api.apify.com/v2" + u, headers=H), timeout=60).read())["data"]
act = get("/acts/s_actors~home-depot-scraper")
print("PRICING", json.dumps(act.get("pricingInfos") or act.get("pricingInfo"))[:1500])
b = get("/acts/s_actors~home-depot-scraper/builds/default")
sch = b.get("inputSchema") or (b.get("actorDefinition") or {}).get("input")
if isinstance(sch, str): sch = json.loads(sch)
for k, v in (sch or {}).get("properties", {}).items():
    print("FIELD", k, "|", v.get("type"), "| default", json.dumps(v.get("default"))[:80], "| enum", v.get("enum"), "| min", v.get("minimum"), "max", v.get("maximum"), "|", (v.get("description") or "")[:260].replace("\n", " "))
print("LIMITS", json.dumps(get("/users/me/limits"))[:600])
