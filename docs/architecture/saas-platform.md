# Avea SaaS Platform Architecture

**Status:** Authoritative technical reference  
**Version:** 1.2  
**Last updated:** 2026-09-18  
**Audience:** Developers, product owners, operators  

This document describes how Avea becomes a commercially sellable SaaS product built on **Odoo 19 Community**. It is based on the completed SaaS feasibility audit, inspection of the live Pets Empire deployment, and the current `avea_dashboard` codebase.

**Legend for implementation status:**

| Tag | Meaning |
|-----|---------|
| **Implemented** | Exists in production codebase or deployment today |
| **Planned** | Agreed direction; not yet built |
| **Future** | Deliberately deferred |
| **Open decision** | Requires an explicit product/technical choice |

---

## 1. Architecture overview

Avea is a **customer-facing retail product**. Odoo Community is the **business engine** underneath. Customers sign up for Avea, not Odoo. Each customer business runs in an **isolated Odoo database**.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  AVEA CONTROL PLANE (Planned — external to Odoo)                        │
│  avea.com — signup, login portal, billing, entitlements, tenant registry │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ provision / sync / suspend
┌───────────────────────────────▼─────────────────────────────────────────┐
│  EDGE / ROUTING (Planned)                                                │
│  Reverse proxy — TLS, subdomain → Odoo dbfilter, rate limits               │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────────┐
│  ODOO WORKER POOL (Implemented — single instance today)                  │
│  Odoo 19 Community + avea_till module                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                   │
│  │ avea_acme    │  │ avea_pilot2  │  │ ...          │  ← one DB each    │
│  └──────────────┘  └──────────────┘  └──────────────┘                   │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────────┐
│  PostgreSQL 16 (Implemented)                                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### Core architectural principles

1. **Avea owns the product experience** — branding, navigation, terminology, onboarding, signup, billing.
2. **Odoo owns business truth** — products, stock moves, POS orders, accounting entries, taxes, partners.
3. **One database per customer** — strongest isolation fit for Odoo Community SaaS (**Planned**; **Implemented** only as single-tenant Pets Empire today).
4. **Do not duplicate business logic** — extend Odoo models; create Avea models only when a workspace genuinely requires it (ADR-003).
5. **Entitlements live outside Odoo; enforcement lives inside Odoo** — control plane is source of truth for plans; tenant DB uses groups and config flags.
6. **Import and export are platform capabilities** — not feature-local shortcuts. Data moves through Avea-defined formats into/out of Odoo primitives (see §21).

---

## 2. Avea's relationship with Odoo Community

### What Odoo Community provides (**Implemented** engine)

| Domain | Odoo primitive | Avea usage |
|--------|----------------|------------|
| POS | `point_of_sale`, `pos.order`, `pos.session` | Avea POS UI overrides; Cash Up; sessions |
| Stock | `stock.*`, `product.template` | Stock Workspace wraps receive/return/take |
| Accounting | `account.*` | Operations wizards; Receive Stock bills |
| Customers | `res.partner` | Credit ledger; partner extensions |
| Loyalty | `loyalty`, `pos_loyalty` | Avea Promotions wrapper |
| HR / cashier | `pos_hr`, `hr` | Cashier selection in POS |
| Mail | `mail` | Receipt emails; register closure reports |

### What Avea provides (**Implemented** product layer)

| Area | Avea models / UI | Status |
|------|------------------|--------|
| Till / Sessions | `avea.till.*`, session dashboard, sales ledger | **Implemented** |
| Business Overview | `avea.business.overview`, performance, transactions | **Implemented** |
| Stock Workspace | `avea.stock.*`, product catalogue | **Implemented** |
| Customer Credit | `avea.credit.*` | **Implemented** |
| Promotions | `avea.promotion` | **Implemented** |
| Operations | expense, transfer, withdraw, manual journal wizards | **Implemented** |
| Settings (partial) | `avea.business.settings`, printed receipt settings | **Partial** — see §19 |
| POS branding | Avea POS navbar, receipts, payment screen | **Implemented** |
| Customer Centre | — | **Planned** |
| Onboarding | — | **Planned** |
| Menu / UX suppression | Owner/Manager/Cashier roles; Odoo roots hidden for Avea users; Sell; `/web` → Avea Dashboard | **Implemented** (Step 1) |

### Avea module facts (**Implemented**)

| Item | Value |
|------|-------|
| Repository folder | `avea_dashboard/` |
| Technical module name (DB) | `avea_till` (ADR-004 rename to `avea_dashboard` accepted; DB record not yet aligned everywhere) |
| Version | `19.0.3.10.0` |
| License | LGPL-3 |
| Declared `depends` | `point_of_sale`, `pos_hr`, `pos_loyalty`, `account`, `contacts`, `mail`, `purchase_stock` |
| Transitive Community deps | 37 modules (verified on `petsempire_dev`) |
| `application` | `True` — appears as "Avea Dashboard" app |
| Tests | 145 test methods across 17 test files |

### Odoo Enterprise separation (**Implemented** — not in use)

| Check | Result |
|-------|--------|
| Docker image | `Odoo Server 19.0-20260504` Community |
| `web_enterprise` in image | Absent |
| Enterprise modules installed | 0 |

**Decision (do not casually change):** Avea SaaS runs on **Odoo Community only**. No Odoo Enterprise modules, assets, or dependencies.

> **Documentation contradiction:** `docs/development-environment.md` states "Odoo 19 Enterprise". The running containers are Community. This document and deployment reality supersede that line until the env doc is corrected.

---

## 3. System components

### 3.1 Control plane (**Planned**)

External service and database. **Not in the Avea repository today.**

| Responsibility | Examples |
|----------------|----------|
| Customer accounts | Email, password hash, verification state |
| Tenant registry | `tenant_id`, slug, Odoo DB name, subdomain, status |
| Subscriptions | Plan, trial end, payment status |
| Entitlements | Feature flags, user seat limits |
| Provisioning orchestration | Queue jobs: create DB, run init, assign subdomain |
| Billing webhooks | Stripe/Paddle → update subscription state |
| Admin operations | List tenants, suspend, impersonation audit log |

**Does not store:** POS orders, stock quantities, accounting entries (those live in tenant Odoo DBs).

### 3.2 Edge / routing layer (**Planned**)

| Responsibility | Example |
|----------------|---------|
| TLS termination | `*.avea.com` certificates |
| Host-based routing | `acme.avea.com` → Odoo with `dbfilter=^avea_acme$` |
| Security headers | HSTS, CSP where applicable |
| Rate limiting | Login, signup, RPC |

### 3.3 Odoo worker pool (**Implemented** — single tenant)

| Item | Pets Empire today |
|------|-------------------|
| Containers | `odoo-odoo-1` (prod), `odoo-dev` (dev) |
| PostgreSQL | `odoo-db-1` |
| Production DB | `petsempire` |
| Dev DB | `petsempire_dev` |
| `list_db` (prod) | `True` — **must be `False` for SaaS** |
| `dbfilter` | Not configured — **Planned** |
| RAM (server) | ~3.7 GB total — insufficient for multi-tenant at scale |

### 3.4 Template database (**Planned**)

A golden Odoo database used to clone new tenants quickly.

| Property | Target |
|----------|--------|
| Name | `avea_template` (convention) |
| Modules | Minimal SaaS baseline only (see §18) |
| Pre-configured | Chart of accounts placeholder per country, Avea groups, default sequences |
| Not included | Pets Empire data, `om_*`, `muk_*`, AGPL addons |
| Versioning | Template version tag synced with `avea_till` module version |

### 3.5 Avea Odoo module (`avea_till`) (**Implemented**)

The tenant-side product. All customer-facing workspaces, POS customisation, security groups, and post-install hooks.

---

## 4. Data ownership and boundaries

```
┌─────────────────────────────┐     ┌─────────────────────────────┐
│  CONTROL PLANE DB           │     │  TENANT ODOO DB (per customer)│
│  (Planned)                  │     │  (Implemented pattern)        │
├─────────────────────────────┤     ├─────────────────────────────┤
│  avea_account               │     │  res.company                │
│  avea_tenant                │     │  res.users                  │
│  avea_subscription          │     │  res.partner (customers)    │
│  avea_entitlement           │     │  product.template           │
│  avea_billing_event         │     │  pos.order / pos.session    │
│  provisioning_job           │     │  stock.move                 │
│                             │     │  account.move               │
│                             │     │  avea.* models              │
└─────────────────────────────┘     └─────────────────────────────┘
         │                                       │
         │    tenant_id, plan, status            │  business operations
         └────────── sync on provision ──────────┘
                    and on plan change
```

| Data | Owner | Notes |
|------|-------|-------|
| Signup credentials | Control plane | Odoo `res.users` created at provision time |
| Plan / payment status | Control plane | Cached in tenant `ir.config_parameter` optional |
| Products, sales, stock | Tenant Odoo DB | Source of truth |
| Customer PII (retail customers) | Tenant Odoo DB | `res.partner` |
| Feature entitlements (authoritative) | Control plane | Enforced via Odoo groups |
| Email templates / receipt config | Tenant Odoo DB | `res.company` Avea fields |

---

## 5. Tenancy model

### Decision: database-per-customer (**Planned** — **do not casually change**)

| Approach | Verdict |
|----------|---------|
| A — One DB, multi-company | **Rejected** for early Avea SaaS |
| B — One DB per customer | **Accepted** |

### Rationale (from feasibility audit)

| Dimension | DB-per-customer advantage |
|-----------|---------------------------|
| Data isolation | PostgreSQL-level separation |
| Backup / restore | Per-customer dump and restore |
| Customer deletion | `DROP DATABASE` |
| Security blast radius | Compromise of one tenant ≠ all tenants |
| Upgrade risk | Failure isolated to one DB during rollout |

### Trade-offs accepted

- Slower provisioning than adding a company (~2–5 minutes with template clone vs seconds).
- N-database upgrade fan-out after each `avea_till` release.
- More operational tooling required.

### Tenant identity (**Planned** convention)

| Field | Example |
|-------|---------|
| `tenant_id` | `tn_01HXYZ...` (control plane) |
| `slug` | `acme-petshop` |
| PostgreSQL database | `avea_acme_petshop` |
| Subdomain | `acme-petshop.avea.com` |
| Odoo `web.base.url` | `https://acme-petshop.avea.com` |

### Multi-company within a tenant (**Future**)

Avea code includes `groups="base.group_multi_company"` on several wizards (**Implemented** guards). Pets Empire runs **one company** today. Multi-company within a single tenant is a **Future** capability for franchise groups, not required for first SaaS customers.

### Multi-store / multi-location (**Future**)

| Today | Target |
|-------|--------|
| 1 warehouse, 1 POS config (Pets Empire) | Multiple `stock.warehouse` and `pos.config` per tenant |
| Stock Take supports `location_id` | Paid-tier feature; provisioning creates one default location |

---

## 6. Signup → provisioning → first login

### End-to-end flow (**Planned**)

```
1. User visits https://avea.com/signup
2. Submits: email, password, business name, country
3. Control plane creates:
     - avea_account (status: pending_verification)
     - provisioning_job (status: queued)
4. Email verification (optional for MVP — Open decision)
5. Provisioning worker:
     a. CREATE DATABASE avea_<slug> (clone from avea_template OR odoo -i)
     b. odoo -d avea_<slug> --stop-after-init  (if fresh install path)
     c. Odoo shell / RPC:
          - Update res.company (name, country, currency)
          - Create owner res.users (login = signup email)
          - Assign groups: POS manager, Avea cash up, etc.
          - Create pos.config (default till)
          - Set ir.config_parameter: web.base.url, report.url
          - Set avea.onboarding.state = 'welcome' (Planned model)
     d. Register subdomain in reverse proxy
     e. Control plane: tenant.status = active
6. Email: "Your Avea is ready — https://<slug>.avea.com"
7. Owner logs in → redirected to Avea onboarding wizard (Planned)
8. Onboarding complete → Avea Dashboard (Business Overview)
```

### Concrete example

```
avea.com/signup
  → account: jane@acmepets.co.za
  → business: "Acme Pets"
  → country: ZA
  → tenant slug: acme-pets
  → DB: avea_acme_pets
  → URL: https://acme-pets.avea.com
  → company: "Acme Pets" (res.company)
  → owner: jane@acmepets.co.za (res.users, admin-equivalent Avea groups)
  → POS: "Main Till" (pos.config)
  → login → onboarding → open POS
```

### What Odoo can automate today (**Implemented** building blocks)

`post_init_hook` in `avea_dashboard/__init__.py` already runs on module install:

- Enables store credit on all POS configs
- Sets up credit company journals
- Ensures owner wizard journal defaults
- Assigns Avea groups to POS managers and admin

**Planned extension:** `_avea_provision_tenant(company, owner, country)` callable from provisioning script.

### What must be external (**Planned**)

- Signup UI and account storage
- Job queue with retry and rollback
- DNS / TLS / reverse proxy
- Subdomain → `dbfilter` mapping
- Failure alerting and support admin UI

### Current state (**Implemented** — manual only)

Pets Empire was provisioned manually: single Odoo install, single company, module install, configuration by operator. No automated path exists in the repository.

---

## 7. Subdomain, routing, and dbfilter

### Routing model (**Planned**)

```
Request: https://acme-pets.avea.com/web/login
  → Reverse proxy forwards to Odoo
  → Odoo dbfilter matches host → database avea_acme_pets
  → Session scoped to that DB only
```

### Odoo configuration (**Planned** production baseline)

```ini
[options]
list_db = False
dbfilter = ^%d$          # %d = first subdomain label, or explicit map
proxy_mode = True
# db_name not set — multi-DB worker
```

### Development today (**Implemented** — not SaaS-ready)

| Instance | `list_db` | `db_name` |
|----------|-----------|-----------|
| Production (`odoo.conf`) | `True` | unset |
| Dev (`odoo-dev.conf`) | `False` | `petsempire_dev` |

**Security requirement:** `list_db = False` on any public SaaS deployment. Database manager must not be exposed.

### `web.base.url` and PDF reports (**Implemented** — known pitfall)

wkhtmltopdf loads report assets via HTTP from `report.url` or `web.base.url`. In Docker, the external URL may be unreachable from inside the container. Dev requires `report.url = http://127.0.0.1:8069` (documented in `docs/development-environment.md`). **Planned:** provisioning sets both parameters per tenant.

---

## 8. Authentication and authorization

### Authentication model

| Layer | Mechanism | Status |
|-------|-----------|--------|
| Avea marketing / account portal | Control plane auth (email + password, OAuth **Future**) | **Planned** |
| Tenant application | Odoo `res.users` session (cookie) | **Implemented** |
| POS | Odoo POS session + `pos_hr` cashier | **Implemented** |
| API / RPC (provisioning) | Odoo `admin_passwd` or API key per worker — **not customer-facing** | **Planned** hardening |

`auth_signup` is installed (transitive Community dep) but **`auth_signup.invite_scope` is `False`** on Pets Empire — public Odoo signup is disabled. **Planned:** SaaS signup happens at avea.com, not Odoo's native signup form.

### Authorization model: capability-based via groups

**Implemented** Avea-specific groups:

| Group | XML ID | Purpose |
|-------|--------|---------|
| Cashier | `avea_till.group_avea_cashier` | Role profile: POS + own till |
| Manager | `avea_till.group_avea_manager` | Role profile: full Avea nav |
| Owner | `avea_till.group_avea_owner` | Role profile: implies Manager; no `group_system` |
| Cash Up User | `avea_till.group_avea_cash_up_user` | Cash up own till |
| Cash Up Manager | `avea_till.group_avea_cash_up_manager` | Cash up any till |
| Credit Manager | `avea_till.group_avea_credit_manager` | Issue store credit |
| Correct Payment | `avea_till.group_avea_correct_payment` | Payment correction in POS |

**Implemented** Odoo groups in use: `point_of_sale.group_pos_user`, `group_pos_manager`, `base.group_user`, `base.group_system`.

### Role profiles (**Implemented** — Step 1)

Roles compose the capability groups above. They do not replace them.

| Avea role | Odoo / Avea groups | Menus visible |
|-----------|--------------------|---------------|
| Owner | Implies Manager (POS manager + all Avea capabilities). No `base.group_system` | Full Avea nav including Sell; no Odoo Apps/Settings |
| Manager | Implies Cashier + POS manager + operational Avea groups | Full Avea nav including Sell; no Odoo Apps/Settings |
| Cashier | POS user + stock user + cash up user | Sell + Sessions (own till) |

Settings administrators (`base.group_system`) keep the full Odoo backend so operators can still reach underlying functionality. Standard Avea users never receive `group_system`.

### Entitlement enforcement (**Planned**)

```
Control plane entitlement "loyalty"
  → provisioning/sync job
  → ensure pos_loyalty installed (if not in template)
  → assign groups / set ir.config_parameter avea.feature.loyalty=true
  → Avea menus for Promotions visible

Control plane entitlement revoked
  → remove group / set flag false
  → deactivate promotions (soft)
```

**Do not rely on groups alone** without hiding Odoo Settings — a user with `base.group_system` can self-assign groups. Standard Avea users never receive `group_system`. Settings administrators keep Odoo Settings for operations.

---

## 9. Free vs Paid plans and entitlements

### Plan model (**Planned**)

| Tier | Intended capabilities |
|------|----------------------|
| **Free** | POS, products, customers (basic), basic stock, cash up, basic reports |
| **Paid / add-ons** | Extra users, loyalty/promotions, customer credit, advanced stock, accounting, multi-location, integrations |

### Enforcement architecture (**Planned** — **do not casually change**)

| Layer | Role |
|-------|-------|
| **Control plane** | Authoritative: plan, trial end, payment status, feature list, seat count |
| **Sync job** | On change: RPC into tenant → update groups, install modules, set `ir.config_parameter` |
| **Odoo groups** | Menu visibility, model access, record rules |
| **`ir.config_parameter`** | Tenant-readable flags for Avea Python/JS (`avea.feature.*`) |
| **Avea UI** | Hide paid menus when flag false; server-side checks on write |

### Example entitlement mapping (**Planned**)

| Feature | Free | Paid enforcement |
|---------|------|------------------|
| POS | ✓ default on provision | — |
| Stock Workspace | ✓ | — |
| Promotions / Loyalty | ✗ | Install `pos_loyalty`; show Promotions menu |
| Customer Credit | ✗ | Assign `group_avea_credit_manager` |
| Extra users | 2 seats | Control plane blocks user create; Odoo check on `res.users` create |
| Accounting (`account` reports) | ✗ | Module install + menu group |
| Multi-location | ✗ | Restrict `stock.warehouse` create |

### Free → Paid flow (**Planned**)

```
1. Owner clicks Upgrade in Avea (or billing portal)
2. Stripe Checkout / Customer Portal
3. Webhook → control plane: subscription.status = active, plan = pro
4. Sync job → tenant RPC:
     - Update ir.config_parameter avea.plan = pro
     - Assign paid groups
     - Install optional modules if not in template
5. Owner sees new menus on next page load (or immediate bus notification)
```

No plan enforcement exists in the codebase today.

---

## 10. Billing and subscription architecture

### Scope

Billing is **explicitly out of scope for first implementation** but architecturally defined here.

### What lives outside Odoo (**Planned**)

| Entity | Store |
|--------|-------|
| Customer account (Avea identity) | Control plane |
| Subscription | Control plane + Stripe/Paddle |
| Plan definition | Control plane |
| Payment method | Payment provider |
| Invoice history (Avea subscription) | Payment provider / control plane |
| Trial / cancellation / suspension | Control plane state machine |

### Payment provider (**Open decision**)

| Option | Notes |
|--------|-------|
| Stripe | Common for SaaS; subscriptions + portal |
| Paddle | Merchant of record; simpler tax |
| Paystack | **Open decision** — relevant for ZA market |

### Communication with tenant Odoo (**Planned**)

```
Billing webhook
  → control plane updates subscription
  → enqueue entitlement_sync(tenant_id)
  → worker calls Odoo XML-RPC/JSON-RPC with admin credentials
  → update groups, config parameters, optional module install/uninstall

Periodic reconciliation (optional)
  → daily job verifies tenant flags match control plane
```

Odoo is **never** the subscription system of record.

### Suspension and cancellation (**Planned**)

| State | Behaviour |
|-------|-----------|
| `active` | Normal operation |
| `past_due` | Banner in Avea; grace period (**Open decision:** duration) |
| `suspended` | Login blocked OR read-only mode via `avea.tenant.suspended` config flag |
| `cancelled` | End of period → suspended → eventual DB archive |
| `deleted` | Export data window → `DROP DATABASE` after retention period |

**Open decision:** Hard block login vs read-only for suspended tenants.

---

## 11. Tenant lifecycle

```
┌──────────┐    ┌────────────┐    ┌────────┐    ┌─────────────┐
│ pending  │───►│ provisioning│───►│ active │───►│ past_due    │
└──────────┘    └────────────┘    └────────┘    └──────┬──────┘
                              │                          │
                              │                    ┌─────▼──────┐
                              │                    │ suspended  │
                              │                    └─────┬──────┘
                              │                          │
                              │                    ┌─────▼──────┐
                              └───────────────────►│ cancelled  │
                                                   └─────┬──────┘
                                                         │
                                                   ┌─────▼──────┐
                                                   │ archived   │
                                                   │ (DB backup │
                                                   │  + drop)   │
                                                   └────────────┘
```

| State | DB exists | User access | Backups |
|-------|-----------|-------------|---------|
| provisioning | being created | none | none |
| active | yes | full per plan | scheduled |
| suspended | yes | blocked/read-only | continue |
| cancelled | yes → archived | none | retention period |
| deleted | dropped after export | none | cold archive only |

---

## 12. Deployment architecture

### Current deployment (**Implemented**)

| Component | Detail |
|-----------|--------|
| Host | Single Ubuntu server, Docker Compose |
| Production | `odoo-odoo-1:8069`, DB `petsempire` |
| Development | `odoo-dev:8070`, DB `petsempire_dev` |
| Addons path (prod) | `/mnt/extra-addons` → `/opt/odoo/addons` |
| Addons path (dev) | `/mnt/custom-addons/avea_till` + `/mnt/extra-addons` |
| PostgreSQL | `odoo-db-1`, version 16 |

### Target SaaS deployment (**Planned**)

| Component | Target |
|-----------|--------|
| Control plane | Separate app (language **Open decision**) + PostgreSQL |
| Odoo workers | Horizontally scaled; shared worker pool, many DBs |
| PostgreSQL | Managed or self-hosted; connection pooling (PgBouncer **Future**) |
| Template DB | On same PG cluster; cloned via `CREATE DATABASE ... TEMPLATE` |
| Object storage | Tenant export archives (S3-compatible **Planned**) |
| Secrets | Vault or env-based; rotate `admin_passwd` per environment |

### Clean separation from Pets Empire (**Planned**)

Pets Empire production has **105 installed modules** including third-party addons not required by Avea. The SaaS template must **not** copy this module set. See §18.

---

## 13. Backup and restore strategy

### Current state (**Implemented** — manual / operator-dependent)

No automated per-tenant backup is documented in the repository. Pets Empire relies on server-level practices.

### Target strategy (**Planned**)

| Scope | Method | Frequency |
|-------|--------|-----------|
| Per-tenant DB | `pg_dump -Fc avea_<slug>` | Daily minimum |
| Template DB | `pg_dump` after each template version bump | On release |
| Control plane DB | Managed backup | Daily |
| Filestore per tenant | `/var/lib/odoo/filestore/avea_<slug>` rsync/sync | Daily with DB |

### Restore procedure (**Planned**)

1. `pg_restore` into new database OR restore over existing (maintenance window).
2. Verify `ir.config_parameter` `web.base.url` matches subdomain.
3. Run `-u avea_till` if module version behind worker.
4. Smoke test: login, POS open, one product.

### Customer data export (**Planned** — regulatory)

On cancellation: offer owner-facing CSV export (products, customers, sales, transactions — see §21.4) before archive, plus control plane PostgreSQL/filestore dump. Implementation **Future**; architecture reserves `avea.export.job` (tenant) and `export_job` (control plane).

---

## 14. Upgrades and version management

### Avea module upgrades (**Implemented** process)

Documented in `docs/deployment.md`:

1. Test on `petsempire_dev`
2. Deploy to production
3. `-u avea_till` (technical name)
4. Restart Odoo workers

### SaaS upgrade fan-out (**Planned**)

```
Release avea_till 19.0.3.10.0
  → update template DB (avea_template)
  → for each active tenant (staged rollout):
       odoo -d avea_<slug> -u avea_till --stop-after-init
       smoke test
       mark tenant.avea_version = 19.0.3.10.0
```

| Strategy | When |
|----------|------|
| Big bang all tenants | Small tenant count (<20) |
| Staged rollout | 10% → 50% → 100% with monitoring |
| Canary | New tenants on new version first |

### Odoo core upgrades (19 → 20) (**Future**)

Major Odoo version upgrades across N databases are a **known high-risk** operation. Plan separately from Avea module releases.

### Template versioning (**Planned**)

Template DB carries `ir.config_parameter` `avea.template_version`. New tenants get latest; existing tenants upgraded via fan-out.

---

## 15. Monitoring and operational requirements

### Required monitoring (**Planned**)

| Signal | Alert threshold (initial) |
|--------|---------------------------|
| Odoo worker health | HTTP 5xx on `/web/health` or login |
| PostgreSQL connections | >80% max |
| Disk usage | >85% |
| Provisioning job failure | Any failed job |
| Backup failure | Any missed daily backup |
| Tenant login errors spike | Anomaly per tenant |

### Operational runbooks (**Planned**)

- Provision new tenant
- Suspend / unsuspend tenant
- Restore tenant from backup
- Upgrade tenant module
- Rotate secrets
- Impersonate tenant (support) with audit log

### Admin architecture (**Planned**)

| Tool | Purpose |
|------|---------|
| Control plane admin UI | Tenant list, status, plan, re-provision |
| Support impersonation | Generate one-time Odoo login link — **audit logged** |
| Internal Grafana/Datadog | Infrastructure metrics |

No admin tooling exists in the repository today.

---

## 16. Security requirements

### Implemented today

- Odoo standard auth (password, optional TOTP via `auth_totp`)
- Avea record rules for cash up (own till vs manager)
- `proxy_mode = True`

### Required for SaaS (**Planned**)

| Requirement | Detail |
|-------------|--------|
| `list_db = False` | Prevent database enumeration |
| Strong `admin_passwd` | Per environment; not shared with customers |
| `dbfilter` | Strict host → DB mapping |
| TLS everywhere | `*.avea.com` |
| Tenant isolation verification | Automated test: tenant A cannot access tenant B data |
| Least-privilege groups | Owners never get `base.group_system` by default |
| Secrets management | No credentials in git |
| Rate limiting | Login and signup endpoints |
| AGPL compliance | Remove `server_action_mass_edit` from SaaS template (see §18) |

### Email and notifications

| Type | Implementation | Status |
|------|----------------|--------|
| POS receipt email | `mail.template`, `avea.business.settings` | **Implemented** |
| Register closure (Z) report | `avea_register_closure_report_email` on `res.company` | **Implemented** |
| Provisioning welcome email | Control plane + SMTP | **Planned** |
| Billing emails | Payment provider | **Planned** |
| Password reset | Odoo `auth_signup` reset flow OR control plane | **Open decision** |

Outbound mail today uses Odoo `ir.mail_server` configuration per instance (**Implemented**). **Planned:** provisioning configures SMTP or delegates to transactional provider (SendGrid, Postmark).

---

## 17. Avea branding and Odoo UX suppression

### Implemented branding

| Surface | Branding |
|---------|----------|
| POS | "Avea POS" wordmark (`static/src/pos/navbar.xml`) |
| Backend app | "Avea Dashboard" (`views/menu.xml`) |
| Backend chrome | Avea title, favicon, login mark, navbar colour (`views/ux/branding.xml`, `static/src/scss/ux/avea_backend.scss`) |
| Reports | `avea_report_branding.xml`, `avea_report_layout.xml` |
| Receipts | Avea email and print templates |

### Odoo UX suppression (**Implemented** — Step 1)

Normal Avea users (Owner / Manager / Cashier, without `base.group_system`) see only the Avea Dashboard app. Non-Avea root menus stay installed and reachable by Settings administrators and by direct URL/RPC; they are filtered out of `ir.ui.menu._visible_menu_ids`.

`/web` and `/odoo` use the user's Avea home action (Business Overview for Manager/Owner, Session Dashboard for Cashier). **Sell** launches the existing Avea POS.

### Avea native navigation (**Implemented** — Step 1 nav, ADR-015)

The Odoo `NavBar` is replaced by an **AveaNav** sidebar shell for product-shell users:

| Pattern | Purpose |
|---------|---------|
| Left sidebar | Modern SaaS layout; default expanded, optional pin/collapse |
| Standalone Home | Business Overview (Manager/Owner) or Today's Session (Cashier) |
| Accordion sections | Business, Sessions, Stock, Customers, Money — nested groups where needed |
| Sell CTA | Full-width primary button at top of sidebar |
| Settings footer | Separated at bottom of sidebar, not a business area |
| Minimal top bar | Company name + Avea user menu (no Odoo systray); page-level sub-nav stays in content |
| Mobile drawer | Hamburger opens the same sidebar structure |
| Server-driven payload | `session.avea_nav` from `avea.nav.mixin`, filtered by role rank and menu visibility |

**Cashier:** Home + Sell only. **Manager/Owner:** Home, Sell, accordion sections, and Settings footer. Existing menu XML IDs and routes are unchanged. POS still uses Odoo POS chrome when Sell opens.

MuK (`muk_web_theme`) may still be installed on Pets Empire. It is **not** an Avea dependency and is not the Avea theme.

### Remaining branding leaks (**Planned**)

Systray, some breadcrumbs, POS chrome, and error messages that say "Odoo" are not fully rewritten. Settings, onboarding, and Customer Centre are later steps.

---

## 18. Clean Community installation requirements

### SaaS template module baseline (**Planned**)

**Install (minimum):**

```
base, web, mail, contacts, account, stock, product, purchase, purchase_stock,
point_of_sale, pos_hr, pos_loyalty, loyalty, barcodes, l10n_<country>, avea_till
```

37 transitive Community modules will install automatically with the above.

### Explicitly exclude from SaaS template

| Module / family | Reason |
|-----------------|--------|
| All Odoo Enterprise | Licensing, not in image |
| `om_*`, `accounting_pdf_reports` | Third-party; not Avea deps; Pets Empire only |
| `muk_web_*` | Third-party theme; optional cosmetic |
| `server_action_mass_edit` | **AGPL-3** — network copyleft risk for SaaS |
| `pos_receipt_clean` | No license in manifest |
| `sale`, `sale_stock`, `sale_management` | Not Avea deps; exposes Sales app |
| `spreadsheet_dashboard_*` | Exposes Dashboards app |
| OCA bank import modules | Phase 5; not first launch |

### Third-party licensing summary

| Component | License | SaaS template |
|-----------|---------|---------------|
| Odoo Community | LGPL-3 | ✓ |
| Avea (`avea_till`) | LGPL-3 | ✓ |
| Odoo Mates (`om_*`) | LGPL-3 | ✗ (exclude) |
| MuK (`muk_*`) | LGPL-3 | ✗ (exclude unless product decision) |
| OCA `server_action_mass_edit` | AGPL-3 | ✗ (remove) |
| `pos_receipt_clean` | Unspecified | ✗ (replace with Avea code if needed) |

### Odoo IAP (`iap`, `partner_autocomplete`)

Installed as POS transitive dependencies. Uses Odoo cloud services for partner autocomplete. **Open decision:** disable for SaaS tenants or accept Odoo IAP ToS.

---

## 19. Control plane vs tenant responsibilities

| Concern | Control plane | Tenant Odoo |
|---------|---------------|-------------|
| Signup / account | ✓ | — |
| Billing / subscription | ✓ | cache only |
| Entitlements (authoritative) | ✓ | enforce |
| Provisioning | ✓ orchestrate | ✓ receive config |
| Products / sales / stock | — | ✓ |
| POS operations | — | ✓ |
| Customer PII (shoppers) | — | ✓ |
| Email receipt content | — | ✓ |
| User authentication (app) | — | ✓ |
| Onboarding state | mirror optional | ✓ primary |
| Backups | orchestrate | data store |
| Upgrades | orchestrate fan-out | `-u avea_till` |

---

## 20. What belongs in Avea vs Odoo primitives

| Concern | Owner | Rationale |
|---------|-------|-----------|
| POS sale, payment, refund | Odoo `pos.order` | Battle-tested; Avea extends |
| Stock valuation, moves | Odoo `stock.*` | ADR-005: no parallel ledger |
| Accounting entries | Odoo `account.move` | ADR-003 |
| Customer record | Odoo `res.partner` | Single source of truth |
| Retail workspaces | Avea `avea.*` | Simplified UX |
| Business overview / KPIs | Avea transient models | Presentation layer |
| Cash up workflow | Avea `avea.cash.up` | Domain-specific |
| Store credit ledger | Avea `avea.credit.ledger.entry` | Avea product concept |
| Promotions UX | Avea `avea.promotion` | Wraps `loyalty.program` |
| Signup, billing, plans | Control plane | Not Odoo's domain |
| Menu / branding | Avea module | Product identity |
| Import / export jobs | Avea `avea.import.*` / `avea.export.*` (**Planned**) | Platform capability; Odoo stores data |
| CSV / file templates | Avea-defined schemas | Product-owned interchange format |

---

## 21. Import and export (platform capability)

Import and export are **platform-wide Avea capabilities**. They are not owned by Customer Centre, Stock Workspace, or any single feature menu. Every workspace may *surface* import/export actions, but the **engine, formats, job model, and permissions** are shared.

**Status today:** **Not implemented** as an Avea product surface. Odoo's generic `base_import` is available in Community but is **not** part of Avea's SaaS template strategy and must not be exposed to retail users (see §18).

### 21.1 Strategic goals

| Goal | Detail |
|------|--------|
| **Onboarding** | New tenants bring products, customers, and opening stock from spreadsheets or prior systems |
| **Migration** | Legitimate business data moves from tools like ShakeYourTail (see `docs/PHASE_5.md`) without parallel databases |
| **Operations** | Owners periodically bulk-update catalogue or customer lists |
| **Compliance & offboarding** | Tenants export their data; Avea exports on cancellation before archive |
| **Support** | Operators assist with validated imports under audit |

### 21.2 Architectural placement

```
┌─────────────────────────────────────────────────────────────────┐
│  AVEA UI (Planned)                                               │
│  Settings → Data  OR  top-level "Import / Export" workspace    │
│  + contextual actions in Stock, Customers, Reports             │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│  AVEA IMPORT/EXPORT ENGINE (Planned — tenant Odoo)               │
│  avea.import.job / avea.export.job                               │
│  Validation → preview → apply (import) / generate (export)       │
└────────────────────────────┬────────────────────────────────────┘
                             │ writes / reads
┌────────────────────────────▼────────────────────────────────────┐
│  ODOO PRIMITIVES (source of truth — Implemented)                 │
│  product.template, res.partner, stock.quant / stock take,        │
│  pos.order, avea.business.transaction, account.move, …           │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  CONTROL PLANE (Planned — tenant lifecycle export only)          │
│  Full DB archive on cancellation; not day-to-day business export │
└─────────────────────────────────────────────────────────────────┘
```

**Decision (do not casually change):** Business import/export runs **inside the tenant Odoo DB** via Avea jobs. Full-database export on tenant deletion is a **control plane** operator action (PostgreSQL dump + filestore), separate from owner-facing CSV exports.

### 21.3 Import domains (Future product roadmap)

| Domain | Target Odoo primitive | Avea entry point (Planned) | Priority |
|--------|----------------------|----------------------------|----------|
| **Products** | `product.template` (+ `product.supplierinfo`) | Stock → Import Products; onboarding | P1 |
| **Customers** | `res.partner` (customer_rank) | Customers → Import; onboarding | P1 |
| **Opening stock** | `avea.stock.take` → apply inventory adjustment | Stock → Import Opening Stock; onboarding | P1 |
| **Suppliers** | `res.partner` (supplier_rank) | Stock → Import Suppliers | P2 |
| **Categories / brands** | `product.category`, `product.tag` | Stock → Import (embedded or separate) | P2 |
| **Opening balances / accounting** | `account.move` (opening entry) | Money / Accounting (**Future**, Phase 5) | P3 |
| **Promotions** | `avea.promotion` / `loyalty.program` | Promotions | P3 |

#### Product import — field mapping (Planned)

Imports write **underlying Odoo fields**, not Avea computed columns. The Stock Workspace displays computed Avea pricing fields (`avea_markup_percent`, `avea_margin_percent`, etc.) but imports must set:

| CSV column (Avea format) | Odoo field | Notes |
|--------------------------|------------|-------|
| `sku` | `default_code` | **Primary match key** for updates |
| `barcode` | `barcode` | Secondary match key |
| `name` | `name` | Required on create |
| `cost_ex_vat` | `standard_price` | ADR-008: cost is EX tax |
| `retail_inc_vat` | `list_price` | ADR-008: retail is INC tax |
| `sales_tax` | `taxes_id` | Resolve by name or rate — country-specific |
| `category` | `categ_id` | Match by name or create (**Open decision**) |
| `sell_on_pos` | `available_in_pos` | Boolean |
| `track_stock` | `is_storable` / tracking flags | Maps to Odoo stock settings |
| `supplier_name` | `seller_ids` via `avea_supplier_id` | Optional |
| `import_ref` | `avea_import_ref` | **Design-now field** — see §21.8 |

#### Customer import — field mapping (Planned)

| CSV column | Odoo field | Notes |
|------------|------------|-------|
| `email` | `email` | Primary match key when present |
| `phone` | `phone` / `mobile` | Secondary match key |
| `name` | `name` | Required on create |
| `street`, `city`, `zip` | address fields | Optional |
| `import_ref` | `avea_import_ref` | **Design-now field** |

#### Opening stock import (Planned)

Opening stock **must not** write quantities directly to a custom table. It must use the same authoritative path as Stock Take (**Implemented**):

1. Create `avea.stock.take` in `review` mode with scope `partial` or `everything`.
2. Populate `avea.stock.take.line` with `counted_qty` from CSV (`sku` / `barcode` match).
3. User previews variances (or onboarding skips review with explicit confirmation).
4. Apply via existing stock take apply logic → Odoo inventory adjustment.

This reuses `avea.stock.take` / `avea.stock.take.line` and avoids a second stock-correction code path (ADR-003).

### 21.4 Export domains (Future product roadmap)

Exports produce **Avea-branded CSV/XLSX** (and PDF where a report already exists). Prefer **Avea read models and workspaces** over raw Odoo technical exports.

| Domain | Source | Avea entry point (Planned) | Format | Priority |
|--------|--------|----------------------------|--------|----------|
| **Products** | `product.template` | Stock → Export | CSV/XLSX | P1 |
| **Customers** | `res.partner` | Customers → Export | CSV/XLSX | P1 |
| **Sales / POS orders** | `pos.order` | Sessions / Reports | CSV/XLSX | P1 |
| **Transactions** | `avea.business.transaction` (**Implemented** view) | Business Overview → Export | CSV/XLSX | P1 |
| **Stock on hand** | `product.template` + `qty_available` | Stock → Export | CSV/XLSX | P1 |
| **Stock movements** | `stock.move` / receive records | Stock → Export | CSV/XLSX | P2 |
| **Store credit ledger** | `avea.credit.ledger.entry` | Customer Credit → Export | CSV/XLSX | P2 |
| **Cash ups** | `avea.cash.up` | Sessions → Export | CSV/XLSX | P2 |
| **Accounting / GL** | `account.move.line` | Money / Accounting (**Future**) | CSV/XLSX | P3 |
| **Full business backup** | Tenant DB | Settings → Data (owner request) | ZIP of CSVs | P2 |
| **Tenant archive** | PostgreSQL + filestore | Control plane on cancellation | Operator dump | P1 (ops) |

**Decision:** Transaction exports for owners use `avea.business.transaction` (ADR-012), not duplicated exports of `pos.payment`, `account.bank.statement.line`, and till movements separately.

### 21.5 Planned job model (not yet built)

| Model | Purpose |
|-------|---------|
| `avea.import.job` | Uploaded file, type (`product`, `customer`, `opening_stock`, …), state (`draft`, `validated`, `applied`, `failed`), error log, row counts |
| `avea.import.job.line` | Per-row validation result, match action (`create`, `update`, `skip`, `error`) |
| `avea.export.job` | Requested export type, filters (date range, category), state, output `ir.attachment` |

Shared infrastructure (**Planned**):

- File upload → `ir.attachment` linked to job
- Async processing for large files (Odoo `queue_job` **Open decision** vs cron chunks)
- Owner notification on completion (mail / bus)
- Audit: `create_uid`, `applied_at`, downloadable error report

### 21.6 Permissions and entitlements

| Capability | Default role | Paid tier (**Planned**) |
|------------|--------------|-------------------------|
| Export products/customers/sales | Owner, Manager | Free (read own data) |
| Import products/customers | Owner | Free (with row limits **Open decision**) |
| Import opening stock | Owner | Free at onboarding only vs always — **Open decision** |
| Export accounting | Owner | Paid / accounting add-on |
| Support-initiated import | Avea operator | Internal only |

Enforce via Avea groups (e.g. `group_avea_data_import`, `group_avea_data_export`) plus optional `ir.config_parameter` row limits for Free tier.

### 21.7 UX placement (Planned)

Import/export is **not** buried inside Customer Centre alone.

| Surface | Import | Export |
|---------|--------|--------|
| **Settings → Data** | All types, history, templates download | All types, job history |
| **Stock Workspace** | Products, opening stock | Products, stock on hand |
| **Customer Centre** | Customers | Customers |
| **Business Overview / Transactions** | — | Transactions, sales summaries |
| **Onboarding wizard** | Simplified product + opening stock + customers | — |

### 21.8 Design now to avoid future rework

The following should be respected **in current and near-term feature work** even before the import/export engine is built. One optional minimal code addition is flagged.

| # | Design rule | Rationale | Action now |
|---|-------------|-----------|------------|
| DN-1 | **SKU (`default_code`) is the canonical product match key** | Stable across import, export, POS, stock | Already true in Stock Workspace — do not introduce parallel product codes |
| DN-2 | **Email / phone are canonical customer match keys** | Import deduplication | Use in Customer Centre list columns |
| DN-3 | **Imports write Odoo base fields, not Avea computed fields** | `avea_markup_percent` etc. are derived (ADR-008) | Document in Stock/import specs; validation in future job |
| DN-4 | **Opening stock uses `avea.stock.take` apply path** | Single stock correction mechanism | Do not add a separate "opening balance" quantity table |
| DN-5 | **Exports use Avea read models where they exist** | Consistent owner-facing columns | `avea.business.transaction` for money history |
| DN-6 | **Do not expose Odoo `base_import` or raw list Export in SaaS** | UX and terminology leak | Suppress with menu/security strategy (§17) |
| DN-7 | **Add `avea_import_ref` on `product.template` and `res.partner`** | Stable external ID for re-import and migrations (ShakeYourTail, etc.) | **Recommended minimal field now** — optional Char, indexed; no import UI yet |
| DN-8 | **CSV templates are versioned** | `avea.import.format.version` in template header row | Define when first import ships |
| DN-9 | **No parallel staging tables for business entities** | ADR-003 | Job lines are validation metadata only, not a second product catalogue |
| DN-10 | **Control plane full export ≠ owner CSV export** | Different audiences and formats | Keep architectures separate (§11, §13) |

#### Optional minimal implementation (recommended, not required for next sprint)

Adding `avea_import_ref` (Char, indexed, copy=False) to `product.template` and `res.partner` is ~30 lines and prevents painful deduplication logic later. **No import UI required yet.** If deferred, imports must rely on SKU/email only and migration from systems without SKUs becomes harder.

### 21.9 Relationship to other roadmap items

| Roadmap item | Import/export dependency |
|--------------|-------------------------|
| **UX suppression** | Must hide Odoo native import/export on list views |
| **Settings consolidation** | "Data" section hosts platform import/export hub |
| **Onboarding** | First import of products, customers, opening stock |
| **Customer Centre** | Customer import/export actions link to shared engine |
| **SaaS cancellation** | Control plane archive complements owner CSV export |

### 21.10 Phased delivery

| Phase | Scope | Status |
|-------|-------|--------|
| **0 — Design hooks** | DN-1–DN-7; optional `avea_import_ref` fields | **Planned** |
| **1 — Export MVP** | Products, customers, transactions CSV | **Future** |
| **2 — Import MVP** | Products, customers with preview/validate | **Future** |
| **3 — Opening stock import** | Via stock take apply | **Future** |
| **4 — Accounting export** | With Phase 5 Money workspace | **Future** |
| **5 — Support tooling** | Operator import on behalf of tenant | **Future** |

---

## 22. What is already implemented

| Area | Evidence |
|------|----------|
| Avea retail product (POS, till, stock, credit, promotions, operations) | `avea_dashboard/` v`19.0.3.11.0` |
| Odoo 19 Community engine | Docker image, 0 Enterprise modules |
| Single-tenant production (Pets Empire) | `petsempire` DB, 1 company, 1 POS |
| Post-install automation | `post_init_hook` in `__init__.py` |
| Avea security groups | `security/till/`, `security/credit/`, `security/ux/` |
| Partial Avea Settings | Email receipt, printed receipt (ADR-011) |
| POS branding | `navbar.xml`, receipt templates |
| Backend product shell | Roles, menu suppression, Sell, `/web` redirect, Avea chrome (ADR-014) |
| Avea native navigation | AveaNav section + sub-nav, role-filtered `session.avea_nav` (ADR-015) |
| Business reporting | Overview, performance, transactions (ADR-010, ADR-012) |
| Dev/prod Docker deployment | `docs/development-environment.md` |
| Architecture ADRs | `docs/decisions.md` ADR-001 through ADR-014 |

---

## 23. What still needs to be built

### Platform (SaaS)

| Component | Priority |
|-----------|----------|
| Control plane (accounts, tenants, entitlements) | P0 |
| Template database | P0 |
| Provisioning worker | P0 |
| Subdomain routing + `dbfilter` | P0 |
| Menu / UX suppression | P0 — **Implemented** Step 1 (roles, hide Odoo roots, AveaNav, Sell, `/web` redirect) |
| Onboarding wizard | P0 |
| Automated backups per tenant | P0 |
| Signup UI (avea.com) | P0 |
| Upgrade fan-out tooling | P1 |
| Billing integration | P1 |
| Support admin / impersonation | P1 |
| Tenant archive export (control plane) | P1 |
| Multi-location provisioning | P2 |

### Import / export platform (see §21)

| Component | Priority |
|-----------|----------|
| Design hooks (`avea_import_ref`, DN-1–DN-7) | P1 |
| Export MVP (products, customers, transactions) | P2 |
| Import MVP (products, customers, preview) | P2 |
| Opening stock import (via stock take) | P2 |
| Settings → Data hub UI | P2 |
| Accounting export | P3 (with Phase 5) |

### Product layer (pre-SaaS polish)

See §24 and the implementation roadmap communicated separately.

---

## 24. Pre-SaaS product layer completion

Before or in parallel with first external tenant, these Avea product gaps identified in the feasibility audit should be addressed. **None are implemented as complete product surfaces today.**

| Area | Current state | Target |
|------|---------------|--------|
| **Customer Centre** | `res.partner` extensions for credit; Odoo Contacts app exposed | Avea Customers workspace |
| **Settings consolidation** | Email/printed receipt in Avea; cash/journal/POS settings still in Odoo Settings | All owner settings in Avea Settings |
| **Odoo UX suppression** | AveaNav for Owner/Manager/Cashier; Settings admins keep Odoo apps | Remaining: POS chrome, deeper "Odoo" string leaks; SaaS template without Sales/Dashboards |
| **Customer onboarding** | None | First-login wizard: business → till → product → open POS |
| **Import / export** | Not implemented (Odoo native import hidden in SaaS) | Platform capability under Settings → Data (§21) |

Recommended implementation order is documented in project planning discussions; architectural dependency is:

1. **UX suppression** — **Implemented** Step 1. Do not reopen except to hide remaining leaks.
2. **Settings consolidation** (onboarding will configure settings; includes **Data** section shell for future import/export)
3. **Onboarding wizard** (depends on settings surface; optional import steps wired later to §21 engine)
4. **Customer Centre** (can parallel after suppression; not blocking first POS sale)
5. **Import / export engine** (after Customer Centre shell and Settings → Data exist; export before import)

#### Import / export vs Customer Centre

Customer Centre will expose **customer** import/export actions only. The shared engine, job history, CSV templates, and Settings → Data hub are **platform-owned** (§21). Do not implement customer CSV logic only inside Customer Centre.

---

## 25. Scaling strategy

### Capacity model (based on current server)

| Metric | Pets Empire (`petsempire_dev`) |
|--------|-------------------------------|
| DB size | ~152 MB |
| Products | 5,380 |
| POS orders | 2,081 |
| Partners | 2,887 |
| Server RAM | 3.7 GB total |
| Odoo prod container | ~215 MB |

### Projections (**inference** — not load tested for SaaS)

| Tenants | Feasibility on current hardware | First bottleneck |
|---------|--------------------------------|----------------|
| 1 (today) | ✓ | — |
| 10 | ✓ with 16+ GB RAM, provisioning automation | Operations manual effort |
| 100 | ✗ without new infrastructure | RAM, PG connections, backup window, upgrade fan-out |
| 1,000 | ✗ without platform redesign | DB count management, worker fleet, observability |

### Scaling levers (**Future**)

- PgBouncer connection pooling
- Multiple Odoo worker containers behind load balancer
- Read replicas for reporting (**Future**)
- Shard tenants across PG clusters by region
- Separate POS-heavy tenants to dedicated workers

---

## 26. Known risks and open architectural questions

### Known risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Odoo UX leakage | High | Menu suppression module; minimal template |
| AGPL `server_action_mass_edit` on Pets Empire | Medium | Exclude from SaaS template |
| `list_db = True` on production | High | Set `False` before any public multi-DB |
| N-database upgrade toil | Medium | Template versioning + staged fan-out |
| Under-resourced server | High | Resize before tenant 2 |
| Docs say Enterprise | Low | Correct `development-environment.md` |
| Technical name `avea_till` vs `avea_dashboard` | Low | Consistent rename in DB on upgrade |
| Odoo version major upgrades | High | Plan 19→20 as separate programme |

### Open decisions

| # | Question | Options |
|---|----------|---------|
| 1 | Payment provider | Stripe / Paddle / Paystack |
| 2 | Control plane stack | Python/FastAPI, Node, etc. |
| 3 | Suspension behaviour | Hard login block vs read-only |
| 4 | Email verification on signup | Required vs optional for MVP |
| 5 | Custom domains | `shop.customer.com` vs subdomain only |
| 6 | Odoo IAP / partner autocomplete | Enable vs disable per tenant |
| 7 | MuK theme on SaaS | **Decided (ADR-014):** Avea own chrome; do not depend on MuK |
| 8 | Country templates at launch | ZA only vs multi-country |
| 9 | Auth: password reset owner | Odoo native vs control plane |
| 10 | Free tier seat limit | 1 vs 2 users |
| 11 | Free tier import row limits | Unlimited vs capped per job |
| 12 | Opening stock import timing | Onboarding only vs always available |
| 13 | Async import processing | Cron chunks vs `queue_job` / external worker |
| 14 | Category/tag on product import | Auto-create vs reject unknown |

---

## 27. Decisions that should not be casually changed

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Odoo Community only; no Enterprise | Licensing and product positioning |
| D2 | Database-per-customer tenancy | Isolation, backup, deletion, Odoo fit |
| D3 | Control plane owns billing and entitlements | Odoo is not a subscription platform |
| D4 | Avea extends Odoo models; no parallel ledgers | ADR-003, ADR-005 |
| D5 | Entitlements enforced via Odoo groups + config flags | Defence in depth |
| D6 | SaaS template ≠ Pets Empire module set | 105 modules includes non-Avea third-party |
| D7 | `list_db = False` on public deployments | Security |
| D8 | Customers sign up at avea.com, not Odoo `/web/signup` | Product brand |
| D9 | Feature namespaces `avea.till.*`, `avea.credit.*` unchanged | Production data in `avea_till_*` tables |
| D10 | Complete product layer (suppression, settings, onboarding) before marketing SaaS broadly | First customer must not see Odoo |
| D11 | Import/export is a platform capability, not a Customer Centre feature | Shared engine, formats, and permissions; avoids duplicate CSV logic |
| D12 | Opening stock import uses `avea.stock.take` apply path | ADR-003: no parallel stock tables |
| D13 | Owner exports use Avea read models (`avea.business.transaction`) where available | ADR-012: consistent owner-facing transaction history |
| D14 | Do not expose Odoo `base_import` to SaaS retail users | UX suppression and product positioning |
| D15 | Avea chrome is first-party; do not depend on MuK as the Avea theme | ADR-014; Pets Empire may still have MuK installed |

---

## 28. Related documents

| Document | Purpose |
|----------|---------|
| `docs/vision.md` | Product philosophy |
| `docs/decisions.md` | ADR-001 – ADR-015 |
| `docs/development-environment.md` | Current Docker deployment (note Enterprise correction pending) |
| `docs/deployment.md` | Module upgrade process |
| `docs/project-structure.md` | Code organisation |
| `docs/PHASE_5.md` | Future accounting / grooming (not first SaaS launch) |
| `docs/decisions.md` | ADR-013 — Import/export platform capability |
| `docs/decisions.md` | ADR-014 — Avea product shell (roles, menu suppression, identity) |
| `docs/decisions.md` | ADR-015 — Avea native navigation (section + contextual sub-nav) |

---

## 29. Revision history

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-09-18 | Avea engineering | Initial authoritative SaaS platform architecture from feasibility audit |
| 1.1 | 2026-09-18 | Avea engineering | §21 Import/export platform capability; design-now rules; roadmap integration |
| 1.2 | 2026-09-18 | Avea engineering | Step 1 UX suppression: roles, menu hide, Sell, `/web` redirect, Avea chrome (ADR-014) |
| 1.3 | 2026-09-18 | Avea engineering | AveaNav: section + sub-nav, role-filtered `session.avea_nav` (ADR-015) |
