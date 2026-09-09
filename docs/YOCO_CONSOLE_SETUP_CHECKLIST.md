# Yoco Console Setup Checklist — Avea Neo Touch

**Date:** 2026-09-08  
**Based on:** `docs/YOCO_NEO_TOUCH_INTEGRATION_FINDINGS.md`, current Avea POS payment architecture, and the live Yoco Developer Console UI (New Application screens).  
**Rule:** Complete Yoco Console / merchant setup first. No Avea code changes until the required credentials and access path are confirmed.

---

## Critical console reality check (from your screenshots)

The public docs describe **OAuth + `business/webpos:*`** for Web POS. Your console currently shows:

| Console option | Status |
| --- | --- |
| Application name `Avea Dashboard Yoco` | OK to use |
| **Live** environment | Only available option |
| **Sandbox** | **Coming soon** — not selectable |
| **Personal application** | Only available option |
| **OAuth application** | **Coming soon** — not selectable |
| Permissions list | Webhooks, capital, catalogue, **devices**, locations, **orders read/write**, payouts, staff |
| `business/webpos:read` / `business/webpos:write` | **Not offered** in the personal permissions picker |

**Implication:** You cannot yet complete the *documented* multi-merchant Web POS OAuth setup from this screen. Proceed with a **Personal + Live** app only for what the console allows, and treat **Web POS API access** as something to **confirm with Yoco** (or wait until OAuth / Web POS scopes appear).

Do **not** assume `business/orders:write` replaces Web POS payment create — that scope is for orders & payment links, not Neo Touch Web POS payments.

---

## Current Avea payment architecture (context)

- Avea POS uses standard Odoo `pos.payment.method` tenders: **Cash**, **Card**, **EFT**, **Store Credit**.
- **Card / EFT** today are accounting/journal tenders (cashier marks method). There is **no** terminal push, redirect, or poll integration yet.
- Correct Payment, Cash Up, and till ledger already assume Card/EFT amounts are final once recorded.
- Future Yoco work will sit beside Card: initiate Neo Touch → wait for Yoco result → then record the Odoo POS payment / order as paid.

---

## I need to do in Yoco Developer Console / Yoco App

### 1. Application setup

- [ ] Keep name: **Avea Dashboard Yoco** (or similar).
- [ ] Select **Live** (only option until Sandbox ships).
- [ ] Select **Personal application** (only option until OAuth ships).
- [ ] Understand this binds the API key to **your / Pets Empire Yoco business**, not multi-merchant install.

### 2. Permissions / scopes (what you can select today)

Add at least:

- [ ] `business/devices:read` — list card machines (Neo Touch serials).
- [ ] `business/orders:read` — list/fetch payments & refunds (reconciliation / audit).
- [ ] `application/webhooks:read` + `application/webhooks:write` — if you want webhook subscriptions later (optional for v1; Web POS completion is poll-based).

Optional later:

- [ ] `business/orders:write` — only if you also use payment links / order create (not required for documented Web POS).
- [ ] `business/locations:read` / `business/staff:read` / payouts / catalogue — not required for Neo Touch charge.

**Still missing for documented Web POS:**

- [ ] Confirm with Yoco when `business/webpos:read` and `business/webpos:write` become available (likely with **OAuth application**).
- [ ] Do **not** Save expecting Web POS to work solely from orders scopes.

### 3. Credentials

After Save:

- [ ] Generate / copy the **Personal API key** (secret). Store offline; show-once secrets are common.
- [ ] Note any **Application ID** / key id shown in the console.
- [ ] Confirm token type: personal JWT / API key usable as `Authorization: Bearer …` against `https://api.yoco.com`.

### 4. OAuth settings / redirect URLs

- [ ] **N/A for now** — OAuth application type is Coming soon.
- [ ] When OAuth appears, you will need:
  - [ ] OAuth app creation + live review/approval
  - [ ] Redirect URI(s) for Avea DEV (and later PROD), e.g. `https://<dev-host>/avea/yoco/oauth/callback` (exact path TBD at implementation)
  - [ ] Scopes including `business/webpos:read` and `business/webpos:write` (+ `offline_access` if long-lived refresh is needed)

### 5. Web POS / device / hardware (merchant side)

In **Yoco App** (not only Developer Console):

- [ ] Neo Touch linked to this Yoco business (Settings → Card machines → serial).
- [ ] Neo Touch powered on, logged in, on Wi‑Fi/cloud, ready to take payments.
- [ ] Note serial number(s) and nicknames for the till(s) you will test.

Web POS logical “device” (`POST /v1/webpos/` named station):

- [ ] Cannot be created from the Console UI — created later via API once Web POS scopes work.
- [ ] For now: no Console step beyond hardware + API key.

### 6. Sandbox / test requirements

- [ ] Sandbox environment in Console: **Coming soon** — plan initial tests on **Live**.
- [ ] Prefer tiny live amounts (e.g. R2+) and a company test card / refund via Yoco App if needed.
- [ ] Ask Yoco whether a sandbox host (`api.yocosandbox.com`) still works with Live personal keys, or is blocked until Console Sandbox ships.

### 7. Anything requiring Yoco approval / support

- [ ] **Ask Yoco Support / Partnerships explicitly:**
  1. How does a **Personal** Live app start **Web POS** payments if `business/webpos:*` is not in the permission list?
  2. Timeline for **OAuth applications** and **Sandbox** in the Developer Console.
  3. Whether Pets Empire / Avea should apply as a **Payment SDK** partner instead (native only — weak fit for Odoo web POS).
  4. Refund path for Web POS–originated Neo Touch payments.
- [ ] Live **OAuth** apps (when available) require Yoco **vetting/review** before merchants can install.
- [ ] Payment SDK access (if pursued) requires the **SDK Integration Application** form.

**Gate to start Avea implementation:** either (A) working Bearer token that can `POST /v1/webpos/.../payments`, or (B) written confirmation from Yoco of the interim Personal-app path.

---

## Cursor can do in Avea (after you hand over credentials / access is confirmed)

### Backend integration

- [ ] Config model / settings for Yoco API base URL + API key (DEV first; secrets not in git).
- [ ] Thin HTTP client for Yoco API (create Web POS device, create payment, fetch payment).
- [ ] Map Avea POS config / till → stored `webpos_device_id`.

### OAuth handling

- [ ] **Defer** until Console OAuth exists; design placeholders only if useful.
- [ ] Later: authorize URL, callback, token store, refresh (14d / 60d).

### Payment creation

- [ ] From POS Card tender: create Web POS payment with amount in cents, unique `client_reference` (order/session attempt id), metadata.
- [ ] Guard against double-create while `pending` / already `successful`.

### Redirect handling

- [ ] Open/embed `redirect_url` for cashier (popup / iframe / new tab) to confirm and select Neo Touch.
- [ ] Keep Avea POS blocked on that payment attempt until result or operator abort policy.

### Status polling

- [ ] Poll `GET .../payments/{id}` until `successful` or `failed`.
- [ ] Local timeout / abandon UX (docs do not define Yoco timeout).

### Checkout UX

- [ ] Card button behaviour: “Pay with Yoco” vs existing manual Card tender.
- [ ] In-progress, success, failure, and abandon states on payment screen.

### Successful / failed payment handling

- [ ] On `successful`: create/finalize Odoo `pos.payment` (Card), complete order as today.
- [ ] Persist Yoco `payment_id`, `client_reference`, terminal serial, auth/RRN if present.
- [ ] On `failed` / abandon: no sale completion; allow retry with new `client_reference`.

### Receipt / payment recording

- [ ] Keep Odoo receipt / session / Cash Up consistent with recorded Card tender.
- [ ] Optional: surface masked PAN / RRN on order chatter for support (no full PAN).

---

## Values to provide to Avea DEV after Yoco setup

Hand these to Cursor (via secure channel / server env — **not** committed to git):

| Value | Notes |
| --- | --- |
| **API base URL** | Expect `https://api.yoco.com` (Live). Confirm if sandbox host is usable. |
| **Personal API key / Bearer token** | From Developer Console after Save. |
| **Application name / id** | e.g. Avea Dashboard Yoco |
| **Granted scopes list** | Exact permissions enabled |
| **Yoco business / merchant identity** | Which business the key belongs to |
| **Neo Touch serial(s)** | And nicknames / which till |
| **Yoco Support answer** | Especially: can this Personal key call Web POS? If yes, sample successful `POST /v1/webpos/` + payment create. |
| When OAuth exists later | `client_id`, `client_secret`, allowed redirect URI(s), approved scopes |

Optional but useful:

| Value | Notes |
| --- | --- |
| Test till / POS config name on DEV | Which Odoo POS should own the integration |
| Preferred Card payment method name | e.g. existing “Card” vs new “Yoco Card” |
| Webhook signing secret | Only if you enable webhooks |

---

## Suggested order of operations

1. **You:** Add the available permissions above → Save Personal Live app → copy API key.  
2. **You:** Confirm Neo Touch is online on that same Yoco business.  
3. **You:** Ask Yoco the Web POS / OAuth / Sandbox questions (gate).  
4. **You:** Send Cursor the table of DEV values (and Yoco’s answer).  
5. **Cursor:** Implement and test on DEV only after Web POS access is proven.

---

*No Avea code or production changes in this step.*
