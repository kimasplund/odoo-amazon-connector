# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class ProductTemplate(models.Model):
    """Extend product.template with Amazon integration fields."""
    _inherit = 'product.template'

    # -------------------------------------------------------------------------
    # AMAZON INTEGRATION FIELDS
    # -------------------------------------------------------------------------
    amazon_listing_ids = fields.One2many(
        comodel_name='amazon.product.listing',
        inverse_name='product_tmpl_id',
        string='Amazon Listings',
        help='Amazon marketplace listings for this product',
    )
    amazon_listing_count = fields.Integer(
        string='# Amazon Listings',
        compute='_compute_amazon_listing_count',
    )
    has_amazon_listing = fields.Boolean(
        string='Has Amazon Listing',
        compute='_compute_amazon_listing_count',
        store=True,
        help='Whether this product has any Amazon listings',
    )
    
    # Quick access fields (computed from listings)
    amazon_primary_asin = fields.Char(
        string='Primary ASIN',
        compute='_compute_amazon_primary_info',
        help='ASIN from the primary/first Amazon listing',
    )
    amazon_primary_sku = fields.Char(
        string='Primary SKU',
        compute='_compute_amazon_primary_info',
        help='SKU from the primary/first Amazon listing',
    )

    # Amazon-specific product data
    amazon_brand = fields.Char(
        string='Amazon Brand',
        help='Brand name as it appears on Amazon (may differ from Odoo brand)',
    )
    amazon_manufacturer = fields.Char(
        string='Amazon Manufacturer',
        help='Manufacturer name for Amazon listings',
    )
    amazon_item_type = fields.Char(
        string='Item Type Keyword',
        help='Amazon item type keyword for categorization',
    )
    amazon_search_terms = fields.Char(
        string='Default Search Terms',
        help='Default search terms template for Amazon listings (max 250 bytes)',
    )

    # Fulfillment preferences
    amazon_default_fulfillment = fields.Selection(
        selection=[
            ('FBM', 'Fulfilled by Merchant'),
            ('FBA', 'Fulfilled by Amazon'),
        ],
        string='Default Fulfillment',
        default='FBM',
        help='Default fulfillment channel for new Amazon listings',
    )

    # Sync control
    amazon_sync_enabled = fields.Boolean(
        string='Amazon Sync Enabled',
        default=True,
        help='Enable/disable Amazon synchronization for this product',
    )
    amazon_auto_create_listing = fields.Boolean(
        string='Auto-Create Listings',
        default=False,
        help='Automatically create Amazon listings when product is created',
    )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    @api.depends('amazon_listing_ids')
    def _compute_amazon_listing_count(self):
        for record in self:
            record.amazon_listing_count = len(record.amazon_listing_ids)
            record.has_amazon_listing = bool(record.amazon_listing_ids)

    @api.depends('amazon_listing_ids', 'amazon_listing_ids.asin', 'amazon_listing_ids.sku')
    def _compute_amazon_primary_info(self):
        """Get ASIN and SKU from the first active listing."""
        for record in self:
            primary = record.amazon_listing_ids.filtered(
                lambda l: l.state == 'active'
            )[:1] or record.amazon_listing_ids[:1]
            record.amazon_primary_asin = primary.asin if primary else False
            record.amazon_primary_sku = primary.sku if primary else False

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------
    def action_view_amazon_listings(self):
        """Open Amazon listings for this product."""
        self.ensure_one()
        
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Amazon Listings'),
            'res_model': 'amazon.product.listing',
            'view_mode': 'tree,form',
            'domain': [('product_tmpl_id', '=', self.id)],
            'context': {
                'default_product_tmpl_id': self.id,
                'default_title': self.name,
            },
        }
        
        # If only one listing, open it directly
        if self.amazon_listing_count == 1:
            action['view_mode'] = 'form'
            action['res_id'] = self.amazon_listing_ids[0].id
        
        return action

    def action_create_amazon_listing(self):
        """Open wizard to create a new Amazon listing."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Amazon Listing'),
            'res_model': 'amazon.product.listing',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_product_tmpl_id': self.id,
                'default_title': self.name,
                'default_brand': self.amazon_brand,
                'default_manufacturer': self.amazon_manufacturer,
                'default_search_terms': self.amazon_search_terms,
                'default_fulfillment_channel': self.amazon_default_fulfillment,
            },
        }

    def action_sync_amazon_listings(self):
        """Sync all Amazon listings for this product."""
        for listing in self.amazon_listing_ids:
            listing.action_sync_from_amazon()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Complete'),
                'message': _('Synced %d Amazon listing(s).') % self.amazon_listing_count,
                'type': 'success',
                'sticky': False,
            },
        }

    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------
    def get_amazon_listing_for_marketplace(self, marketplace):
        """Get the Amazon listing for a specific marketplace.
        
        Args:
            marketplace: amazon.marketplace record or marketplace code string
            
        Returns:
            amazon.product.listing recordset (may be empty)
        """
        self.ensure_one()
        
        if isinstance(marketplace, str):
            domain = [
                ('product_tmpl_id', '=', self.id),
                ('marketplace_id.code', '=', marketplace),
            ]
        else:
            domain = [
                ('product_tmpl_id', '=', self.id),
                ('marketplace_id', '=', marketplace.id),
            ]
        
        return self.env['amazon.product.listing'].search(domain, limit=1)

    def get_amazon_listings_by_account(self, account):
        """Get all Amazon listings for a specific seller account.
        
        Args:
            account: amazon.account record
            
        Returns:
            amazon.product.listing recordset
        """
        self.ensure_one()
        return self.amazon_listing_ids.filtered(
            lambda l: l.account_id == account
        )
