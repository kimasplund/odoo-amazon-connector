# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AmazonMarketplace(models.Model):
    """Amazon Marketplace configuration.
    
    Represents an Amazon marketplace (e.g., Amazon.de, Amazon.co.uk).
    Each marketplace has its own endpoint, currency, and regional settings.
    """
    _name = 'amazon.marketplace'
    _description = 'Amazon Marketplace'
    _order = 'sequence, name'
    _rec_name = 'display_name'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    name = fields.Char(
        string='Marketplace Name',
        required=True,
        help='Display name of the marketplace (e.g., Amazon Germany)',
    )
    marketplace_id = fields.Char(
        string='Marketplace ID',
        required=True,
        index=True,
        help='Amazon Marketplace ID (e.g., A1PA6795UKMFR9 for Germany)',
    )
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Used to order marketplaces in lists',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Set to False to hide the marketplace without deleting it',
    )

    # Regional Settings
    country_id = fields.Many2one(
        comodel_name='res.country',
        string='Country',
        help='Country where this marketplace operates',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        help='Default currency for this marketplace',
    )
    lang_id = fields.Many2one(
        comodel_name='res.lang',
        string='Primary Language',
        help='Primary language for product listings',
    )

    # API Configuration
    region = fields.Selection(
        selection=[
            ('eu', 'Europe'),
            ('na', 'North America'),
            ('fe', 'Far East'),
        ],
        string='Region',
        required=True,
        default='eu',
        help='Amazon SP-API region for endpoint routing',
    )
    endpoint_url = fields.Char(
        string='API Endpoint URL',
        compute='_compute_endpoint_url',
        store=True,
        help='SP-API endpoint URL for this marketplace',
    )
    seller_central_url = fields.Char(
        string='Seller Central URL',
        help='URL to Seller Central for this marketplace',
    )
    domain = fields.Char(
        string='Website Domain',
        help='Amazon website domain (e.g., amazon.de)',
    )

    # Relationships
    account_ids = fields.Many2many(
        comodel_name='amazon.account',
        relation='amazon_account_marketplace_rel',
        column1='marketplace_id',
        column2='account_id',
        string='Seller Accounts',
        help='Seller accounts registered in this marketplace',
    )
    account_count = fields.Integer(
        string='# Accounts',
        compute='_compute_account_count',
    )
    listing_ids = fields.One2many(
        comodel_name='amazon.product.listing',
        inverse_name='marketplace_id',
        string='Product Listings',
    )
    listing_count = fields.Integer(
        string='# Listings',
        compute='_compute_listing_count',
    )

    # Tax & Compliance
    vat_required = fields.Boolean(
        string='VAT Required',
        default=False,
        help='Whether VAT registration is required to sell in this marketplace',
    )
    tax_calculation_method = fields.Selection(
        selection=[
            ('marketplace', 'Marketplace Facilitator'),
            ('seller', 'Seller Responsible'),
        ],
        string='Tax Calculation',
        default='seller',
        help='Who is responsible for calculating and remitting taxes',
    )

    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------
    _sql_constraints = [
        ('marketplace_id_unique', 'UNIQUE(marketplace_id)', 'Marketplace ID must be unique!'),
        ('domain_unique', 'UNIQUE(domain)', 'Domain must be unique!'),
    ]

    @api.constrains('marketplace_id')
    def _check_marketplace_id_format(self):
        """Validate marketplace ID format (Amazon uses alphanumeric codes)."""
        for record in self:
            if record.marketplace_id and not record.marketplace_id.isalnum():
                raise ValidationError(
                    _('Marketplace ID must be alphanumeric: %s') % record.marketplace_id
                )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    @api.depends('name', 'country_id.code')
    def _compute_display_name(self):
        for record in self:
            if record.country_id:
                record.display_name = f"{record.name} ({record.country_id.code})"
            else:
                record.display_name = record.name

    @api.depends('region')
    def _compute_endpoint_url(self):
        """Set SP-API endpoint URL based on region."""
        endpoints = {
            'na': 'https://sellingpartnerapi-na.amazon.com',
            'eu': 'https://sellingpartnerapi-eu.amazon.com',
            'fe': 'https://sellingpartnerapi-fe.amazon.com',
        }
        for record in self:
            record.endpoint_url = endpoints.get(record.region, endpoints['eu'])

    def _compute_account_count(self):
        for record in self:
            record.account_count = len(record.account_ids)

    def _compute_listing_count(self):
        for record in self:
            record.listing_count = len(record.listing_ids)

    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------
    def action_view_accounts(self):
        """Open list of seller accounts for this marketplace."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Seller Accounts'),
            'res_model': 'amazon.account',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.account_ids.ids)],
            'context': {'default_marketplace_ids': [(4, self.id)]},
        }

    def action_view_listings(self):
        """Open list of product listings for this marketplace."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Product Listings'),
            'res_model': 'amazon.product.listing',
            'view_mode': 'tree,form',
            'domain': [('marketplace_id', '=', self.id)],
            'context': {'default_marketplace_id': self.id},
        }

    def get_product_url(self, asin):
        """Generate product page URL for an ASIN."""
        self.ensure_one()
        if not self.domain or not asin:
            return False
        return f"https://www.{self.domain}/dp/{asin}"

    def get_seller_central_product_url(self, asin):
        """Generate Seller Central product edit URL."""
        self.ensure_one()
        if not self.seller_central_url or not asin:
            return False
        return f"{self.seller_central_url}/product-search?q={asin}"
