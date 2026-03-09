# Salesforce CRM Integration Plan

## Context

Veteran Lawns & Landscapes uses a local PostgreSQL DB as the authoritative data store. Salesforce receives **one-way, read-only copies** for CRM/operations purposes — the local DB is never updated from Salesforce.

**Recommended products**:
- **Starter Suite** ($25/user/month) — Contacts, Accounts, Opportunities, email marketing
- **Field Service Cloud** ($50–165/user/month per technician) — Work Orders, Dispatcher Console, mobile app

---

## Current Status

| Component | Status |
|---|---|
| `services/salesforce.py` | **Not created** |
| `simple-salesforce` in `requirements.txt` | **Not added** |
| `config.py` Salesforce block | **Not added** (Paychex is currently last block) |
| Admin Integrations tab Salesforce card | **Not added** |
| Router integration points | **Not wired** |

---

## Data Mapping

| App Event | Salesforce Action | SF Objects |
|---|---|---|
| Quote submitted (`POST /quotes/estimate`) | Create Lead | `Lead` |
| Stripe payment confirmed (webhook) | Create Account + Contact + Opportunity (Closed Won) | `Account`, `Contact`, `Opportunity` |
| Service schedule set (post-payment) | Create Work Order | `WorkOrder` |
| Landscaping inquiry submitted | Create Lead | `Lead` |
| Landscaping proposal accepted | Create Account + Contact + Opportunity + Work Order | `Account`, `Contact`, `Opportunity`, `WorkOrder` |
| Customer cancels service | Log only — manual Closed Lost in SF UI | — |
| Email campaigns | Configured in SF Marketing UI from synced Contacts | — |

---

## Implementation Steps

### 1. `requirements.txt`
```
simple-salesforce>=1.12.0
```

### 2. `config.py`
Add after the Paychex block (currently last):
```python
# Salesforce CRM (optional)
salesforce_instance_url: str = ""      # e.g. https://yourorg.my.salesforce.com
salesforce_username: str = ""          # API user email
salesforce_password: str = ""
salesforce_security_token: str = ""    # Appended to password for non-IP-restricted auth
salesforce_client_id: str = ""         # Reserved for future OAuth 2.0 JWT Bearer upgrade
```

### 3. `.env.example`
```bash
# Salesforce CRM (optional)
SALESFORCE_INSTANCE_URL=
SALESFORCE_USERNAME=
SALESFORCE_PASSWORD=
SALESFORCE_SECURITY_TOKEN=
SALESFORCE_CLIENT_ID=
```

### 4. `services/salesforce.py` (new file)

Mirrors the pattern used by `services/fieldroutes.py` and `services/zillow.py`:
- `_is_configured()` — checks 4 required credentials
- `_get_client()` → `Salesforce | None` — username+password+token auth; `None` on error
- Result dataclasses: `SalesforceLead`, `SalesforceOpportunity`, `SalesforceWorkOrder`
- All functions wrap synchronous `simple-salesforce` calls in `asyncio.to_thread()`
- Every function: checks `_is_configured()` first, catches all exceptions, logs, never raises

**Functions:**
```
create_lawn_quote_lead(name, email, phone, address, acreage, monthly_quote)
  → Lead(LeadSource="Web", Company="Residential") → SalesforceLead | None

convert_lead_to_opportunity(name, email, phone, address, monthly_quote, stripe_session_id)
  → Account → Contact → Opportunity(Closed Won, amount=monthly×12) → SalesforceOpportunity | None

create_lawn_service_work_order(account_id, address, frequency, start_date, monthly_rate)
  → WorkOrder linked to Account → SalesforceWorkOrder | None

create_landscaping_lead(name, email, phone, address, project_type, project_scope, budget_range, description)
  → Lead with project details in Description → SalesforceLead | None

create_landscaping_opportunity(name, email, phone, address, project_type, rom_low, rom_high, project_id)
  → Account → Contact → Opportunity(Closed Won, amount=ROM midpoint) → SalesforceOpportunity | None

create_landscaping_work_order(account_id, address, project_type, rom_low, rom_high)
  → WorkOrder for landscaping project → SalesforceWorkOrder | None
```

`WorkOrder` requires Field Service Cloud — catch `SalesforceError` gracefully so Opportunity still succeeds on Starter Suite.

### 5. `routers/quotes.py`

After `await db.refresh(customer)`, before `logger.info()`:
```python
from services.salesforce import create_lawn_quote_lead

await create_lawn_quote_lead(
    name=customer.name, email=customer.email, phone=customer.phone,
    address=full_address, acreage=actual_size, monthly_quote=monthly_quote,
)
```

### 6. `routers/payments.py`

Add after `_sync_to_fieldroutes()`:
```python
from services.salesforce import convert_lead_to_opportunity, create_lawn_service_work_order

async def _sync_to_salesforce(customer: Customer) -> None:
    try:
        opp = await convert_lead_to_opportunity(
            name=customer.name, email=customer.email, phone=customer.phone,
            address=customer.address, monthly_quote=customer.quote or 0.0,
            stripe_session_id=customer.stripe_payment_id or "",
        )
        if opp and customer.service_start_date:
            await create_lawn_service_work_order(
                account_id=opp.account_id, address=customer.address,
                frequency=customer.service_frequency or "weekly",
                start_date=customer.service_start_date.isoformat(),
                monthly_rate=customer.quote or 0.0,
            )
    except Exception:
        logger.exception(f"Salesforce sync error for customer {customer.id}")
```

Call `await _sync_to_salesforce(customer)` after `_sync_to_fieldroutes`.

On cancellation: add `logger.info(f"Salesforce manual Closed Lost needed for customer {customer.id}")` inside `_handle_subscription_cancelled()`.

### 7. `routers/landscaping.py`

After inquiry DB commit:
```python
from services.salesforce import create_landscaping_lead, create_landscaping_opportunity, create_landscaping_work_order

await create_landscaping_lead(
    name=project.name, email=project.email, phone=project.phone,
    address=full_address, project_type=project.project_type,
    project_scope=project.project_scope, budget_range=project.budget_range,
    project_description=project.project_description,
)
```

After proposal accepted DB commit:
```python
if project.customer_response == "accepted" and project.rom_estimate_low and project.rom_estimate_high:
    opp = await create_landscaping_opportunity(
        name=project.name, email=project.email, phone=project.phone,
        address=project.address, project_type=project.project_type,
        rom_estimate_low=project.rom_estimate_low,
        rom_estimate_high=project.rom_estimate_high, project_id=project.id,
    )
    if opp:
        await create_landscaping_work_order(
            account_id=opp.account_id, address=project.address,
            project_type=project.project_type,
            rom_low=project.rom_estimate_low, rom_high=project.rom_estimate_high,
        )
```

### 8. Admin Integrations Tab

Add a Salesforce card in `templates/admin.html` (Integrations tab) following the same pattern as the existing Paychex card. Fields: Instance URL, Username, Password (reveal/copy), Security Token (reveal/copy), Client ID. CSS header class: `.salesforce-header` (blue `#0070d2→#1589ee`).

---

## Design Decisions

- **Auth**: Username + password + security token. `client_id` reserved for future OAuth JWT Bearer.
- **`asyncio.to_thread()`**: `simple-salesforce` is sync; wrapping avoids blocking the event loop (same pattern as `services/zillow.py`).
- **No SF ID storage**: Don't add SF ID columns until bidirectional sync is needed. Admins find records by email in SF UI.
- **Field Service degradation**: `WorkOrder` failures are caught and logged; Opportunity still persists.
- **Lead conversion**: Create Account/Contact/Opportunity directly on payment — skip SF's programmatic lead conversion API.
- **Cancellations**: Log-only until SF IDs are stored locally.

---

## Verification Checklist

- [ ] No SF env vars set → quote + payment + landscaping flows return 200 (graceful degradation)
- [ ] Quote submitted → SF Lead with correct email, address, acreage
- [ ] Stripe test payment → SF Account + Contact + Opportunity (Closed Won, amount = monthly × 12)
- [ ] Same test → SF WorkOrder linked to Account (requires Field Service enabled)
- [ ] Landscaping inquiry → SF Lead with project_type in Description
- [ ] Landscaping proposal accepted → SF Opportunity (ROM midpoint) + WorkOrder
- [ ] `pytest` passes with no SF env vars in test environment
