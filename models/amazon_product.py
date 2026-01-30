# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AmazonProductListing(models.Model):
    """Amazon Product Listing.
    
    Represents a product listing on a specific Amazon marketplace.
    Links Odoo products to Amazon ASINs/SKUs with marketplace-specific data.
    """
    _name = 'amazon.product.listing'
    _description = 'Amazon Product Listing'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'write_date desc'
    _rec_name = 'display_name'

    # -------------------------------------------------------------------------
    # FIELDS - Identification
    # -------------------------------------------------------------------------
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )
    asin = fields.Char(
        string='ASIN',
        required=True,
        index=True,
        tracking=True,
        help='Amazon Standard Identification Number',
    )
    sku = fields.Char(
        string='Seller SKU',
        required=True,
        index=True,
        tracking=True,
        help='Your unique product identifier for this listing',
    )
    fnsku = fields.Char(
        string='FNSKU',
        index=True,
        help='Fulfillment Network SKU (for FBA items)',
    )
    ean = fields.Char(
        string='EAN',
        help='European Article Number',
    )
    upc = fields.Char(
        string='UPC',
        help='Universal Product Code',
    )

    # -------------------------------------------------------------------------
    # FIELDS - Relationships
    # -------------------------------------------------------------------------
    product_tmpl_id = fields.Many2one(
        comodel_name='product.template',
        string='Product Template',
        required=True,
        ondelete='cascade',
        index=True,
        help='Linked Odoo product template',
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Product Variant',
        ondelete='cascade',
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
        help='Specific product variant (if applicable)',
    )
    account_id = fields.Many2one(
        comodel_name='amazon.account',
        string='Seller Account',
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True,
        help='Amazon seller account for this listing',
    )
    marketplace_id = fields.Many2one(
        comodel_name='amazon.marketplace',
        string='Marketplace',
        required=True,
        ondelete='restrict',
        index=True,
        tracking=True,
        help='Amazon marketplace for this listing',
    )
    amazon_category_id = fields.Many2one(
        comodel_name='amazon.product.category',
        string='Amazon Category',
        ondelete='set null',
        help='Amazon product category (Browse Node)',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='account_id.company_id',
        store=True,
        index=True,
    )

    # -------------------------------------------------------------------------
    # FIELDS - Status & State
    # -------------------------------------------------------------------------
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('pending', 'Pending'),
            ('active', 'Active'),
            ('inactive', 'Inactive'),
            ('suppressed', 'Suppressed'),
            ('incomplete', 'Incomplete'),
            ('error', 'Error'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        index=True,
        help='Current listing status on Amazon',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    is_buybox_winner = fields.Boolean(
        string='Buy Box Winner',
        readonly=True,
        help='Whether this listing currently owns the Buy Box',
    )
    listing_quality_score = fields.Integer(
        string='Listing Quality Score',
        readonly=True,
        help='Amazon listing quality score (0-100)',
    )
    listing_issues = fields.Text(
        string='Listing Issues',
        readonly=True,
        help='Quality issues reported by Amazon',
    )

    # -------------------------------------------------------------------------
    # FIELDS - Fulfillment
    # -------------------------------------------------------------------------
    fulfillment_channel = fields.Selection(
        selection=[
            ('FBM', 'Fulfilled by Merchant'),
            ('FBA', 'Fulfilled by Amazon'),
        ],
        string='Fulfillment Channel',
        required=True,
        default='FBM',
        tracking=True,
        help='Who fulfills orders for this listing',
    )
    is_fba = fields.Boolean(
        string='Is FBA',
        compute='_compute_is_fba',
        store=True,
    )
    fba_inbound_guidance = fields.Selection(
        selection=[
            ('eligible', 'Eligible'),
            ('ineligible', 'Ineligible'),
            ('restricted', 'Restricted'),
        ],
        string='FBA Inbound Guidance',
        readonly=True,
        help='FBA eligibility status',
    )

    # -------------------------------------------------------------------------
    # FIELDS - Pricing
    # -------------------------------------------------------------------------
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='marketplace_id.currency_id',
        store=True,
    )
    list_price = fields.Monetary(
        string='List Price',
        currency_field='currency_id',
        tracking=True,
        help='Current listing price on Amazon',
    )
    sale_price = fields.Monetary(
        string='Sale Price',
        currency_field='currency_id',
        help='Active sale/promotional price',
    )
    sale_price_start = fields.Datetime(
        string='Sale Start',
        help='When the sale price becomes active',
    )
    sale_price_end = fields.Datetime(
        string='Sale End',
        help='When the sale price ends',
    )
    is_on_sale = fields.Boolean(
        string='On Sale',
        compute='_compute_is_on_sale',
        store=True,
    )
    minimum_price = fields.Monetary(
        string='Minimum Price',
        currency_field='currency_id',
        help='Minimum allowed price (for repricing)',
    )
    maximum_price = fields.Monetary(
        string='Maximum Price',
        currency_field='currency_id',
        help='Maximum allowed price (for repricing)',
    )
    buybox_price = fields.Monetary(
        string='Buy Box Price',
        currency_field='currency_id',
        readonly=True,
        help='Current Buy Box price (may be competitor)',
    )
    landed_cost = fields.Monetary(
        string='Landed Cost',
        currency_field='currency_id',
        help='Total cost including shipping and fees',
    )
    profit_margin = fields.Float(
        string='Profit Margin (%)',
        compute='_compute_profit_margin',
        digits=(5, 2),
        store=True,
    )

    # -------------------------------------------------------------------------
    # FIELDS - Inventory
    # -------------------------------------------------------------------------
    quantity_available = fields.Integer(
        string='Quantity Available',
        readonly=True,
        help='Current quantity available on Amazon',
    )
    quantity_inbound = fields.Integer(
        string='Quantity Inbound',
        readonly=True,
        help='Quantity in transit to FBA',
    )
    quantity_reserved = fields.Integer(
        string='Quantity Reserved',
        readonly=True,
        help='Quantity reserved for pending orders',
    )
    quantity_unfulfillable = fields.Integer(
        string='Quantity Unfulfillable',
        readonly=True,
        help='Quantity in unfulfillable status',
    )
    total_fba_quantity = fields.Integer(
        string='Total FBA Quantity',
        compute='_compute_total_fba_quantity',
        store=True,
    )
    restock_recommended = fields.Integer(
        string='Recommended Restock',
        readonly=True,
        help='Amazon recommended restock quantity',
    )

    # -------------------------------------------------------------------------
    # FIELDS - Content
    # -------------------------------------------------------------------------
    title = fields.Char(
        string='Listing Title',
        tracking=True,
        help='Product title on Amazon',
    )
    bullet_point_1 = fields.Char(string='Bullet Point 1')
    bullet_point_2 = fields.Char(string='Bullet Point 2')
    bullet_point_3 = fields.Char(string='Bullet Point 3')
    bullet_point_4 = fields.Char(string='Bullet Point 4')
    bullet_point_5 = fields.Char(string='Bullet Point 5')
    description = fields.Text(
        string='Product Description',
        help='Full product description',
    )
    search_terms = fields.Char(
        string='Search Terms',
        help='Backend search keywords (max 250 bytes)',
    )
    brand = fields.Char(
        string='Brand',
        help='Product brand name',
    )
    manufacturer = fields.Char(
        string='Manufacturer',
        help='Product manufacturer',
    )

    # -------------------------------------------------------------------------
    # FIELDS - Category
    # -------------------------------------------------------------------------
    browse_node_id = fields.Char(
        string='Browse Node ID',
        help='Amazon category browse node',
    )
    browse_node_path = fields.Char(
        string='Category Path',
        help='Full category path',
    )
    item_type_keyword = fields.Char(
        string='Item Type',
        help='Amazon item type keyword',
    )

    # -------------------------------------------------------------------------
    # FIELDS - Images
    # -------------------------------------------------------------------------
    main_image_url = fields.Char(
        string='Main Image URL',
        help='URL of the main product image on Amazon',
    )
    image_urls = fields.Text(
        string='Additional Images',
        help='JSON list of additional image URLs',
    )

    # -------------------------------------------------------------------------
    # FIELDS - Metrics & Dates
    # -------------------------------------------------------------------------
    last_sync_date = fields.Datetime(
        string='Last Synced',
        readonly=True,
    )
    last_price_sync = fields.Datetime(
        string='Last Price Sync',
        readonly=True,
    )
    last_inventory_sync = fields.Datetime(
        string='Last Inventory Sync',
        readonly=True,
    )
    amazon_created_date = fields.Date(
        string='Listed On Amazon',
        readonly=True,
    )
    sales_rank = fields.Integer(
        string='Sales Rank',
        readonly=True,
        help='Best Sellers Rank in main category',
    )
    review_count = fields.Integer(
        string='Review Count',
        readonly=True,
    )
    average_rating = fields.Float(
        string='Average Rating',
        digits=(2, 1),
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # FIELDS - Fees
    # -------------------------------------------------------------------------
    referral_fee_percent = fields.Float(
        string='Referral Fee %',
        digits=(5, 2),
        readonly=True,
        help='Amazon referral fee percentage',
    )
    fba_fee = fields.Monetary(
        string='FBA Fee',
        currency_field='currency_id',
        readonly=True,
        help='FBA fulfillment fee per unit',
    )
    closing_fee = fields.Monetary(
        string='Closing Fee',
        currency_field='currency_id',
        readonly=True,
        help='Variable closing fee (if applicable)',
    )
    estimated_total_fees = fields.Monetary(
        string='Est. Total Fees',
        currency_field='currency_id',
        compute='_compute_estimated_total_fees',
        store=True,
    )

    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------
    _sql_constraints = [
        (
            'sku_account_marketplace_unique',
            'UNIQUE(sku, account_id, marketplace_id)',
            'SKU must be unique per account and marketplace!',
        ),
        (
            'asin_account_marketplace_unique',
            'UNIQUE(asin, account_id, marketplace_id)',
            'ASIN must be unique per account and marketplace!',
        ),
    ]

    @api.constrains('asin')
    def _check_asin_format(self):
        """Validate ASIN format (10 alphanumeric characters)."""
        for record in self:
            if record.asin:
                asin = record.asin.upper().strip()
                if len(asin) != 10 or not asin.isalnum():
                    raise ValidationError(
                        _('ASIN must be exactly 10 alphanumeric characters: %s') % record.asin
                    )

    @api.constrains('minimum_price', 'maximum_price', 'list_price')
    def _check_price_range(self):
        """Ensure price boundaries are valid."""
        for record in self:
            if record.minimum_price and record.maximum_price:
                if record.minimum_price > record.maximum_price:
                    raise ValidationError(
                        _('Minimum price cannot exceed maximum price.')
                    )
            if record.minimum_price and record.list_price:
                if record.list_price < record.minimum_price:
                    raise ValidationError(
                        _('List price cannot be below minimum price.')
                    )
            if record.maximum_price and record.list_price:
                if record.list_price > record.maximum_price:
                    raise ValidationError(
                        _('List price cannot exceed maximum price.')
                    )

    @api.constrains('search_terms')
    def _check_search_terms_length(self):
        """Amazon limits search terms to 250 bytes."""
        for record in self:
            if record.search_terms:
                byte_length = len(record.search_terms.encode('utf-8'))
                if byte_length > 250:
                    raise ValidationError(
                        _('Search terms exceed 250 bytes (%d bytes). '
                          'Please shorten.') % byte_length
                    )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    @api.depends('asin', 'sku', 'marketplace_id.country_id.code')
    def _compute_display_name(self):
        for record in self:
            parts = []
            if record.sku:
                parts.append(record.sku)
            if record.asin:
                parts.append(f'({record.asin})')
            if record.marketplace_id.country_id:
                parts.append(f'[{record.marketplace_id.country_id.code}]')
            record.display_name = ' '.join(parts) if parts else _('New Listing')

    @api.depends('fulfillment_channel')
    def _compute_is_fba(self):
        for record in self:
            record.is_fba = record.fulfillment_channel == 'FBA'

    @api.depends('sale_price', 'sale_price_start', 'sale_price_end')
    def _compute_is_on_sale(self):
        now = fields.Datetime.now()
        for record in self:
            record.is_on_sale = bool(
                record.sale_price and
                (not record.sale_price_start or record.sale_price_start <= now) and
                (not record.sale_price_end or record.sale_price_end > now)
            )

    @api.depends('quantity_available', 'quantity_inbound', 'quantity_reserved')
    def _compute_total_fba_quantity(self):
        for record in self:
            record.total_fba_quantity = (
                record.quantity_available +
                record.quantity_inbound +
                record.quantity_reserved
            )

    @api.depends('list_price', 'landed_cost')
    def _compute_profit_margin(self):
        for record in self:
            if record.list_price and record.landed_cost:
                profit = record.list_price - record.landed_cost
                record.profit_margin = (profit / record.list_price) * 100
            else:
                record.profit_margin = 0.0

    @api.depends('list_price', 'referral_fee_percent', 'fba_fee', 'closing_fee')
    def _compute_estimated_total_fees(self):
        for record in self:
            referral = (record.list_price or 0) * (record.referral_fee_percent or 0) / 100
            record.estimated_total_fees = referral + (record.fba_fee or 0) + (record.closing_fee or 0)

    # -------------------------------------------------------------------------
    # ONCHANGE
    # -------------------------------------------------------------------------
    @api.onchange('marketplace_id')
    def _onchange_marketplace_id(self):
        """Filter account selection to those registered in the marketplace."""
        if self.marketplace_id:
            return {
                'domain': {
                    'account_id': [
                        ('marketplace_ids', 'in', self.marketplace_id.id),
                        ('state', '=', 'active'),
                    ]
                }
            }

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        """Pre-fill listing data from product template."""
        if self.product_tmpl_id:
            self.title = self.product_tmpl_id.name
            self.brand = self.product_tmpl_id.product_brand_id.name if hasattr(
                self.product_tmpl_id, 'product_brand_id'
            ) else False
            # Use product's barcode as EAN if available
            if self.product_tmpl_id.barcode:
                barcode = self.product_tmpl_id.barcode
                if len(barcode) == 13:
                    self.ean = barcode
                elif len(barcode) == 12:
                    self.upc = barcode

    # -------------------------------------------------------------------------
    # CRUD OVERRIDES
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """Normalize ASINs and SKUs on creation."""
        for vals in vals_list:
            if vals.get('asin'):
                vals['asin'] = vals['asin'].upper().strip()
            if vals.get('sku'):
                vals['sku'] = vals['sku'].strip()
        return super().create(vals_list)

    def write(self, vals):
        """Normalize ASINs and SKUs on update."""
        if vals.get('asin'):
            vals['asin'] = vals['asin'].upper().strip()
        if vals.get('sku'):
            vals['sku'] = vals['sku'].strip()
        return super().write(vals)

    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------
    def action_sync_from_amazon(self):
        """Sync listing data from Amazon."""
        for record in self:
            _logger.info('Syncing listing %s from Amazon', record.display_name)
            # TODO: Implement via sp_api_products service
            record.last_sync_date = fields.Datetime.now()

    def action_push_to_amazon(self):
        """Push listing data to Amazon."""
        for record in self:
            if record.state == 'draft':
                raise UserError(
                    _('Cannot push draft listings. Set to pending first.')
                )
            _logger.info('Pushing listing %s to Amazon', record.display_name)
            # TODO: Implement via sp_api_feeds service

    def action_sync_price(self):
        """Sync pricing data from Amazon."""
        for record in self:
            _logger.info('Syncing price for %s', record.display_name)
            # TODO: Implement via sp_api_products service
            record.last_price_sync = fields.Datetime.now()

    def action_update_price(self):
        """Push price update to Amazon."""
        for record in self:
            if not record.list_price:
                raise UserError(_('List price is required.'))
            _logger.info('Updating price for %s to %s', 
                        record.display_name, record.list_price)
            # TODO: Implement via sp_api_feeds service

    def action_sync_inventory(self):
        """Sync inventory levels from Amazon."""
        for record in self:
            _logger.info('Syncing inventory for %s', record.display_name)
            # TODO: Implement via sp_api_fba service
            record.last_inventory_sync = fields.Datetime.now()

    def action_open_on_amazon(self):
        """Open the product page on Amazon."""
        self.ensure_one()
        url = self.marketplace_id.get_product_url(self.asin)
        if not url:
            raise UserError(_('Cannot generate Amazon URL.'))
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

    def action_open_in_seller_central(self):
        """Open the product in Seller Central."""
        self.ensure_one()
        url = self.marketplace_id.get_seller_central_product_url(self.asin)
        if not url:
            raise UserError(_('Cannot generate Seller Central URL.'))
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

    def action_set_active(self):
        """Activate the listing."""
        self.write({'state': 'active'})

    def action_set_inactive(self):
        """Deactivate the listing."""
        self.write({'state': 'inactive'})

    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------
    def get_effective_price(self):
        """Get the current effective selling price."""
        self.ensure_one()
        if self.is_on_sale and self.sale_price:
            return self.sale_price
        return self.list_price

    def get_bullet_points(self):
        """Get list of non-empty bullet points."""
        self.ensure_one()
        bullets = [
            self.bullet_point_1,
            self.bullet_point_2,
            self.bullet_point_3,
            self.bullet_point_4,
            self.bullet_point_5,
        ]
        return [b for b in bullets if b]
