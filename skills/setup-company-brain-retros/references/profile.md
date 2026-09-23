# Company Brain retro profile contract

## Location

Use `${XDG_CONFIG_HOME:-$HOME/.config}/reservamos/company-brain-retros/profile.yaml`.
The profile is local presentation metadata, not an authorization cache.

## Schema version 1

The exact allowlist is:

```yaml
schema_version: 1
display_name: "Ada Lovelace"
default_squad: revenue
collaborating_squads: []
```

- `schema_version` must equal integer `1`.
- `display_name` and `default_squad` are required non-empty strings.
- `collaborating_squads` is optional; when present it is a unique list of non-empty strings.
- Squad values use lowercase kebab-case.
- Unknown fields are forbidden. In particular, reject any token, credential, secret, scope, retro body, policy body, person slug, write prefix, direct-write grant, or authorization value.

## Safe replacement

1. Parse the existing file if present. Reject unsupported versions, invalid types, and fields outside the exact allowlist. Keep its exact bytes and mode in memory for rollback; do not copy it to a durable backup file.
2. Show the complete replacement and obtain confirmation when repairing an invalid existing profile; never silently merge it.
3. Use host-native or dependency-free YAML handling. Do not install or assume PyYAML or another runtime package, and do not leave helper scripts or scratchpad artifacts in the project.
4. Create the parent directory with user-only access.
5. Write the complete YAML to a temporary file in the same directory without following a symlink.
6. Set the temporary file to mode `0600`, flush it, and verify its complete parsed value before replacement.
7. Atomically rename it over `profile.yaml`, flush the directory, then re-read the destination and verify the exact values, schema version, regular-file status, owner, and mode `0600`.
8. Remove leftover temporary files. If post-replacement verification fails, atomically restore the prior bytes and mode; when no prior file existed, remove the invalid destination.

A tooling failure before atomic replacement may be retried once after verifying that the destination bytes and mode are unchanged and every temporary file is gone. Any failure after replacement must restore the previous profile (or remove a newly created invalid destination) and report `NOT READY`. Never persist credentials, policy snapshots, retro content, OAuth scopes, authorization prefixes, or a publication destination.
