# Existing Amazon Connectors Analysis

Research on existing Odoo Amazon integrations and best practices.

## 1. Known Connectors

### 1.1 Official Odoo Amazon Connector (`sale_amazon`)

**Status:** Odoo Enterprise (proprietary, Odoo 15+)

**Key Features:**
- Synchronizes confirmed orders (FBA and FBM)
- Creates missing partners (contact and delivery address)
- Notifies Amazon of confirmed shipments (FBM)
- Synchronizes available quantities (FBM)
- Supports multiple seller accounts
- Supports multiple marketplaces per account

**Model Structure (inferred from documentation):**
- `amazon.account` - Seller account configuration
- `amazon.marketplace` - Marketplace definitions
- `amazon.offer` - SKU-to-product pairings
- Uses standard `sale.order` with Amazon extensions

**Limitations:**
- Enterprise-only (not open source)
- No standalone FBA inventory management
- No multi-channel fulfillment (MCF)
- Limited reporting capabilities
- No repricing features

### 1.2 Emipro Technologies Connectors

**Status:** Commercial (paid apps on Odoo Apps Store)

**Common Model Naming Convention (`.ept` suffix):**
```
amazon.instance.ept       # Amazon account/instance
amazon.seller.ept         # Seller configuration
amazon.marketplace.ept    # Marketplace settings
amazon.product.ept        # Product listings
amazon.sale.order.ept     # Amazon orders (separate from sale.order)
amazon.order.line.ept     # Order line items
amazon.fulfillment.ept    # Fulfillment management
amazon.fba.live.stock.report.ept  # FBA inventory reports
```

**Architecture Patterns:**
- Separate models for Amazon entities (doesn't extend core models directly)
- Uses queues for import/export operations
- Scheduled actions for sync operations
- Logs operations in dedicated log models

### 1.3 OCA Sale Channel Framework

**Repository:** https://github.com/OCA/sale-channel (18.0 branch)

**Available Modules:**
| Module | Version | Description |
|--------|---------|-------------|
| `sale_channel` | 18.0.1.0.0 | Base sale channels concept |
| `sale_channel_category` | 18.0.1.0.0 | Link categories with channels |
| `sale_channel_product` | 18.0.1.0.0 | Link products with channels |
| `sale_channel_partner` | 16.0.0.0.0 (unported) | Bind channels to contacts |
| `sale_channel_search_engine` | 16.0.0.1.2 (unported) | Search engine integration |

**Key Concepts:**
- `sale.channel` - Abstract representation of a sales channel
- Channel-specific product bindings
- Channel-specific category mappings
- Foundation for marketplace integrations

### 1.4 Other Third-Party Connectors

- **Teqstars Amazon Connector** - Commercial, feature-rich
- **Technaureus Amazon Integration** - Commercial
- **Various freelance implementations** - GitHub, varying quality

---

## 2. Common Model Patterns

### 2.1 Naming Conventions

| Pattern | Example | Usage |
|---------|---------|-------|
| `amazon.<entity>` | `amazon.account` | Official Odoo style |
| `<entity>.amazon` | `sale.amazon` | Extension-focused |
| `amazon.<entity>.ept` | `amazon.seller.ept` | Emipro convention |
| `<provider>.<entity>` | `amazon.marketplace` | Generic marketplace |

**Recommendation:** Use `amazon.<entity>` pattern for clarity:
```python
amazon.account          # Account configuration
amazon.marketplace      # Marketplace settings
amazon.product.listing  # Product listings on Amazon
amazon.order            # Amazon order sync records
amazon.offer            # SKU-to-product mapping
amazon.fba.inventory    # FBA inventory tracking
```

### 2.2 Account Structure

**Common Fields for Amazon Account:**
```python
class AmazonAccount(models.Model):
    _name = 'amazon.account'
    _description = 'Amazon Seller Account'

    name = fields.Char('Account Name', required=True)
    seller_id = fields.Char('Seller ID')
    
    # OAuth/LWA Credentials
    client_id = fields.Char('LWA Client ID')
    client_secret = fields.Char('LWA Client Secret')  # Encrypted
    refresh_token = fields.Text('Refresh Token')       # Encrypted
    access_token = fields.Text('Access Token')         # Runtime, not stored
    token_expiry = fields.Datetime('Token Expiry')
    
    # Region Configuration
    home_marketplace_id = fields.Many2one('amazon.marketplace')
    marketplace_ids = fields.Many2many('amazon.marketplace')
    
    # Sync Configuration
    company_id = fields.Many2one('res.company')
    warehouse_id = fields.Many2one('stock.warehouse')
    pricelist_id = fields.Many2one('product.pricelist')
    
    # Sync State
    last_order_sync = fields.Datetime()
    last_inventory_sync = fields.Datetime()
    active = fields.Boolean(default=True)
```

### 2.3 Marketplace Configuration

**Amazon Marketplace IDs (from official docs):**
```python
MARKETPLACES = {
    # North America
    'A2EUQ1WTGCTBG2': {'name': 'Amazon.ca', 'region': 'NA', 'country': 'CA'},
    'A1AM78C64UM0Y8': {'name': 'Amazon.com.mx', 'region': 'NA', 'country': 'MX'},
    'ATVPDKIKX0DER': {'name': 'Amazon.com', 'region': 'NA', 'country': 'US'},
    
    # Europe
    'A1PA6795UKMFR9': {'name': 'Amazon.de', 'region': 'EU', 'country': 'DE'},
    'A1RKKUPIHCS9HS': {'name': 'Amazon.es', 'region': 'EU', 'country': 'ES'},
    'A13V1IB3VIYBER': {'name': 'Amazon.fr', 'region': 'EU', 'country': 'FR'},
    'A1F83G8C2ARO7P': {'name': 'Amazon.co.uk', 'region': 'EU', 'country': 'GB'},
    'APJ6JRA9NG5V4': {'name': 'Amazon.it', 'region': 'EU', 'country': 'IT'},
    'A1805IZSGTT6HS': {'name': 'Amazon.nl', 'region': 'EU', 'country': 'NL'},
    
    # Far East
    'A1VC38T7YXB528': {'name': 'Amazon.co.jp', 'region': 'FE', 'country': 'JP'},
    'A39IBJ37TRP1C6': {'name': 'Amazon.com.au', 'region': 'FE', 'country': 'AU'},
}

# SP-API Endpoints by Region
ENDPOINTS = {
    'NA': 'https://sellingpartnerapi-na.amazon.com',
    'EU': 'https://sellingpartnerapi-eu.amazon.com',
    'FE': 'https://sellingpartnerapi-fe.amazon.com',
}
```

---

## 3. OAuth/Token Management

### 3.1 Login with Amazon (LWA) Flow

**Authorization URI Pattern:**
```
https://sellercentral.amazon.com/apps/authorize/consent
  ?application_id={app_id}
  &state={csrf_token}
  &version=beta  # For draft apps only
```

**Token Exchange Endpoint:**
```
POST https://api.amazon.com/auth/o2/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code={spapi_oauth_code}
&redirect_uri={registered_uri}
&client_id={lwa_client_id}
&client_secret={lwa_client_secret}
```

**Token Refresh Pattern:**
```python
def refresh_access_token(self):
    """Refresh LWA access token using refresh_token."""
    response = requests.post(
        'https://api.amazon.com/auth/o2/token',
        data={
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
        }
    )
    data = response.json()
    self.access_token = data['access_token']
    self.token_expiry = datetime.now() + timedelta(seconds=data['expires_in'])
    return self.access_token
```

### 3.2 Token Storage Best Practices

**DO:**
- Encrypt refresh tokens at rest
- Store in database with proper access controls
- Implement token rotation
- Log token usage (without exposing token values)
- Handle token expiration gracefully

**DON'T:**
- Store access tokens (regenerate as needed)
- Log full token values
- Store tokens in config files
- Share tokens between accounts

---

## 4. Order Sync Patterns

### 4.1 Order Pull Strategy

**Using python-amazon-sp-api:**
```python
from sp_api.api import Orders
from datetime import datetime, timedelta

def sync_orders(self):
    """Pull orders from Amazon SP-API."""
    client = Orders(
        credentials={
            'refresh_token': self.account_id.refresh_token,
            'lwa_app_id': self.account_id.client_id,
            'lwa_client_secret': self.account_id.client_secret,
        },
        marketplace=Marketplaces[self.marketplace_id.code],
    )
    
    # Get orders modified in last 24 hours
    response = client.get_orders(
        LastUpdatedAfter=(datetime.utcnow() - timedelta(days=1)).isoformat(),
        MarketplaceIds=[self.marketplace_id.api_identifier],
    )
    
    for order_data in response.payload.get('Orders', []):
        self._process_amazon_order(order_data)
```

### 4.2 Order Model Extension

**Option A: Extend sale.order (Odoo official approach):**
```python
class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    amazon_order_id = fields.Char('Amazon Order ID', index=True)
    amazon_account_id = fields.Many2one('amazon.account')
    amazon_marketplace_id = fields.Many2one('amazon.marketplace')
    amazon_fulfillment_channel = fields.Selection([
        ('MFN', 'Merchant Fulfilled'),
        ('AFN', 'Amazon Fulfilled'),
    ])
    amazon_order_status = fields.Char('Amazon Status')
    amazon_last_sync = fields.Datetime()
```

**Option B: Separate sync model (Emipro approach):**
```python
class AmazonOrder(models.Model):
    _name = 'amazon.order'
    _description = 'Amazon Order Sync Record'
    
    amazon_order_id = fields.Char(required=True, index=True)
    sale_order_id = fields.Many2one('sale.order', ondelete='set null')
    account_id = fields.Many2one('amazon.account', required=True)
    raw_data = fields.Text('Raw API Response')  # For debugging
    state = fields.Selection([
        ('pending', 'Pending'),
        ('imported', 'Imported'),
        ('error', 'Error'),
    ])
```

**Recommendation:** Use hybrid approach:
- Extend `sale.order` with minimal Amazon fields
- Create `amazon.order.sync` for tracking sync state and raw data

---

## 5. Inventory Sync Approaches

### 5.1 FBM (Fulfilled by Merchant) Inventory

**Push inventory to Amazon:**
```python
from sp_api.api import Feeds
from sp_api.base.reportTypes import ReportType

def push_inventory(self):
    """Submit inventory feed to Amazon."""
    products = self._get_products_to_sync()
    
    # Build XML feed
    feed_content = self._build_inventory_feed(products)
    
    # Submit via Feeds API
    client = Feeds(credentials=self._get_credentials())
    response = client.submit_feed(
        feedType='POST_INVENTORY_AVAILABILITY_DATA',
        file=feed_content.encode(),
        content_type='text/xml',
    )
    
    return response.payload['feedId']
```

### 5.2 FBA (Fulfilled by Amazon) Inventory

**Pull FBA inventory reports:**
```python
from sp_api.api import Reports

def sync_fba_inventory(self):
    """Request and process FBA inventory report."""
    client = Reports(credentials=self._get_credentials())
    
    # Request report
    response = client.create_report(
        reportType=ReportType.GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA
    )
    report_id = response.payload['reportId']
    
    # Poll for completion, then download and process
    # (Implement with scheduled action)
```

**FBA Stock Location Pattern:**
```python
class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'
    
    is_amazon_fba = fields.Boolean('Is Amazon FBA')
    amazon_account_id = fields.Many2one('amazon.account')

# Create virtual location for FBA stock
fba_location = self.env['stock.location'].create({
    'name': 'Amazon FBA',
    'usage': 'internal',
    'company_id': account.company_id.id,
})
```

---

## 6. SP-API Integration Details

### 6.1 Key APIs for Odoo Integration

| API | Purpose | Priority |
|-----|---------|----------|
| **Orders API** | Sync orders from Amazon | Critical |
| **Feeds API** | Push inventory, prices, listings | Critical |
| **Reports API** | Pull reports (inventory, settlements) | High |
| **Catalog Items API** | Product information | High |
| **FBA Inventory API** | Real-time FBA stock levels | High |
| **Notifications API** | Real-time order notifications | Medium |
| **Fulfillment Outbound API** | Multi-Channel Fulfillment | Medium |
| **Listings Items API** | Manage product listings | Medium |
| **Product Pricing API** | Competitive pricing data | Low |

### 6.2 python-amazon-sp-api Usage

**Installation:**
```bash
pip install python-amazon-sp-api
```

**Basic Configuration:**
```python
from sp_api.base import Marketplaces

credentials = {
    'refresh_token': '<refresh_token>',
    'lwa_app_id': '<client_id>',
    'lwa_client_secret': '<client_secret>',
}

# For async operations (recommended for Odoo cron jobs)
from sp_api.asyncio.api import Orders
import asyncio

async def get_orders():
    async with Orders(credentials=credentials) as client:
        response = await client.get_orders(...)
```

---

## 7. Best Practices Observed

### 7.1 Architecture

1. **Modular Design**
   - Separate core from marketplace-specific logic
   - Use abstract base classes for common patterns
   - Keep API client code isolated

2. **Queue-Based Processing**
   - Use job queues for API operations
   - Implement retry logic with backoff
   - Track operation history

3. **Error Handling**
   - Catch and log API errors
   - Store raw responses for debugging
   - Implement human-readable error messages

### 7.2 Performance

1. **Batch Operations**
   - Group API calls where possible
   - Use bulk create/write in Odoo
   - Implement pagination for large datasets

2. **Caching**
   - Cache marketplace and catalog data
   - Implement token caching (avoid unnecessary refreshes)
   - Use Odoo's ORM caching effectively

3. **Scheduling**
   - Use `ir.cron` for periodic syncs
   - Implement incremental sync (last modified dates)
   - Spread load across time windows

### 7.3 Security

1. **Credential Management**
   - Encrypt sensitive fields (`refresh_token`, `client_secret`)
   - Use Odoo's parameter system for global settings
   - Implement proper access controls

2. **Audit Trail**
   - Log all API operations
   - Track who changed what
   - Maintain sync history

---

## 8. Anti-Patterns to Avoid

### 8.1 Technical

❌ **Storing access tokens** - They expire in 1 hour, regenerate as needed

❌ **Synchronous API calls in UI** - Block users, cause timeouts

❌ **Ignoring rate limits** - Amazon throttles aggressively

❌ **Overriding core Odoo methods without super()** - Breaks compatibility

❌ **Storing raw JSON in Text fields** - Use proper relational models

### 8.2 Functional

❌ **Auto-confirming orders** - Let users review before confirmation

❌ **Auto-creating products** - Can create duplicates, let users map manually

❌ **Ignoring FBA vs FBM** - Different workflows, treat separately

❌ **Single account assumption** - Always design for multi-account

---

## 9. Feature Gaps We Can Fill

### 9.1 Gaps in Official Odoo Connector

| Feature | Official | Our Opportunity |
|---------|----------|-----------------|
| Open source | ❌ Enterprise only | ✅ AGPL-3 |
| FBA inventory management | ⚠️ Basic | ✅ Full integration |
| Multi-Channel Fulfillment | ❌ | ✅ MCF support |
| Real-time notifications | ❌ | ✅ SQS integration |
| Settlement reports | ⚠️ Basic | ✅ Full reconciliation |
| Repricing | ❌ | ✅ Competitive pricing |
| Returns processing | ⚠️ Manual | ✅ Automated |

### 9.2 Unique Value Propositions

1. **True Open Source** - Community-driven, no license fees
2. **Modern SP-API** - Full support for current Amazon APIs
3. **OCA Quality** - Following OCA guidelines and standards
4. **Odoo 18 Native** - Built for latest Odoo patterns
5. **European Focus** - VAT/OSS compliance, EU marketplaces

---

## 10. References

### Documentation
- [Amazon SP-API Documentation](https://developer-docs.amazon.com/sp-api/docs/welcome)
- [SP-API Models (GitHub)](https://github.com/amzn/selling-partner-api-models)
- [Odoo 18 Amazon Connector Docs](https://www.odoo.com/documentation/18.0/applications/sales/sales/amazon_connector.html)

### Libraries
- [python-amazon-sp-api](https://pypi.org/project/python-amazon-sp-api/) - Primary SP-API client
- [python-amazon-sp-api Docs](https://python-amazon-sp-api.readthedocs.io/)

### OCA Repositories
- [OCA/sale-channel](https://github.com/OCA/sale-channel) - Sale channel framework
- [OCA/connector](https://github.com/OCA/connector) - Connector base framework

### API Endpoints
- NA: `https://sellingpartnerapi-na.amazon.com`
- EU: `https://sellingpartnerapi-eu.amazon.com`
- FE: `https://sellingpartnerapi-fe.amazon.com`
- LWA Token: `https://api.amazon.com/auth/o2/token`

---

*Last Updated: 2026-01-30*
*Research Agent - Odoo 18 Amazon Connector Project*
