import json, re, sys, time
from pathlib import Path
import requests
from bs4 import BeautifulSoup

CATS = [
    ("menus","https://www.quick.fr/produits/menu"),
    ("kids","https://www.quick.fr/produits/menus-enfants"),
    ("burgers","https://www.quick.fr/produits/burgers"),
    ("salads","https://www.quick.fr/produits/salades"),
    ("fries","https://www.quick.fr/produits/frites"),
    ("finger","https://www.quick.fr/produits/finger-food"),
    ("desserts","https://www.quick.fr/produits/desserts"),
    ("cold_drinks","https://www.quick.fr/produits/boissons-froides"),
    ("hot_drinks","https://www.quick.fr/produits/boissons-chaudes"),
]

def slug_to_sku(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return re.sub(r"_+", "_", s).upper()

def extract_names(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    # Les cartes produits affichent des titres en clair (SSR/CSR mix).
    # On récupère tous les noeuds texte “propres” dans la grille.
    names = set()
    for el in soup.find_all(text=True):
        txt = (el or "").strip()
        # heuristique: lignes courtes, sans “Mon compte”, etc.
        if 2 <= len(txt) <= 60:
            if not any(bad in txt for bad in ["Mon compte","Nos produits","Fidélité","Pour votre santé"]):
                # On détecte quelques patterns Quick typiques (Giant, Long, Suprême, etc.)
                if re.search(r"(Giant|Long|Supr[eè]me|ClassiQ|Quick'N Toast|Menu|Frites|Nuggets|Sundae|Brownie|Coca|Fanta|Salade|Poulet|Fish|Wings|Dips)", txt, re.I):
                    names.add(txt)
    return sorted(names)

def main():
    root = Path(__file__).parent
    menu_path = root / "menu.json"
    if menu_path.exists():
        data = json.loads(menu_path.read_text(encoding="utf-8"))
    else:
        data = {"categories": [], "items": []}

    # index existants
    cat_ids = {c["id"] for c in data.get("categories", [])}
    existing = { (it["name"].lower(), it["category"]) for it in data.get("items", []) }

    # ensure categories
    for cid, url in CATS:
        if cid not in cat_ids:
            data.setdefault("categories", []).append({"id": cid, "name": cid, "source": url})

    # fetch pages
    for cid, url in CATS:
        print(f"Fetching {cid} → {url}")
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        names = extract_names(r.text)
        for name in names:
            key = (name.lower(), cid)
            if key in existing:
                continue
            sku = slug_to_sku(name)
            data["items"].append({"sku": sku, "name": name, "category": cid})
        time.sleep(0.7)  # politesse

    # sauvegarde
    menu_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {menu_path}")

if __name__ == "__main__":
    try:
        import bs4 # check BeautifulSoup installed
    except Exception:
        print("Install: pip install beautifulsoup4", file=sys.stderr)
        sys.exit(1)
    main()
