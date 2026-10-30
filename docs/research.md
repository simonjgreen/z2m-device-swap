# Replacing a Zigbee2MQTT bulb

Zigbee2MQTT documents removal, pairing, device rename and group membership as separate operations. Its rename request can ask Home Assistant to update entity IDs with `homeassistant_rename: true`. These APIs supply the steps for an assisted replacement workflow; the documented API does not expose a single atomic device substitution operation.

Home Assistant's entity ID and internal device identity are separate. Restoring the same entity ID allows entity-based references to continue using that name. It does not preserve an internal device ID or automatically repair device-based automation references. This project's scope is the established manual procedure: restore exact entity IDs and rejoin the old Zigbee groups.

Related projects examined include nphil/z2m_ha (HA-native Zigbee2MQTT network management) and nordstad/zigporter-hacs (network topology and migration-related tooling). The inspected descriptions did not establish a complete faulty-bulb substitution wizard. This is a bounded prior-art search, not proof that no other implementation exists.

The integration uses HA's configured MQTT connection and authenticated frontend session. It snapshots the old entity IDs and group endpoints, requires an explicitly selected and interviewed replacement, checks feature/entity compatibility before removal, then journals each operation. Completion requires checking the actual replacement and normal room controls.

## Primary sources

- [Zigbee2MQTT MQTT API](https://www.zigbee2mqtt.io/guide/usage/mqtt_topics_and_messages.html)
- [Zigbee2MQTT Home Assistant integration](https://www.zigbee2mqtt.io/guide/usage/integrations/home_assistant.html)
- [Zigbee2MQTT groups](https://www.zigbee2mqtt.io/guide/usage/groups.html)
- [Home Assistant entity registry](https://developers.home-assistant.io/docs/entity_registry_index/)
- [Home Assistant device registry](https://developers.home-assistant.io/docs/device_registry_index/)
- [Home Assistant device triggers and replacement considerations](https://www.home-assistant.io/triggers/device/)
- [HA architecture discussion about replacement](https://github.com/home-assistant/architecture/discussions/1088)
- [nphil/z2m_ha](https://github.com/nphil/z2m_ha)
- [nordstad/zigporter-hacs](https://github.com/nordstad/zigporter-hacs)
