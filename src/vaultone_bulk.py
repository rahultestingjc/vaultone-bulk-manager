#!/usr/bin/env python3
# ============================================================
# VaultOne Bulk Resource Manager
# Bulk create / update servers and websites in JumpCloud VaultOne
# from a single CSV file.
#
#   Resources:  Servers | Websites
#   Operations: create | update-replace | update-append | dry-run
#
# The API user running the script is ALWAYS granted Manage
# access on every resource it touches, so the automation never
# locks itself out of the records it manages.
#
# Author : Rahul Saini
# License: MIT
# ============================================================

import os
import sys
import json
import argparse
import datetime
import requests
import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv is optional; env vars can also be set in the shell.
    pass

# ========================================
# CONFIGURATION (loaded from environment / .env)
# ========================================

VAULTONE_AUTH_URL = os.environ.get("VAULTONE_AUTH_URL", "").rstrip("/")
VAULTONE_API_URL  = os.environ.get("VAULTONE_API_URL", "").rstrip("/")
USERNAME          = os.environ.get("VAULTONE_USERNAME", "")
PASSWORD          = os.environ.get("VAULTONE_PASSWORD", "")
TENANT_ID         = os.environ.get("VAULTONE_TENANT_ID", "101")

VERBOSE = os.environ.get("VAULTONE_VERBOSE", "false").strip().lower() in ("1", "true", "yes")

# Repo layout: this file lives in src/, sample CSVs live in samples/
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.dirname(SCRIPT_DIR)
SAMPLES_DIR = os.environ.get("VAULTONE_CSV_DIR", os.path.join(REPO_ROOT, "samples"))

# Per-resource settings. Servers and Websites use parallel APIs that differ
# only in endpoints, the "connect" permission string, and a few fields.
RESOURCE_CONFIGS = {
    "server": {
        "label": "Server",
        "csv": "servers.csv",
        "list_endpoint": "Servers/GetAll",
        "edit_endpoint": "Servers/GetServerForEdit",
        "save_endpoint": "Servers/CreateOrEdit",
        "connect_perm": "Resource.Connect",
        "edit_key": "server",          # GetServerForEdit wraps record in result.server
        "connector_required": True,
    },
    "website": {
        "label": "Website",
        "csv": "websites.csv",
        "list_endpoint": "Websites/GetAll",
        "edit_endpoint": "Websites/GetWebsiteForEdit",
        "save_endpoint": "Websites/CreateOrEdit",
        "connect_perm": "Resource.Connect.WE",  # web resources use a different connect perm
        "edit_key": "website",
        "connector_required": False,   # websites can launch without a connector
    },
}

# ========================================
# LOGGING
# ========================================

LOG_LINES = []

def log(msg=""):
    print(msg)
    LOG_LINES.append(str(msg))

def save_log():
    log_dir = os.path.join(REPO_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = os.path.join(log_dir, f"run_{stamp}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(LOG_LINES))
    return path

# ========================================
# PERMISSION HELPERS (resource-aware)
# ========================================

def perm_sets(connect_perm):
    """Return (view, connect, full) permission lists for a resource type."""
    view = ["Resource.View.Detail"]
    connect = [connect_perm, "Resource.View.Detail"]
    full = ["Manage", connect_perm, "Resource.View.Detail"]
    return view, connect, full

# ========================================
# API HELPERS
# ========================================

def api_headers(token):
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "abp-tenantid": TENANT_ID,
    }


def authenticate():
    url = f"{VAULTONE_AUTH_URL}/api/TokenAuth/Authenticate"
    payload = {"userNameOrEmailAddress": USERNAME, "password": PASSWORD, "rememberClient": True}
    response = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
    if VERBOSE:
        log(f"Auth status: {response.status_code}")
        log(f"Auth body:   {response.text[:500]}")
    if response.status_code != 200:
        return None
    return response.json().get("result", {})


def get_group_id_map(token):
    url = f"{VAULTONE_API_URL}/api/services/app/OrganizationUnit/GetOrganizationUnits"
    response = requests.get(url, headers=api_headers(token))
    if response.status_code != 200:
        log(f"WARNING: Could not fetch groups (status {response.status_code}).")
        return {}
    items = response.json().get("result", {}).get("items", [])
    return {i["displayName"]: i["id"] for i in items if "displayName" in i and "id" in i}


def get_user_id_map(token):
    url = f"{VAULTONE_API_URL}/api/services/app/User/FindUsers"
    response = requests.get(url, headers=api_headers(token), params={"MaxResultCount": 5000, "SkipCount": 0})
    if response.status_code != 200:
        log(f"WARNING: Could not fetch users (status {response.status_code}).")
        return {}
    items = response.json().get("result", {}).get("items", [])
    return {i["emailAddress"]: {"id": i["id"], "name": i["name"]} for i in items if "emailAddress" in i and "id" in i}


def get_connector_id_map(token):
    url = f"{VAULTONE_API_URL}/api/services/app/Connectors/GetAll"
    response = requests.get(url, headers=api_headers(token), params={"DescriptionFilter": ""})
    if response.status_code != 200:
        log(f"WARNING: Could not fetch connectors (status {response.status_code}).")
        return {}
    items = response.json().get("result", {}).get("items", [])
    id_map = {}
    for item in items:
        cid = item.get("id")
        display = item.get("description") or item.get("name")
        if cid and display:
            id_map[display] = cid
    return id_map


def get_resource_name_map(token, list_endpoint):
    """Paginated fetch of all resources of a type -> {name: id}."""
    url = f"{VAULTONE_API_URL}/api/services/app/{list_endpoint}"
    name_map = {}
    skip = 0
    while True:
        params = {"MaxResultCount": 100, "SkipCount": skip, "ArchivedFilter": "false"}
        response = requests.get(url, headers=api_headers(token), params=params)
        if response.status_code != 200:
            log(f"ERROR: Could not fetch resources (status {response.status_code}): {response.text[:300]}")
            return {}
        result = response.json().get("result", {})
        items = result.get("items", [])
        for item in items:
            rid = item.get("id") or item.get("server", {}).get("id") or item.get("website", {}).get("id")
            name = item.get("name") or item.get("server", {}).get("name") or item.get("website", {}).get("name")
            if rid and name:
                name_map[name] = rid
        total = result.get("totalCount", len(items))
        skip += len(items)
        if skip >= total or not items:
            break
    return name_map


def get_resource_for_edit(token, edit_endpoint, edit_key, resource_id):
    url = f"{VAULTONE_API_URL}/api/services/app/{edit_endpoint}"
    response = requests.get(url, headers=api_headers(token), params={"Id": resource_id})
    if VERBOSE:
        log(f"[DEBUG] {edit_endpoint} {resource_id}: {response.status_code}")
        log(f"[DEBUG] {response.text[:800]}")
    if response.status_code != 200:
        log(f"ERROR: Could not fetch resource {resource_id} for edit (status {response.status_code}): {response.text[:300]}")
        return None
    result = response.json().get("result", {})
    # The record may be wrapped (result.server / result.website) or returned flat.
    inner = result.get(edit_key) or result.get("server") or result.get("website") or result
    return inner

# ========================================
# CSV / POLICY HELPERS
# ========================================

def _split(value):
    raw = str(value).strip()
    if not raw or raw == "nan":
        return []
    return [v.strip() for v in raw.split(";") if v.strip()]


def yes(value, default=True):
    raw = str(value).strip().lower()
    if raw in ("", "nan"):
        return default
    return raw in ("yes", "y", "true", "1")


def normalize_tags(value):
    """CSV uses semicolons; API expects comma-separated string."""
    if pd.isna(value) or str(value).strip() in ("", "nan"):
        return ""
    return ",".join(t.strip() for t in str(value).split(";") if t.strip())


def build_access_groups(row, group_id_map, connect_perm, warnings):
    view, connect, full = perm_sets(connect_perm)
    seen = {}
    for g in _split(row.get("GROUP_VIEW", "")):
        seen.setdefault(g, set()).update(view)
    for g in _split(row.get("GROUP_CONNECT", "")):
        seen.setdefault(g, set()).update(connect)
    for g in _split(row.get("GROUP_MANAGE", "")):
        seen.setdefault(g, set()).update(full)

    result = []
    for gname, perms in seen.items():
        gid = group_id_map.get(gname)
        if gid is None:
            warnings.append(f"Group '{gname}' not found - skipped")
            continue
        result.append({"name": gname, "id": gid, "permissions": list(perms)})
    return result


def build_access_users(row, user_id_map, connect_perm, warnings):
    view, connect, full = perm_sets(connect_perm)
    seen = {}
    for e in _split(row.get("USER_VIEW", "")):
        seen.setdefault(e, set()).update(view)
    for e in _split(row.get("USER_CONNECT", "")):
        seen.setdefault(e, set()).update(connect)
    for e in _split(row.get("USER_MANAGE", "")):
        seen.setdefault(e, set()).update(full)

    result = []
    for email, perms in seen.items():
        user = user_id_map.get(email)
        if user is None:
            warnings.append(f"User '{email}' not found - skipped")
            continue
        result.append({"name": user["name"], "email": email, "id": user["id"], "permissions": list(perms)})
    return result


def inject_api_user(users_list, api_user, connect_perm):
    """The API user always gets full Manage access - upgraded if present, appended if not."""
    _, _, full = perm_sets(connect_perm)
    for u in users_list:
        if u.get("id") == api_user["id"]:
            u["permissions"] = list(set(u.get("permissions", []) + full))
            return users_list
    users_list.append({
        "name": api_user["name"],
        "email": api_user["email"],
        "id": api_user["id"],
        "permissions": full,
    })
    return users_list


def merge_policies(existing_list, new_list, key="id"):
    """
    Append-mode merge: start from existing entries, layer CSV entries on top.
    Permissions are unioned (upgrade only, never downgrade).
    """
    merged = {}
    for entry in existing_list or []:
        k = entry.get(key)
        if k is not None:
            merged[k] = dict(entry)
            merged[k]["permissions"] = set(entry.get("permissions") or [])
    for entry in new_list:
        k = entry.get(key)
        if k in merged:
            merged[k]["permissions"].update(entry.get("permissions") or [])
            for field in ("name", "email"):
                if entry.get(field):
                    merged[k][field] = entry[field]
        else:
            merged[k] = dict(entry)
            merged[k]["permissions"] = set(entry.get("permissions") or [])
    out = []
    for entry in merged.values():
        entry["permissions"] = list(entry["permissions"])
        out.append(entry)
    return out

# ========================================
# ROW PARSING (per resource type)
# ========================================

def parse_row(row, resource_type):
    """Extract + sanitize fields. Returns None for blank rows."""
    name = row.get("NAME*")
    uri = row.get("URI*")
    if pd.isna(name) or pd.isna(uri):
        return None

    common = {
        "name": str(name).strip(),
        "uri": str(uri).strip(),
        "tags": normalize_tags(row.get("Tags", "")),
        "connector": str(row.get("CONNECTOR", "")).strip(),
    }

    if resource_type == "server":
        port = row.get("PORT*")
        if pd.isna(port):
            return None
        common.update({
            "os": str(row.get("SO*", "")).strip(),
            "protocol": str(row.get("PROTOCOL*", "")).strip(),
            "port": str(port).strip(),
            "record_video": yes(row.get("Recording", "Yes")),
        })
    else:  # website
        common.update({
            "webshield": yes(row.get("WEBSHIELD", "No"), default=False),
            "reverse_proxy": yes(row.get("REVERSE_PROXY", "No"), default=False),
            "auto_submit": yes(row.get("AUTO_SUBMIT", "Yes"), default=True),
        })
    return common

# ========================================
# PAYLOAD BUILDERS
# ========================================

def build_server_payload(p, connector_id, groups, users, resource_id=None, existing=None):
    ex = existing or {}
    ex_proto = ex.get("protocol") or {}
    payload = {
        "name": p["name"],
        "uri": p["uri"],
        "notes": ex.get("notes"),
        "os": p["os"],
        "recordVideo": p["record_video"],
        "useRemoteApp": ex.get("useRemoteApp", False),
        "useSslTls": ex.get("useSslTls", False),
        "disableFileTransfer": ex.get("disableFileTransfer", False),
        "disableClipboard": ex.get("disableClipboard", False),
        "connector": connector_id,
        "protocol": {
            "category": p["protocol"],
            "port": int(p["port"]),
            "rdpSecurity": ex_proto.get("rdpSecurity", "any"),
            "nla": ex_proto.get("nla"),
            "communicationHttps": ex_proto.get("communicationHttps", False),
            "standard": ex_proto.get("standard", False),
            "remoteApp": ex_proto.get("remoteApp"),
            "remoteAppDir": ex_proto.get("remoteAppDir"),
            "remoteAppArgs": ex_proto.get("remoteAppArgs"),
            "namespace": ex_proto.get("namespace"),
            "pod": ex_proto.get("pod"),
            "container": ex_proto.get("container"),
        },
        "accessPolicies": {"isPrivate": False, "groups": groups, "users": users},
        "linkedCredentialsAccessPolicies": ex.get("linkedCredentialsAccessPolicies") or {},
        "tags": p["tags"],
        "isPool": ex.get("isPool", False),
        "credentials": ex.get("credentials", []),
    }
    if resource_id:
        payload["id"] = resource_id
        payload["usePool"] = ex.get("usePool", False)
        payload["poolId"] = ex.get("poolId")
    return payload


def build_website_payload(p, connector_id, groups, users, resource_id=None, existing=None):
    ex = existing or {}
    ex_rbi = ex.get("rbiSettings") or {}
    ex_vnc = (ex_rbi.get("vncSettings") or {})
    payload = {
        "name": p["name"],
        "uri": p["uri"],
        "tags": p["tags"],
        "notes": ex.get("notes"),
        "accessPolicies": {"isPrivate": False, "groups": groups, "users": users},
        "linkedCredentialsAccessPolicies": ex.get("linkedCredentialsAccessPolicies") or {},
        "useRemoteBrowserIsolation": p["webshield"],
        "reverseProxy": p["reverse_proxy"],
        "connector": connector_id,
        "rbiSettings": {
            "whitelistUri": ex_rbi.get("whitelistUri", []),
            "blacklistUri": ex_rbi.get("blacklistUri", []),
            "vncSettings": {
                "colorDepth": ex_vnc.get("colorDepth", 32),
                "qualityLevel": ex_vnc.get("qualityLevel", 5),
                "compressionLevel": ex_vnc.get("compressionLevel", -1),
            },
        },
        "parametersExtension": {"makeAutoSubmit": p["auto_submit"]},
        "credentials": ex.get("credentials", []),
    }
    if resource_id:
        payload["id"] = resource_id
    return payload


def post_create_or_edit(token, save_endpoint, payload, name, dry_run):
    if dry_run:
        log(f"  [DRY RUN] Payload for '{name}':")
        log(json.dumps(payload, indent=2))
        return True
    url = f"{VAULTONE_API_URL}/api/services/app/{save_endpoint}"
    response = requests.post(url, json=payload, headers=api_headers(token))
    if VERBOSE:
        log(f"  Response {response.status_code}: {response.text[:500]}")
    if response.status_code == 200:
        try:
            result = response.json()
            if result.get("success"):
                return True
            log(f"  API error: {result.get('error')}")
            return False
        except Exception as e:
            log(f"  Failed to parse response: {e} - {response.text[:300]}")
            return False
    log(f"  HTTP {response.status_code}: {response.text[:300]}")
    return False

# ========================================
# PRE-FLIGHT
# ========================================

def preflight(df, resource_type, base_mode, cfg,
              connector_id_map, group_id_map, user_id_map, resource_name_map):
    ready = []
    issues = []
    for idx, row in df.iterrows():
        parsed = parse_row(row, resource_type)
        if parsed is None:
            continue
        problems = []
        fatal = False

        conn = parsed["connector"]
        if not conn or conn == "nan":
            if cfg["connector_required"]:
                problems.append("no connector specified")
                fatal = True
        elif conn not in connector_id_map:
            problems.append(f"connector '{conn}' not found")
            fatal = True

        for col in ("GROUP_VIEW", "GROUP_CONNECT", "GROUP_MANAGE"):
            for g in _split(row.get(col, "")):
                if g not in group_id_map:
                    problems.append(f"group '{g}' not found ({col})")
        for col in ("USER_VIEW", "USER_CONNECT", "USER_MANAGE"):
            for e in _split(row.get(col, "")):
                if e not in user_id_map:
                    problems.append(f"user '{e}' not found ({col})")

        if base_mode == "create":
            if parsed["name"] in resource_name_map:
                problems.append(f"'{parsed['name']}' already exists (would create duplicate)")
        else:
            if parsed["name"] not in resource_name_map:
                problems.append(f"'{parsed['name']}' not found in VaultOne")
                fatal = True

        if problems:
            issues.append((idx + 2, parsed["name"], problems))
        if not fatal:
            ready.append((idx, row, parsed))
    return ready, issues

# ========================================
# MENU / ARGS
# ========================================

MODE_LABELS = {
    "create": "CREATE",
    "update_replace": "UPDATE (replace policies)",
    "update_append": "UPDATE (append policies)",
}


def ask_menu():
    print("Select resource type:")
    print("  1. Servers")
    print("  2. Websites")
    rt = input("\nEnter choice (1/2): ").strip()
    resource_type = {"1": "server", "2": "website"}.get(rt)
    if not resource_type:
        log("Invalid resource type. Exiting.")
        sys.exit(1)

    print("\nSelect operation:")
    print("  1. Create new resources (import)")
    print("  2. Update - REPLACE access policies")
    print("  3. Update - APPEND to existing access policies")
    print("  4. Dry run (choose a mode, preview payloads, change nothing)")
    choice = input("\nEnter choice (1/2/3/4): ").strip()

    dry_run = False
    if choice == "4":
        choice = input("Dry run which mode? (1=create / 2=replace / 3=append): ").strip()
        dry_run = True

    mode = {"1": "create", "2": "update_replace", "3": "update_append"}.get(choice)
    if not mode:
        log("Invalid operation. Exiting.")
        sys.exit(1)
    return resource_type, mode, dry_run


def parse_args():
    parser = argparse.ArgumentParser(
        description="Bulk create/update JumpCloud VaultOne servers and websites from CSV.")
    parser.add_argument("--resource", choices=["server", "website"],
                        help="Resource type. Omit for interactive menu.")
    parser.add_argument("--mode", choices=["create", "replace", "append"],
                        help="Operation. Omit for interactive menu.")
    parser.add_argument("--csv", help="Path to a CSV file (overrides the default sample).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate and preview payloads without making changes.")
    parser.add_argument("--yes", action="store_true",
                        help="Skip the confirmation prompt (use with care).")
    return parser.parse_args()

# ========================================
# MAIN
# ========================================

def main():
    args = parse_args()

    log("=" * 50)
    log("     VaultOne Bulk Resource Manager")
    log("=" * 50)

    # --- Config sanity ---
    missing = [k for k, v in {
        "VAULTONE_AUTH_URL": VAULTONE_AUTH_URL,
        "VAULTONE_API_URL": VAULTONE_API_URL,
        "VAULTONE_USERNAME": USERNAME,
        "VAULTONE_PASSWORD": PASSWORD,
    }.items() if not v]
    if missing:
        log("X Missing configuration: " + ", ".join(missing))
        log("  Copy .env.example to .env and fill in your values.")
        sys.exit(1)

    # --- Authenticate ---
    auth = authenticate()
    if not auth or not auth.get("accessToken"):
        log("X Authentication failed. Check credentials and URLs in your .env.")
        sys.exit(1)
    token = auth["accessToken"]
    api_user = {
        "id": auth.get("userId"),
        "name": auth.get("userName") or USERNAME,
        "email": auth.get("emailAddress") or USERNAME,
    }
    log(f"OK Authenticated as: {api_user['name']} (ID: {api_user['id']})")
    log(f"   This user will be granted Manage access on every resource processed.")
    log("")

    # --- Resolve resource / mode (args or interactive) ---
    if args.resource and args.mode:
        resource_type = args.resource
        mode = {"create": "create", "replace": "update_replace", "append": "update_append"}[args.mode]
        dry_run = args.dry_run
    else:
        resource_type, mode, dry_run = ask_menu()
        dry_run = dry_run or args.dry_run

    cfg = RESOURCE_CONFIGS[resource_type]
    mode_label = MODE_LABELS[mode]
    log(f"Resource: {cfg['label']}  |  Mode: {mode_label}{'  [DRY RUN]' if dry_run else ''}")
    log("")

    # --- Load CSV ---
    csv_path = args.csv or os.path.join(SAMPLES_DIR, cfg["csv"])
    if not os.path.exists(csv_path):
        log(f"X CSV file not found: {csv_path}")
        sys.exit(1)
    df = pd.read_csv(csv_path, sep=",", dtype=str)
    log(f"Loaded {len(df)} rows from {os.path.basename(csv_path)}")

    # --- Lookup maps ---
    log("Loading VaultOne data...")
    group_id_map = get_group_id_map(token)
    user_id_map = get_user_id_map(token)
    connector_id_map = get_connector_id_map(token)
    resource_name_map = get_resource_name_map(token, cfg["list_endpoint"])
    log(f"  Groups: {len(group_id_map)} | Users: {len(user_id_map)} | "
        f"Connectors: {len(connector_id_map)} | {cfg['label']}s: {len(resource_name_map)}")
    log("")

    # --- Pre-flight ---
    base_mode = "create" if mode == "create" else "update"
    ready, issues = preflight(df, resource_type, base_mode, cfg,
                              connector_id_map, group_id_map, user_id_map, resource_name_map)

    log("---------- PRE-FLIGHT CHECK ----------")
    if issues:
        for line_no, name, problems in issues:
            for p in problems:
                log(f"  ! Row {line_no} ('{name}'): {p}")
    else:
        log("  OK All rows passed validation.")
    log(f"  {len(ready)} row(s) ready to process.")
    log("--------------------------------------")

    if not ready:
        log("Nothing to do. Exiting.")
        save_log()
        sys.exit(0)

    if not dry_run and not args.yes:
        if input("\nProceed? (y/n): ").strip().lower() != "y":
            log("Aborted by user.")
            save_log()
            sys.exit(0)
    log("")

    connect_perm = cfg["connect_perm"]
    build_payload = build_server_payload if resource_type == "server" else build_website_payload

    success = failed = 0
    total = len(ready)

    for i, (idx, row, parsed) in enumerate(ready, start=1):
        name = parsed["name"]
        log(f"[{i}/{total}] {mode_label} {cfg['label']}: {name}")

        conn = parsed["connector"]
        connector_id = connector_id_map.get(conn) if conn and conn != "nan" else None

        warnings = []
        access_groups = build_access_groups(row, group_id_map, connect_perm, warnings)
        access_users = build_access_users(row, user_id_map, connect_perm, warnings)
        for w in warnings:
            log(f"  ! {w}")

        resource_id = None
        existing = None
        if mode != "create":
            resource_id = resource_name_map[name]
            existing = get_resource_for_edit(token, cfg["edit_endpoint"], cfg["edit_key"], resource_id)
            if existing is None:
                log(f"  X Could not fetch existing record - skipped")
                failed += 1
                continue
            if mode == "update_append":
                ex_pol = existing.get("accessPolicies") or {}
                access_groups = merge_policies(ex_pol.get("groups"), access_groups)
                access_users = merge_policies(ex_pol.get("users"), access_users)

        access_users = inject_api_user(access_users, api_user, connect_perm)

        payload = build_payload(parsed, connector_id, access_groups, access_users,
                                resource_id=resource_id, existing=existing)

        if post_create_or_edit(token, cfg["save_endpoint"], payload, name, dry_run):
            log(f"  OK {'Previewed' if dry_run else 'Done'}")
            success += 1
        else:
            log(f"  X Failed")
            failed += 1

    log("")
    log("============== RUN COMPLETE ==============")
    log(f"  Resource:    {cfg['label']}")
    log(f"  Mode:        {mode_label}{'  [DRY RUN]' if dry_run else ''}")
    log(f"  Total rows:  {total}")
    log(f"  Success:     {success}")
    log(f"  Failed:      {failed}")
    log(f"  Log saved:   {save_log()}")
    log("==========================================")


if __name__ == "__main__":
    main()
