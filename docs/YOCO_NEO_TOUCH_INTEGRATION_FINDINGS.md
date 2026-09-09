# Yoco Neo Touch — Third-Party POS Integration Findings

**Date:** 2026-09-08  
**Scope:** Read-only review of the public [Yoco Developer Hub](https://developer.yoco.com/) and related Help Centre material.  
**Goal:** Identify the supported way for a third-party POS (e.g. Avea / Odoo web POS) to start an in-person Neo Touch card payment and receive the result.  
**Status:** Investigation only — no Avea code or production changes.

---

## Verdict

For a **browser / server-based third-party POS**, the publicly documented mechanism that initiates Neo Touch in-person card payments and returns an outcome is the **Yoco Web POS API** under the versioned Yoco API (`https://api.yoco.com/v1/webpos/...`).

There is a second path — the **native Payment SDK** (iOS/Android) — aimed at native POS apps. Access is **partner-gated** (SDK integration application / limited partners). That is not an open drop-in for a web POS like Odoo.

The **Checkout API** (`payments.yoco.com`) is for **online hosted card checkout**, not Neo Touch in-person payments.

Merchant Help Centre “POS Integrations” (Lightspeed, Loyverse, etc.) describes **pre-built partner apps**, not a public API Avea can call directly.

---

## 1. Supported integration mechanisms

| Mechanism | In-person Neo Touch? | Fit for Avea (web POS) | Access |
| --- | --- | --- | --- |
| **Web POS API** | Yes (docs example uses `"model": "Neo Touch"`) | **Primary fit** | OAuth scopes `business/webpos:*` (OAuth apps only) |
| **Payment SDK** (iOS/Android) | Yes (`charge` + terminal pairing) | Poor fit (native app required) | Limited partners; SDK secret after form approval |
| **Checkout API** | No | Online only | Secret keys / Checkout webhooks |
| **Pre-built POS partners** | Yes (merchant setup) | N/A unless becoming an official partner product | Commercial partner channel |

---

## 2. Web POS API — exact flow (recommended public path)

Base URLs:

- Production: `https://api.yoco.com`
- Sandbox: `https://api.yocosandbox.com`

### Authentication & merchant authorisation

- **JWT Bearer** token on every call (`Authorization: Bearer <token>`).
- Web POS scopes are **OAuth application-only**:
  - `business/webpos:write` — create devices / payment requests  
  - `business/webpos:read` — fetch progress / results  
- OAuth uses **authorization code flow only** (no client credentials, PKCE, device code, or implicit).
- Merchant must log in and **consent** to the app.
- Live OAuth apps require **Yoco review**; sandbox apps can be created/tested without live approval.
- Access token ~**14 days**; refresh token ~**60 days**.
- Personal API keys are for a **single business**; they do **not** list `business/webpos:*` on the scopes page. For multi-merchant SaaS, plan on **OAuth**, not personal keys.
- OAuth apps must use OAuth tokens for merchant data (API keys on OAuth apps are for app-level things such as webhooks).

### “Device” registration (not the Neo Touch itself)

- `POST /v1/webpos/` with `{ "name": "Reception" }` creates a **Web POS device** = logical station / browser instance (Reception, Back Office, Joe’s iPad, …).
- `GET /v1/webpos/{webpos_device_id}` fetches that logical device.
- This is **not** the same as listing physical card machines (`GET /v1/card_machines/`, scope `business/devices:read`).

### Terminal / Neo Touch pairing

- Physical Neo Touch is linked to the merchant in the **Yoco App** (serial number), and must be online (Wi‑Fi / cloud).
- For Web POS, the payment create response returns a **`redirect_url`**. Docs say load it in an **iframe, window, or tab** so the **merchant** can confirm the session and **choose / monitor** the terminal in Yoco’s hosted UI.
- Terminal details (`model`, `serial_number`) appear on the payment **after** an operator selects a terminal or one is auto-selected — not as a required field on create.
- There is **no** documented Web POS API to bind `serial_number` on create payment.
- Native SDK pairing (`Yoco.pairTerminal()` / `YocoSDK.pairTerminal`) applies to the **Payment SDK**, not Web POS.

### Payment initiation

```http
POST /v1/webpos/{webpos_device_id}/payments
Scopes: business/webpos:read + business/webpos:write
```

Body:

- `amount.amount` — integer in **cents**
- `amount.currency` — ISO 4217 (examples use `ZAR`)
- `client_reference` — **required**; host POS reference, echoed back
- `metadata` — optional string map, echoed back

Response includes:

- `id` — Web POS payment id  
- `redirect_url` — merchant UI for confirm / progress  
- `status` — `pending` | `successful` | `failed`  
- Later: `payment_details` (auth id, masked PAN, entry mode, RRN, …) and `terminal` (e.g. Neo Touch + serial)

### Getting the result (callbacks vs polling)

**Documented, reliable host-POS path:**

1. Create payment → store `id` + `client_reference`.
2. Open `redirect_url` for the cashier.
3. **Poll** `GET /v1/webpos/{webpos_device_id}/payments/{payment_id}` until `status` is terminal (`successful` or `failed`).

**Webhooks:**

- Platform webhooks include `payment.created` and `payment.refunded` (plus catalogue/order events).
- There is **no** documented `webpos.payment.*` event type.
- Do **not** treat webhooks alone as a complete Web POS completion contract; use **GET payment** (and optionally correlate with `payment.created` if useful).

### Cancellation

- Web POS API reference exposes only **create device**, **fetch device**, **create payment**, **fetch payment**.
- **No cancel / abort Web POS payment** endpoint is documented.
- Cancellation, if any, would be inside Yoco’s `redirect_url` UI or by treating prolonged `pending` / eventual `failed` as non-success — **not specified** in public docs.
- Payment SDK **does** expose `ResultCode.cancelled` for native flows.

### Timeout

- **No** documented Web POS payment timeout or auto-expire interval.
- Host POS must define its own wait policy and keep polling / UX until `successful` or `failed` (or operator abandons with a clear local policy).

### Duplicate-payment handling

- Web POS create does **not** document an `Idempotency-Key` header (Checkout API does).
- `client_reference` is required and echoed — host POS should use a **unique per attempt** id and refuse to create a second charge while a payment for that sale is still `pending` or already `successful`.
- Re-fetch by `payment_id` rather than blindly re-POSTing.

### Refunds

- Web POS API has **no** create-refund endpoint.
- Yoco API can **list/fetch refunds** (`business/orders:read`); webhook `payment.refunded` exists.
- **In-app card refunds** for SDK integrations use Payment SDK `refund(transactionID:)` (full or partial).
- For Web POS–originated sales, public docs do **not** clearly define a REST “refund this Web POS payment id” call; expect refunds via **Yoco App / partner refund tooling**, and/or SDK if using that stack. Treat REST refund **creation** for Web POS as **underspecified** until Yoco confirms.

### Test / sandbox

- Web POS endpoints list sandbox host: `https://api.yocosandbox.com`.
- Separate sandbox vs live **applications**.
- Sandbox OAuth apps: create/test without live approval; live apps need review.

### Hardware note (Help Centre / partners)

- Third-party Web POS integrators (e.g. SalonBridge) report Web POS works with **Neo Touch** and **Khumo Print**.
- Official Help Centre “POS Integrations” setup guides focus on Lightspeed / Loyverse; Neo Touch uses **cloud/Wi‑Fi**, not Bluetooth, for those partner apps.

---

## 3. Payment SDK path (native only, gated)

- Purpose: charge Neo (and other) readers from a **native** POS app.
- Access: submit **SDK Integration Application**; limited partner capacity.
- Auth: SDK **integration secret** (+ optional business API token for seamless login); environments include production (and SDK-configured environments).
- Pairing: `pairTerminal()` / first `charge` may force pairing UI.
- Result: completion handlers + `PaymentResult.result` (`success`, `cancelled`, `failure`, `inProgress`, connectivity/token/machine errors, etc.).
- Recovery: transaction / integrator transaction lookup APIs.
- Refunds: `refund` with prior `transactionID`, optional partial amount.

Relevant if Avea ships a dedicated iOS/Android POS shell — **not** for current Odoo browser POS without a native bridge.

---

## 4. Requirements & limitations for third-party POS partners

1. Prefer **Web POS API + OAuth** for multi-merchant web POS; request `business/webpos:read` and `business/webpos:write`.
2. Expect a **cashier-facing Yoco UI** (`redirect_url`) — not a fully headless “push amount to serial X” REST call in public docs.
3. **Poll** Web POS payment status; do not rely on undocumented cancel/timeout behaviour.
4. Use strong **`client_reference` / local locking** to avoid double charges.
5. Live OAuth apps need **Yoco vetting**.
6. Native SDK is a **separate, restricted** programme.
7. Checkout API must not be used for Neo Touch in-person acceptance.
8. Refund creation over REST for Web POS payments is **not clearly documented** — confirm with Yoco before promising in-product card refunds.

---

## 5. Implications for Avea (informational)

- Closest documented fit: server-side Web POS create + poll, with POS UI embedding or opening `redirect_url`, after merchant OAuth connect.
- Map Avea till / session / order id into `client_reference` and `metadata`.
- Treat Neo Touch selection as part of Yoco’s hosted step unless Yoco later documents terminal-id on create.
- Partner outreach may still be required for live OAuth approval and clarity on refunds/cancel/timeouts.

---

## Primary sources

- [Yoco Developer Hub](https://developer.yoco.com/) / [docs index](https://yoco.docs.buildwithfern.com/llms.txt)
- Web POS: [Create payment](https://yoco.docs.buildwithfern.com/api-reference/yoco-api/web-pos/create-web-pos-payment-v-1-webpos-webpos-device-id-payments-post), [Fetch payment](https://yoco.docs.buildwithfern.com/api-reference/yoco-api/web-pos/fetch-web-pos-payment-v-1-webpos-webpos-device-id-payments-payment-id-get), [Create device](https://yoco.docs.buildwithfern.com/api-reference/yoco-api/web-pos/create-web-pos-device-v-1-webpos-post)
- [Scopes](https://yoco.docs.buildwithfern.com/docs/api/authentication/scopes) · [OAuth 2.0](https://yoco.docs.buildwithfern.com/docs/api/authentication/oauth) · [Applications](https://yoco.docs.buildwithfern.com/docs/api/authentication/applications)
- [Payment SDK overview](https://yoco.docs.buildwithfern.com/sdks/payment-sdk) · [Prerequisites](https://yoco.docs.buildwithfern.com/sdks/payment-sdk/prerequisites) · [Payment result](https://yoco.docs.buildwithfern.com/sdks/payment-sdk/ios/using-the-sdk/payments/processing-a-payment-result)
- [Webhook event types](https://yoco.docs.buildwithfern.com/api-reference/yoco-api/webhooks/list-webhook-event-definitions-v-1-webhooks-events-get) · [List card machines](https://yoco.docs.buildwithfern.com/api-reference/yoco-api/card-machines/list-card-machines-v-1-card-machines-get)
- Help: [Neo Touch + POS Integrations](https://support.yoco.help/en/articles/362693-setting-up-the-neo-touch-using-pos-integrations)

---

*End of findings. No implementation performed.*
