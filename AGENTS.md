# Instructions for future agents

This project controls physical AirProce AI-370 and AI-600 purifiers. The owner
requested a local Home Assistant integration with transparent forwarding of the
purifiers' existing cloud traffic. Cloud login, account APIs, filter reset,
provisioning, and unrelated device controls are outside scope.

## Public repository: never commit secrets or private deployment information

Treat every tracked file, commit message, commit author/committer field, branch,
tag, release archive, screenshot and published log as public. Permission to
inspect a device or deploy locally is not permission to publish its details.

- Never commit passwords, API keys, access/refresh tokens, cookies, SSH/private
  keys, Wi-Fi credentials, cloud account data, or device authenticators. AirProce
  registration frames contain identifiers and authentication material: do not
  copy live frames into source, fixtures, documentation, diagnostics or logs.
- Never commit a user's real LAN/public IPs, MAC addresses, device serials,
  private domains/hostnames, SSH usernames, personal email/name, absolute local
  paths, HA configuration/registries/backups, router rulesets, deployment
  receipts, packet captures, HAR files, screenshots or private conversations.
  Document reusable setup concepts and anonymized validation results instead.
- Use synthetic identities and documentation-only addresses such as
  `192.0.2.10`, `198.51.100.20`, `example.com` and `02:00:00:00:00:01` in
  examples. Tests should use loopback networking and synthetic or carefully
  sanitized fixtures. Inspect binary/hex payloads for embedded identifiers,
  credentials and identifying metadata; encoding is not redaction.
- Public vendor endpoints, approved public repository/account identifiers and
  required upstream license attribution may remain. Do not remove copyright
  notices or mistake an ordinary package checksum for a credential.
- Keep necessary private investigation/deployment records only in ignored local
  `test-artifacts/` (or an explicitly private location outside the repository).
  Do not force-add ignored files. `.gitignore` does not protect already tracked
  files or historical commits. Release builds must use an explicit file list.
- Before each commit, review the exact staged filenames and diff for private
  data and secrets, including generated files and IDE metadata. Check the Git
  author/committer identity; use the approved public handle and GitHub noreply
  address. Do not silently use a personal global Git identity. Change no global
  Git configuration as part of this project.
- Before publishing, inspect all outgoing commits and their metadata, not just
  the current tree. Check archives separately. Do not publish until findings
  are resolved. A deletion or redaction commit leaves the old contents in Git
  history. Explain findings without repeating secret values; if history needs
  rewriting, prepare a recoverable local backup and obtain explicit approval
  before rewriting history or force-pushing. Exposed credentials also require
  revocation/rotation; deleting a file cannot make them secret again.

## Router changes require an audit and manual review

The integration must never SSH to a router, install redirection rules, change
DNS, or manage firewall persistence. The owner wants a future agent to review
the actual network and manually apply narrowly scoped rules when deployment is
explicitly requested. Building and testing does not authorize deployment.

Before touching routing:

1. Read `docs/router-setup.md` and `docs/validation.md`. Inspect the current
   interfaces, addressing, firewall/NAT, flow offload, policy routing, and any
   OpenClash or VPN rules. Do not assume the previous topology still applies.
2. Verify the purifier MAC/IP mapping, current cloud destination, HA listener,
   return path, source address seen by HA, and whether HA's upstream connection
   follows the same route as the original purifier connection.
3. Review the exact source/destination/port matches and rollback plan before
   applying a rule. Exclude HA's upstream connection from redirection. Use one
   listener per purifier if SNAT obscures the original source address.
4. Change only task-owned, narrowly scoped rules. Never flush firewall tables,
   clear all connection tracking, restart networking, or disable a proxy/VPN
   globally. Have automatic cleanup for temporary tests and inspect its result.
   The owner explicitly forbids changing or bypassing OpenClash, including
   temporary packet-mark overrides. Only essential purifier redirection and
   return-path NAT rules are authorized for live tests.
5. Verify local state/control AND official app state/control. A connected TCP
   socket alone does not establish working cloud forwarding. Restore original
   device settings and verify cleanup after tests. Document any unverified path.

Do not deploy into a running Home Assistant or make routing persistent without
the user's deployment instruction. Tests use isolated directories and loopback
ports; live device tests use bounded temporary rules. Ask when a missing fact
affects behavior instead of guessing. Commit tested work as it is completed.

## Development

Python 3.14; tested against Home Assistant 2026.10.4 on Linux. Transport tests
also run on Windows without installing Home Assistant. Run pytest and Ruff.
Keep real credentials, raw LAN packet captures, and private host-specific test
scripts out of Git. `test-artifacts/` is ignored for this purpose.
