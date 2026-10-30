# Manual router setup and rollback

Read `AGENTS.md` first. Deployment is a separate, explicit user action. The
integration does not connect to or configure the router. These are review
instructions for a future agent, not an installation script.

**Do not change or bypass OpenClash.** Do not change its configuration, packet
marks, policy routes, chains, exclusions, or service state. Only the essential
purifier-specific destination NAT and return-path source NAT are authorized.
If the existing upstream route prevents forwarding, report the evidence and
ask the owner rather than changing other networking policy.

## Inspect before applying anything

- Confirm the purifier's reserved IPv4 address and MAC, HA's reachable address,
  and the current destination of the purifier's connection. The observed
  endpoint was `tcpaph.airproce.com`, TCP 8283; never assume its IP stays fixed.
- Verify the chosen HA listening port is unused, then configure and start the
  integration. Each purifier needs a different port when router SNAT hides the
  source. Existing HA ports are unrelated to these new listeners.
- Inspect current firewall hooks, NAT priorities, LAN interfaces, routing,
  flow offload and existing proxy policy read-only. Do not reuse an unreviewed
  rule from another router. Save a read-only before/after snapshot for review.
- Verify the exact table/chain names are not already owned by another task.
  Review a timed rollback before the first test. Validate nft syntax before
  applying it. Change one purifier first.

## Essential packet matching

The destination-NAT rule must match **all three** of:

| Match | Destination after translation |
| --- | --- |
| Selected purifier source IPv4 + verified cloud destination IPv4 + TCP destination port 8283 | HA's LAN IPv4 + that purifier's dedicated listener port |

Never redirect all clients, all traffic on port 8283, or all AirProce domains.
Do not override DNS. HA's own upstream TCP connection must not match the rule;
the exact purifier source match provides that exclusion.

When the purifier and HA are on the same subnet, plain DNAT is insufficient:
HA otherwise replies directly to the purifier, bypassing the router that
performed NAT. A corresponding SNAT rule must match only the translated flow
from that purifier to that HA listener, ideally also checking the original
destination/port and DNAT connection status, and use the router's LAN address.
Configure the integration's **expected source address** to the router LAN IP.

Conceptually, for each purifier:

```text
Purifier → verified-cloud-IP:8283
    DNAT → HA-LAN-IP:dedicated-port
    SNAT → router-LAN-IP (only that translated flow)

HA → tcpaph.airproce.com:8283
    Existing normal routing; never redirect back to HA
```

On the tested network, temporary rules used a dedicated `ip` table with a
prerouting NAT hook at priority -101 and postrouting NAT hook at priority 99.
Those priorities are observations, not portable defaults. A future agent must
review their interaction with the current router without modifying OpenClash.

An established connection can retain old NAT state. If necessary, remove only
the connection-tracking entries for this purifier, this cloud IP and TCP 8283
after the listener and rules are ready. This forces a fresh connection and
briefly interrupts the official app. Never clear the full connection table.

## Verify before keeping rules

1. Check the expected device reaches the correct listener and the peer IP
   matches the configured allowed source.
2. Confirm valid local measurements, fan state and one already verified
   control, restoring its original state afterward.
3. Allow several minutes for initial cloud recovery. The purifier can send
   retries for roughly two minutes before emitting a fresh registration. A TCP
   connection alone is not proof of a working cloud session.
4. Check official app status and app-issued commands through the relay. Confirm
   a local command also appears in the app.
5. Test cloud-session recovery while local status/control remain responsive.
   Do this only with scoped test connections, never by disrupting the network.
6. Verify each additional purifier separately. Retain/persist reviewed rules
   only when the owner requests deployment and the entire validation passes.

## Rollback

Remove only the exact task-owned rules/table. If necessary, remove only the
same purifier/cloud TCP connection-tracking entries so the next connection
uses its original route. Stop only the task-owned listener/capture processes.
Verify no task-owned rules or listeners remain and cloud communication
recovers. Do not flush tables, restart networking, reboot, or alter OpenClash.

If HA stops while redirection remains, the official app's connection also
loses its relay. There is no automatic router failover. Keep the reviewed
rollback available and understand this dependency before deployment.
