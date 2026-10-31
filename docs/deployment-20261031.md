# Owner's Home Assistant deployment, 2026-10-31

This records the explicitly authorized installation into the owner's running
Home Assistant. It is not a portable router installation script. Future agents
must read `AGENTS.md`, audit the live network and review the current rules before
changing anything. Do not change or bypass OpenClash.

## Installed configuration

Version 0.1.0 was copied to `/config/custom_components/airproce_proxy` in the
existing `homeassistant` container on `192.168.1.70`. HA 2026.10.4 was restarted
once. Two entries were created through HA's normal setup UI, with five entities
each. Both listeners bind only `192.168.1.70` and accept the router's translated
source address, `192.168.1.1`.

| Model | Purifier IP | HA listener | Fan entity |
| --- | --- | --- | --- |
| AI-370 | 192.168.1.158 | 192.168.1.70:19001 | `fan.airproce_370` |
| AI-600 | 192.168.1.112 | 192.168.1.70:19002 | `fan.airproce_600` |

The source package SHA256 was
`fb850ad672cecab9021dc583beea1617cff15dd602e80ed1e64e65846466557a`.
No cloud account, cloud API token, router credentials or automatic router
management are part of the integration.

## Deployment validation and final audit

- All 15 installed integration files matched the reviewed repository source.
  Compilation passed in the running HA container. No AirProce runtime error
  appeared in the HA log; the standard custom-integration warning was expected.
- Both devices supplied fresh temperature, humidity, PM2.5, VOC and fan state.
  Each passed HA manual speed 2 (33%) and was returned to Smart/Auto.
- Each completed a real cloud registration after its initial retry/reconnect
  cycle. On the AI-370, passive observation also verified registration,
  installed-version and status replies arriving from the real upstream and
  reaching the device. The bounded capture ended and left no router process.
- After installation, the owner separately confirmed live official-app status
  and manual-speed controls, returning to Smart, on both AI-370 and AI-600.
- The rules were applied one purifier at a time. Exactly one existing
  purifier/cloud connection-tracking entry per purifier was deleted, using
  the narrowly scoped commands below, to establish the new translated path.
- The final live comparison found exactly two added chains and four added
  rules, with no pre-existing table, chain or rule removed or modified. Packet
  counters and kernel-assigned handles were excluded from that comparison.
  Policy-routing rules and routes were unchanged.
- Hashes of every pre-existing `/etc/config` file, nftables include and the
  OpenClash firewall include were unchanged. Only
  `/etc/nftables.d/90-airproce-proxy.nft` was added to those persistent files.
  The include matched the reviewed file exactly, and `fw4 check` passed.

There was no router reboot, network/firewall reload, DNS change, packet-mark
override, OpenClash bypass or service change during this deployment. No
automatic router helper, scheduled job or persistent router process was added.
The only intended persistent router changes are the four NAT rules below and
their dedicated include file. Existing HA integrations and other containers
were not reconfigured.

## Reviewed router rules

The verified cloud destination was `116.62.124.233:8283`. Only connections
originating from the two purifier IPs are redirected. HA's own upstream traffic
uses existing router policy and cannot match these rules.

The four rules belong to two dedicated chains inside `inet fw4`. The persistent
include is `/etc/nftables.d/90-airproce-proxy.nft`, which firewall4 includes
inside that table:

```nft
chain airproce_proxy_prerouting {
    type nat hook prerouting priority -101; policy accept;
    ip saddr 192.168.1.158 ip daddr 116.62.124.233 tcp dport 8283 counter dnat ip to 192.168.1.70:19001 comment "AirProce AI-370 to HA"
    ip saddr 192.168.1.112 ip daddr 116.62.124.233 tcp dport 8283 counter dnat ip to 192.168.1.70:19002 comment "AirProce AI-600 to HA"
}
chain airproce_proxy_postrouting {
    type nat hook postrouting priority 99; policy accept;
    ip saddr 192.168.1.158 ip daddr 192.168.1.70 tcp dport 19001 ct status dnat ct original ip daddr 116.62.124.233 ct original proto-dst 8283 counter snat ip to 192.168.1.1 comment "AirProce AI-370 return path"
    ip saddr 192.168.1.112 ip daddr 192.168.1.70 tcp dport 19002 ct status dnat ct original ip daddr 116.62.124.233 ct original proto-dst 8283 counter snat ip to 192.168.1.1 comment "AirProce AI-600 return path"
}
```

The source NAT rules apply only to these already destination-translated flows,
checking their original cloud address and port. They keep replies on the router
return path because the purifiers and HA share the same subnet.

## Scoped rollback for a future authorized maintenance action

Inspect the file and both named chains first, confirming they still contain only
these task-owned rules. Remove only `/etc/nftables.d/90-airproce-proxy.nft` to
remove persistence. For the live rules, submit this batch without reloading the
whole firewall:

```nft
flush chain inet fw4 airproce_proxy_prerouting
flush chain inet fw4 airproce_proxy_postrouting
delete chain inet fw4 airproce_proxy_prerouting
delete chain inet fw4 airproce_proxy_postrouting
```

If existing connections retain old NAT state, delete only the corresponding
purifier/cloud TCP connection-tracking entries:

```sh
conntrack -D -p tcp -s 192.168.1.158 -d 116.62.124.233 --dport 8283
conntrack -D -p tcp -s 192.168.1.112 -d 116.62.124.233 --dport 8283
```

Never flush the whole ruleset or connection table. Do not restart networking,
the router, OpenClash or the whole firewall. Verify both original cloud paths
recover afterward. These addresses must be rechecked at the time of rollback.

While redirection is active, HA must run for the app's relay path to work. The
router has no automatic failover. A future cloud IP or LAN address change needs
a fresh manual audit; this integration does not update router rules.
