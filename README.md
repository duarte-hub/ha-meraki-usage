# Meraki Data Usage for Home Assistant

Shows today's internet usage from a Cisco Meraki MX as a Sankey diagram, flowing from **internet line → home → device → app**, with a per-device table and a 30-day history strip.

## What it does

The `meraki_usage` integration polls the Meraki Dashboard API every 10 minutes (you can change this) and counts usage since local midnight:

| Data | Endpoint |
|---|---|
| Per-uplink usage (WAN 1 / WAN 2 / cellular) | `GET /organizations/{org}/appliance/uplinks/usage/byNetwork` |
| Per-client usage | `GET /networks/{net}/clients` |
| Per-client application usage (top N devices) | `GET /networks/{net}/clients/applicationUsage` |
| Network-wide application usage | `GET /organizations/{org}/summary/top/applications/byUsage` (falls back to `/networks/{net}/traffic`) |

It creates:

- `sensor.meraki_data_usage_internet_usage_today`: GB since midnight (`total_increasing`, so it keeps long-term daily statistics). The full breakdown is in its attributes, and those attributes are left out of the recorder.
- `sensor.meraki_data_usage_clients_with_traffic_today`

The `apps_missing` attribute lists any top devices that Meraki returned no application data for. Their traffic is split by the network-wide app mix, after removing what's already attributed to other devices. In the card these flows are drawn fainter, marked `~` in the table and labelled *estimated* in tooltips.

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
The integration serves and loads the card for you, so there's no resource to add, and HACS updates also update the card. Use it on any dashboard:

```yaml
type: custom:meraki-usage-card
entity: sensor.meraki_data_usage_internet_usage_today
title: Data usage today   # optional
max_apps: 9               # optional, app nodes before "Other apps"
height: 460               # optional, sankey height
days: 30                  # optional, history strip length
```

Panel view recommended. Hover over a line, device or app to highlight its flows and see its share of today's usage. On touch screens, tap to pin and tap again to clear.

## Live flows (optional, via ntopng)

Click a device in the Sankey to open a panel with its active flows: peer, service, app, rate and bytes, refreshed every 3 seconds. The Meraki API has no live traffic endpoint, so this uses NetFlow from the MX:

1. Run **ntopng** (Community is fine) with **[netflow2ng](https://github.com/synfinatic/netflow2ng)** as a free NetFlow v9 collector. nProbe also works but needs a licence. Example with host networking:
   ```sh
   docker run -d --name ntopng-redis --net host redis:alpine redis-server --port 6390 --bind 127.0.0.1
   docker run -d --name netflow2ng --net host synfinatic/netflow2ng -a 0.0.0.0:2055 -m 127.0.0.1:8091 -z tcp://127.0.0.1:5556
   docker run -d --name ntopng --net host -v /path/ntopng:/var/lib/ntopng ntop/ntopng:latest \
     --community -r 127.0.0.1:6390@0 -i tcp://127.0.0.1:5556 -w 3001 -m 192.168.0.0/16 --zmq-disable-encryption
   ```
2. In Meraki go to Network-wide → General → **Reporting** and set **NetFlow traffic reporting** to *enabled*, with the collector at `<host>:2055`.
3. In ntopng (`http://<host>:3001`), change the default `admin` password. Optionally create an API token under the user's settings.
4. In Home Assistant open **Meraki Data Usage → Configure**, then set the ntopng URL and either the username and password or the API token.

NetFlow from the MX arrives in flow-export intervals, so "live" means seconds to about a minute behind.

## Requirements
- A Meraki network with an MX appliance.
- **Traffic Analysis** enabled (Network-wide → General). Set it to *Detailed* for the best app names.
- Name your clients in the Meraki dashboard so devices are readable.

## Limitations
- Meraki usage data runs a few minutes behind.
- The history strip starts filling from the day you install the integration, and it shows daily totals only. The per-day breakdown isn't stored.
