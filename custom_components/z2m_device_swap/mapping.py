"""Match Z2M discovery entities by their feature suffix, never by display name."""


def entity_mapping(old_entities, new_entities, old_ieee, new_ieee):
    indexed = {(e['domain'], e['unique_id']): e for e in new_entities}
    result = []
    for entity in old_entities:
        prefix = old_ieee + '_'
        if not entity['unique_id'].startswith(prefix):
            raise ValueError(f"Unrecognized discovery identity for {entity['entity_id']}")
        unique_id = new_ieee + entity['unique_id'][len(old_ieee):]
        replacement = indexed.get((entity['domain'], unique_id))
        if replacement is None:
            raise ValueError(f"Missing replacement entity for {entity['entity_id']}")
        result.append((replacement['entity_id'], entity['entity_id']))
    return result
