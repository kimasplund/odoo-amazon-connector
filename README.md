# Amazon Connector for Odoo 18

[![License: LGPL-3](https://img.shields.io/badge/License-LGPL%20v3-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0)
[![Odoo Version](https://img.shields.io/badge/Odoo-18.0-purple.svg)](https://www.odoo.com)

Enterprise-grade **Amazon Selling Partner API (SP-API)** integration for Odoo 18. Seamlessly connect your Odoo ERP with Amazon marketplaces worldwide.

---

## ✨ Features

### 📦 Product Management
- Full product catalog synchronization
- ASIN/SKU mapping with variant support
- Category and browse node mapping
- A+ Content and Brand Registry support

### 📊 Inventory Management
- Real-time inventory synchronization
- Multi-warehouse support
- FBA inventory tracking
- Safety stock and replenishment alerts

### 🚚 FBA Integration
- Inbound shipment creation and tracking
- FBA fee calculation and monitoring
- Multi-Channel Fulfillment (MCF)
- Inventory placement optimization

### 🛒 Order Management
- Automatic order import (FBA & FBM)
- Order status synchronization
- Shipping and tracking updates
- Returns and refunds processing

### 💰 Financial & Reporting
- Settlement report import
- Fee reconciliation
- VAT calculation (EU compliance)
- Comprehensive Amazon dashboard

### 🌍 Supported Marketplaces
| Region | Marketplaces |
|--------|-------------|
| Europe | DE, UK, FR, IT, ES, NL, SE, PL, BE |
| Americas | US, CA, MX, BR |
| Asia-Pacific | JP, AU, IN |
| Middle East | UAE, SA, TR |

---

## 📋 Requirements

### Odoo
- **Odoo 18.0** (Community or Enterprise)

### Python Packages
```
requests
cryptography
python-dateutil
```

### Odoo Module Dependencies
- `base`
- `sale_management`
- `stock`
- `product`
- `account`
- `delivery`
- `sale_stock`

---

## 🚀 Installation

### 1. Clone the Repository
```bash
cd /path/to/odoo/custom-addons
git clone https://github.com/YOUR_USERNAME/odoo18-amazon-connector.git amazon_connector
```

### 2. Install Python Dependencies
```bash
pip install requests cryptography python-dateutil
```

### 3. Update Odoo Addons Path
Add your custom addons folder to `odoo.conf`:
```ini
addons_path = /path/to/odoo/addons,/path/to/odoo/custom-addons
```

### 4. Restart Odoo & Install
```bash
# Restart Odoo service
sudo systemctl restart odoo

# Or via command line
./odoo-bin -u amazon_connector -d your_database
```

### 5. Activate the Module
1. Go to **Apps** menu
2. Search for "Amazon Connector"
3. Click **Install**

---

## ⚙️ Configuration

### Step 1: Create Amazon SP-API Credentials
1. Register as a developer in [Amazon Seller Central](https://sellercentral.amazon.com/)
2. Create an SP-API application
3. Obtain your credentials:
   - LWA Client ID
   - LWA Client Secret
   - Refresh Token

### Step 2: Configure in Odoo
1. Navigate to **Sales → Amazon → Accounts**
2. Create a new Amazon Account
3. Enter your SP-API credentials
4. Select your marketplace(s)
5. Test the connection

### Step 3: Set Up Synchronization
1. Configure product mapping rules
2. Set up warehouse mappings for FBA
3. Enable automated cron jobs for:
   - Order import
   - Inventory sync
   - Settlement import

---

## 📸 Screenshots

*Coming soon*

<!-- 
![Dashboard](static/description/screenshot_dashboard.png)
![Orders](static/description/screenshot_orders.png)
![Products](static/description/screenshot_products.png)
-->

---

## 🔧 Technical Details

### Module Structure
```
amazon_connector/
├── controllers/     # API endpoints
├── data/           # Default data & cron jobs
├── demo/           # Demo data
├── doc/            # Documentation
├── models/         # Business logic
├── security/       # Access rights
├── services/       # SP-API service layer
├── static/         # Assets (CSS, JS, images)
├── tests/          # Unit tests
├── views/          # UI definitions
└── wizards/        # Transient models
```

### SP-API Integration
This module implements the official Amazon SP-API including:
- OAuth 2.0 / LWA authentication
- Role-based credential management
- Rate limiting compliance
- Sandbox testing support

---

## 📄 License

This project is licensed under the **GNU Lesser General Public License v3.0 (LGPL-3.0)**.

See [LICENSE](LICENSE) for the full license text.

---

## 👥 Authors & Contributors

**Amazon Connector Team**

---

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

---

## 📞 Support

For issues and feature requests, please use the [GitHub Issues](https://github.com/YOUR_USERNAME/odoo18-amazon-connector/issues) page.
