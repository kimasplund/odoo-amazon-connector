# Architecture Decisions Record (ADR)

> **Module:** Odoo 18 Amazon Connector  
> **Date:** 2025-01-30  
> **Method:** Tree of Thoughts (ToT) Evaluation  
> **Status:** Approved

---

## Table of Contents
1. [ADR-001: OAuth Token Storage](#adr-001-oauth-token-storage)
2. [ADR-002: Order Sync Architecture](#adr-002-order-sync-architecture)
3. [ADR-003: Multi-Marketplace Handling](#adr-003-multi-marketplace-handling)
4. [ADR-004: FBA Inventory Model](#adr-004-fba-inventory-model)

---

## ADR-001: OAuth Token Storage

### Context
Amazon SP-API requires OAuth 2.0 authentication via Login with Amazon (LWA). We must securely store:
- LWA Client ID & Secret (long-lived, per-app)
- Refresh Token (long-lived, per-seller authorization)
- Access Token (short-lived, ~1 hour)
- AWS credentials (IAM keys for request signing)

### Options Evaluated

#### Option A: Store in amazon_account model fields (encrypted)
Store all credentials directly as fields on `amazon.account` with `groups='base.group_system'`.

| Criteria | Score (1-5) | Notes |
|----------|-------------|-------|
| Security | 3 | Relies on Odoo field ACL; data encrypted at rest if DB encrypted |
| Maintainability | 5 | Simple, no extra models; standard Odoo pattern |
| UX | 5 | Single form view, intuitive field grouping |
| Odoo Conventions | 5 | Matches sale.payment_provider, social connectors |
| Implementation Effort | 5 | Minimal overhead |
| **Total** | **23/25** | |

#### Option B: Separate amazon_credential model
Dedicated model for credentials with One2one relationship to amazon_account.

| Criteria | Score (1-5) | Notes |
|----------|-------------|-------|
| Security | 4 | Isolation enables finer ACL; separate audit trail |
| Maintainability | 3 | Extra model, joins, sync complexity |
| UX | 3 | Credential tab/popup needed; context switching |
| Odoo Conventions | 2 | Unusual pattern; over-engineered for use case |
| Implementation Effort | 3 | Extra model, views, security rules |
| **Total** | **15/25** | |

#### Option C: Use Odoo's ir.config_parameter
Store credentials as system parameters with module prefix.

| Criteria | Score (1-5) | Notes |
|----------|-------------|-------|
| Security | 2 | No field-level ACL; visible in Settings > Parameters |
| Maintainability | 2 | Key-value; hard to manage multiple accounts |
| UX | 1 | No dedicated UI; manual parameter editing |
| Odoo Conventions | 2 | Only for global settings, not per-record secrets |
| Implementation Effort | 3 | Easy setup but poor multi-account support |
| **Total** | **10/25** | |

#### Option D: External secrets manager integration
Use HashiCorp Vault, AWS Secrets Manager, or similar.

| Criteria | Score (1-5) | Notes |
|----------|-------------|-------|
| Security | 5 | Enterprise-grade; audit, rotation, encryption |
| Maintainability | 2 | External dependency; sync complexity |
| UX | 2 | External tool configuration required |
| Odoo Conventions | 1 | Non-standard; requires connector module |
| Implementation Effort | 1 | Significant infrastructure overhead |
| **Total** | **11/25** | |

### Decision Matrix Summary

| Option | Security | Maintain. | UX | Conventions | Effort | Total |
|--------|----------|-----------|-----|-------------|--------|-------|
| **A. Account Fields** | 3 | 5 | 5 | 5 | 5 | **23** ✓ |
| B. Separate Model | 4 | 3 | 3 | 2 | 3 | 15 |
| C. ir.config_parameter | 2 | 2 | 1 | 2 | 3 | 10 |
| D. External Vault | 5 | 2 | 2 | 1 | 1 | 11 |

### ✅ Recommendation: Option A — Store in amazon_account model

### Implementation Guidance

```python
class AmazonAccount(models.Model):
    _name = 'amazon.account'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    # LWA OAuth Credentials
    lwa_client_id = fields.Char(
        string='LWA Client ID',
        groups='base.group_system',  # Restrict to Admins
        copy=False,
    )
    lwa_client_secret = fields.Char(
        string='LWA Client Secret',
        groups='base.group_system',
        copy=False,
    )
    refresh_token = fields.Char(
        string='Refresh Token',
        groups='base.group_system',
        copy=False,
    )
    
    # Short-lived tokens
    access_token = fields.Char(groups='base.group_system', copy=False)
    access_token_expiry = fields.Datetime(groups='base.group_system')
    
    # AWS Signing Credentials
    aws_access_key = fields.Char(groups='base.group_system', copy=False)
    aws_secret_key = fields.Char(groups='base.group_system', copy=False)
    aws_role_arn = fields.Char(groups='base.group_system', copy=False)
```

**Security Enhancements:**
1. Use `groups='base.group_system'` on all credential fields
2. Add `copy=False` to prevent credential duplication
3. Enable Odoo database encryption (PostgreSQL TDE or Odoo.sh encryption)
4. Add audit logging for credential access/modification
5. Implement token masking in logs: `****${last4}`

**Token Refresh Pattern:**
```python
def _refresh_access_token(self):
    """Refresh OAuth access token before API calls."""
    self.ensure_one()
    if self.access_token and self.access_token_expiry:
        if fields.Datetime.now() < self.access_token_expiry - timedelta(minutes=5):
            return self.access_token
    
    # Call LWA token endpoint
    new_token, expires_in = self._call_lwa_token_refresh()
    self.sudo().write({
        'access_token': new_token,
        'access_token_expiry': fields.Datetime.now() + timedelta(seconds=expires_in - 60),
    })
    return new_token
```

---

## ADR-002: Order Sync Architecture

### Context
Amazon orders must be synchronized with Odoo for fulfillment, invoicing, and reporting. Amazon SP-API provides:
- Orders API for pulling orders
- Notifications API for push-based events (limited availability)
- Up to 20 orders/second burst rate on Orders API

### Options Evaluated

#### Option A: Pull-based (Cron polls Amazon)
Scheduled jobs periodically fetch new/updated orders via SP-API.

| Criteria | Score (1-5) | Notes |
|----------|-------------|-------|
| Reliability | 5 | Deterministic; no external dependencies |
| Latency | 3 | 5-30 min delay depending on cron interval |
| API Quota Usage | 3 | Constant polling burns quota even when idle |
| Implementation Complexity | 5 | Simple, well-understood pattern |
| Recovery | 5 | Easy catch-up; just increase date range |
| **Total** | **21/25** | |

#### Option B: Push-based (Webhooks from Amazon)
Amazon Notifications API pushes events via SQS → Lambda → Odoo webhook.

| Criteria | Score (1-5) | Notes |
|----------|-------------|-------|
| Reliability | 2 | Depends on SQS/Lambda infra; event loss risk |
| Latency | 5 | Near real-time (seconds) |
| API Quota Usage | 5 | No polling; events only when orders arrive |
| Implementation Complexity | 2 | Requires AWS infrastructure setup |
| Recovery | 2 | Missed events need separate recovery mechanism |
| **Total** | **16/25** | |

#### Option C: Hybrid (Webhooks + Cron fallback)
Webhooks for real-time updates, cron job as safety net and gap-filler.

| Criteria | Score (1-5) | Notes |
|----------|-------------|-------|
| Reliability | 5 | Cron guarantees eventual consistency |
| Latency | 5 | Webhooks provide real-time when working |
| API Quota Usage | 4 | Reduced polling; still some cron overhead |
| Implementation Complexity | 2 | Double implementation; state reconciliation |
| Recovery | 5 | Built-in via cron fallback |
| **Total** | **21/25** | |

### Decision Matrix Summary

| Option | Reliability | Latency | Quota | Complexity | Recovery | Total |
|--------|-------------|---------|-------|------------|----------|-------|
| **A. Pull (Cron)** | 5 | 3 | 3 | 5 | 5 | **21** ✓ |
| B. Push (Webhooks) | 2 | 5 | 5 | 2 | 2 | 16 |
| C. Hybrid | 5 | 5 | 4 | 2 | 5 | 21 |

### ✅ Recommendation: Option A (Pull-based) with C as Phase 2

**Rationale:** Pull-based is simpler, more reliable, and sufficient for MVP. Amazon SP-API Notifications require AWS infrastructure (SQS) which adds operational complexity. For sellers processing <10,000 orders/day, 5-minute sync intervals are acceptable.

**Phase 2 Enhancement:** Add webhook support for high-volume sellers needing real-time sync.

### Implementation Guidance

**Cron Configuration:**
```xml
<record id="ir_cron_amazon_sync_orders" model="ir.cron">
    <field name="name">Amazon: Sync Orders</field>
    <field name="model_id" ref="model_amazon_account"/>
    <field name="state">code</field>
    <field name="code">model._cron_sync_orders()</field>
    <field name="interval_number">5</field>
    <field name="interval_type">minutes</field>
    <field name="numbercall">-1</field>
    <field name="active">True</field>
    <field name="priority">5</field>
</record>
```

**Sync Logic:**
```python
def _cron_sync_orders(self):
    """Cron job: Sync orders from all active Amazon accounts."""
    accounts = self.search([('state', '=', 'active'), ('sync_orders', '=', True)])
    for account in accounts:
        try:
            account.with_context(cron=True)._sync_orders()
            self.env.cr.commit()
        except Exception as e:
            _logger.exception("Order sync failed for %s: %s", account.name, e)
            account.write({'last_error': str(e)})
            self.env.cr.rollback()

def _sync_orders(self, days=None):
    """Fetch orders from Amazon and create/update in Odoo."""
    self.ensure_one()
    days = days or self.order_sync_days
    last_updated = fields.Datetime.now() - timedelta(days=days)
    
    # Fetch from SP-API with pagination
    orders = self._fetch_orders_from_api(last_updated_after=last_updated)
    
    for order_data in orders:
        existing = self.env['amazon.order'].search([
            ('amazon_order_id', '=', order_data['AmazonOrderId']),
            ('account_id', '=', self.id),
        ], limit=1)
        
        if existing:
            existing._update_from_amazon(order_data)
        else:
            self.env['amazon.order']._create_from_amazon(order_data, self)
    
    self.last_sync_date = fields.Datetime.now()
```

**Incremental Sync Optimization:**
```python
# Track sync watermark for efficient incremental pulls
last_order_sync = fields.Datetime(string='Last Order Sync Watermark')

def _sync_orders_incremental(self):
    """Only fetch orders modified since last sync."""
    since = self.last_order_sync or (fields.Datetime.now() - timedelta(days=7))
    orders = self._fetch_orders_from_api(last_updated_after=since)
    # ... process orders ...
    self.last_order_sync = fields.Datetime.now()
```

---

## ADR-003: Multi-Marketplace Handling

### Context
Amazon sellers often operate across multiple marketplaces (DE, FR, UK, etc.). SP-API credentials are typically per-region, but a single seller account may be authorized for multiple marketplaces within a region.

**Real-world patterns:**
- Single-market seller: 1 account → 1 marketplace
- EU Pan-European seller: 1 account → 8+ marketplaces
- Global seller: Multiple accounts (NA, EU, FE regions)

### Options Evaluated

#### Option A: One account per marketplace
Create separate `amazon.account` records for each marketplace.

| Criteria | Score (1-5) | Notes |
|----------|-------------|-------|
| UX | 2 | Repetitive setup; credential duplication |
| Data Model Complexity | 5 | Simple 1:1 relationship |
| Real-World Fit | 2 | Doesn't match Pan-European selling pattern |
| Reporting | 3 | Need aggregation for cross-marketplace views |
| API Alignment | 2 | SP-API allows multi-marketplace per auth |
| **Total** | **14/25** | |

#### Option B: One account, multiple marketplace configs
`amazon.account` has Many2many with `amazon.marketplace`; settings per marketplace via link model.

| Criteria | Score (1-5) | Notes |
|----------|-------------|-------|
| UX | 5 | Single auth, enable marketplaces with toggles |
| Data Model Complexity | 4 | Moderate; link model for per-marketplace settings |
| Real-World Fit | 5 | Matches Amazon Unified Account pattern |
| Reporting | 5 | Easy cross-marketplace reporting |
| API Alignment | 5 | One credential set for entire region |
| **Total** | **24/25** | |

#### Option C: Global account + marketplace-specific credentials
Single account with marketplace-level credential overrides.

| Criteria | Score (1-5) | Notes |
|----------|-------------|-------|
| UX | 3 | Confusing: which credentials apply where? |
| Data Model Complexity | 2 | Complex inheritance; override logic |
| Real-World Fit | 3 | Over-designed; credentials rarely differ per-MP |
| Reporting | 4 | Good aggregation but complex queries |
| API Alignment | 2 | SP-API doesn't work this way |
| **Total** | **14/25** | |

### Decision Matrix Summary

| Option | UX | Complexity | Real-World | Reporting | API | Total |
|--------|-----|------------|------------|-----------|-----|-------|
| A. One per MP | 2 | 5 | 2 | 3 | 2 | 14 |
| **B. Multi-MP Config** | 5 | 4 | 5 | 5 | 5 | **24** ✓ |
| C. Global + Override | 3 | 2 | 3 | 4 | 2 | 14 |

### ✅ Recommendation: Option B — One account, multiple marketplace configs

### Implementation Guidance

**Model Structure:**
```python
class AmazonAccount(models.Model):
    _name = 'amazon.account'
    
    # One set of credentials per account (covers entire region)
    lwa_client_id = fields.Char(groups='base.group_system')
    lwa_client_secret = fields.Char(groups='base.group_system')
    refresh_token = fields.Char(groups='base.group_system')
    
    # Region (determines available marketplaces)
    region = fields.Selection([
        ('na', 'North America'),
        ('eu', 'Europe'),
        ('fe', 'Far East'),
    ], required=True, default='eu')
    
    # Enabled marketplaces (Many2many)
    marketplace_ids = fields.Many2many(
        'amazon.marketplace',
        relation='amazon_account_marketplace_rel',
        column1='account_id',
        column2='marketplace_id',
        string='Active Marketplaces',
    )
    default_marketplace_id = fields.Many2one(
        'amazon.marketplace',
        string='Primary Marketplace',
    )

class AmazonMarketplace(models.Model):
    _name = 'amazon.marketplace'
    
    name = fields.Char(required=True)  # e.g., "Amazon Germany"
    code = fields.Char(required=True)  # e.g., "DE"
    marketplace_id = fields.Char(required=True)  # e.g., "A1PA6795UKMFR9"
    region = fields.Selection([
        ('na', 'North America'),
        ('eu', 'Europe'),
        ('fe', 'Far East'),
    ])
    endpoint = fields.Char()  # SP-API endpoint
    currency_id = fields.Many2one('res.currency')
    country_id = fields.Many2one('res.country')
```

**Per-Marketplace Settings (via link model):**
```python
class AmazonAccountMarketplace(models.Model):
    """Per-marketplace settings for an Amazon account."""
    _name = 'amazon.account.marketplace'
    
    account_id = fields.Many2one('amazon.account', required=True, ondelete='cascade')
    marketplace_id = fields.Many2one('amazon.marketplace', required=True, ondelete='cascade')
    
    # Marketplace-specific settings
    warehouse_id = fields.Many2one('stock.warehouse', string='Fulfillment Warehouse')
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist')
    fiscal_position_id = fields.Many2one('account.fiscal.position')
    sync_enabled = fields.Boolean(default=True)
    
    _sql_constraints = [
        ('unique_account_marketplace', 'UNIQUE(account_id, marketplace_id)', 
         'Marketplace already configured for this account!'),
    ]
```

**UI Pattern:**
- Account form shows marketplace checkboxes (quick enable/disable)
- Dedicated "Marketplace Settings" tab for per-MP configurations
- Smart defaults based on region selection

---

## ADR-004: FBA Inventory Model

### Context
FBA (Fulfillment by Amazon) inventory is stored at Amazon warehouses. We need to track:
- Sellable quantity per SKU per marketplace
- Reserved, inbound, and unfulfillable quantities
- Fulfillment center locations (for analytics)

### Options Evaluated

#### Option A: Virtual stock.location per FBA warehouse
Create Odoo stock locations for each Amazon FC; use stock.quant for inventory.

| Criteria | Score (1-5) | Notes |
|----------|-------------|-------|
| Odoo Integration | 5 | Native stock reports, available qty, reservations |
| Reporting | 5 | Standard Odoo inventory reports work |
| Real-Time Accuracy | 2 | Odoo quants may drift from Amazon reality |
| Implementation Complexity | 4 | Location hierarchy setup; sync logic |
| Uniqueness | 3 | 200+ FCs globally; many locations to manage |
| **Total** | **19/25** | |

#### Option B: Dedicated amazon_fba_inventory model
Custom model tracking Amazon inventory separately; linked to products.

| Criteria | Score (1-5) | Notes |
|----------|-------------|-------|
| Odoo Integration | 3 | Requires custom reports; not in native stock |
| Reporting | 4 | Custom Amazon dashboard; flexible fields |
| Real-Time Accuracy | 5 | Mirrors Amazon exactly; no Odoo drift |
| Implementation Complexity | 5 | Simple CRUD; no stock move reconciliation |
| Uniqueness | 5 | Stores Amazon-specific data (FNSKU, FC codes) |
| **Total** | **22/25** | |

#### Option C: Extend stock.quant with amazon fields
Add amazon_* fields to stock.quant; use standard Odoo model.

| Criteria | Score (1-5) | Notes |
|----------|-------------|-------|
| Odoo Integration | 4 | Leverages existing quant; some native reports |
| Reporting | 3 | Mixed Amazon/non-Amazon data in same model |
| Real-Time Accuracy | 2 | Quant changes need stock.move; complex sync |
| Implementation Complexity | 2 | Inheritance can conflict with other modules |
| Uniqueness | 3 | Amazon-specific fields on generic model |
| **Total** | **14/25** | |

### Decision Matrix Summary

| Option | Integration | Reporting | Accuracy | Complexity | Unique | Total |
|--------|-------------|-----------|----------|------------|--------|-------|
| A. Virtual Locations | 5 | 5 | 2 | 4 | 3 | 19 |
| **B. Dedicated Model** | 3 | 4 | 5 | 5 | 5 | **22** ✓ |
| C. Extend stock.quant | 4 | 3 | 2 | 2 | 3 | 14 |

### ✅ Recommendation: Option B — Dedicated amazon_fba_inventory model

**Rationale:** FBA inventory is "informational" from Odoo's perspective — you can't reserve or pick from it directly. A dedicated model cleanly separates Amazon's reported quantities from Odoo's actual warehouse stock. This avoids:
- Stock move complexity for external inventory changes
- Drift between Amazon and Odoo when syncs lag
- Conflicts with stock valuation and accounting

For **available-to-promise** calculations, sum FBA inventory via computed fields on product.

### Implementation Guidance

**Model Structure:**
```python
class AmazonFBAInventory(models.Model):
    _name = 'amazon.fba.inventory'
    _description = 'Amazon FBA Inventory'
    _rec_name = 'display_name'
    _order = 'last_updated desc'
    
    # Relationships
    account_id = fields.Many2one('amazon.account', required=True, ondelete='cascade')
    marketplace_id = fields.Many2one('amazon.marketplace', required=True)
    product_id = fields.Many2one('product.product', ondelete='set null', index=True)
    listing_id = fields.Many2one('amazon.product.listing', ondelete='set null')
    
    # Amazon Identifiers
    amazon_sku = fields.Char(required=True, index=True)
    amazon_asin = fields.Char(index=True)
    amazon_fnsku = fields.Char()  # FBA-specific barcode
    
    # Fulfillment Center
    fulfillment_center_id = fields.Char(string='FC Code')  # e.g., "FRA1"
    
    # Quantities (from Inventory Summary report)
    qty_available = fields.Float(string='Sellable', digits='Product Unit of Measure')
    qty_reserved = fields.Float(string='Reserved', digits='Product Unit of Measure')
    qty_inbound_working = fields.Float(string='Inbound Working')
    qty_inbound_shipped = fields.Float(string='Inbound Shipped')
    qty_inbound_receiving = fields.Float(string='Inbound Receiving')
    qty_unfulfillable = fields.Float(string='Unfulfillable')
    
    # Computed totals
    qty_total = fields.Float(compute='_compute_qty_total', store=True)
    qty_inbound_total = fields.Float(compute='_compute_qty_inbound', store=True)
    
    # Sync metadata
    last_updated = fields.Datetime(default=fields.Datetime.now)
    
    @api.depends('qty_available', 'qty_reserved', 'qty_unfulfillable')
    def _compute_qty_total(self):
        for rec in self:
            rec.qty_total = rec.qty_available + rec.qty_reserved + rec.qty_unfulfillable
    
    @api.depends('qty_inbound_working', 'qty_inbound_shipped', 'qty_inbound_receiving')
    def _compute_qty_inbound(self):
        for rec in self:
            rec.qty_inbound_total = (
                rec.qty_inbound_working + 
                rec.qty_inbound_shipped + 
                rec.qty_inbound_receiving
            )
```

**Product Integration (computed field for ATP):**
```python
class ProductProduct(models.Model):
    _inherit = 'product.product'
    
    amazon_fba_qty = fields.Float(
        string='Amazon FBA Stock',
        compute='_compute_amazon_fba_qty',
        help='Total sellable quantity across all FBA warehouses',
    )
    
    @api.depends('amazon_fba_inventory_ids.qty_available')
    def _compute_amazon_fba_qty(self):
        FBAInventory = self.env['amazon.fba.inventory']
        for product in self:
            fba_records = FBAInventory.search([
                ('product_id', '=', product.id),
            ])
            product.amazon_fba_qty = sum(fba_records.mapped('qty_available'))
```

**Optional: Virtual Location for Reporting**

If native Odoo stock reports are critical, create a single "Amazon FBA" virtual location:

```python
# One location per account, not per fulfillment center
fba_location_id = fields.Many2one(
    'stock.location',
    string='FBA Stock Location',
    help='Virtual location for FBA inventory (reporting only)',
)

def _create_fba_location(self):
    """Create a virtual location for FBA stock visibility."""
    location = self.env['stock.location'].create({
        'name': f'Amazon FBA - {self.name}',
        'usage': 'internal',
        'location_id': self.env.ref('stock.stock_location_locations_virtual').id,
    })
    self.fba_location_id = location
```

Sync quants to this location periodically if needed, but treat `amazon.fba.inventory` as the source of truth.

---

## Summary of Decisions

| Decision | Recommendation | Confidence |
|----------|---------------|------------|
| ADR-001: OAuth Storage | Store in amazon_account fields | High |
| ADR-002: Order Sync | Pull-based (cron) | High |
| ADR-003: Multi-Marketplace | One account, multi-MP configs | High |
| ADR-004: FBA Inventory | Dedicated amazon_fba_inventory model | High |

---

## Revision History

| Date | Author | Changes |
|------|--------|---------|
| 2025-01-30 | Architecture Agent | Initial ADR document |
