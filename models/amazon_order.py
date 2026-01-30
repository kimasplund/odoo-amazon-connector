# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from ..services import encryption

_logger = logging.getLogger(__name__)


class AmazonOrder(models.Model):
    """Amazon Order imported from SP-API.
    
    This model stores the complete Amazon order data including buyer information,
    shipping details, payment status, and EU VAT compliance fields (IOSS, OSS).
    Each Amazon order is linked to an Odoo sale.order for fulfillment processing.
    """
    _name = 'amazon.order'
    _description = 'Amazon Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'purchase_date desc, id desc'
    _rec_name = 'amazon_order_id'

    # ══════════════════════════════════════════════════════════════════════════
    # CORE IDENTIFIERS
    # ══════════════════════════════════════════════════════════════════════════
    
    amazon_order_id = fields.Char(
        string='Amazon Order ID',
        required=True,
        index=True,
        tracking=True,
        copy=False,
        help="Unique Amazon order identifier (e.g., 302-1234567-1234567)"
    )
    seller_order_id = fields.Char(
        string='Seller Order ID',
        help="Seller-defined order identifier"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # RELATIONSHIPS
    # ══════════════════════════════════════════════════════════════════════════
    
    account_id = fields.Many2one(
        comodel_name='amazon.account',
        string='Amazon Account',
        required=True,
        ondelete='restrict',
        index=True,
        tracking=True,
    )
    marketplace_id = fields.Many2one(
        comodel_name='amazon.marketplace',
        string='Marketplace',
        required=True,
        ondelete='restrict',
        index=True,
        tracking=True,
    )
    sale_order_id = fields.Many2one(
        comodel_name='sale.order',
        string='Odoo Sale Order',
        ondelete='set null',
        index=True,
        tracking=True,
        copy=False,
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Customer',
        ondelete='set null',
        index=True,
        tracking=True,
    )
    order_line_ids = fields.One2many(
        comodel_name='amazon.order.line',
        inverse_name='order_id',
        string='Order Lines',
    )
    return_ids = fields.One2many(
        comodel_name='amazon.return',
        inverse_name='order_id',
        string='Returns',
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # ORDER STATUS
    # ══════════════════════════════════════════════════════════════════════════
    
    order_status = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('unshipped', 'Unshipped'),
            ('partially_shipped', 'Partially Shipped'),
            ('shipped', 'Shipped'),
            ('invoice_unconfirmed', 'Invoice Unconfirmed'),
            ('canceled', 'Canceled'),
            ('unfulfillable', 'Unfulfillable'),
            ('pending_availability', 'Pending Availability'),
        ],
        string='Order Status',
        default='pending',
        required=True,
        index=True,
        tracking=True,
    )
    fulfillment_channel = fields.Selection(
        selection=[
            ('MFN', 'Merchant Fulfilled (FBM)'),
            ('AFN', 'Amazon Fulfilled (FBA)'),
        ],
        string='Fulfillment Channel',
        required=True,
        default='MFN',
        tracking=True,
        help="MFN = Merchant Fulfilled Network (FBM), AFN = Amazon Fulfilled Network (FBA)"
    )
    is_fba = fields.Boolean(
        string='Is FBA',
        compute='_compute_is_fba',
        store=True,
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # DATES
    # ══════════════════════════════════════════════════════════════════════════
    
    purchase_date = fields.Datetime(
        string='Purchase Date',
        required=True,
        index=True,
        tracking=True,
        help="Date when the order was placed"
    )
    last_update_date = fields.Datetime(
        string='Last Update Date',
        help="Date when the order was last modified on Amazon"
    )
    earliest_ship_date = fields.Datetime(
        string='Earliest Ship Date',
        help="Earliest date to ship the order"
    )
    latest_ship_date = fields.Datetime(
        string='Latest Ship Date',
        help="Latest date to ship the order to meet delivery promise"
    )
    earliest_delivery_date = fields.Datetime(
        string='Earliest Delivery Date',
        help="Earliest promised delivery date"
    )
    latest_delivery_date = fields.Datetime(
        string='Latest Delivery Date',
        help="Latest promised delivery date"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # BUYER INFORMATION
    # ══════════════════════════════════════════════════════════════════════════
    
    buyer_email_encrypted = fields.Char(string='Buyer Email (Encrypted)')
    buyer_email = fields.Char(
        string='Buyer Email',
        compute='_compute_pii_fields',
        inverse='_inverse_pii_fields',
        help="Amazon-anonymized buyer email address"
    )
    buyer_name_encrypted = fields.Char(string='Buyer Name (Encrypted)')
    buyer_name = fields.Char(
        string='Buyer Name',
        compute='_compute_pii_fields',
        inverse='_inverse_pii_fields',
    )
    is_business_order = fields.Boolean(
        string='Business Order (B2B)',
        default=False,
        help="True if this is an Amazon Business order"
    )
    is_prime = fields.Boolean(
        string='Prime Order',
        default=False,
        help="True if the order is an Amazon Prime order"
    )
    is_premium_order = fields.Boolean(
        string='Premium Order',
        default=False,
        help="True if the order has a premium shipping option"
    )
    is_global_express_enabled = fields.Boolean(
        string='Global Express Enabled',
        default=False,
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # SHIPPING ADDRESS
    # ══════════════════════════════════════════════════════════════════════════
    
    ship_name_encrypted = fields.Char(string='Ship To Name (Encrypted)')
    ship_name = fields.Char(
        string='Ship To Name',
        compute='_compute_pii_fields',
        inverse='_inverse_pii_fields',
    )
    ship_address_line1_encrypted = fields.Char(string='Address Line 1 (Encrypted)')
    ship_address_line1 = fields.Char(
        string='Address Line 1',
        compute='_compute_pii_fields',
        inverse='_inverse_pii_fields',
    )
    ship_address_line2_encrypted = fields.Char(string='Address Line 2 (Encrypted)')
    ship_address_line2 = fields.Char(
        string='Address Line 2',
        compute='_compute_pii_fields',
        inverse='_inverse_pii_fields',
    )
    ship_address_line3_encrypted = fields.Char(string='Address Line 3 (Encrypted)')
    ship_address_line3 = fields.Char(
        string='Address Line 3',
        compute='_compute_pii_fields',
        inverse='_inverse_pii_fields',
    )
    ship_city = fields.Char(
        string='City',
    )
    ship_state_or_region = fields.Char(
        string='State/Region',
    )
    ship_postal_code = fields.Char(
        string='Postal Code',
    )
    ship_country_code = fields.Char(
        string='Country Code',
        help="Two-letter ISO country code"
    )
    ship_country_id = fields.Many2one(
        comodel_name='res.country',
        string='Country',
        compute='_compute_ship_country_id',
        store=True,
    )
    ship_phone_encrypted = fields.Char(string='Phone (Encrypted)')
    ship_phone = fields.Char(
        string='Phone',
        compute='_compute_pii_fields',
        inverse='_inverse_pii_fields',
    )
    address_type = fields.Selection(
        selection=[
            ('residential', 'Residential'),
            ('commercial', 'Commercial'),
        ],
        string='Address Type',
        default='residential',
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # SHIPPING & DELIVERY
    # ══════════════════════════════════════════════════════════════════════════
    
    shipment_service_level_category = fields.Selection(
        selection=[
            ('expedited', 'Expedited'),
            ('free_economy', 'Free Economy'),
            ('next_day', 'Next Day'),
            ('same_day', 'Same Day'),
            ('second_day', 'Second Day'),
            ('scheduled', 'Scheduled'),
            ('standard', 'Standard'),
        ],
        string='Shipping Service Level',
    )
    ship_service_level = fields.Char(
        string='Ship Service Level',
        help="Exact shipping service level name from Amazon"
    )
    is_ispu = fields.Boolean(
        string='In-Store Pickup (ISPU)',
        default=False,
        help="True if this is an in-store pickup order"
    )
    is_scheduled_delivery_shipment = fields.Boolean(
        string='Scheduled Delivery',
        default=False,
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # ORDER TOTALS (in order currency)
    # ══════════════════════════════════════════════════════════════════════════
    
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        required=True,
    )
    order_total = fields.Monetary(
        string='Order Total',
        currency_field='currency_id',
        tracking=True,
    )
    
    # Computed totals from order lines
    amount_items = fields.Monetary(
        string='Items Subtotal',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
    )
    amount_shipping = fields.Monetary(
        string='Shipping',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
    )
    amount_gift_wrap = fields.Monetary(
        string='Gift Wrap',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
    )
    amount_discount = fields.Monetary(
        string='Promotions/Discounts',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
    )
    amount_tax = fields.Monetary(
        string='Tax Total',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
    )
    amount_fees = fields.Monetary(
        string='Amazon Fees',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
    )
    
    number_of_items_shipped = fields.Integer(
        string='Items Shipped',
    )
    number_of_items_unshipped = fields.Integer(
        string='Items Unshipped',
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # EU VAT COMPLIANCE (IOSS/OSS)
    # ══════════════════════════════════════════════════════════════════════════
    
    is_replacement_order = fields.Boolean(
        string='Replacement Order',
        default=False,
        help="True if this is a replacement order"
    )
    replaced_order_id = fields.Char(
        string='Replaced Order ID',
        help="Amazon Order ID of the order being replaced"
    )
    
    # VAT Invoice fields
    is_vat_invoice_required = fields.Boolean(
        string='VAT Invoice Required',
        default=False,
        help="True if VAT invoice is required (business orders)"
    )
    buyer_tax_registration_id_encrypted = fields.Char(string='Buyer VAT Number (Encrypted)')
    buyer_tax_registration_id = fields.Char(
        string='Buyer VAT Number',
        compute='_compute_pii_fields',
        inverse='_inverse_pii_fields',
        help="Buyer's VAT registration number for B2B orders"
    )
    buyer_company_legal_name_encrypted = fields.Char(string='Buyer Company Name (Encrypted)')
    buyer_company_legal_name = fields.Char(
        string='Buyer Company Name',
        compute='_compute_pii_fields',
        inverse='_inverse_pii_fields',
        help="Legal company name for B2B orders"
    )
    
    # IOSS (Import One-Stop Shop) - for imports ≤150 EUR
    is_ioss_order = fields.Boolean(
        string='IOSS Order',
        default=False,
        help="True if order uses IOSS for import VAT collection"
    )
    ioss_number = fields.Char(
        string='IOSS Number',
        help="Import One-Stop Shop VAT number"
    )
    
    # OSS (One-Stop Shop) - for EU intra-community distance sales
    is_oss_order = fields.Boolean(
        string='OSS Order',
        default=False,
        help="True if order uses OSS (intra-EU distance selling)"
    )
    
    # Tax collection model
    is_sold_by_ab = fields.Boolean(
        string='Sold by Amazon',
        default=False,
        help="True if Amazon is seller of record"
    )
    tax_collection_model = fields.Selection(
        selection=[
            ('marketplace_facilitator', 'Marketplace Facilitator'),
            ('seller_liable', 'Seller Liable'),
            ('mixed', 'Mixed'),
        ],
        string='Tax Collection Model',
        default='seller_liable',
        help="Who is responsible for tax collection/remittance"
    )
    
    # Marketplace Facilitator Tax (US states, UK, AU, etc.)
    marketplace_tax_collected = fields.Monetary(
        string='Marketplace Tax Collected',
        currency_field='currency_id',
        help="Tax collected and remitted by Amazon as marketplace facilitator"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # GIFT OPTIONS
    # ══════════════════════════════════════════════════════════════════════════
    
    is_gift = fields.Boolean(
        string='Gift Order',
        default=False,
    )
    gift_message_text = fields.Text(
        string='Gift Message',
    )
    gift_wrap_level = fields.Char(
        string='Gift Wrap Level',
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # PAYMENT
    # ══════════════════════════════════════════════════════════════════════════
    
    payment_method = fields.Selection(
        selection=[
            ('cod', 'Cash on Delivery'),
            ('cvs', 'Convenience Store'),
            ('credit_card', 'Credit Card'),
            ('gcgc', 'Gift Card/Gift Certificate'),
            ('other', 'Other'),
        ],
        string='Payment Method',
    )
    payment_method_details = fields.Char(
        string='Payment Method Details',
        help="Sub-classification of payment method"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # SALES CHANNEL
    # ══════════════════════════════════════════════════════════════════════════
    
    sales_channel = fields.Char(
        string='Sales Channel',
        help="E.g., Amazon.de, Amazon.co.uk"
    )
    order_channel = fields.Char(
        string='Order Channel',
        help="Order channel, if other than Amazon"
    )
    easy_ship_shipment_status = fields.Selection(
        selection=[
            ('pending_schedule', 'Pending Schedule'),
            ('pending_pickup', 'Pending Pickup'),
            ('pending_drop_off', 'Pending Drop Off'),
            ('label_canceled', 'Label Canceled'),
            ('pickup_scheduled', 'Pickup Scheduled'),
            ('at_origin_fc', 'At Origin FC'),
            ('at_destination_fc', 'At Destination FC'),
            ('delivered', 'Delivered'),
            ('rejected_by_buyer', 'Rejected by Buyer'),
            ('undeliverable', 'Undeliverable'),
            ('returning_to_seller', 'Returning to Seller'),
            ('returned_to_seller', 'Returned to Seller'),
            ('lost', 'Lost'),
            ('out_for_delivery', 'Out for Delivery'),
            ('damaged', 'Damaged'),
        ],
        string='Easy Ship Status',
        help="Status for Amazon Easy Ship orders (IN, JP)"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # SYNC STATUS
    # ══════════════════════════════════════════════════════════════════════════
    
    sync_status = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('synced', 'Synced'),
            ('error', 'Error'),
        ],
        string='Sync Status',
        default='pending',
        tracking=True,
    )
    last_sync_date = fields.Datetime(
        string='Last Sync Date',
    )
    sync_error_message = fields.Text(
        string='Sync Error',
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # COMPUTED / HELPER FIELDS
    # ══════════════════════════════════════════════════════════════════════════
    
    order_line_count = fields.Integer(
        string='Line Count',
        compute='_compute_order_line_count',
    )
    return_count = fields.Integer(
        string='Return Count',
        compute='_compute_return_count',
    )
    has_returns = fields.Boolean(
        string='Has Returns',
        compute='_compute_return_count',
    )
    ship_deadline_passed = fields.Boolean(
        string='Ship Deadline Passed',
        compute='_compute_ship_deadline_passed',
    )
    formatted_ship_address = fields.Text(
        string='Ship Address',
        compute='_compute_formatted_ship_address',
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # SQL CONSTRAINTS
    # ══════════════════════════════════════════════════════════════════════════
    
    _sql_constraints = [
        (
            'amazon_order_id_account_uniq',
            'UNIQUE(amazon_order_id, account_id)',
            'Amazon Order ID must be unique per account!'
        ),
    ]
    
    # ══════════════════════════════════════════════════════════════════════════
    # COMPUTE METHODS
    # ══════════════════════════════════════════════════════════════════════════
    
    @api.depends('fulfillment_channel')
    def _compute_is_fba(self):
        for order in self:
            order.is_fba = order.fulfillment_channel == 'AFN'
    
    def _compute_pii_fields(self):
        for record in self:
            record.buyer_email = encryption.decrypt(self.env, record.buyer_email_encrypted) if record.buyer_email_encrypted else False
            record.buyer_name = encryption.decrypt(self.env, record.buyer_name_encrypted) if record.buyer_name_encrypted else False
            record.ship_name = encryption.decrypt(self.env, record.ship_name_encrypted) if record.ship_name_encrypted else False
            record.ship_address_line1 = encryption.decrypt(self.env, record.ship_address_line1_encrypted) if record.ship_address_line1_encrypted else False
            record.ship_address_line2 = encryption.decrypt(self.env, record.ship_address_line2_encrypted) if record.ship_address_line2_encrypted else False
            record.ship_address_line3 = encryption.decrypt(self.env, record.ship_address_line3_encrypted) if record.ship_address_line3_encrypted else False
            record.ship_phone = encryption.decrypt(self.env, record.ship_phone_encrypted) if record.ship_phone_encrypted else False
            record.buyer_tax_registration_id = encryption.decrypt(self.env, record.buyer_tax_registration_id_encrypted) if record.buyer_tax_registration_id_encrypted else False
            record.buyer_company_legal_name = encryption.decrypt(self.env, record.buyer_company_legal_name_encrypted) if record.buyer_company_legal_name_encrypted else False

    def _inverse_pii_fields(self):
        for record in self:
            record.buyer_email_encrypted = encryption.encrypt(self.env, record.buyer_email) if record.buyer_email else False
            record.buyer_name_encrypted = encryption.encrypt(self.env, record.buyer_name) if record.buyer_name else False
            record.ship_name_encrypted = encryption.encrypt(self.env, record.ship_name) if record.ship_name else False
            record.ship_address_line1_encrypted = encryption.encrypt(self.env, record.ship_address_line1) if record.ship_address_line1 else False
            record.ship_address_line2_encrypted = encryption.encrypt(self.env, record.ship_address_line2) if record.ship_address_line2 else False
            record.ship_address_line3_encrypted = encryption.encrypt(self.env, record.ship_address_line3) if record.ship_address_line3 else False
            record.ship_phone_encrypted = encryption.encrypt(self.env, record.ship_phone) if record.ship_phone else False
            record.buyer_tax_registration_id_encrypted = encryption.encrypt(self.env, record.buyer_tax_registration_id) if record.buyer_tax_registration_id else False
            record.buyer_company_legal_name_encrypted = encryption.encrypt(self.env, record.buyer_company_legal_name) if record.buyer_company_legal_name else False

    @api.model
    def _cron_anonymize_pii(self):
        """
        Anonymize PII for orders older than 30 days to comply with Amazon DPP.
        """
        cutoff_date = fields.Datetime.now() - timedelta(days=30)

        # Search for orders older than 30 days that still have PII
        # We check encrypted fields as they are the source of truth
        domain = [
            ('purchase_date', '<', cutoff_date),
            '|', '|', '|', '|', '|', '|', '|', '|',
            ('buyer_email_encrypted', '!=', False),
            ('buyer_name_encrypted', '!=', False),
            ('ship_name_encrypted', '!=', False),
            ('ship_address_line1_encrypted', '!=', False),
            ('ship_address_line2_encrypted', '!=', False),
            ('ship_address_line3_encrypted', '!=', False),
            ('ship_phone_encrypted', '!=', False),
            ('buyer_tax_registration_id_encrypted', '!=', False),
            ('buyer_company_legal_name_encrypted', '!=', False),
        ]

        # Process in batches to avoid timeouts
        orders = self.search(domain, limit=100)

        while orders:
            _logger.info("Anonymizing PII for %d Amazon orders", len(orders))

            vals = {
                'buyer_email': False,
                'buyer_name': False,
                'ship_name': False,
                'ship_address_line1': False,
                'ship_address_line2': False,
                'ship_address_line3': False,
                'ship_phone': False,
                'buyer_tax_registration_id': False,
                'buyer_company_legal_name': False,
            }
            orders.write(vals)

            # Commit to ensure progress is saved if next batch fails
            self.env.cr.commit()

            orders = self.search(domain, limit=100)

    @api.depends('ship_country_code')
    def _compute_ship_country_id(self):
        Country = self.env['res.country']
        for order in self:
            if order.ship_country_code:
                country = Country.search([
                    ('code', '=', order.ship_country_code.upper())
                ], limit=1)
                order.ship_country_id = country.id if country else False
            else:
                order.ship_country_id = False
    
    @api.depends('order_line_ids', 'order_line_ids.item_price', 
                 'order_line_ids.shipping_price', 'order_line_ids.gift_wrap_price',
                 'order_line_ids.promotion_discount', 'order_line_ids.item_tax',
                 'order_line_ids.total_fees')
    def _compute_amounts(self):
        for order in self:
            lines = order.order_line_ids
            order.amount_items = sum(lines.mapped('item_price'))
            order.amount_shipping = sum(lines.mapped('shipping_price'))
            order.amount_gift_wrap = sum(lines.mapped('gift_wrap_price'))
            order.amount_discount = sum(lines.mapped('promotion_discount'))
            order.amount_tax = sum(lines.mapped('item_tax'))
            order.amount_fees = sum(lines.mapped('total_fees'))
    
    @api.depends('order_line_ids')
    def _compute_order_line_count(self):
        for order in self:
            order.order_line_count = len(order.order_line_ids)
    
    @api.depends('return_ids')
    def _compute_return_count(self):
        for order in self:
            order.return_count = len(order.return_ids)
            order.has_returns = bool(order.return_count)
    
    @api.depends('latest_ship_date')
    def _compute_ship_deadline_passed(self):
        now = fields.Datetime.now()
        for order in self:
            if order.latest_ship_date and order.order_status in ('pending', 'unshipped'):
                order.ship_deadline_passed = order.latest_ship_date < now
            else:
                order.ship_deadline_passed = False
    
    @api.depends('ship_name', 'ship_address_line1', 'ship_address_line2',
                 'ship_address_line3', 'ship_city', 'ship_state_or_region',
                 'ship_postal_code', 'ship_country_code')
    def _compute_formatted_ship_address(self):
        for order in self:
            parts = [
                order.ship_name,
                order.ship_address_line1,
                order.ship_address_line2,
                order.ship_address_line3,
                ' '.join(filter(None, [
                    order.ship_postal_code,
                    order.ship_city,
                ])),
                order.ship_state_or_region,
                order.ship_country_code,
            ]
            order.formatted_ship_address = '\n'.join(filter(None, parts))
    
    # ══════════════════════════════════════════════════════════════════════════
    # BUSINESS LOGIC
    # ══════════════════════════════════════════════════════════════════════════
    
    def action_create_sale_order(self):
        """Create linked Odoo sale.order from Amazon order."""
        self.ensure_one()
        if self.sale_order_id:
            raise UserError(_("Sale order already exists for this Amazon order."))
        
        partner = self._get_or_create_partner()
        
        sale_order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'partner_invoice_id': partner.id,
            'partner_shipping_id': partner.id,
            'amazon_order_id': self.id,
            'amazon_order_ref': self.amazon_order_id,
            'client_order_ref': self.amazon_order_id,
            'date_order': self.purchase_date,
            'pricelist_id': self._get_pricelist().id,
        })
        
        for line in self.order_line_ids:
            line._create_sale_order_line(sale_order)
        
        self.sale_order_id = sale_order
        return sale_order
    
    def _get_or_create_partner(self):
        """Get or create customer partner from Amazon buyer info."""
        self.ensure_one()
        
        if self.partner_id:
            return self.partner_id
        
        Partner = self.env['res.partner']
        
        # Try to find existing by email
        if self.buyer_email:
            partner = Partner.search([
                ('email', '=', self.buyer_email),
                ('amazon_buyer', '=', True),
            ], limit=1)
            if partner:
                self.partner_id = partner
                return partner
        
        # Create new partner
        country = self.ship_country_id
        state = False
        if self.ship_state_or_region and country:
            state = self.env['res.country.state'].search([
                ('country_id', '=', country.id),
                '|',
                ('code', '=ilike', self.ship_state_or_region),
                ('name', '=ilike', self.ship_state_or_region),
            ], limit=1)
        
        partner_vals = {
            'name': self.ship_name or self.buyer_name or self.buyer_email or 'Amazon Customer',
            'email': self.buyer_email,
            'phone': self.ship_phone,
            'street': self.ship_address_line1,
            'street2': ' '.join(filter(None, [
                self.ship_address_line2,
                self.ship_address_line3,
            ])) or False,
            'city': self.ship_city,
            'state_id': state.id if state else False,
            'zip': self.ship_postal_code,
            'country_id': country.id if country else False,
            'amazon_buyer': True,
            'is_company': self.is_business_order,
            'vat': self.buyer_tax_registration_id if self.is_business_order else False,
        }
        
        partner = Partner.create(partner_vals)
        self.partner_id = partner
        return partner
    
    def _get_pricelist(self):
        """Get appropriate pricelist for the order currency."""
        pricelist = self.env['product.pricelist'].search([
            ('currency_id', '=', self.currency_id.id),
        ], limit=1)
        if not pricelist:
            pricelist = self.env['product.pricelist'].search([], limit=1)
        return pricelist
    
    def action_view_sale_order(self):
        """Open linked sale order."""
        self.ensure_one()
        if not self.sale_order_id:
            raise UserError(_("No sale order linked to this Amazon order."))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.sale_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    def action_view_returns(self):
        """Open returns for this order."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Returns'),
            'res_model': 'amazon.return',
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
            'context': {'default_order_id': self.id},
        }
    
    def action_sync_from_amazon(self):
        """Refresh order data from Amazon SP-API."""
        for order in self:
            try:
                order.account_id._sync_order(order.amazon_order_id)
                order.sync_status = 'synced'
                order.last_sync_date = fields.Datetime.now()
                order.sync_error_message = False
            except Exception as e:
                order.sync_status = 'error'
                order.sync_error_message = str(e)
                _logger.exception("Failed to sync Amazon order %s", order.amazon_order_id)
    
    def action_confirm_shipment(self):
        """Mark order as shipped and upload tracking to Amazon."""
        self.ensure_one()
        if self.fulfillment_channel == 'AFN':
            raise UserError(_("FBA orders are shipped by Amazon."))
        
        # Check if sale order exists
        if not self.sale_order_id:
            raise UserError(_("No linked sale order found for shipping details."))

        # Find pickings that are done and have tracking info
        pickings = self.sale_order_id.picking_ids.filtered(
            lambda p: p.state == 'done' and p.carrier_tracking_ref
        )

        if not pickings:
            raise UserError(_("No shipped pickings with tracking number found."))

        # For this implementation, we'll take the most recent shipping info
        picking = pickings[-1]

        tracking_number = picking.carrier_tracking_ref
        carrier = picking.carrier_id

        # Determine carrier code
        carrier_name = carrier.name if carrier else 'Other'

        # Collect items from the picking
        items_payload = []
        for move in picking.move_ids:
            if move.state == 'done' and move.sale_line_id and move.sale_line_id.amazon_order_line_id:
                # Use 'quantity' (v17+) or 'product_uom_qty'
                qty = getattr(move, 'quantity', move.product_uom_qty)

                items_payload.append({
                    'orderItemId': move.sale_line_id.amazon_order_line_id.order_item_id,
                    'quantity': int(qty)
                })

        if not items_payload:
            _logger.warning("Could not map picking items to Amazon items for order %s. Confirming without item details.", self.amazon_order_id)

        self.account_id._confirm_shipment(
            order_id=self.amazon_order_id,
            carrier_code=carrier_name,
            tracking_number=tracking_number,
            items=items_payload if items_payload else None
        )

        # Recalculate items shipped from ALL done pickings to handle split shipments correctly
        all_done_pickings = self.sale_order_id.picking_ids.filtered(lambda p: p.state == 'done')

        total_shipped = 0
        for p in all_done_pickings:
            for move in p.move_ids:
                if move.state == 'done' and move.sale_line_id and move.sale_line_id.amazon_order_line_id:
                     qty = getattr(move, 'quantity', move.product_uom_qty)
                     total_shipped += int(qty)

        total_ordered = sum(self.order_line_ids.mapped('quantity_ordered'))

        new_status = 'shipped' if total_shipped >= total_ordered else 'partially_shipped'

        self.write({
            'order_status': new_status,
            'number_of_items_shipped': total_shipped,
            'number_of_items_unshipped': max(0, total_ordered - total_shipped),
        })
    
    # ══════════════════════════════════════════════════════════════════════════
    # IMPORT FROM SP-API
    # ══════════════════════════════════════════════════════════════════════════
    
    @api.model
    def create_from_spapi(self, account, order_data, marketplace_cache=None, currency_cache=None):
        """Create or update Amazon order from SP-API response.
        
        Args:
            account: amazon.account record
            order_data: dict from SP-API Orders API
            marketplace_cache: dict to cache marketplace records
            currency_cache: dict to cache currency records
            
        Returns:
            amazon.order record
        """
        amazon_order_id = order_data.get('AmazonOrderId')
        
        existing = self.search([
            ('amazon_order_id', '=', amazon_order_id),
            ('account_id', '=', account.id),
        ], limit=1)
        
        vals = self._prepare_vals_from_spapi(
            account, order_data,
            marketplace_cache=marketplace_cache,
            currency_cache=currency_cache
        )
        
        if existing:
            existing.write(vals)
            return existing
        else:
            return self.create(vals)
    
    @api.model
    def _prepare_vals_from_spapi(self, account, data, marketplace_cache=None, currency_cache=None):
        """Transform SP-API order data to model values."""
        # Get marketplace
        marketplace_id_amz = data.get('MarketplaceId')
        marketplace = None

        if marketplace_cache is not None and marketplace_id_amz in marketplace_cache:
            marketplace = marketplace_cache[marketplace_id_amz]
        else:
            marketplace = self.env['amazon.marketplace'].search([
                ('marketplace_id', '=', marketplace_id_amz)
            ], limit=1)
            if marketplace_cache is not None and marketplace:
                marketplace_cache[marketplace_id_amz] = marketplace
        
        # Get currency
        order_total = data.get('OrderTotal', {})
        currency_code = order_total.get('CurrencyCode', 'EUR')
        currency = None

        if currency_cache is not None and currency_code in currency_cache:
            currency = currency_cache[currency_code]
        else:
            currency = self.env['res.currency'].search([
                ('name', '=', currency_code)
            ], limit=1)
            if not currency:
                currency = self.env.ref('base.EUR', raise_if_not_found=False) or \
                           self.env['res.currency'].search([], limit=1)

            if currency_cache is not None and currency:
                currency_cache[currency_code] = currency
        
        # Parse shipping address
        ship_addr = data.get('ShippingAddress', {})
        
        # Map order status
        status_map = {
            'Pending': 'pending',
            'Unshipped': 'unshipped',
            'PartiallyShipped': 'partially_shipped',
            'Shipped': 'shipped',
            'InvoiceUnconfirmed': 'invoice_unconfirmed',
            'Canceled': 'canceled',
            'Unfulfillable': 'unfulfillable',
            'PendingAvailability': 'pending_availability',
        }
        
        # Map shipment service level
        service_map = {
            'Expedited': 'expedited',
            'FreeEconomy': 'free_economy',
            'NextDay': 'next_day',
            'SameDay': 'same_day',
            'SecondDay': 'second_day',
            'Scheduled': 'scheduled',
            'Standard': 'standard',
        }
        
        # Parse payment method
        payment_methods = data.get('PaymentMethodDetails', [])
        payment_method = 'other'
        payment_detail = None
        if payment_methods:
            pm = payment_methods[0]
            payment_map = {
                'COD': 'cod',
                'CVS': 'cvs',
                'CreditCard': 'credit_card',
                'GC': 'gcgc',
            }
            for key, val in payment_map.items():
                if key.lower() in pm.lower():
                    payment_method = val
                    break
            payment_detail = pm
        
        vals = {
            'account_id': account.id,
            'marketplace_id': marketplace.id if marketplace else False,
            'amazon_order_id': data.get('AmazonOrderId'),
            'seller_order_id': data.get('SellerOrderId'),
            'purchase_date': self._parse_datetime(data.get('PurchaseDate')),
            'last_update_date': self._parse_datetime(data.get('LastUpdateDate')),
            'order_status': status_map.get(data.get('OrderStatus'), 'pending'),
            'fulfillment_channel': data.get('FulfillmentChannel', 'MFN'),
            'sales_channel': data.get('SalesChannel'),
            'order_channel': data.get('OrderChannel'),
            'currency_id': currency.id,
            'order_total': float(order_total.get('Amount', 0)),
            'number_of_items_shipped': data.get('NumberOfItemsShipped', 0),
            'number_of_items_unshipped': data.get('NumberOfItemsUnshipped', 0),
            
            # Shipping
            'shipment_service_level_category': service_map.get(
                data.get('ShipmentServiceLevelCategory')
            ),
            'ship_service_level': data.get('ShipServiceLevel'),
            'earliest_ship_date': self._parse_datetime(data.get('EarliestShipDate')),
            'latest_ship_date': self._parse_datetime(data.get('LatestShipDate')),
            'earliest_delivery_date': self._parse_datetime(data.get('EarliestDeliveryDate')),
            'latest_delivery_date': self._parse_datetime(data.get('LatestDeliveryDate')),
            'is_ispu': data.get('IsISPU', False),
            'is_scheduled_delivery_shipment': data.get('IsScheduledDeliveryShipment', False),
            
            # Shipping address
            'ship_name': ship_addr.get('Name'),
            'ship_address_line1': ship_addr.get('AddressLine1'),
            'ship_address_line2': ship_addr.get('AddressLine2'),
            'ship_address_line3': ship_addr.get('AddressLine3'),
            'ship_city': ship_addr.get('City'),
            'ship_state_or_region': ship_addr.get('StateOrRegion'),
            'ship_postal_code': ship_addr.get('PostalCode'),
            'ship_country_code': ship_addr.get('CountryCode'),
            'ship_phone': ship_addr.get('Phone'),
            'address_type': 'commercial' if ship_addr.get('AddressType') == 'Commercial' else 'residential',
            
            # Buyer
            'buyer_email': data.get('BuyerInfo', {}).get('BuyerEmail'),
            'buyer_name': data.get('BuyerInfo', {}).get('BuyerName'),
            
            # Flags
            'is_business_order': data.get('IsBusinessOrder', False),
            'is_prime': data.get('IsPrime', False),
            'is_premium_order': data.get('IsPremiumOrder', False),
            'is_global_express_enabled': data.get('IsGlobalExpressEnabled', False),
            'is_replacement_order': data.get('IsReplacementOrder', False),
            'replaced_order_id': data.get('ReplacedOrderId'),
            
            # Payment
            'payment_method': payment_method,
            'payment_method_details': payment_detail,
            
            # Gift
            'is_gift': data.get('IsGift', False),
            
            # Easy Ship (India, Japan)
            'easy_ship_shipment_status': data.get('EasyShipShipmentStatus'),
            
            # Sync
            'sync_status': 'synced',
            'last_sync_date': fields.Datetime.now(),
        }
        
        # Handle tax info from BuyerTaxInformation
        tax_info = data.get('BuyerTaxInformation', {})
        if tax_info:
            vals['buyer_tax_registration_id'] = tax_info.get('BuyerTaxRegistrationId')
            vals['buyer_company_legal_name'] = tax_info.get('BuyerLegalCompanyName')
            vals['is_vat_invoice_required'] = True
        
        # Handle marketplace tax (IOSS)
        automated_ship_tax = data.get('AutomatedShippingSettings', {})
        if automated_ship_tax.get('HasAutomatedShippingSettings'):
            vals['is_ioss_order'] = True
            vals['tax_collection_model'] = 'marketplace_facilitator'
        
        return vals
    
    @staticmethod
    def _parse_datetime(value):
        """Parse ISO datetime string to datetime object."""
        if not value:
            return False
        try:
            # SP-API uses ISO 8601 format
            if isinstance(value, str):
                # Remove timezone and parse
                value = value.replace('Z', '+00:00')
                return datetime.fromisoformat(value.replace('+00:00', ''))
            return value
        except (ValueError, TypeError):
            return False
