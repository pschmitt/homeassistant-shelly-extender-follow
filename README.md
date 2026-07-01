# Shelly Extender Follow

A Home Assistant integration that keeps a **roaming Shelly**'s `shelly` config
entry pointed at wherever the device is actually reachable.

Some Shelly devices roam between two networks:

- **Direct** — on the main network they answer on their own mDNS name at the
  normal HTTP port (usually `:80`).
- **Via an extender** — when they fall back behind another Shelly running the
  Gen2+ **WiFi range extender** function, they are only reachable through that
  Shelly's port-forward on a dynamically assigned port (`mport`).

When the device roams, Home Assistant's own zeroconf discovery rewrites the
config entry's **host** but leaves the **port** stale — so the entry ends up
pointing at, say, the direct IP on the *extender* port and goes into
`setup_retry`. This integration fixes that.

## How it works

Every poll it:

1. Probes the client Shelly directly (`WiFi.GetStatus` on its mDNS name +
   direct port). If it answers, that endpoint wins.
2. Otherwise finds it behind an extender via `WiFi.ListAPClients`, matching the
   client's MAC and reading the forwarded port (`mport`). If a specific
   extender host was configured, only that one is queried; otherwise **all
   other Shellies are scanned** to auto-detect whichever one is currently
   extending the device (the last match is remembered and tried first).
3. If the reachable endpoint differs from the client entry's current
   host+port, it updates the entry **and reloads it** (Shelly does not reload
   on a data change by itself). In direct mode it tolerates zeroconf's host
   churn and only intervenes when the port is wrong or the entry failed to
   load, so it never ping-pongs against discovery.

It exposes one `sensor` per configured device whose state is `direct`,
`extender`, or `unreachable`, with the resolved `host`/`port`/`ssid`/`ip`/
`mport`/`client_mac` and the `last_reconfigure` timestamp as attributes.

## Configuration

Add the integration from the UI. You can either:

- **Add a single Shelly** — pick the `shelly` config entry, its direct host
  (mDNS name, e.g. `shelly-master-bathroom-ventilation.lan`), and optionally an
  extender host. Leave the extender blank to auto-detect it.
- **Discover and add all Shellies** — multi-select every un-followed Shelly at
  once; each one's direct host defaults to its current address and the extender
  is auto-detected (or you can pin a shared one).

The **extender host is optional**: blank means "figure it out" — when the
device is not directly reachable, every other Shelly's AP-client table is
scanned to find which one is extending it. A Shelly that never roams simply
stays healed to its direct address.

Each followed Shelly gets, on its own device page, a **Reachability** sensor
(`direct` / `extender` / `unreachable`) and an **Auto-follow** switch. Per-entry
options: poll interval (default 30 s) and direct port (default 80).
