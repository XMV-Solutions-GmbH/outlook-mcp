#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
#
# Bootstrap the multi-tenant Entra (Azure AD) app registration that
# `mcp-server-outlook` ships as its default `OUTLOOK_CLIENT_ID`.
# Run this ONCE, the first time the OSS package is provisioned.
#
# What it does:
#
#   1. `az login` (interactive) into the XMV Azure tenant.
#   2. Creates a public-client multi-tenant app registration named
#      "mcp-server-outlook" with Device Code flow allowed.
#   3. Adds the delegated Microsoft Graph permissions for v0.1 + v0.2:
#        Mail.Read, Mail.ReadWrite,
#        Calendars.Read, Calendars.ReadWrite,
#        User.Read, offline_access.
#      It does NOT grant Mail.Send — that's the point of this server.
#   4. Prints the resulting `appId` so you can paste it as
#      `DEFAULT_CLIENT_ID` into src/outlook_mcp/auth/flow.py.
#
# Prerequisites:
#   - `az` (Azure CLI) installed.
#   - You have rights to create app registrations in the XMV tenant.

set -euo pipefail

APP_NAME="mcp-server-outlook"
SIGN_IN_AUDIENCE="AzureADMultipleOrgs"  # multi-tenant work/school
GRAPH_APP_ID="00000003-0000-0000-c000-000000000000"  # Microsoft Graph well-known

# Microsoft Graph delegated permission scope IDs.
# Verified from `az ad sp show --id 00000003-0000-0000-c000-000000000000 --query "oauth2PermissionScopes"`.
SCOPE_MAIL_READ="570282fd-fa5c-430d-a7fd-fc8dc98a9dca"
SCOPE_MAIL_READWRITE="024d486e-b451-40bb-833d-3e66d98c5c73"
SCOPE_MAIL_SEND="e383f46e-2787-4529-855e-0e479a3ffac0"
SCOPE_CALENDARS_READ="465a38f9-76ea-45b9-9f34-9e8b0d4b0b42"
SCOPE_CALENDARS_READWRITE="1ec239c2-d7c9-4623-a91a-a9775856bb36"
SCOPE_USER_READ="e1fe6dd8-ba31-4d61-89e7-88639da4683d"
SCOPE_OFFLINE_ACCESS="7427e0e9-2fba-42fe-b0c0-848c9e6a8182"

# IMPORTANT: Mail.Send is REGISTERED on the app but is NOT in the
# default OAuth scope request. The runtime auth flow only includes
# Mail.Send in its scope request when the user has set
# `OUTLOOK_ALLOW_SEND=true` in their MCP client configuration. That
# means a default install — without the env flag — never sees
# "this app can send mail as you" in the consent screen, even though
# the app registration permits it.
#
# Why register-but-don't-default-request: that's the tradeoff of
# Option B from the v0.3 design discussion. We give power users a
# clean opt-in path (they don't need a BYO Entra app) while keeping
# the default consent surface drafts-only. The website privacy +
# terms pages document this design explicitly.

red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
blue()  { printf '\033[0;34m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[0;33m%s\033[0m\n' "$*"; }

# Publisher-info URLs — point at the live xmv.de subpages.
PRIVACY_URL="https://www.xmv.de/oss/outlook-mcp/privacy"
TERMS_URL="https://www.xmv.de/oss/outlook-mcp/terms"
MARKETING_URL="https://github.com/XMV-Solutions-GmbH/outlook-mcp"
SUPPORT_URL="https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues"

command -v az >/dev/null 2>&1 || { red "ERROR: az CLI not installed."; exit 1; }
command -v jq >/dev/null 2>&1 || { red "ERROR: jq not installed."; exit 1; }

blue ">> Step 1/5: Verify Azure login"
if ! az account show >/dev/null 2>&1; then
    yellow "    Not signed in — running 'az login'..."
    az login --output none
fi
TENANT=$(az account show --query "tenantDisplayName" -o tsv)
USER=$(az account show --query "user.name" -o tsv)
green ">> Signed in as ${USER} on tenant ${TENANT}"

blue ">> Step 2/5: Find or create app registration '${APP_NAME}' (idempotent)"
EXISTING=$(az ad app list --display-name "${APP_NAME}" --query "[0].appId" -o tsv 2>/dev/null || true)
if [[ -n "${EXISTING}" ]]; then
    APP_ID="${EXISTING}"
    yellow ">> Found existing app registration; reusing appId=${APP_ID}"
else
    APP_ID=$(az ad app create \
        --display-name "${APP_NAME}" \
        --sign-in-audience "${SIGN_IN_AUDIENCE}" \
        --is-fallback-public-client true \
        --required-resource-accesses "$(cat <<EOF
[
    {
        "resourceAppId": "${GRAPH_APP_ID}",
        "resourceAccess": [
            {"id": "${SCOPE_MAIL_READ}",         "type": "Scope"},
            {"id": "${SCOPE_MAIL_READWRITE}",    "type": "Scope"},
            {"id": "${SCOPE_MAIL_SEND}",         "type": "Scope"},
            {"id": "${SCOPE_CALENDARS_READ}",    "type": "Scope"},
            {"id": "${SCOPE_CALENDARS_READWRITE}","type": "Scope"},
            {"id": "${SCOPE_USER_READ}",         "type": "Scope"},
            {"id": "${SCOPE_OFFLINE_ACCESS}",    "type": "Scope"}
        ]
    }
]
EOF
)" \
        --query "appId" -o tsv)
    green ">> App registration created. appId=${APP_ID}"
fi

blue ">> Step 3/5: Confirm public-client redirect URI for Device Code flow"
# Microsoft requires the well-known Device Code redirect URI to be present
# even on public-client apps for the flow to succeed in some tenants.
az ad app update \
    --id "${APP_ID}" \
    --public-client-redirect-uris "https://login.microsoftonline.com/common/oauth2/nativeclient" \
    --output none
green ">> Public-client redirect URI configured."

blue ">> Step 4/5: Set publisher-info URLs (privacy / terms / marketing / support)"
OBJECT_ID=$(az ad app show --id "${APP_ID}" --query "id" -o tsv)
az rest --method PATCH \
    --uri "https://graph.microsoft.com/v1.0/applications/${OBJECT_ID}" \
    --headers "Content-Type=application/json" \
    --body "$(cat <<EOF
{
    "info": {
        "privacyStatementUrl": "${PRIVACY_URL}",
        "termsOfServiceUrl":   "${TERMS_URL}",
        "marketingUrl":        "${MARKETING_URL}",
        "supportUrl":          "${SUPPORT_URL}"
    }
}
EOF
)" \
    --output none
green ">> Publisher info URLs configured."

blue ">> Step 5/5: Sanity check — list configured permissions"
az ad app permission list \
    --id "${APP_ID}" \
    --query "[].resourceAccess[].id" -o tsv | sort
echo

green "==================================================================="
green "  Done. The default client id for outlook-mcp is:"
green ""
green "      DEFAULT_CLIENT_ID = \"${APP_ID}\""
green ""
green "  If src/outlook_mcp/auth/flow.py still has a different value,"
green "  patch it and commit + push so users pick it up from the next"
green "  published release."
green "==================================================================="

yellow ""
yellow "  Note: 'Mail.Send' IS in the permission list (v0.3+) but is"
yellow "  NOT requested by the runtime auth flow unless the end user"
yellow "  sets OUTLOOK_ALLOW_SEND=true in their MCP client config."
yellow "  Default installs see a drafts-only consent screen; the"
yellow "  Mail.Send opt-in surfaces explicitly in the consent prompt"
yellow "  when the user activates it. The agent never auto-sends —"
yellow "  ol_email_send_draft requires an explicit per-draft tool"
yellow "  call AFTER the human has reviewed the draft in Outlook."
