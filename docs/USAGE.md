# Usage Guide

A complete reference for the VaultOne Bulk Resource Manager.

---

## 1. Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then edit .env with your values
```

| Variable | Required | Description |
|---|---|---|
| `VAULTONE_AUTH_URL` | Yes | Token endpoint, e.g. `https://acme.api.vault.jumpcloud.com` |
| `VAULTONE_API_URL` | Yes | Resource API, e.g. `https://acme.app.vault.jumpcloud.com` |
| `VAULTONE_USERNAME` | Yes | API user |
| `VAULTONE_PASSWORD` | Yes | API password |
| `VAULTONE_TENANT_ID` | No | Defaults to `101` |
| `VAULTONE_VERBOSE` | No | `true` prints full API responses |
| `VAULTONE_CSV_DIR` | No | Override the folder CSVs are read from |

> **Note on the two URLs.** VaultOne issues tokens on the `*.api.*` host but
> serves resource calls on the `*.app.*` host. Both are required.

---

## 2. Operations

| Mode | What it does |
|---|---|
| **Create** | Creates new resources. Flags any row whose name already exists so you don't create duplicates. |
| **Update — Replace** | Looks up the resource by name and **overwrites** its access policies with what's in the CSV. |
| **Update — Append** | Looks up the resource, reads its current access policies, and **merges** the CSV entries on top. Permissions are unioned — an existing user is never downgraded, and users not in the CSV keep their access. |
| **Dry run** | Runs validation and prints the exact payload for each row. Makes no changes. |

---

## 3. CSV column reference

### Shared columns

| Column | Required | Notes |
|---|---|---|
| `NAME*` | Yes | Display name. For updates it must match the existing resource exactly. |
| `URI*` | Yes | Server IP/hostname, or the full website URL. |
| `Tags` | No | Semicolon-separated, e.g. `Cloud;Production`. |
| `CONNECTOR` | Servers: yes / Websites: optional | Must match the connector's display name in VaultOne. |

### Server-only columns

| Column | Required | Notes |
|---|---|---|
| `SO*` | Yes | Operating system, e.g. `Windows Server 2022`. |
| `PROTOCOL*` | Yes | `RDP`, `SSH`, `VNC`, etc. |
| `PORT*` | Yes | Numeric, e.g. `3389`. |
| `Recording` | No | `Yes`/`No` — session video recording. Default `Yes`. |

### Website-only columns

| Column | Required | Notes |
|---|---|---|
| `WEBSHIELD` | No | `Yes`/`No` — enable Remote Browser Isolation. Default `No`. |
| `REVERSE_PROXY` | No | `Yes`/`No`. Default `No`. |
| `AUTO_SUBMIT` | No | `Yes`/`No` — auto-submit stored credentials. Default `Yes`. |

### Permission columns (both resource types)

Each accepts multiple values separated by `;`.

| Column | Resource.View.Detail | Connect | Manage |
|---|:---:|:---:|:---:|
| `GROUP_VIEW` / `USER_VIEW` | ✓ | | |
| `GROUP_CONNECT` / `USER_CONNECT` | ✓ | ✓ | |
| `GROUP_MANAGE` / `USER_MANAGE` | ✓ | ✓ | ✓ |

- Groups are matched by **display name**; users by **email address**.
- A name listed in more than one column receives the **union** of the permissions.
- Missing groups/users produce a warning and are skipped — the row still runs.

---

## 4. Worked example

CSV row:

```
GROUP_CONNECT = DBA;DevOps
GROUP_MANAGE  = DBA
USER_MANAGE   = admin@example.com
```

Resulting access policy:

| Principal | Permissions |
|---|---|
| `DBA` (group) | Manage + Connect + View  _(union of CONNECT and MANAGE)_ |
| `DevOps` (group) | Connect + View |
| `admin@example.com` (user) | Manage + Connect + View |
| _the API user_ | Manage + Connect + View  _(always injected)_ |

---

## 5. Command-line flags

| Flag | Purpose |
|---|---|
| `--resource {server,website}` | Skip the resource menu. |
| `--mode {create,replace,append}` | Skip the operation menu. |
| `--csv PATH` | Use a specific CSV instead of the default sample. |
| `--dry-run` | Validate and preview only. |
| `--yes` | Skip the confirmation prompt (for automation). |

If `--resource` and `--mode` are both given, the script runs without prompts.

---

## 6. How it works (architecture)

1. **Authenticate** on the `*.api.*` host and capture the API user's identity.
2. **Load lookups once** — groups, users, connectors, and existing resources
   (servers or websites), with pagination.
3. **Pre-flight** — validate every row against those lookups and report issues
   with their CSV line numbers.
4. **Per row** — build the access policies, inject the API user with Manage,
   and (for updates) fetch the existing record so untouched fields and linked
   credentials are preserved.
5. **Send** to `CreateOrEdit` (or print the payload in dry-run).
6. **Log** a timestamped transcript and a summary to `logs/`.

Servers and websites use the same code path; only the endpoints, the "connect"
permission string (`Resource.Connect` vs `Resource.Connect.WE`), and a few
resource-specific fields differ — all centralised in one config block.
