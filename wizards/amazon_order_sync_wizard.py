# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

import logging
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmazonOrderSyncWizard(models.TransientModel):
    """
    Wizard for manual Amazon order synchronization.
    Imports orders from Amazon and creates corresponding sale orders in Odoo.
    """
    _name = 'amazon.order.sync.wizard'
    _description = 'Sync Amazon Orders'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    
    # Account & Marketplace Selection
    account_id = fields.Many2one(
        'amazon.account',
        string='Amazon Account',
        required=True,
        default=lambda self: self._default_account_id(),
    )
    marketplace_ids = fields.Many2many(
        'amazon.marketplace',
        string='Marketplaces',
        domain="[('account_ids', 'in', account_id)]",
        help='Leave empty to sync from all marketplaces.',
    )
    
    # Date Range
    date_from = fields.Datetime(
        string='From Date',
        required=True,
        default=lambda self: fields.Datetime.now() - timedelta(days=7),
    )
    date_to = fields.Datetime(
        string='To Date',
        required=True,
        default=lambda self: fields.Datetime.now(),
    )
    
    # Filter Options
    order_status = fields.Selection([
        ('all', 'All Orders'),
        ('Pending', 'Pending'),
        ('Unshipped', 'Unshipped'),
        ('PartiallyShipped', 'Partially Shipped'),
        ('Shipped', 'Shipped'),
        ('Canceled', 'Canceled'),
    ], string='Order Status', default='all',
       help='Filter orders by status.')
    
    fulfillment_channel = fields.Selection([
        ('all', 'All Channels'),
        ('MFN', 'Merchant Fulfilled (FBM)'),
        ('AFN', 'Amazon Fulfilled (FBA)'),
    ], string='Fulfillment', default='all',
       help='Filter by fulfillment channel.')
    
    order_type = fields.Selection([
        ('all', 'All Orders'),
        ('StandardOrder', 'Standard Orders'),
        ('Preorder', 'Preorders'),
    ], string='Order Type', default='all')
    
    # Sync Options
    sync_mode = fields.Selection([
        ('new', 'New Orders Only'),
        ('update', 'Update Existing Orders'),
        ('all', 'New and Update Existing'),
    ], string='Sync Mode', default='new', required=True,
       help='New: Only import new orders\n'
            'Update: Only update existing orders\n'
            'All: Import new and update existing')
    
    # Sale Order Options
    create_sale_orders = fields.Boolean(
        string='Create Sale Orders',
        default=True,
        help='Create Odoo sale orders for imported Amazon orders.',
    )
    auto_confirm_orders = fields.Boolean(
        string='Auto-Confirm Orders',
        default=False,
        help='Automatically confirm created sale orders.',
    )
    team_id = fields.Many2one(
        'crm.team',
        string='Sales Team',
        help='Assign sale orders to this sales team.',
    )
    
    # Customer Options
    create_customers = fields.Boolean(
        string='Create Customers',
        default=True,
        help='Create customer records for new buyers.',
    )
    default_customer_id = fields.Many2one(
        'res.partner',
        string='Default Customer',
        help='Use this customer for all orders (e.g., Amazon generic customer).',
    )
    
    # State & Progress
    state = fields.Selection([
        ('draft', 'Configuration'),
        ('syncing', 'Syncing'),
        ('preview', 'Preview'),
        ('importing', 'Importing'),
        ('done', 'Completed'),
        ('error', 'Error'),
    ], string='State', default='draft')
    
    progress_percent = fields.Float(string='Progress', default=0.0)
    progress_message = fields.Char(string='Status')
    
    # Preview
    preview_line_ids = fields.One2many(
        'amazon.order.sync.wizard.line',
        'wizard_id',
        string='Orders Found',
    )
    preview_count = fields.Integer(
        string='Orders Found',
        compute='_compute_preview_stats',
    )
    preview_new = fields.Integer(
        string='New Orders',
        compute='_compute_preview_stats',
    )
    preview_existing = fields.Integer(
        string='Existing Orders',
        compute='_compute_preview_stats',
    )
    preview_total = fields.Monetary(
        string='Total Value',
        compute='_compute_preview_stats',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )
    
    # Results
    result_imported = fields.Integer(string='Orders Imported', default=0)
    result_updated = fields.Integer(string='Orders Updated', default=0)
    result_errors = fields.Integer(string='Errors', default=0)
    result_sale_orders = fields.Integer(string='Sale Orders Created', default=0)
    result_log = fields.Text(string='Sync Log')
    
    imported_order_ids = fields.Many2many(
        'amazon.order',
        string='Imported Orders',
    )
    created_sale_order_ids = fields.Many2many(
        'sale.order',
        string='Created Sale Orders',
    )
    
    # -------------------------------------------------------------------------
    # DEFAULT METHODS
    # -------------------------------------------------------------------------
    
    def _default_account_id(self):
        return self.env['amazon.account'].search([('active', '=', True)], limit=1)
    
    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    
    @api.depends('preview_line_ids', 'preview_line_ids.status', 'preview_line_ids.total_amount')
    def _compute_preview_stats(self):
        for wizard in self:
            lines = wizard.preview_line_ids
            wizard.preview_count = len(lines)
            wizard.preview_new = len(lines.filtered(lambda l: l.status == 'new'))
            wizard.preview_existing = len(lines.filtered(lambda l: l.status == 'existing'))
            wizard.preview_total = sum(lines.mapped('total_amount'))
    
    # -------------------------------------------------------------------------
    # ONCHANGE METHODS
    # -------------------------------------------------------------------------
    
    @api.onchange('account_id')
    def _onchange_account_id(self):
        self.marketplace_ids = False
    
    @api.onchange('create_sale_orders')
    def _onchange_create_sale_orders(self):
        if not self.create_sale_orders:
            self.auto_confirm_orders = False
    
    # -------------------------------------------------------------------------
    # CONSTRAINT METHODS
    # -------------------------------------------------------------------------
    
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from > wizard.date_to:
                raise UserError(_('From Date must be before To Date.'))
            if (wizard.date_to - wizard.date_from).days > 90:
                raise UserError(_('Date range cannot exceed 90 days.'))
    
    # -------------------------------------------------------------------------
    # ACTION METHODS
    # -------------------------------------------------------------------------
    
    def action_fetch_orders(self):
        """Fetch orders from Amazon for preview."""
        self.ensure_one()
        
        self.state = 'syncing'
        self.progress_message = _('Connecting to Amazon...')
        self.preview_line_ids.unlink()
        
        try:
            sp_api = self.account_id._get_sp_api_client()
            
            # Build marketplace filter
            marketplace_ids = self.marketplace_ids.mapped('marketplace_id') if self.marketplace_ids else None
            
            # Build status filter
            statuses = None
            if self.order_status != 'all':
                statuses = [self.order_status]
            
            # Build fulfillment filter
            fulfillment = None
            if self.fulfillment_channel != 'all':
                fulfillment = self.fulfillment_channel
            
            self.progress_message = _('Fetching orders...')
            
            # Fetch orders
            orders = sp_api.get_orders(
                marketplace_ids=marketplace_ids,
                created_after=self.date_from,
                created_before=self.date_to,
                order_statuses=statuses,
                fulfillment_channels=[fulfillment] if fulfillment else None,
            )
            
            self.progress_message = _('Processing %d orders...', len(orders))
            
            for order_data in orders:
                # Check if order exists
                existing = self.env['amazon.order'].search([
                    ('amazon_order_id', '=', order_data.get('amazon_order_id')),
                ], limit=1)
                
                # Apply sync mode filter
                if self.sync_mode == 'new' and existing:
                    continue
                if self.sync_mode == 'update' and not existing:
                    continue
                
                self.env['amazon.order.sync.wizard.line'].create({
                    'wizard_id': self.id,
                    'selected': True,
                    'amazon_order_id': order_data.get('amazon_order_id'),
                    'purchase_date': order_data.get('purchase_date'),
                    'order_status': order_data.get('order_status'),
                    'fulfillment_channel': order_data.get('fulfillment_channel'),
                    'marketplace_name': order_data.get('marketplace_name', ''),
                    'buyer_name': order_data.get('buyer_name', _('Amazon Customer')),
                    'buyer_email': order_data.get('buyer_email', ''),
                    'ship_city': order_data.get('shipping_address', {}).get('city', ''),
                    'ship_country': order_data.get('shipping_address', {}).get('country_code', ''),
                    'total_amount': order_data.get('order_total', {}).get('amount', 0.0),
                    'currency': order_data.get('order_total', {}).get('currency', 'EUR'),
                    'item_count': order_data.get('number_of_items_unshipped', 0) + 
                                  order_data.get('number_of_items_shipped', 0),
                    'status': 'existing' if existing else 'new',
                    'existing_order_id': existing.id if existing else False,
                    'order_data': str(order_data),  # Store for import
                })
            
            self.state = 'preview'
            self.progress_message = _('Found %d orders', len(self.preview_line_ids))
            
        except Exception as e:
            _logger.exception('Error fetching Amazon orders')
            self.state = 'error'
            self.progress_message = _('Error: %s', str(e))
        
        return self._return_wizard()
    
    def action_sync(self):
        """Import selected orders."""
        self.ensure_one()
        
        selected = self.preview_line_ids.filtered(lambda l: l.selected)
        if not selected:
            raise UserError(_('Please select at least one order to sync.'))
        
        self.state = 'importing'
        self.result_imported = 0
        self.result_updated = 0
        self.result_errors = 0
        self.result_sale_orders = 0
        log_lines = []
        imported_ids = []
        sale_order_ids = []
        
        try:
            sp_api = self.account_id._get_sp_api_client()
            
            total = len(selected)
            for idx, line in enumerate(selected, 1):
                self.progress_percent = (idx / total) * 100
                self.progress_message = _('Syncing order %s (%d/%d)...', 
                                         line.amazon_order_id, idx, total)
                
                try:
                    # Get full order details including items
                    order_details = sp_api.get_order(line.amazon_order_id)
                    order_items = sp_api.get_order_items(line.amazon_order_id)
                    order_details['items'] = order_items
                    
                    # Create/update Amazon order
                    amazon_order = self._sync_order(line, order_details)
                    imported_ids.append(amazon_order.id)
                    
                    if line.status == 'new':
                        self.result_imported += 1
                    else:
                        self.result_updated += 1
                    
                    # Create sale order if enabled
                    if self.create_sale_orders and not amazon_order.sale_order_id:
                        sale_order = self._create_sale_order(amazon_order)
                        if sale_order:
                            sale_order_ids.append(sale_order.id)
                            self.result_sale_orders += 1
                    
                    log_lines.append(f"✓ {line.amazon_order_id}: {line.total_amount} {line.currency}")
                    line.sync_status = 'success'
                    
                except Exception as e:
                    _logger.exception('Error syncing order %s', line.amazon_order_id)
                    log_lines.append(f"✗ {line.amazon_order_id}: {e}")
                    line.sync_status = 'error'
                    line.sync_message = str(e)[:200]
                    self.result_errors += 1
            
            self.imported_order_ids = [(6, 0, imported_ids)]
            self.created_sale_order_ids = [(6, 0, sale_order_ids)]
            self.state = 'done'
            self.progress_percent = 100.0
            self.progress_message = _(
                'Completed: %d imported, %d updated, %d sale orders, %d errors',
                self.result_imported, self.result_updated,
                self.result_sale_orders, self.result_errors
            )
            
        except Exception as e:
            _logger.exception('Error during order sync')
            self.state = 'error'
            self.progress_message = _('Error: %s', str(e))
        
        self.result_log = '\n'.join(log_lines)
        return self._return_wizard()
    
    def action_select_all(self):
        """Select all orders."""
        self.preview_line_ids.write({'selected': True})
        return self._return_wizard()
    
    def action_select_none(self):
        """Deselect all orders."""
        self.preview_line_ids.write({'selected': False})
        return self._return_wizard()
    
    def action_select_new(self):
        """Select only new orders."""
        self.preview_line_ids.write({'selected': False})
        self.preview_line_ids.filtered(lambda l: l.status == 'new').write({'selected': True})
        return self._return_wizard()
    
    def action_view_orders(self):
        """View imported Amazon orders."""
        if not self.imported_order_ids:
            raise UserError(_('No orders to view.'))
        
        return {
            'name': _('Imported Orders'),
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.imported_order_ids.ids)],
        }
    
    def action_view_sale_orders(self):
        """View created sale orders."""
        if not self.created_sale_order_ids:
            raise UserError(_('No sale orders to view.'))
        
        return {
            'name': _('Sale Orders'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.created_sale_order_ids.ids)],
        }
    
    def action_back(self):
        """Go back to configuration."""
        self.state = 'draft'
        return self._return_wizard()
    
    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------
    
    def _sync_order(self, line, order_data):
        """Create or update Amazon order record."""
        AmazonOrder = self.env['amazon.order']
        
        # Find marketplace
        marketplace = self.env['amazon.marketplace'].search([
            ('name', 'ilike', line.marketplace_name),
        ], limit=1) or self.marketplace_ids[:1]
        
        order = line.existing_order_id or AmazonOrder
        
        vals = {
            'account_id': self.account_id.id,
            'marketplace_id': marketplace.id if marketplace else False,
            'amazon_order_id': line.amazon_order_id,
            'purchase_date': line.purchase_date,
            'order_status': line.order_status,
            'fulfillment_channel': line.fulfillment_channel,
            'buyer_name': line.buyer_name,
            'buyer_email': line.buyer_email,
            'order_total': line.total_amount,
            'currency_id': self.env['res.currency'].search([
                ('name', '=', line.currency)
            ], limit=1).id,
            'last_sync_date': fields.Datetime.now(),
        }
        
        # Add shipping address
        shipping = order_data.get('shipping_address', {})
        if shipping:
            vals.update({
                'ship_name': shipping.get('name', ''),
                'ship_address_1': shipping.get('address_line_1', ''),
                'ship_address_2': shipping.get('address_line_2', ''),
                'ship_city': shipping.get('city', ''),
                'ship_state': shipping.get('state_or_region', ''),
                'ship_postal_code': shipping.get('postal_code', ''),
                'ship_country_code': shipping.get('country_code', ''),
            })
        
        if order.exists():
            order.write(vals)
        else:
            order = AmazonOrder.create(vals)
        
        # Sync order items
        self._sync_order_items(order, order_data.get('items', []))
        
        return order
    
    def _sync_order_items(self, order, items):
        """Sync order line items."""
        OrderLine = self.env['amazon.order.line']
        
        # Clear existing lines for update
        order.line_ids.unlink()
        
        for item in items:
            sku = item.get('seller_sku', '')
            
            # Find product
            product = None
            listing = self.env['amazon.product.listing'].search([
                ('seller_sku', '=', sku),
                ('account_id', '=', self.account_id.id),
            ], limit=1)
            if listing:
                product = listing.product_tmpl_id.product_variant_id
            
            OrderLine.create({
                'order_id': order.id,
                'amazon_order_item_id': item.get('order_item_id'),
                'seller_sku': sku,
                'asin': item.get('asin'),
                'title': item.get('title', '')[:256],
                'quantity': item.get('quantity_ordered', 1),
                'item_price': item.get('item_price', {}).get('amount', 0.0),
                'item_tax': item.get('item_tax', {}).get('amount', 0.0),
                'shipping_price': item.get('shipping_price', {}).get('amount', 0.0),
                'shipping_tax': item.get('shipping_tax', {}).get('amount', 0.0),
                'product_id': product.id if product else False,
            })
    
    def _create_sale_order(self, amazon_order):
        """Create Odoo sale order from Amazon order."""
        SaleOrder = self.env['sale.order']
        
        # Get or create customer
        customer = self._get_or_create_customer(amazon_order)
        if not customer:
            return None
        
        # Create sale order
        so_vals = {
            'partner_id': customer.id,
            'amazon_order_id': amazon_order.id,
            'origin': amazon_order.amazon_order_id,
            'date_order': amazon_order.purchase_date,
            'client_order_ref': amazon_order.amazon_order_id,
        }
        
        if self.team_id:
            so_vals['team_id'] = self.team_id.id
        
        sale_order = SaleOrder.create(so_vals)
        
        # Pre-fetch and create placeholder products in batch to avoid N+1 queries
        lines_missing_products = amazon_order.line_ids.filtered(lambda l: not l.product_id and l.seller_sku)
        sku_to_product = {}

        if lines_missing_products:
            Product = self.env['product.product']
            skus = list(set(lines_missing_products.mapped('seller_sku')))

            # Batch search existing
            existing_products = Product.search([('default_code', 'in', skus)])
            for p in existing_products:
                if p.default_code:
                    sku_to_product[p.default_code] = p

            # Batch create missing
            create_vals = []
            seen_skus = set(sku_to_product.keys())

            for line in lines_missing_products:
                if line.seller_sku not in seen_skus:
                    create_vals.append({
                        'name': line.title or f'Amazon Product {line.seller_sku}',
                        'default_code': line.seller_sku,
                        'type': 'consu',
                        'list_price': line.item_price,
                    })
                    seen_skus.add(line.seller_sku)

            if create_vals:
                new_products = Product.create(create_vals)
                for p in new_products:
                    if p.default_code:
                        sku_to_product[p.default_code] = p

        # Create sale order lines
        for line in amazon_order.line_ids:
            product = line.product_id
            if not product:
                # Use pre-fetched/created placeholder product
                if line.seller_sku and line.seller_sku in sku_to_product:
                    product = sku_to_product[line.seller_sku]
                else:
                    # Fallback for edge cases (e.g., missing seller_sku)
                    product = self._get_placeholder_product(line)
            
            self.env['sale.order.line'].create({
                'order_id': sale_order.id,
                'product_id': product.id,
                'name': line.title or product.name,
                'product_uom_qty': line.quantity,
                'price_unit': line.item_price,
            })
        
        # Link back to Amazon order
        amazon_order.sale_order_id = sale_order.id
        
        # Auto-confirm if enabled
        if self.auto_confirm_orders:
            sale_order.action_confirm()
        
        return sale_order
    
    def _get_or_create_customer(self, amazon_order):
        """Get or create customer partner for Amazon order."""
        if self.default_customer_id:
            return self.default_customer_id
        
        if not self.create_customers:
            return self.env.company.partner_id
        
        Partner = self.env['res.partner']
        
        # Try to find by email
        if amazon_order.buyer_email:
            partner = Partner.search([
                ('email', '=', amazon_order.buyer_email),
            ], limit=1)
            if partner:
                return partner
        
        # Create new customer
        country = self.env['res.country'].search([
            ('code', '=', amazon_order.ship_country_code),
        ], limit=1)
        
        return Partner.create({
            'name': amazon_order.buyer_name or amazon_order.ship_name or _('Amazon Customer'),
            'email': amazon_order.buyer_email,
            'street': amazon_order.ship_address_1,
            'street2': amazon_order.ship_address_2,
            'city': amazon_order.ship_city,
            'zip': amazon_order.ship_postal_code,
            'country_id': country.id if country else False,
            'is_amazon_customer': True,
        })
    
    def _get_placeholder_product(self, order_line):
        """Get or create placeholder product for unknown SKU."""
        Product = self.env['product.product']
        
        # Try to find by SKU
        product = Product.search([
            ('default_code', '=', order_line.seller_sku),
        ], limit=1)
        
        if not product:
            product = Product.create({
                'name': order_line.title or f'Amazon Product {order_line.seller_sku}',
                'default_code': order_line.seller_sku,
                'type': 'consu',
                'list_price': order_line.item_price,
            })
        
        return product
    
    def _return_wizard(self):
        """Return action to keep wizard open."""
        return {
            'name': _('Sync Amazon Orders'),
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.order.sync.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }


class AmazonOrderSyncWizardLine(models.TransientModel):
    """Order preview line for sync wizard."""
    _name = 'amazon.order.sync.wizard.line'
    _description = 'Order Sync Preview Line'
    _order = 'purchase_date desc'
    
    wizard_id = fields.Many2one(
        'amazon.order.sync.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    selected = fields.Boolean(string='Sync', default=True)
    
    # Order Data
    amazon_order_id = fields.Char(string='Order ID', required=True)
    purchase_date = fields.Datetime(string='Purchase Date')
    order_status = fields.Char(string='Status')
    fulfillment_channel = fields.Selection([
        ('MFN', 'FBM'),
        ('AFN', 'FBA'),
    ], string='Fulfillment')
    marketplace_name = fields.Char(string='Marketplace')
    
    # Buyer Info
    buyer_name = fields.Char(string='Buyer')
    buyer_email = fields.Char(string='Email')
    ship_city = fields.Char(string='City')
    ship_country = fields.Char(string='Country')
    
    # Amounts
    total_amount = fields.Float(string='Total')
    currency = fields.Char(string='Currency')
    item_count = fields.Integer(string='Items')
    
    # Status
    status = fields.Selection([
        ('new', 'New'),
        ('existing', 'Existing'),
    ], string='Status', default='new')
    existing_order_id = fields.Many2one('amazon.order', string='Existing Order')
    
    # Sync Result
    sync_status = fields.Selection([
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('error', 'Error'),
    ], string='Sync Status', default='pending')
    sync_message = fields.Char(string='Message')
    
    # Raw data storage
    order_data = fields.Text(string='Order Data')
