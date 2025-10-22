# backend/policy.py
import os, re
from typing import Dict, Any, Tuple, Set, List

# --- limits (config .env) ---
MAX_QTY_PER_LINE = int(os.getenv("MAX_QTY_PER_LINE", "10"))
MAX_TOTAL_ITEMS  = int(os.getenv("MAX_TOTAL_ITEMS", "30"))

PROFANITY_FR = [
    "connard", "conne", "fdp", "nique ta", "salope", "va te faire", "merde",
    "pute", "enculé", "encule", "ta gueule", "gros con"
]

def build_menu_index(menu: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, List[str]]]:
    by_sku: Dict[str, Any] = {}
    required: Dict[str, List[str]] = {}
    for it in menu.get("items", []):
        sku = it.get("sku")
        if not sku: continue
        by_sku[sku] = it
        opts = it.get("options", {})
        req = []
        for k in ["size", "drink", "fries"]:
            if k in opts:
                req.append(k)
        if req:
            required[sku] = req
    return by_sku, required

def analyze_utterance_flags(utterance: str, max_qty_per_line: int) -> List[str]:
    notes: List[str] = []
    u = (utterance or "").lower()
    if any(b in u for b in PROFANITY_FR):
        notes.append("ABUSE_DETECTED")
    for m in re.finditer(r"\b(\d{3,})\b", u):
        try:
            n = int(m.group(1))
            if n > max_qty_per_line:
                notes.append(f"QTY_ABSURD_{n}")
                break
        except:
            pass
    return notes

def _total_items(order: Dict[str, Any]) -> int:
    return sum(int(max(0, l.get("qty", 1))) for l in order.get("lines", []))

def validate_order(
    order: Dict[str, Any],
    by_sku: Dict[str, Any],
    required_options: Dict[str, List[str]],
    oos: Set[str],
    max_qty_per_line: int,
    max_total_items: int
) -> List[str]:
    errors: List[str] = []
    lines = order.get("lines", [])
    for l in lines:
        sku = (l.get("sku") or "").upper()
        qty = int(l.get("qty", 1))
        if sku not in by_sku:
            errors.append(f"POLICY_SKU_UNKNOWN:{sku}")
            continue
        if qty <= 0:
            errors.append(f"POLICY_QTY_INVALID:{sku}")
        if qty > max_qty_per_line:
            errors.append(f"POLICY_QTY_TOO_HIGH:{sku}:{qty} (max {max_qty_per_line})")
        if sku in oos:
            errors.append(f"POLICY_OOS:{sku}")
        req = required_options.get(sku, [])
        mods = l.get("mods", {})
        for opt in req:
            if opt not in mods or str(mods.get(opt, "")).strip() == "":
                errors.append(f"POLICY_CLARIFY_OPTION:{sku}.{opt}")
    total = _total_items(order)
    if total > max_total_items:
        errors.append(f"POLICY_TOTAL_TOO_HIGH:{total} (max {max_total_items})")
    return errors
