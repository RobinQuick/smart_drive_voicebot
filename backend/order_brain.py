from __future__ import annotations
import re
from typing import Dict, Any, List, Tuple

class OrderBrain:
    def __init__(self, menu: Dict[str, Any]):
        self.menu = menu
        self.by_sku = {i["sku"]: i for i in menu["items"]}
        self.by_name = {i["name"].lower(): i for i in menu["items"]}
        # index par catégorie
        self.by_cat = {}
        for it in menu["items"]:
            self.by_cat.setdefault(it["category"], []).append(it)

        # synonymes FR simples -> SKU / valeurs d'options
        self.syn_items = {
            # Burgers
            "giant": "GIANT",
            "mega giant": "MEGA_GIANT",
            "méga giant": "MEGA_GIANT",
            "giant max": "GIANT_MAX",
            "long bacon": "LONG_BACON",
            "long chicken": "LONG_CHICKEN",
            "long fish": "LONG_FISH",
            "long spicy": "LONG_SPICY",
            "quick n toast": "QUICK_N_TOAST_BACON",
            "quick'n toast": "QUICK_N_TOAST_BACON",
            "supreme classiq": "SUPREME_CLASSIQ",
            "suprême classiq": "SUPREME_CLASSIQ",
            "supreme bacon": "SUPREME_BACON",
            "suprême bacon": "SUPREME_BACON",
            "junior giant": "JUNIOR_GIANT",
            "wrap giant veggie": "WRAP_GIANT_VEGGIE",
            # Sides / salades / finger food
            "frites": "FRIES_M",
            "frites medium": "FRIES_M",
            "frites large": "FRIES_L",
            "salade poulet": "SALAD_CHICKEN",
            "petite salade": "PETITE_SALADE",
            "chicken wings": "CHICKEN_WINGS_5",
            "chicken dips": "CHICKEN_DIPS_7",
            "bâtonnets de fromage": "CHEESE_STICKS_4",
            # Desserts
            "brownie": "BROWNIE",
            "sundae": "SUNDAE",
            # Boissons
            "eau": "WATER",
            "coca": "COKE_M",
            "coca cola": "COKE_M",
            "fanta": "FANTA",
            "café": "COFFEE",
            "cafe": "COFFEE",
            # Menus directs
            "giant menu": "GIANT_MENU",
            "long bacon menu": "LONG_BACON_MENU",
            "giant max menu": "GIANT_MAX_MENU",
            "méga giant menu": "MEGA_GIANT_MENU",
            "mega giant menu": "MEGA_GIANT_MENU",
            "long chicken menu": "LONG_CHICKEN_MENU",
            "long fish menu": "LONG_FISH_MENU",
            "long spicy menu": "LONG_SPICY_MENU",
            "menu kids": "KIDS_MENU",
        }

        self.syn_sizes = {
            "xl": "XL", "x l": "XL",
            "l": "L", "grande": "L", "grand": "L",
            "m": "M", "moyen": "M", "moyenne": "M",
            "petite": "M", "petit": "M"  # pour frites “petit” -> map sur M par défaut
        }

        self.syn_drinks = {
            "eau": "Eau",
            "coca": "Coca-Cola",
            "coca cola": "Coca-Cola",
            "coca zero": "Coca-Cola Sans Sucres",
            "zero": "Coca-Cola Sans Sucres",
            "sans sucre": "Coca-Cola Sans Sucres",
            "sans sucres": "Coca-Cola Sans Sucres",
            "fanta": "Fanta",
            "sprite": "Sprite"
        }

        self.no_onions_patterns = [
            r"sans oignon", r"sans oignons"
        ]

        # reverse alias index for quantity detection
        self.alias_by_sku: Dict[str, List[str]] = {}
        for alias, sku in self.syn_items.items():
            self.alias_by_sku.setdefault(sku, []).append(alias)

        self.number_words = {
            "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4,
            "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10
        }

    # -------------------- PUBLIC API --------------------

    def parse(self, utterance: str) -> Dict[str, Any]:
        """
        Retourne un brouillon de commande à partir d'une phrase FR.
        {
          "lines":[{"sku":..., "qty":1, "mods":{...}}, ...],
          "notes":[ "... upsell ...", "... guidance ..."]
        }
        """
        u = (utterance or "").lower()
        order: Dict[str, Any] = {"lines": [], "notes": []}

        # 1) détecter si la personne parle d'un MENU ou d'un BURGER seul
        mentions_menu = ("menu" in u) or ("menus" in u)

        # 2) extraire taille
        size = self._detect_size(u)  # "M/L/XL" ou None

        # 3) extraire boisson
        drink = self._detect_drink(u)  # "Eau"/"Coca-Cola"/...

        # 4) oignons ?
        no_onions = any(re.search(p, u) for p in self.no_onions_patterns)

        # 5) détecter items par synonymes
        found_skus = self._detect_items(u, prefer_menu=mentions_menu)

        # 6) Si rien de précis, guidance
        guide = self._recommend(u)
        if guide:
            order["notes"].append(guide)

        # 7) Construire les lignes
        for sku in found_skus:
            qty = self._guess_qty(u, sku) or 1
            line = {"sku": sku, "qty": qty, "mods": {}}
            cat = self.by_sku.get(sku, {}).get("category")

            if cat == "menus":
                # options par défaut depuis menu.json si disponibles
                opts = self.by_sku[sku].get("options", {})
                # taille
                if size and "size" in opts:
                    if size in opts["size"]["values"]:
                        line["mods"]["size"] = size
                    # frites grandes si XL
                    if size == "XL" and "fries" in opts:
                        if "L" in opts["fries"]["values"]:
                            line["mods"]["fries"] = "L"
                # boisson
                if drink and "drink" in opts:
                    if drink in opts["drink"]["values"]:
                        line["mods"]["drink"] = drink
                # oignons (si le menu supporte)
                if no_onions:
                    # on ne sait pas quel sandwich exact dans le menu => note
                    line["mods"]["onions"] = False

            elif cat in ("burgers",):
                if no_onions:
                    line["mods"]["onions"] = False

            order["lines"].append(line)

        # 8) si on a parlé frites/boisson seules
        if "frites" in u and not any(self.by_sku.get(l["sku"],{}).get("category")=="fries" for l in order["lines"]):
            order["lines"].append({"sku":"FRIES_M","qty":1,"mods":{}})
        if ("eau" in u or "coca" in u or "fanta" in u or "sprite" in u) and not any(self.by_sku.get(l["sku"],{}).get("category")=="cold_drinks" for l in order["lines"]):
            if drink == "Eau":
                order["lines"].append({"sku":"WATER","qty":1,"mods":{}})
            elif drink == "Coca-Cola":
                order["lines"].append({"sku":"COKE_M","qty":1,"mods":{}})
            elif drink == "Fanta":
                order["lines"].append({"sku":"FANTA","qty":1,"mods":{}})

        # 9) upsell systématique (1 seule suggestion)
        upsell = self._upsell(order)
        if upsell:
            order["notes"].append(upsell)

        return order

    def validate(self, order: Dict[str, Any]) -> List[str]:
        errs = []
        for l in order.get("lines", []):
            if l["sku"] not in self.by_sku:
                errs.append(f"SKU inconnu: {l['sku']}")
        return errs

    # -------------------- HELPERS --------------------

    def _detect_items(self, u: str, prefer_menu: bool) -> List[str]:
        skus: List[str] = []

        # 1) correspondances exactes "xxx menu" -> SKU _MENU
        for key, sku in self.syn_items.items():
            if key in u:
                # si on dit "menu" sans préciser -> favoriser la version MENU si elle existe
                if prefer_menu and not sku.endswith("_MENU"):
                    # tenter de trouver la version menu correspondante dans items
                    name = self.by_sku.get(sku, {}).get("name", "")
                    cand = (name + " Menu").lower()
                    if cand in self.by_name:
                        skus.append(self.by_name[cand]["sku"])
                        continue
                    # fallback: suffixer
                    if (sku + "_MENU") in self.by_sku:
                        skus.append(sku + "_MENU")
                        continue
                skus.append(sku)

        # 2) si aucun alias n’a matché mais on a dit juste “menu”
        if not skus and prefer_menu:
            # proposer top seller menu (Giant Menu si présent)
            if "GIANT_MENU" in self.by_sku:
                skus.append("GIANT_MENU")

        # dédoublonner en gardant l’ordre
        seen = set()
        skus2 = []
        for s in skus:
            if s not in seen:
                seen.add(s)
                skus2.append(s)
        return skus2

    def _detect_size(self, u: str) -> str | None:
        for k, v in self.syn_sizes.items():
            if re.search(rf"\b{k}\b", u):
                return v
        return None

    def _detect_drink(self, u: str) -> str | None:
        for k, v in self.syn_drinks.items():
            if re.search(rf"\b{k}\b", u):
                return v
        return None

    def _guess_qty(self, u: str, sku: str) -> int | None:
        """Try to infer quantity from phrases like '2 giant', 'deux menus giant', 'giant x2'."""
        u = u.lower()
        # 1) direct numeric patterns near aliases
        aliases = self.alias_by_sku.get(sku, [])
        for a in aliases:
            a_esc = re.escape(a)
            m = re.search(rf"\b(\d+)\s+{a_esc}\b", u)
            if m:
                try:
                    return max(1, int(m.group(1)))
                except:
                    pass
            m = re.search(rf"\b{a_esc}\s*(?:x|\*)\s*(\d+)\b", u)
            if m:
                try:
                    return max(1, int(m.group(1)))
                except:
                    pass
            # word numbers before alias
            for w, n in self.number_words.items():
                if re.search(rf"\b{w}\s+{a_esc}\b", u):
                    return n
        # 2) generic 'deux menus' when sku is a menu
        cat = self.by_sku.get(sku, {}).get("category")
        if cat == "menus":
            m = re.search(r"\b(\d+)\s+menus?\b", u)
            if m:
                try:
                    return max(1, int(m.group(1)))
                except:
                    pass
            for w, n in self.number_words.items():
                if re.search(rf"\b{w}\s+menus?\b", u):
                    return n
        return None

    # ---- Guidance “je ne sais pas / enfant / faim / budget / léger”
    def _recommend(self, u: str) -> str:
        u = u.lower()
        if any(k in u for k in ["je ne sais pas", "je sais pas", "j'hésite", "je hesite", "aucune idée"]):
            return ("Vous hésitez ? Nos tops ventes : *Giant Menu* et *Long Bacon Menu*. "
                    "Plutôt goût classique (Giant) ou bacon fumé (Long Bacon) ?")

        m_age = re.search(r"(\d{1,2})\s*(ans|an)", u)
        if m_age:
            age = int(m_age.group(1))
            if age < 6:
                return "Pour moins de 6 ans : *Menu Kids* avec petite boisson. On part là-dessus ?"
            if age <= 11:
                return "Pour 7–11 ans : *Menu Kids* ou sandwich simple + petite boisson. Je propose *Menu Kids* ?"

        if any(k in u for k in ["petit budget", "budget", "pas cher", "moins cher"]):
            return "Pour un petit budget : *Menu Value* ou *Junior Giant*. Ça vous conviendrait ?"

        if any(k in u for k in ["léger", "leger", "light", "salade"]):
            return "En plus léger : *Salade Poulet* avec de l’eau. Ça vous tente ?"

        if any(k in u for k in ["très faim", "tres faim", "j'ai faim", "j ai faim"]):
            return "Très faim ? *Menu XL* (boisson + frites grandes). Je vous le propose ?"

        return ""

    # ---- Upsell : 1 seule suggestion pertinente
    def _upsell(self, order: Dict[str, Any]) -> str:
        lines = order.get("lines", [])
        cats = [self.by_sku[l["sku"]]["category"] for l in lines if l["sku"] in self.by_sku]

        has_menu = any(c == "menus" for c in cats)
        has_dessert = any(self.by_sku[l["sku"]]["category"] == "desserts" for l in lines)
        has_side = any(self.by_sku[l["sku"]]["category"] in ("fries", "finger") for l in lines)

        if has_menu:
            if not has_dessert:
                return "Un dessert pour compléter ? *Sundae* ou *Brownie* ?"
            if not has_side:
                return "Souhaitez-vous ajouter un accompagnement ? *Frites L* ou *Chicken Dips* ?"
            # sinon proposer XL si pas déjà demandé
            for l in lines:
                if self.by_sku[l["sku"]]["category"] == "menus":
                    if l.get("mods", {}).get("size") != "XL":
                        return "Vous préférez **XL** pour la boisson et les frites ?"
            return ""
        # burger seul -> conversion en menu
        if any(c == "burgers" for c in cats):
            return "Souhaitez-vous le *MENU* avec boisson et frites pour compléter ?"
        # par défaut
        return "Je vous suggère un *Brownie* pour finir en douceur. Ça vous ferait plaisir ?"
