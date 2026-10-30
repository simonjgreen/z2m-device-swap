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


def identify_service(entities, light_effects):
    """Use an exposed native action; generic MQTT flash is not guaranteed."""
    for entity in entities:
        if (entity['domain'] == 'button' and '_identify_' in entity['unique_id']
                and not entity.get('disabled_by')):
            return 'button', 'press', {'entity_id': entity['entity_id']}
    for entity in entities:
        if (entity['domain'] == 'light' and not entity.get('disabled_by')
                and 'blink' in light_effects.get(entity['entity_id'], [])):
            return 'light', 'turn_on', {'entity_id': entity['entity_id'], 'effect': 'blink'}
    raise ValueError('This bulb has no enabled Identify button or supported blink effect')
