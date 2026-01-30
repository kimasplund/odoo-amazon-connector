# Odoo 18 Amazon Connector - Project Specification

## Overview
A comprehensive, enterprise-grade Amazon integration module for Odoo 18 that provides full connectivity with Amazon Selling Partner API (SP-API) across all European and global marketplaces.

## Target Marketplaces
- **Primary:** Amazon DE (Germany)
- **European:** UK, FR, IT, ES, NL, SE, PL, BE
- **Global:** US, CA, MX, JP, AU, IN, UAE, SA, TR, BR

## Core Features

### 1. Product Management
- Full product catalog sync (Odoo → Amazon)
- ASIN/SKU mapping and management
- Product variant support
- Category/browse node mapping
- Bullet points, descriptions, search terms
- Product images sync
- A+ Content support
- Brand registry integration
- Listing quality optimization

### 2. Inventory Management
- Real-time inventory sync
- Multi-warehouse support
- FBA inventory tracking
- Safety stock management
- Replenishment alerts
- Inventory reconciliation

### 3. FBA (Fulfillment by Amazon)
- Inbound shipment creation
- Shipment tracking
- FBA fee calculation
- Storage fee monitoring
- Removal orders
- FBA vs FBM routing logic
- Multi-channel fulfillment (MCF)

### 4. Order Management
- Order import (FBA & FBM)
- Order status sync
- Shipping confirmation
- Tracking number upload
- Returns/refunds processing
- Gift orders handling
- Business orders (B2B)
- Invoice generation

### 5. Pricing
- Dynamic pricing sync
- Sale price scheduling
- Price rules automation
- Competitive pricing
- Buy Box monitoring
- Currency conversion

### 6. Financial
- Settlement reports import
- Fee reconciliation
- VAT calculation (EU)
- Financial reports
- Commission tracking

### 7. Advertising (Optional Phase 2)
- Sponsored Products
- Campaign management
- Performance reports

### 8. Reporting & Analytics
- Sales dashboard
- Performance metrics
- Inventory health
- Order analytics
- Marketplace comparison

## Technical Architecture

### Models Structure
```
amazon_marketplace          - Marketplace configurations
amazon_account              - Seller Central accounts
amazon_credential           - SP-API credentials (LWA)
amazon_product_listing      - Product listings per marketplace
amazon_product_template     - Extended product.template
amazon_order                - Amazon orders (linked to sale.order)
amazon_order_line           - Order lines
amazon_fba_shipment         - Inbound FBA shipments
amazon_fba_shipment_item    - Shipment items
amazon_fba_inventory        - FBA inventory levels
amazon_settlement           - Settlement reports
amazon_fee                  - Fee breakdown
amazon_return               - Returns/refunds
```

### SP-API Integration
- OAuth 2.0 with LWA (Login with Amazon)
- Rate limiting & throttling
- Automatic token refresh
- Request queuing
- Error handling & retry logic
- Sandbox/Production modes

### Background Jobs
- Cron-based sync schedules
- Queue-based processing
- Webhook receivers (notifications)

## Odoo 18 Compatibility
- OWL 2 components
- New web client architecture
- Python 3.10+ features
- Async capabilities where applicable

## Security
- Encrypted credential storage
- Role-based access control
- Audit logging
- GDPR compliance

## File Structure
```
odoo18_amazon_connector/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── amazon_marketplace.py
│   ├── amazon_account.py
│   ├── amazon_credential.py
│   ├── amazon_product.py
│   ├── amazon_order.py
│   ├── amazon_fba.py
│   ├── amazon_inventory.py
│   ├── amazon_settlement.py
│   ├── product_template.py (inherit)
│   └── sale_order.py (inherit)
├── wizards/
│   ├── __init__.py
│   ├── amazon_product_export.py
│   ├── amazon_fba_shipment_wizard.py
│   └── amazon_settlement_import.py
├── views/
│   ├── amazon_marketplace_views.xml
│   ├── amazon_account_views.xml
│   ├── amazon_product_views.xml
│   ├── amazon_order_views.xml
│   ├── amazon_fba_views.xml
│   ├── amazon_dashboard.xml
│   └── menus.xml
├── security/
│   ├── ir.model.access.csv
│   └── amazon_security.xml
├── data/
│   ├── amazon_marketplace_data.xml
│   ├── amazon_cron_data.xml
│   └── mail_template_data.xml
├── controllers/
│   ├── __init__.py
│   └── amazon_webhook.py
├── services/
│   ├── __init__.py
│   ├── sp_api_client.py
│   ├── sp_api_auth.py
│   ├── sp_api_products.py
│   ├── sp_api_orders.py
│   ├── sp_api_fba.py
│   ├── sp_api_feeds.py
│   └── sp_api_reports.py
├── static/
│   └── src/
│       ├── js/
│       ├── css/
│       └── xml/
└── tests/
    ├── __init__.py
    └── test_amazon_connector.py
```
