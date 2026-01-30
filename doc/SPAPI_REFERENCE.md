# Amazon SP-API Reference

> **Last Updated:** 2026-01-30  
> **Source:** Official Amazon SP-API Documentation (developer-docs.amazon.com/sp-api/)  
> **Status:** VERIFIED - All information sourced from official Amazon documentation

---

## Table of Contents

1. [Overview](#overview)
2. [Regional Endpoints](#regional-endpoints)
3. [Marketplace IDs](#marketplace-ids)
4. [Authentication (LWA OAuth)](#authentication-lwa-oauth)
5. [Request Signing & Headers](#request-signing--headers)
6. [Rate Limits & Throttling](#rate-limits--throttling)
7. [Key APIs for Odoo Integration](#key-apis-for-odoo-integration)
8. [Python SDK Options](#python-sdk-options)
9. [Deprecated APIs (Avoid!)](#deprecated-apis-avoid)

---

## Overview

The **Selling Partner API (SP-API)** is Amazon's modern API for sellers and vendors, replacing the deprecated Marketplace Web Service (MWS). SP-API uses OAuth 2.0 (Login with Amazon) for authentication and AWS Signature Version 4 for request signing.

**Official Documentation:** https://developer-docs.amazon.com/sp-api/  
**GitHub Repository:** https://github.com/amzn/selling-partner-api-models  
**API Health Dashboard:** https://sellercentral.amazon.com/sp-api-status

---

## Regional Endpoints

SP-API has three regional endpoints. Choose based on target marketplace:

| Selling Region | Endpoint URL | AWS Region |
|----------------|--------------|------------|
| **North America** (CA, US, MX, BR) | `https://sellingpartnerapi-na.amazon.com` | `us-east-1` |
| **Europe** (UK, DE, FR, IT, ES, NL, PL, SE, BE, IE, SA, AE, EG, TR, ZA, IN) | `https://sellingpartnerapi-eu.amazon.com` | `eu-west-1` |
| **Far East** (JP, AU, SG) | `https://sellingpartnerapi-fe.amazon.com` | `us-west-2` |

### LWA Token Endpoint (All Regions)
```
POST https://api.amazon.com/auth/o2/token
```

---

## Marketplace IDs

Each Amazon marketplace has a unique identifier. These are **exact values** from official docs:

### North America

| Country | Marketplace ID | Country Code |
|---------|----------------|--------------|
| Canada | `A2EUQ1WTGCTBG2` | CA |
| United States | `ATVPDKIKX0DER` | US |
| Mexico | `A1AM78C64UM0Y8` | MX |
| Brazil | `A2Q3Y263D00KWC` | BR |

### Europe

| Country | Marketplace ID | Country Code |
|---------|----------------|--------------|
| Ireland | `A28R8C7NBKEWEA` | IE |
| Spain | `A1RKKUPIHCS9HS` | ES |
| United Kingdom | `A1F83G8C2ARO7P` | UK |
| France | `A13V1IB3VIYZZH` | FR |
| Belgium | `AMEN7PMS3EDWL` | BE |
| Netherlands | `A1805IZSGTT6HS` | NL |
| Germany | `A1PA6795UKMFR9` | DE |
| Italy | `APJ6JRA9NG5V4` | IT |
| Sweden | `A2NODRKZP88ZB9` | SE |
| South Africa | `AE08WJ6YKNBMC` | ZA |
| Poland | `A1C3SOZRARQ6R3` | PL |
| Egypt | `ARBP9OOSHTCHU` | EG |
| Turkey | `A33AVAJ2PDY3EV` | TR |
| Saudi Arabia | `A17E79C6D8DWNP` | SA |
| United Arab Emirates | `A2VIGQ35RCS4UG` | AE |
| India | `A21TJRUUN4KGV` | IN |

### Far East

| Country | Marketplace ID | Country Code |
|---------|----------------|--------------|
| Singapore | `A19VAU5U5O7RUS` | SG |
| Australia | `A39IBJ37TRP1C6` | AU |
| Japan | `A1VC38T7YXB528` | JP |

---

## Authentication (LWA OAuth)

SP-API uses **Login with Amazon (LWA)** OAuth 2.0 for authentication.

### Token Request

**Endpoint:** `POST https://api.amazon.com/auth/o2/token`  
**Content-Type:** `application/x-www-form-urlencoded;charset=UTF-8`

#### For Operations Requiring Seller Authorization (most operations):

```
grant_type=refresh_token
&refresh_token=<LWA_REFRESH_TOKEN>
&client_id=<LWA_CLIENT_ID>
&client_secret=<LWA_CLIENT_SECRET>
```

#### For Grantless Operations (Notifications API, Application Management):

```
grant_type=client_credentials
&scope=<SCOPE>
&client_id=<LWA_CLIENT_ID>
&client_secret=<LWA_CLIENT_SECRET>
```

**Grantless Scopes:**
- `sellingpartnerapi::notifications` - For Notifications API
- `sellingpartnerapi::client_credential:rotation` - For Application Management API

### Token Response

```json
{
  "access_token": "Atza|IQEBLjAsAh...",
  "token_type": "bearer",
  "expires_in": 3600,
  "refresh_token": "Atzr|IQEBLzAt..."
}
```

**Important:**
- Access tokens expire after **1 hour** (3600 seconds)
- Maximum token size: 2048 bytes
- Refresh tokens do not expire but can be revoked

### Restricted Data Token (RDT)

For operations returning **Personally Identifiable Information (PII)**, use a Restricted Data Token instead of regular access token. Obtained via the **Tokens API**.

---

## Request Signing & Headers

### Required Headers

| Header | Description |
|--------|-------------|
| `host` | Regional endpoint (e.g., `sellingpartnerapi-na.amazon.com`) |
| `x-amz-access-token` | LWA access token (or RDT for restricted operations) |
| `x-amz-date` | Request timestamp (ISO 8601 format) |
| `user-agent` | Application identifier (max 500 chars) |

### User-Agent Format

```
AppName/AppVersion (Language=LanguageName/Version; Platform=OS/Version)
```

**Examples:**
- `MySellingTool/2.0 (Language=Python/3.11; Platform=Linux)`
- `OdooConnector/1.0 (Language=Python/3.10; Platform=Ubuntu/22.04)`

### Example Request

```http
GET /orders/v0/orders?MarketplaceIds=ATVPDKIKX0DER&CreatedAfter=2024-01-01T00:00:00Z HTTP/1.1
Host: sellingpartnerapi-na.amazon.com
x-amz-access-token: Atza|IQEBLjAsAhRmHjNgHpi0U-Dme37rR6CuUpSREXAMPLE
x-amz-date: 20240130T123600Z
user-agent: OdooAmazonConnector/1.0 (Language=Python/3.11)
```

---

## Rate Limits & Throttling

SP-API uses the **token bucket algorithm** for rate limiting.

### Key Concepts

- **Rate Limit:** Tokens added per second
- **Burst Limit:** Maximum bucket size (max requests before throttling)
- **429 Response:** Throttled - implement exponential backoff

### Rate Limit Factors

1. **API Operation:** Each operation has its own limits
2. **Seller + Application Pair:** Limits apply per seller-app combination
3. **Region/Marketplace:** Different accounts have separate buckets

### Usage Plan Types

- **Standard:** Static limits for all callers
- **Dynamic:** Auto-adjusted based on seller's business metrics

### Response Header

Check `x-amzn-RateLimit-Limit` header for current rate limit (when available).

### Common API Rate Limits

#### Feeds API v2021-06-30

| Operation | Rate/sec | Burst |
|-----------|----------|-------|
| `createFeed` | 0.0083 | 15 |
| `createFeedDocument` | 0.5 | 15 |
| `getFeed` | 2 | 15 |
| `getFeeds` | 0.0222 | 10 |
| `getFeedDocument` | 0.0222 | 10 |
| `cancelFeed` | 2 | 15 |

**Special Limits for JSON_LISTINGS_FEED:**
- Max 5 feeds per account per 5 minutes
- Max 25,000 records per feed submission

#### Orders API (Dynamic - varies by seller)

Typical defaults (verify via response headers):

| Operation | Rate/sec | Burst |
|-----------|----------|-------|
| `getOrders` | 0.0167 | 20 |
| `getOrder` | 0.5 | 30 |
| `getOrderItems` | 0.5 | 30 |

#### Reports API v2021-06-30

| Operation | Rate/sec | Burst |
|-----------|----------|-------|
| `createReport` | 0.0167 | 15 |
| `getReport` | 2 | 15 |
| `getReports` | 0.0222 | 10 |
| `getReportDocument` | 0.0167 | 15 |

### Handling Throttling

```python
import time
from random import uniform

def call_with_retry(api_func, max_retries=5):
    for attempt in range(max_retries):
        try:
            return api_func()
        except ThrottlingException:
            if attempt == max_retries - 1:
                raise
            # Exponential backoff with jitter
            wait_time = (2 ** attempt) + uniform(0, 1)
            time.sleep(wait_time)
```

---

## Key APIs for Odoo Integration

### Orders API

**Current Version:** v2026-01-01 (also v0 available)  
**Purpose:** Retrieve and manage orders

**Key Operations:**
- `getOrders` - List orders with filters
- `getOrder` - Get single order details  
- `getOrderItems` - Get order line items
- `getOrderBuyerInfo` - Get buyer PII (requires RDT)
- `getOrderAddress` - Get shipping address (requires RDT)
- `confirmShipment` - Confirm order shipment

**Note:** Orders API supports orders from 2016+ for JP/AU/SG, last 2 years for others.

### Feeds API

**Current Version:** v2021-06-30  
**Purpose:** Upload data to Amazon (inventory, pricing, orders)

**Workflow:**
1. `createFeedDocument` - Get upload URL
2. Upload file to presigned URL
3. `createFeed` - Submit feed for processing
4. `getFeed` - Poll for completion
5. `getFeedDocument` - Get processing report

**Key Feed Types:**
- `POST_FLAT_FILE_INVLOADER_DATA` - Inventory updates
- `POST_FLAT_FILE_PRICEANDQUANTITYONLY_UPDATE_DATA` - Price/quantity updates
- `JSON_LISTINGS_FEED` - Modern JSON listing updates

### Reports API

**Current Version:** v2021-06-30  
**Purpose:** Request and download reports

**Workflow:**
1. `createReport` - Request report generation
2. `getReport` - Poll until status is `DONE`
3. `getReportDocument` - Get download URL
4. Download and decompress (usually gzip)

**Key Report Types:**
- `GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE` - All orders
- `GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA` - FBA inventory
- `GET_MERCHANT_LISTINGS_ALL_DATA` - All listings

### FBA Inventory API

**Current Version:** v1  
**Purpose:** Track FBA inventory levels

**Key Operation:**
- `getInventorySummaries` - Get inventory quantities by SKU

**Returns:**
- Fulfillable quantity
- Inbound quantity
- Reserved quantity
- Unfulfillable quantity

### Fulfillment Inbound API

**Current Version:** v2024-03-20 (also v0 legacy)  
**Purpose:** Create FBA inbound shipments

**Key Operations:**
- `createInboundPlan` - Create shipment plan
- `listInboundPlans` - List existing plans
- `confirmPlacementOption` - Confirm placement

### Notifications API

**Current Version:** v1  
**Purpose:** Subscribe to real-time notifications

**Key Notification Types:**
- `ORDER_CHANGE` - Order status changes
- `ANY_OFFER_CHANGED` - Pricing/Buy Box changes
- `FBA_INVENTORY_AVAILABILITY_CHANGES` - Inventory changes
- `FEED_PROCESSING_FINISHED` - Feed completion

**Destination Types:**
- Amazon EventBridge
- Amazon SQS

### Catalog Items API

**Current Version:** v2022-04-01  
**Purpose:** Search and retrieve product catalog information

**Key Operations:**
- `searchCatalogItems` - Search by keywords, ASIN, etc.
- `getCatalogItem` - Get item details by ASIN

### Product Pricing API

**Current Version:** v2022-05-01 (also v0)  
**Purpose:** Get competitive pricing information

**Key Operations:**
- `getCompetitiveSummary` - Competitive pricing
- `getFeaturedOfferExpectedPriceBatch` - Featured offer pricing

---

## Python SDK Options

### 1. Official Amazon Prebuilt SDK (Recommended)

**Package:** `amzn-sp-api`  
**PyPI:** https://pypi.org/project/amzn-sp-api/  
**GitHub:** https://github.com/amzn/selling-partner-api-sdk

```bash
pip install amzn-sp-api
```

```python
from sp_api.api import Orders
from sp_api.base import Marketplaces

# Configuration
credentials = {
    'refresh_token': '<refresh_token>',
    'lwa_app_id': '<client_id>',
    'lwa_client_secret': '<client_secret>',
}

# Initialize and call
orders_api = Orders(credentials=credentials, marketplace=Marketplaces.US)
response = orders_api.get_orders(CreatedAfter='2024-01-01T00:00:00Z')
```

### 2. Generate Custom SDK

Use OpenAPI Generator with official Swagger models:

```bash
# Download models from GitHub
git clone https://github.com/amzn/selling-partner-api-models.git

# Generate Python SDK
openapi-generator generate \
  -i selling-partner-api-models/models/orders-api-model/ordersV0.json \
  -g python \
  -o ./generated-sdk/orders
```

### 3. Community SDK: python-amazon-sp-api

**Package:** `python-amazon-sp-api`  
**Note:** Third-party, not officially maintained by Amazon

```bash
pip install python-amazon-sp-api
```

### SDK Requirements

- Python 3.9 or higher (per official SDK docs)
- `requests` for HTTP
- `boto3` for AWS signature (if not using SDK)

---

## Deprecated APIs (Avoid!)

### ⚠️ MWS (Marketplace Web Service)

**Status:** DEPRECATED - Do not use for new integrations  
**Migration:** Use SP-API equivalents

| MWS API | SP-API Replacement |
|---------|-------------------|
| Orders API (MWS) | Orders API v0/v2026-01-01 |
| Feeds API (MWS) | Feeds API v2021-06-30 |
| Reports API (MWS) | Reports API v2021-06-30 |
| Products API (MWS) | Catalog Items API v2022-04-01 |
| FBA Inventory (MWS) | FBA Inventory API v1 |

### Deprecated SP-API Versions

Check the official deprecation schedule:  
https://developer-docs.amazon.com/sp-api/docs/sp-api-deprecations

**Currently Deprecated:**
- Catalog Items v0 - Use v2022-04-01
- Catalog Items v2020-12-01 - Use v2022-04-01
- Fulfillment Inbound v0 - Use v2024-03-20 (partial)
- Orders v0 - Consider v2026-01-01

---

## Additional Resources

- **API References:** https://developer-docs.amazon.com/sp-api/reference
- **Code Samples:** https://developer-docs.amazon.com/sp-api/recipes
- **Release Notes:** https://developer-docs.amazon.com/sp-api/page/release-notes
- **FAQ:** https://developer-docs.amazon.com/sp-api/page/faq
- **YouTube Channel:** https://www.youtube.com/@amazon-sp-api

---

## Document History

| Date | Change |
|------|--------|
| 2026-01-30 | Initial verified reference created from official Amazon documentation |
