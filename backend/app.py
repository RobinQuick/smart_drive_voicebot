# backend/app.py
import os, json, time, random
from typing import Dict, Any, Set, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import requests

from order_brain import OrderBrain
from pos_adapter import POSAdapter
from policy import (
    MAX_QTY_PER_LINE, MAX_TOTAL_ITEMS,
    build_menu_index, analyze_utterance_flags, validate_order
)

# --- env & config ---
load_dotenv()
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL   = os.getenv("OPENAI_BASE_URL", "https://api.openai.com")
REALTIME_MODEL    = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview")
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.65"))  # min 0.6 côté Realtime
TEMP_JITTER       = float(os.getenv("MODEL_TEMPERATURE_JITTER", "0.05"))

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing")

# --- guardrails texte ---
AGENT_INSTRUCTIONS = """
Tu es l’assistant DRIVE de QUICK (France). Français uniquement.

LIMITES & SOURCES
- Tu NE PROPOSES QUE des produits Quick présents dans le menu fourni par le serveur (menu.json).
- Catégories autorisées : Menus, Menus Enfants, Burgers, Salades, Frites, Finger food,
  Desserts, Boissons froides, Boissons chaudes.
- Interdits : autres cuisines/marques (sushis, pizzas, kebab…), alcool. Si demandé : refuse poliment
  et propose une alternative Quick proche (ex. poisson → Long Fish). N’invente JAMAIS de produit.

BOISSONS AUTORISÉES (exemples) :
{DRINKS_TEXT}

RÈGLES BOISSON :
- Toujours proposer 3 choix concrets par défaut (ex. Coca-Cola, Fanta, Eau).
- Si le client dit « sans sucre », l'interpréter comme « Coca-Cola Sans Sucres » (sauf autre marque citée).
- Ne JAMAIS valider un menu sans boisson explicitement choisie.

COMPRÉHENSION & CLARIFICATION
- Si un nom est inconnu : « Je n’ai pas cet article. Voulez-vous plutôt <ALTERNATIVE_QUICK> ? »
- Si ambigu (taille boisson/frites, Zéro/Sans sucres, options oignons/sauce) → pose UNE question fermée.
- Si bruits/inaudible : « Je vous entends mal, après le bip, pouvez-vous répéter ? »

UPSÉLL
- 1 seul upsell pertinent par tour (XL boisson/frites, dessert/café, convertir burger → MENU). Jamais insistant.

ENFANTS / ORIENTATION
- <6 ans → Menu Kids ; 7–11 ans → Menu Kids ou sandwich simple + petite boisson ;
  léger → Salade + eau ; très faim → Menu XL ; budget serré → Junior Giant/Value.

FLUX DE CONVERSATION
- Pas de barge-in : ne parle pas en même temps que le client.
- Après « c’est tout » : RÉCAPITULER (produits, tailles, boissons, options, quantités),
  puis : « Je transmets la commande en cuisine. »

CONFORMITÉ & ABUS
- Pas d’infos personnelles. Allergènes : « La carte allergènes est disponible au comptoir. »
- Quantités : maximum 10 par article, 30 au total. Si dépassé : refuse poliment et propose une quantité raisonnable.
- Langage injurieux : rappeler une fois la courtoisie ; si répétition, passer à un équipier.

AUTO-CORRECTION
- Si tu proposes un article non-Quick ou hors menu : excuse-toi et corrige immédiatement en ne proposant que Quick.
""".strip()

# --- menu / brain / pos ---
MENU_PATH = os.path.join(os.path.dirname(__file__), "menu.json")
with open(MENU_PATH, "r", encoding="utf-8") as f:
    menu = json.load(f)

def list_drinks(menu: Dict[str, Any]) -> List[str]:
    drinks = []
    for it in menu.get("items", []):
        if it.get("category") in ("cold_drinks", "hot_drinks"):
            name = it.get("name")
            if name:
                drinks.append(name)
    return sorted(set(drinks))[:30]

DRINKS      = list_drinks(menu)
DRINKS_TEXT = " ; ".join(DRINKS)

brain = OrderBrain(menu)
pos   = POSAdapter()

BY_SKU, REQUIRED_OPTIONS = build_menu_index(menu)
OOS: Set[str] = set()

# --- FastAPI app ---
app = FastAPI(
    title="Smart Drive Voice Bot API",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

origins = [
    o.strip()
    for o in os.getenv("ALLOW_ORIGINS", "http://127.0.0.1:5500,http://localhost:5500").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
print("CORS allow_origins =", origins)

# --- models ---
class EphemeralToken(BaseModel):
    client_secret: str
    expires_at: int

class NLUIn(BaseModel):
    utterance: str

class OrderIn(BaseModel):
    order: dict

# --- health ---
@app.get("/ping")
def ping():
    return {"ok": True, "model": REALTIME_MODEL}

# --- realtime token ---
@app.get("/token", response_model=EphemeralToken)
def mint_ephemeral_token():
    url = f"{OPENAI_BASE_URL}/v1/realtime/sessions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
        "OpenAI-Beta": "realtime=v1",
    }
    temp = max(0.6, round(MODEL_TEMPERATURE + random.uniform(-TEMP_JITTER, TEMP_JITTER), 2))
    instr = (
        AGENT_INSTRUCTIONS.replace("{DRINKS_TEXT}", DRINKS_TEXT)
        + "\n\nPRONONCIATION\n"
        + "- Parle en français.\n"
        + "- Prononce ces termes avec un accent anglais naturel (sans l'écrire différemment) : Giant, Long Bacon, Quick n Toast, Sprite, Fanta.\n"
        + "- Ne pas afficher d'IPA ni de parenthèses dans tes phrases.\n"
        + "\nEFFICACITE TOKENS\n"
        + "- Réponses très courtes et concrètes. Une seule question fermée à la fois.\n"
        + "- Évite les répétitions et les formules de politesse longues.\n"
        + "- Ne lis pas la carte complète : propose 2–3 choix max.\n"
        + "\nFIN DE COMMANDE\n"
        + "- Quand ça semble fini, récapitule en 1 phrase et demande confirmation: ‘C’est tout pour vous ?’.\n"
        + "- Après confirmation, dis exactement: ‘votre commande est en cuisine, vous pouvez avancer à la prochaine cabine pour régler. bon appétit !’.\n"
    ).strip()
    payload = {
        "model": REALTIME_MODEL,
        "instructions": instr,
        "voice": os.getenv("VOICE_NAME", "verse"),
        "temperature": temp,
        # pas de max_response_output_tokens → évite les phrases tronquées
    }
    r = requests.post(url, headers=headers, json=payload, timeout=20)
    if r.status_code >= 300:
        raise HTTPException(r.status_code, r.text)
    data = r.json()
    cs = data.get("client_secret", {}) or {}
    value = cs.get("value")
    expires = cs.get("expires_at", int(time.time()) + 60)
    if not value:
        raise HTTPException(502, f"Unexpected token response: {data}")
    return {"client_secret": value, "expires_at": expires}

# --- OOS ---
@app.post("/oos/{sku}")
def set_oos(sku: str):
    OOS.add(sku.upper())
    return {"ok": True, "oos": sorted(list(OOS))}

@app.delete("/oos/{sku}")
def clear_oos(sku: str):
    OOS.discard(sku.upper())
    return {"ok": True, "oos": sorted(list(OOS))}

# --- NLU & POS ---
@app.post("/nlu")
def nlu(in_: NLUIn):
    order = brain.parse(in_.utterance)
    policy_notes = analyze_utterance_flags(in_.utterance, MAX_QTY_PER_LINE)
    if isinstance(order, dict):
        order.setdefault("notes", [])
        order["notes"].extend([n for n in policy_notes if n not in order["notes"]])
    hard_errors = validate_order(order, BY_SKU, REQUIRED_OPTIONS, OOS, MAX_QTY_PER_LINE, MAX_TOTAL_ITEMS)
    try:
        soft_errors = brain.validate(order)
    except Exception:
        soft_errors = []
    errors = list(dict.fromkeys(hard_errors + soft_errors))
    return {"order": order, "errors": errors}

@app.post("/pos/order")
def push_order(in_: OrderIn):
    errors = validate_order(in_.order, BY_SKU, REQUIRED_OPTIONS, OOS, MAX_QTY_PER_LINE, MAX_TOTAL_ITEMS)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    return pos.create_order(in_.order)
