from typing import Dict, Any

class POSAdapter:
    """Swap this mock with Merim POS write APIs."""

    def create_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: map to Merim payload (site_id, kiosk_id, cashier_id, etc.)
        # For now, return a fake ticket id
        total_items = sum(l.get("qty", 1) for l in order.get("lines", []))
        return {
            "ticket_id": "SIM-" + str(abs(hash(str(order))) % 10_000),
            "items": total_items,
        }
