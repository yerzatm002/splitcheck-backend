
def split_cents_evenly(total_cents: int, participant_ids: list[int]) -> list[tuple[int, int]]:
    if not participant_ids:
        raise ValueError("At least one participant is required")

    ids = sorted(set(participant_ids))
    base = total_cents // len(ids)
    remainder = total_cents % len(ids)

    result: list[tuple[int, int]] = []
    for index, participant_id in enumerate(ids):
        amount = base + (1 if index < remainder else 0)
        result.append((participant_id, amount))
    return result
