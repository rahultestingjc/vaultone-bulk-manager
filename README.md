<h1 align="center">VaultOne Bulk Resource Manager</h1>

<p align="center">
  <strong>Bulk-onboard servers and websites into JumpCloud VaultOne from a single CSV — interactive, validated, and safe.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.8%2B-blue.svg" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT">
  <img src="https://img.shields.io/badge/JumpCloud-VaultOne-orange.svg" alt="JumpCloud VaultOne">
</p>

---

## The problem

Onboarding a new customer to JumpCloud VaultOne can mean adding **dozens or hundreds** of servers and web applications by hand through the UI — one form at a time, each with its own access policies. It is slow, repetitive, and easy to get wrong.

This tool turns that into a **single CSV and one command**. Fill in a spreadsheet, run the script, and every resource is created or updated with the right access policies in seconds — with validation up front so nothing breaks halfway through.

## What it does

- 🖥️ **Servers and 🌐 Websites** — manage both resource types from one tool
- ➕ **Create** new resources in bulk from a CSV
- 🔄 **Update** existing resources — *replace* their access policies, or *append* to them
- 🔍 **Pre-flight validation** — every connector, group, user, and resource name is checked **before** any change is made
- 🧪 **Dry-run mode** — preview the exact API payloads without touching anything
- 🔐 **Self-protecting** — the API user running the script is always granted `Manage` access, so the automation can never lock itself out
- 🎚️ **Three permission levels** — `View`, `Connect`, and `Manage`, for both groups and users
- 📝 **Audit logs** — every run is saved with a timestamp

## Demo

<p align="center">
  <img src="docs/images/menu-demo.png" alt="Interactive menu" width="700">
</p>

> _Replace this image with a screenshot of the menu running — see `docs/images/`._

## Quick start

```bash
# 1. Clone
git clone https://github.com/rahultestingjc/vaultone-bulk-manager.git
cd vaultone-bulk-manager

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure (copy the template and fill in your tenant + credentials)
cp .env.example .env

# 4. Run
python src/vaultone_bulk.py
```

The script walks you through choosing a resource type and an operation:

```
Select resource type:
  1. Servers
  2. Websites

Select operation:
  1. Create new resources (import)
  2. Update - REPLACE access policies
  3. Update - APPEND to existing access policies
  4. Dry run (preview payloads, change nothing)
```

### Non-interactive / scripted runs

```bash
python src/vaultone_bulk.py --resource server  --mode create
python src/vaultone_bulk.py --resource website --mode append --dry-run
python src/vaultone_bulk.py --resource server  --mode replace --csv ./my-servers.csv --yes
```

## CSV format

Both resource types share the same access-policy columns. Each permission column accepts **multiple values separated by `;`**.

| Column | Grants |
|---|---|
| `GROUP_VIEW` / `USER_VIEW` | View Detail |
| `GROUP_CONNECT` / `USER_CONNECT` | Connect + View Detail |
| `GROUP_MANAGE` / `USER_MANAGE` | Manage + Connect + View Detail |

**Servers** ([samples/servers.csv](samples/servers.csv)):

```
NAME*, URI*, SO*, PROTOCOL*, PORT*, Tags, CONNECTOR, Recording, <permission columns>
```

**Websites** ([samples/websites.csv](samples/websites.csv)):

```
NAME*, URI*, Tags, CONNECTOR, WEBSHIELD, REVERSE_PROXY, AUTO_SUBMIT, <permission columns>
```

See [docs/USAGE.md](docs/USAGE.md) for a full column reference and worked examples.

## Safety by design

| Feature | Why it matters |
|---|---|
| **Pre-flight validation** | Catches a bad connector or missing user before a single resource is changed. |
| **Dry-run** | Review the exact JSON that would be sent — perfect for change reviews. |
| **API-user injection** | The script always keeps `Manage` access for itself, so re-runs never fail with a permission error. |
| **Append mode** | Add access without wiping what's already there — permissions are only ever upgraded, never removed. |

## Configuration

All configuration lives in `.env` (never committed). See [.env.example](.env.example):

| Variable | Description |
|---|---|
| `VAULTONE_AUTH_URL` | Token/authentication endpoint |
| `VAULTONE_API_URL` | Resource API endpoint |
| `VAULTONE_USERNAME` / `VAULTONE_PASSWORD` | API user credentials |
| `VAULTONE_TENANT_ID` | Tenant ID (default `101`) |

## License

[MIT](LICENSE) © Rahul Saini
