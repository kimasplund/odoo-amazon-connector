# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmazonFBAInventory(models.Model):
    """
    Amazon FBA Inventory.
    
    Tracks inventory levels at Amazon Fulfillment Centers, including
    available, reserved, inbound, and unfulfillable quantities.
    """
    _name = 'amazon.fba.inventory'
    _description = 'Amazon FBA Inventory'
    _order = 'last_updated desc'
    _rec_name = 'display_name'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    
    # Identification
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )
    
    # Relationships
    account_id = fields.Many2one(
        'amazon.account',
        string='Amazon Account',
        required=True,
        ondelete='cascade',
        index=True,
    )
    marketplace_id = fields.Many2one(
        'amazon.marketplace',
        string='Marketplace',
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        ondelete='set null',
        index=True,
    )
    listing_id = fields.Many2one(
        'amazon.product.listing',
        string='Amazon Listing',
        ondelete='set null',
    )
    
    # Amazon Identifiers
    amazon_sku = fields.Char(
        string='Amazon SKU',
        required=True,
        index=True,
    )
    amazon_asin = fields.Char(
        string='ASIN',
        index=True,
    )
    amazon_fnsku = fields.Char(
        string='FNSKU',
    )
    product_name = fields.Char(
        string='Product Name',
    )
    
    # Fulfillment Center
    fulfillment_center_id = fields.Char(
        string='Fulfillment Center',
        help='Specific FC code if tracking per-FC inventory.',
    )
    country_code = fields.Char(
        string='Country Code',
    )
    
    # Inventory Quantities
    quantity_available = fields.Integer(
        string='Available',
        default=0,
        help='Quantity available for sale.',
    )
    quantity_reserved = fields.Integer(
        string='Reserved',
        default=0,
        help='Quantity reserved for pending orders.',
    )
    quantity_inbound_working = fields.Integer(
        string='Inbound (Working)',
        default=0,
        help='Quantity in inbound shipments being prepared.',
    )
    quantity_inbound_shipped = fields.Integer(
        string='Inbound (Shipped)',
        default=0,
        help='Quantity in shipped inbound shipments.',
    )
    quantity_inbound_receiving = fields.Integer(
        string='Inbound (Receiving)',
        default=0,
        help='Quantity being received at fulfillment center.',
    )
    quantity_unfulfillable = fields.Integer(
        string='Unfulfillable',
        default=0,
        help='Quantity that cannot be fulfilled (damaged, etc.).',
    )
    quantity_researching = fields.Integer(
        string='Researching',
        default=0,
        help='Quantity under investigation.',
    )
    
    # Computed Totals
    quantity_total = fields.Integer(
        string='Total FBA',
        compute='_compute_totals',
        store=True,
        help='Total quantity at Amazon (available + reserved + unfulfillable).',
    )
    quantity_inbound_total = fields.Integer(
        string='Total Inbound',
        compute='_compute_totals',
        store=True,
        help='Total quantity in inbound shipments.',
    )
    quantity_sellable = fields.Integer(
        string='Sellable',
        compute='_compute_totals',
        store=True,
        help='Available + Inbound receiving.',
    )
    
    # Alerts & Thresholds
    restock_level = fields.Integer(
        string='Restock Level',
        default=0,
        help='Minimum quantity before restock alert.',
    )
    needs_restock = fields.Boolean(
        string='Needs Restock',
        compute='_compute_needs_restock',
        store=True,
    )
    days_of_supply = fields.Float(
        string='Days of Supply',
        digits=(16, 1),
        help='Estimated days until stockout based on sales velocity.',
    )
    
    # Fees & Storage
    storage_type = fields.Selection(
        selection=[
            ('standard', 'Standard Size'),
            ('oversize', 'Oversize'),
            ('apparel', 'Apparel'),
            ('footwear', 'Footwear'),
            ('dangerous_goods', 'Dangerous Goods'),
        ],
        string='Storage Type',
        default='standard',
    )
    monthly_storage_fee = fields.Monetary(
        string='Monthly Storage Fee',
        currency_field='currency_id',
    )
    long_term_storage_fee = fields.Monetary(
        string='Long-term Storage Fee',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='marketplace_id.currency_id',
        store=True,
    )
    
    # Inventory Age
    inventory_age_0_90 = fields.Integer(
        string='0-90 Days',
        default=0,
    )
    inventory_age_91_180 = fields.Integer(
        string='91-180 Days',
        default=0,
    )
    inventory_age_181_270 = fields.Integer(
        string='181-270 Days',
        default=0,
    )
    inventory_age_271_365 = fields.Integer(
        string='271-365 Days',
        default=0,
    )
    inventory_age_365_plus = fields.Integer(
        string='365+ Days',
        default=0,
        help='Inventory older than 365 days (long-term storage fees apply).',
    )
    
    # Stranded Inventory
    is_stranded = fields.Boolean(
        string='Stranded',
        default=False,
        help='Inventory without an active listing.',
    )
    stranded_reason = fields.Char(
        string='Stranded Reason',
    )
    
    # Sync Information
    last_updated = fields.Datetime(
        string='Last Updated',
        readonly=True,
    )
    last_sync_date = fields.Datetime(
        string='Last Synced',
        readonly=True,
    )
    sync_error = fields.Text(
        string='Sync Error',
        readonly=True,
    )
    
    # -------------------------------------------------------------------------
    # COMPUTES
    # -------------------------------------------------------------------------
    
    @api.depends('amazon_sku', 'product_name', 'marketplace_id')
    def _compute_display_name(self):
        for inv in self:
            parts = []
            if inv.amazon_sku:
                parts.append(inv.amazon_sku)
            if inv.product_name:
                parts.append(inv.product_name[:50])
            if inv.marketplace_id:
                parts.append(f'[{inv.marketplace_id.code}]')
            inv.display_name = ' - '.join(parts) or _('New')
    
    @api.depends(
        'quantity_available', 'quantity_reserved', 'quantity_unfulfillable',
        'quantity_inbound_working', 'quantity_inbound_shipped', 'quantity_inbound_receiving'
    )
    def _compute_totals(self):
        for inv in self:
            inv.quantity_total = (
                inv.quantity_available + 
                inv.quantity_reserved + 
                inv.quantity_unfulfillable
            )
            inv.quantity_inbound_total = (
                inv.quantity_inbound_working + 
                inv.quantity_inbound_shipped + 
                inv.quantity_inbound_receiving
            )
            inv.quantity_sellable = (
                inv.quantity_available + 
                inv.quantity_inbound_receiving
            )
    
    @api.depends('quantity_available', 'restock_level')
    def _compute_needs_restock(self):
        for inv in self:
            inv.needs_restock = (
                inv.restock_level > 0 and 
                inv.quantity_available <= inv.restock_level
            )
    
    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------
    
    _sql_constraints = [
        (
            'account_marketplace_sku_unique',
            'UNIQUE(account_id, marketplace_id, amazon_sku)',
            'SKU must be unique per account and marketplace!'
        ),
    ]
    
    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'last_updated' not in vals:
                vals['last_updated'] = fields.Datetime.now()
        return super().create(vals_list)
    
    def write(self, vals):
        if any(f in vals for f in [
            'quantity_available', 'quantity_reserved', 'quantity_inbound_working',
            'quantity_inbound_shipped', 'quantity_inbound_receiving', 'quantity_unfulfillable'
        ]):
            vals['last_updated'] = fields.Datetime.now()
        return super().write(vals)
    
    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------
    
    def action_refresh(self):
        """Refresh inventory from Amazon."""
        self.ensure_one()
        self._sync_from_amazon()
        return True
    
    def action_view_product(self):
        """Open the product form."""
        self.ensure_one()
        if not self.product_id:
            raise UserError(_('No product linked to this inventory record.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Product'),
            'res_model': 'product.product',
            'res_id': self.product_id.id,
            'view_mode': 'form',
        }
    
    def action_view_listing(self):
        """Open the Amazon listing."""
        self.ensure_one()
        if not self.listing_id:
            raise UserError(_('No Amazon listing linked.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Amazon Listing'),
            'res_model': 'amazon.product.listing',
            'res_id': self.listing_id.id,
            'view_mode': 'form',
        }
    
    def action_create_removal_order(self):
        """Create a removal order for unfulfillable inventory."""
        self.ensure_one()
        # Placeholder for removal order wizard
        raise UserError(_('Removal order creation not yet implemented.'))
    
    def action_view_shipments(self):
        """View inbound shipments for this SKU."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('FBA Shipments'),
            'res_model': 'amazon.fba.shipment',
            'view_mode': 'tree,form',
            'domain': [
                ('account_id', '=', self.account_id.id),
                ('marketplace_id', '=', self.marketplace_id.id),
                ('item_ids.amazon_sku', '=', self.amazon_sku),
            ],
        }
    
    def action_open_in_amazon(self):
        """Open inventory management in Seller Central."""
        self.ensure_one()
        base_urls = {
            'DE': 'https://sellercentral.amazon.de',
            'UK': 'https://sellercentral.amazon.co.uk',
            'FR': 'https://sellercentral.amazon.fr',
            'US': 'https://sellercentral.amazon.com',
        }
        base_url = base_urls.get(
            self.marketplace_id.code,
            'https://sellercentral.amazon.com'
        )
        url = f"{base_url}/hz/fba/storage-management"
        
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }
    
    # -------------------------------------------------------------------------
    # SYNC METHODS
    # -------------------------------------------------------------------------
    
    def _sync_from_amazon(self):
        """Sync this inventory record from Amazon."""
        self.ensure_one()
        _logger.info('Syncing FBA inventory for SKU: %s', self.amazon_sku)
        
        try:
            # In production: Fetch from SP-API
            # client = self.account_id._get_sp_api_client()
            # response = client.fba_inventory.get_inventory_summaries(
            #     sellerSkus=[self.amazon_sku],
            #     marketplaceIds=[self.marketplace_id.amazon_marketplace_id],
            # )
            
            self.write({
                'last_sync_date': fields.Datetime.now(),
                'sync_error': False,
            })
            
        except Exception as e:
            _logger.exception('Error syncing inventory for SKU %s', self.amazon_sku)
            self.write({
                'sync_error': str(e),
                'last_sync_date': fields.Datetime.now(),
            })
            raise
        
        return True
    
    @api.model
    def _update_or_create_from_amazon(self, account_id, marketplace_id, data):
        """
        Update or create inventory record from Amazon data.
        
        :param account_id: amazon.account ID
        :param marketplace_id: amazon.marketplace ID
        :param data: Dict with inventory data from Amazon
        :return: amazon.fba.inventory record
        """
        existing = self.search([
            ('account_id', '=', account_id),
            ('marketplace_id', '=', marketplace_id),
            ('amazon_sku', '=', data.get('sellerSku')),
        ], limit=1)
        
        details = data.get('inventoryDetails', {})
        vals = {
            'amazon_sku': data.get('sellerSku'),
            'amazon_asin': data.get('asin'),
            'amazon_fnsku': data.get('fnsku'),
            'product_name': data.get('productName'),
            'quantity_available': details.get('fulfillableQuantity', 0),
            'quantity_reserved': details.get('reservedQuantity', {}).get('totalReservedQuantity', 0),
            'quantity_inbound_working': details.get('inboundWorkingQuantity', 0),
            'quantity_inbound_shipped': details.get('inboundShippedQuantity', 0),
            'quantity_inbound_receiving': details.get('inboundReceivingQuantity', 0),
            'quantity_unfulfillable': details.get('unfulfillableQuantity', {}).get('totalUnfulfillableQuantity', 0),
            'quantity_researching': details.get('researchingQuantity', {}).get('totalResearchingQuantity', 0),
            'last_sync_date': fields.Datetime.now(),
            'sync_error': False,
        }
        
        # Try to link to product
        if not existing or not existing.product_id:
            product = self._find_product_by_sku(data.get('sellerSku'))
            if product:
                vals['product_id'] = product.id
        
        if existing:
            existing.write(vals)
            return existing
        else:
            vals.update({
                'account_id': account_id,
                'marketplace_id': marketplace_id,
            })
            return self.create(vals)
    
    @api.model
    def _find_product_by_sku(self, sku):
        """Find product by SKU/default_code."""
        if not sku:
            return False
        
        # First try amazon.product.listing
        listing = self.env['amazon.product.listing'].search([
            ('seller_sku', '=', sku),
        ], limit=1)
        if listing and listing.product_id:
            return listing.product_id
        
        # Fallback to product.product default_code
        product = self.env['product.product'].search([
            ('default_code', '=', sku),
        ], limit=1)
        
        return product or False
    
    # -------------------------------------------------------------------------
    # REPORTING
    # -------------------------------------------------------------------------
    
    @api.model
    def get_inventory_summary(self, account_id=None, marketplace_id=None):
        """
        Get inventory summary for dashboard.
        
        :return: Dict with summary statistics
        """
        domain = []
        if account_id:
            domain.append(('account_id', '=', account_id))
        if marketplace_id:
            domain.append(('marketplace_id', '=', marketplace_id))
        
        records = self.search(domain)
        
        return {
            'total_skus': len(records),
            'total_available': sum(records.mapped('quantity_available')),
            'total_reserved': sum(records.mapped('quantity_reserved')),
            'total_inbound': sum(records.mapped('quantity_inbound_total')),
            'total_unfulfillable': sum(records.mapped('quantity_unfulfillable')),
            'needs_restock': len(records.filtered('needs_restock')),
            'stranded': len(records.filtered('is_stranded')),
            'aged_365_plus': sum(records.mapped('inventory_age_365_plus')),
        }
