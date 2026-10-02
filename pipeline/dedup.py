from db.database import is_seen, mark_seen


def dedup(lots: list[dict]) -> list[dict]:
    new_lots = []
    for lot in lots:
        lot_id = lot["lot_id"]
        source = lot["source"]
        if not is_seen(lot_id, source):
            mark_seen(lot_id, source)
            new_lots.append(lot)
    return new_lots
