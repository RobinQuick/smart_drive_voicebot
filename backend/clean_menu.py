import json, re, unicodedata, sys
from pathlib import Path
from copy import deepcopy

print(">> clean_menu.py starting...", flush=True)

ROOT = Path(__file__).parent
MENU_PATH = ROOT / "menu.json"
OUT_PATH  = ROOT / "menu.cleaned.json"

print(f">> Working dir: {ROOT}", flush=True)
print(f">> Input:  {MENU_PATH.exists()}  -> {MENU_PATH}", flush=True)

GENERIC_NAMES = {
    "menus", "salades", "frites", "menus enfants", "menus chez quick",
    "salades chez quick", "frites chez quick", "menus enfants chez quick"
}
VALID_CATS = {
    "menus","kids","burgers","salads","fries","finger","desserts","cold_drinks","hot_drinks"
}
FORCE_MENU_SUFFIX = (" menu",)
DEFAULT_OPTIONS_BY_CAT = {
    "menus": {
        "size":{"type":"enum","values":["M","L","XL"],"default":"M"},
        "drink":{"type":"enum","values":["Coca-Cola","Fanta","Sprite","Eau"],"default":"Coca-Cola"},
        "fries":{"type":"enum","values":["M","L"],"default":"M"}
    },
    "kids": {
        "toy":{"type":"bool","default":True},
        "drink":{"type":"enum","values":["Eau","Jus d'orange","Coca-Cola"],"default":"Eau"},
        "side":{"type":"enum","values":["Frites","Petite salade"],"default":"Frites"}
    }
}

def skuify(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in nfkd if not unicodedata.combining(c))
    s = s.replace("'", "").replace("’","")
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_")
    s = re.sub(r"_+", "_", s)
    return s.upper()

def is_generic(name: str) -> bool:
    return name.lower().strip() in GENERIC_NAMES

def main():
    if not MENU_PATH.exists():
        print("!! menu.json introuvable à cet emplacement", file=sys.stderr, flush=True)
        sys.exit(2)
    try:
        raw = MENU_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as e:
        print(f"!! Impossible de lire/decoder menu.json : {e}", file=sys.stderr, flush=True)
        sys.exit(3)

    items = data.get("items", [])
    print(f">> Loaded items: {len(items)}", flush=True)

    cleaned = []
    seen = set()

    for it in items:
        name = (it.get("name") or "").strip()
        cat  = (it.get("category") or "").strip()
        if not name or cat not in VALID_CATS:
            continue
        if is_generic(name):
            continue

        name_l = name.lower()
        forced_menu = any(name_l.endswith(suf) for suf in FORCE_MENU_SUFFIX)
        if forced_menu:
            cat = "menus"

        obj = {
            "name": name,
            "category": cat,
            "sku": it.get("sku") or skuify(name)
        }
        if cat == "menus" and not name_l.endswith(" menu"):
            if "menu" not in name_l:
                obj["name"] = f"{name} Menu"

        if cat == "menus" and not obj["sku"].endswith("_MENU"):
            obj["sku"] = skuify(obj["name"]) if "menu" in obj["name"].lower() else (obj["sku"] + "_MENU")

        if cat in DEFAULT_OPTIONS_BY_CAT:
            obj["options"] = deepcopy(DEFAULT_OPTIONS_BY_CAT[cat])

        key = (obj["name"].lower(), cat)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(obj)

    # Dedup by SKU
    final = []
    seen_sku = set()
    for it in cleaned:
        sku = it["sku"]
        if sku in seen_sku:
            if it["category"] == "menus" and not sku.endswith("_MENU"):
                sku = sku + "_MENU"
                if sku in seen_sku:
                    continue
                it["sku"] = sku
            else:
                continue
        seen_sku.add(sku)
        final.append(it)

    out = {
        "categories": [c for c in data.get("categories", []) if c.get("id") in VALID_CATS],
        "items": final
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f">> Saved: {OUT_PATH}  (items: {len(final)})", flush=True)

if __name__ == "__main__":
    main()
