# Meraki Data Usage for Home Assistant

Shows today's internet usage from a Cisco Meraki MX as a Sankey diagram, flowing from **internet line → home → device → app**, with a per-device table and a 30-day history strip.

## What it does

The `meraki_usage` integration polls the Meraki Dashboard API every 10 minutes (you can change this) and counts usage since local midnight:

| Data | Endpoint |
|---|---|
| Per-uplink usage (WAN 1 / WAN 2 / cellular) | `GET /organizations/{org}/appliance/uplinks/usage/byNetwork` |
| Per-client usage | `GET /networks/{net}/clients` |
| Per-client application usage (top N devices) | `GET /networks/{net}/clients/applicationUsage` |

It creates:

- `sensor.meraki_data_usage_internet_usage_today`: GB since midnight (`total_increasing`, so it keeps long-term daily statistics). The full breakdown is in its attributes, and those attributes are left out of the recorder.
- `sensor.meraki_data_usage_clients_with_traffic_today`

"Not broken down" is traffic the MX counted on its uplinks but couldn't attribute to a client.

## Install

### HACS
1. Open HACS → ⋮ → **Custom repositories** → add `duarte-hub/ha-meraki-usage`, category **Integration**.
2. Download **Meraki Data Usage** and restart Home Assistant.
3. Go to Settings → Devices & Services → **Add Integration** → *Meraki Data Usage*.
   - Leave the API key blank to reuse the key from an existing `meraki_ha` or core `meraki` integration.
   - The integration picks the network that has an MX, and asks you to choose if there's more than one.

Options: poll interval (5–60 min) and how many devices get the per-app breakdown (3–20).

### Card
Add `card/meraki-usage-card.js` as a dashboard resource of type `module`. For example, copy it to `/config/www/` and register `/local/meraki-usage-card.js`. Then use the card:

```yaml
type: custom:meraki-usage-card
entity: sensor.meraki_data_usage_internet_usage_today
title: Data usage today   # optional
max_apps: 9               # optional, app nodes before "Other apps"
height: 460               # optional, sankey height
days: 30                  # optional, history strip length
```

Panel view recommended.

## Requirements
- A Meraki network with an MX appliance.
- **Traffic Analysis** enabled (Network-wide → General). Set it to *Detailed* for the best app names.
- Name your clients in the Meraki dashboard so devices are readable.

## Limitations
- Meraki usage data runs a few minutes behind.
- The history strip starts filling from the day you install the integration, and it shows daily totals only. The per-day breakdown isn't stored.
