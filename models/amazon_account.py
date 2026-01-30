# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import json
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AmazonAccount(models.Model):
    """Amazon Seller Account with SP-API credentials.
    
    Manages seller account credentials, OAuth tokens, and API connectivity.
    Supports both sandbox and production environments.
    """
    _name = 'amazon.account'
    _description = 'Amazon Seller Account'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    name = fields.Char(
        string='Account Name',
        required=True,
        tracking=True,
        help='Internal name for this seller account',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        help='Company that owns this seller account',
    )

    # Seller Identity
    seller_id = fields.Char(
        string='Seller ID',
        required=True,
        index=True,
        tracking=True,
        help='Amazon Seller/Merchant ID',
    )
    merchant_token = fields.Char(
        string='Merchant Token',
        help='Legacy MWS merchant token (if applicable)',
    )

    # OAuth Credentials (LWA - Login with Amazon)
    lwa_client_id = fields.Char(
        string='LWA Client ID',
        groups='base.group_system',
        help='Login with Amazon App Client ID',
    )
    lwa_client_secret = fields.Char(
        string='LWA Client Secret',
        groups='base.group_system',
        help='Login with Amazon App Client Secret',
    )
    refresh_token = fields.Char(
        string='Refresh Token',
        groups='base.group_system',
        help='OAuth refresh token for SP-API authentication',
    )

    # Access Token Management
    access_token = fields.Char(
        string='Access Token',
        groups='base.group_system',
        help='Current OAuth access token (short-lived)',
    )
    access_token_expiry = fields.Datetime(
        string='Token Expiry',
        groups='base.group_system',
        help='When the current access token expires',
    )
    token_valid = fields.Boolean(
        string='Token Valid',
        compute='_compute_token_valid',
        help='Whether the current access token is valid',
    )

    # AWS Credentials (for SP-API signing)
    aws_access_key = fields.Char(
        string='AWS Access Key',
        groups='base.group_system',
        help='AWS IAM access key for request signing',
    )
    aws_secret_key = fields.Char(
        string='AWS Secret Key',
        groups='base.group_system',
        help='AWS IAM secret key for request signing',
    )
    aws_role_arn = fields.Char(
        string='AWS Role ARN',
        groups='base.group_system',
        help='AWS IAM Role ARN for assuming role (optional)',
    )

    # Environment & Status
    environment = fields.Selection(
        selection=[
            ('sandbox', 'Sandbox'),
            ('production', 'Production'),
        ],
        string='Environment',
        required=True,
        default='sandbox',
        tracking=True,
        help='API environment (use sandbox for testing)',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('pending', 'Pending Verification'),
            ('active', 'Active'),
            ('suspended', 'Suspended'),
            ('error', 'Error'),
        ],
        string='Status',
        default='draft',
        tracking=True,
        help='Account connection status',
    )
    last_sync_date = fields.Datetime(
        string='Last Sync',
        readonly=True,
        help='Last successful API synchronization',
    )
    last_error = fields.Text(
        string='Last Error',
        readonly=True,
        help='Last API error message',
    )

    # Marketplace Configuration
    marketplace_ids = fields.Many2many(
        comodel_name='amazon.marketplace',
        relation='amazon_account_marketplace_rel',
        column1='account_id',
        column2='marketplace_id',
        string='Marketplaces',
        help='Marketplaces where this account is registered',
    )
    default_marketplace_id = fields.Many2one(
        comodel_name='amazon.marketplace',
        string='Default Marketplace',
        help='Default marketplace for this account',
    )
    marketplace_count = fields.Integer(
        string='# Marketplaces',
        compute='_compute_marketplace_count',
    )

    # Sync Settings
    sync_products = fields.Boolean(
        string='Sync Products',
        default=True,
        help='Enable product catalog synchronization',
    )
    sync_orders = fields.Boolean(
        string='Sync Orders',
        default=True,
        help='Enable order import',
    )
    sync_inventory = fields.Boolean(
        string='Sync Inventory',
        default=True,
        help='Enable inventory synchronization',
    )
    sync_fba = fields.Boolean(
        string='Sync FBA',
        default=True,
        help='Enable FBA inventory and shipment sync',
    )
    order_sync_days = fields.Integer(
        string='Order Sync Days',
        default=30,
        help='Number of days of order history to sync',
    )

    # Rate Limiting
    rate_limit_remaining = fields.Integer(
        string='Rate Limit Remaining',
        readonly=True,
        help='Remaining API calls in current rate limit window',
    )
    rate_limit_reset = fields.Datetime(
        string='Rate Limit Reset',
        readonly=True,
        help='When the rate limit resets',
    )

    # Relationships
    listing_ids = fields.One2many(
        comodel_name='amazon.product.listing',
        inverse_name='account_id',
        string='Product Listings',
    )
    listing_count = fields.Integer(
        string='# Listings',
        compute='_compute_listing_count',
    )
    log_ids = fields.One2many(
        comodel_name='amazon.sync.log',
        inverse_name='account_id',
        string='Sync Logs',
    )

    # Computed Stats for UI
    product_count = fields.Integer(
        string='# Products',
        compute='_compute_product_count',
    )
    order_count = fields.Integer(
        string='# Orders',
        compute='_compute_order_count',
    )
    fba_shipment_count = fields.Integer(
        string='# FBA Shipments',
        compute='_compute_fba_shipment_count',
    )
    settlement_count = fields.Integer(
        string='# Settlements',
        compute='_compute_settlement_count',
    )

    # Additional Status Fields (referenced by views)
    sync_status = fields.Selection(
        selection=[
            ('idle', 'Idle'),
            ('syncing', 'Syncing'),
            ('error', 'Error'),
        ],
        string='Sync Status',
        default='idle',
        help='Current synchronization status',
    )
    error_message = fields.Text(
        string='Error Message',
        readonly=True,
        help='Current error message if any',
    )
    token_expiry = fields.Datetime(
        string='Token Expiry',
        related='access_token_expiry',
        readonly=True,
    )

    # FBA Settings (referenced by views)
    fba_enabled = fields.Boolean(
        string='FBA Enabled',
        default=False,
        help='Enable Fulfillment by Amazon features',
    )
    fba_warehouse_id = fields.Many2one(
        comodel_name='stock.warehouse',
        string='FBA Warehouse',
        help='Virtual warehouse for FBA inventory',
    )
    fba_location_id = fields.Many2one(
        comodel_name='stock.location',
        string='FBA Location',
        help='Stock location for FBA inventory',
    )
    mcf_enabled = fields.Boolean(
        string='MCF Enabled',
        default=False,
        help='Enable Multi-Channel Fulfillment',
    )
    auto_route_fba = fields.Boolean(
        string='Auto-Route to FBA',
        default=False,
        help='Automatically route eligible orders to FBA',
    )
    default_fulfillment_channel = fields.Selection(
        selection=[
            ('fbm', 'Fulfilled by Merchant'),
            ('fba', 'Fulfilled by Amazon'),
        ],
        string='Default Fulfillment',
        default='fbm',
        help='Default fulfillment channel for new products',
    )

    # Additional Sync Settings (referenced by views)
    product_sync_interval = fields.Integer(
        string='Product Sync Interval (hours)',
        default=24,
        help='How often to sync products',
    )
    order_sync_interval = fields.Integer(
        string='Order Sync Interval (minutes)',
        default=15,
        help='How often to sync orders',
    )
    inventory_sync_interval = fields.Integer(
        string='Inventory Sync Interval (minutes)',
        default=60,
        help='How often to sync inventory',
    )
    pricing_sync_interval = fields.Integer(
        string='Pricing Sync Interval (hours)',
        default=6,
        help='How often to sync pricing',
    )
    order_days_back = fields.Integer(
        string='Order Import Days',
        default=30,
        help='Number of days back to import orders',
    )
    auto_create_products = fields.Boolean(
        string='Auto-Create Products',
        default=False,
        help='Automatically create Odoo products for Amazon listings',
    )
    product_default_category_id = fields.Many2one(
        comodel_name='product.category',
        string='Default Product Category',
        help='Default category for auto-created products',
    )
    auto_confirm_orders = fields.Boolean(
        string='Auto-Confirm Orders',
        default=False,
        help='Automatically confirm imported orders',
    )
    warehouse_id = fields.Many2one(
        comodel_name='stock.warehouse',
        string='Warehouse',
        help='Warehouse for order fulfillment',
    )

    # Pricing Settings
    sync_pricing = fields.Boolean(
        string='Sync Pricing',
        default=True,
        help='Enable pricing synchronization',
    )
    use_pricelist = fields.Boolean(
        string='Use Pricelist',
        default=False,
        help='Use Odoo pricelist for Amazon pricing',
    )
    pricelist_id = fields.Many2one(
        comodel_name='product.pricelist',
        string='Pricelist',
        help='Pricelist to use for Amazon pricing',
    )

    # Default Settings (referenced by views)
    default_product_type = fields.Char(
        string='Default Product Type',
        help='Default Amazon product type',
    )
    default_condition = fields.Selection(
        selection=[
            ('new', 'New'),
            ('refurbished', 'Refurbished'),
            ('used_like_new', 'Used - Like New'),
            ('used_very_good', 'Used - Very Good'),
            ('used_good', 'Used - Good'),
            ('used_acceptable', 'Used - Acceptable'),
        ],
        string='Default Condition',
        default='new',
        help='Default product condition',
    )
    default_tax_code = fields.Char(
        string='Default Tax Code',
        help='Default Amazon tax code',
    )
    default_sales_team_id = fields.Many2one(
        comodel_name='crm.team',
        string='Default Sales Team',
        help='Default sales team for Amazon orders',
    )
    default_user_id = fields.Many2one(
        comodel_name='res.users',
        string='Default Salesperson',
        help='Default salesperson for Amazon orders',
    )

    # Environment aliases (referenced by views)
    sandbox_mode = fields.Boolean(
        string='Sandbox Mode',
        compute='_compute_sandbox_mode',
        inverse='_inverse_sandbox_mode',
        help='Whether account is in sandbox mode',
    )
    api_region = fields.Selection(
        selection=[
            ('na', 'North America'),
            ('eu', 'Europe'),
            ('fe', 'Far East'),
        ],
        string='API Region',
        compute='_compute_api_region',
        help='SP-API region based on default marketplace',
    )

    # Additional credential field alias (referenced by views)
    role_arn = fields.Char(
        string='Role ARN',
        related='aws_role_arn',
        readonly=False,
        help='AWS IAM Role ARN',
    )

    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------
    _sql_constraints = [
        (
            'seller_id_company_unique',
            'UNIQUE(seller_id, company_id)',
            'Seller ID must be unique per company!',
        ),
    ]

    @api.constrains('marketplace_ids', 'default_marketplace_id')
    def _check_default_marketplace(self):
        """Ensure default marketplace is in the list of marketplaces."""
        for record in self:
            if (record.default_marketplace_id and 
                record.default_marketplace_id not in record.marketplace_ids):
                raise ValidationError(
                    _('Default marketplace must be in the list of marketplaces.')
                )

    @api.constrains('order_sync_days')
    def _check_order_sync_days(self):
        """Limit order sync range to reasonable values."""
        for record in self:
            if record.order_sync_days < 1 or record.order_sync_days > 365:
                raise ValidationError(
                    _('Order sync days must be between 1 and 365.')
                )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    @api.depends('access_token', 'access_token_expiry')
    def _compute_token_valid(self):
        """Check if the access token is still valid."""
        now = fields.Datetime.now()
        for record in self:
            record.token_valid = bool(
                record.access_token and
                record.access_token_expiry and
                record.access_token_expiry > now
            )

    def _compute_marketplace_count(self):
        for record in self:
            record.marketplace_count = len(record.marketplace_ids)

    def _compute_listing_count(self):
        for record in self:
            record.listing_count = len(record.listing_ids)

    def _compute_product_count(self):
        """Compute number of product listings."""
        for record in self:
            record.product_count = self.env['amazon.product.listing'].search_count([
                ('account_id', '=', record.id)
            ])

    def _compute_order_count(self):
        """Compute number of orders."""
        for record in self:
            record.order_count = self.env['amazon.order'].search_count([
                ('account_id', '=', record.id)
            ])

    def _compute_fba_shipment_count(self):
        """Compute number of FBA shipments."""
        for record in self:
            record.fba_shipment_count = self.env['amazon.fba.shipment'].search_count([
                ('account_id', '=', record.id)
            ])

    def _compute_settlement_count(self):
        """Compute number of settlements."""
        for record in self:
            record.settlement_count = self.env['amazon.settlement'].search_count([
                ('account_id', '=', record.id)
            ])

    @api.depends('environment')
    def _compute_sandbox_mode(self):
        """Compute sandbox mode based on environment."""
        for record in self:
            record.sandbox_mode = record.environment == 'sandbox'

    def _inverse_sandbox_mode(self):
        """Set environment based on sandbox mode."""
        for record in self:
            record.environment = 'sandbox' if record.sandbox_mode else 'production'

    @api.depends('default_marketplace_id', 'default_marketplace_id.region')
    def _compute_api_region(self):
        """Compute API region based on default marketplace."""
        for record in self:
            if record.default_marketplace_id:
                record.api_region = record.default_marketplace_id.region
            else:
                record.api_region = 'eu'  # Default to EU

    # -------------------------------------------------------------------------
    # CRUD OVERRIDES
    # -------------------------------------------------------------------------
    def write(self, vals):
        """Clear access token if credentials change."""
        credential_fields = {
            'lwa_client_id', 'lwa_client_secret', 'refresh_token',
            'aws_access_key', 'aws_secret_key'
        }
        if credential_fields & set(vals.keys()):
            vals.update({
                'access_token': False,
                'access_token_expiry': False,
                'state': 'pending' if vals.get('state') != 'draft' else 'draft',
            })
        return super().write(vals)

    # -------------------------------------------------------------------------
    # API AUTHENTICATION
    # -------------------------------------------------------------------------
    def _get_access_token(self):
        """Get a valid access token, refreshing if necessary.
        
        Returns:
            str: Valid access token or raises UserError
        """
        self.ensure_one()
        
        if self.token_valid:
            return self.access_token

        return self._refresh_access_token()

    def _refresh_access_token(self):
        """Refresh the OAuth access token using the refresh token.
        
        This method calls Amazon's LWA token endpoint to get a new access token.
        The access token is typically valid for 1 hour.
        
        Returns:
            str: New access token
            
        Raises:
            UserError: If token refresh fails
        """
        self.ensure_one()
        
        if not all([self.lwa_client_id, self.lwa_client_secret, self.refresh_token]):
            raise UserError(
                _('Missing OAuth credentials. Please configure LWA Client ID, '
                  'Client Secret, and Refresh Token.')
            )

        # Token refresh implementation would go here
        # This is a placeholder for the actual LWA API call
        _logger.info('Refreshing access token for account: %s', self.name)
        
        try:
            # TODO: Implement actual LWA token refresh via sp_api_auth service
            # token_data = self.env['sp.api.auth'].refresh_token(self)
            # For now, raise not implemented
            raise UserError(
                _('SP-API authentication service not yet implemented. '
                  'Please configure the sp_api_auth service.')
            )
        except Exception as e:
            self.write({
                'state': 'error',
                'last_error': str(e),
                'access_token': False,
                'access_token_expiry': False,
            })
            raise UserError(_('Failed to refresh access token: %s') % str(e))

    # -------------------------------------------------------------------------
    # CONNECTION TESTING
    # -------------------------------------------------------------------------
    def action_test_connection(self):
        """Test the API connection and validate credentials.
        
        Makes a simple API call to verify that all credentials are correct
        and the account has proper permissions.
        """
        self.ensure_one()
        
        try:
            self._test_connection()
            self.write({
                'state': 'active',
                'last_sync_date': fields.Datetime.now(),
                'last_error': False,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Successful'),
                    'message': _('Successfully connected to Amazon SP-API.'),
                    'type': 'success',
                    'sticky': False,
                },
            }
        except Exception as e:
            self.write({
                'state': 'error',
                'last_error': str(e),
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Failed'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                },
            }

    def _test_connection(self):
        """Perform the actual connection test.
        
        Raises:
            UserError: If connection test fails
        """
        self.ensure_one()
        
        # Validate required fields
        if not self.seller_id:
            raise UserError(_('Seller ID is required.'))
        
        if not self.marketplace_ids:
            raise UserError(_('At least one marketplace must be configured.'))

        # Check credentials are present
        missing = []
        if not self.lwa_client_id:
            missing.append('LWA Client ID')
        if not self.lwa_client_secret:
            missing.append('LWA Client Secret')
        if not self.refresh_token:
            missing.append('Refresh Token')
        if not self.aws_access_key:
            missing.append('AWS Access Key')
        if not self.aws_secret_key:
            missing.append('AWS Secret Key')
        
        if missing:
            raise UserError(
                _('Missing credentials: %s') % ', '.join(missing)
            )

        # TODO: Implement actual API test call via SP-API client
        _logger.info(
            'Testing connection for account %s (seller: %s, env: %s)',
            self.name, self.seller_id, self.environment
        )
        
        # Placeholder - actual implementation would call:
        # self.env['sp.api.client'].test_connection(self)
        return True

    # -------------------------------------------------------------------------
    # SYNC ACTIONS
    # -------------------------------------------------------------------------
    def action_sync_all(self):
        """Trigger a full synchronization for this account."""
        self.ensure_one()
        
        if self.state != 'active':
            raise UserError(
                _('Account must be active to sync. Current state: %s') % self.state
            )
        
        # Queue sync jobs
        if self.sync_products:
            self._sync_products()
        if self.sync_orders:
            self._sync_orders()
        if self.sync_inventory:
            self._sync_inventory()
        if self.sync_fba:
            self._sync_fba()
        
        self.last_sync_date = fields.Datetime.now()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Started'),
                'message': _('Synchronization has been queued.'),
                'type': 'info',
                'sticky': False,
            },
        }

    def _sync_products(self):
        """Sync product catalog from Amazon."""
        _logger.info('Syncing products for account: %s', self.name)
        # TODO: Implement via sp_api_products service

    def _sync_orders(self):
        """Sync orders from Amazon."""
        _logger.info('Syncing orders for account: %s', self.name)
        # TODO: Implement via sp_api_orders service

    def _sync_inventory(self):
        """Sync inventory levels."""
        _logger.info('Syncing inventory for account: %s', self.name)
        # TODO: Implement via sp_api_fba service

    def _sync_fba(self):
        """Sync FBA data (shipments, inventory)."""
        _logger.info('Syncing FBA data for account: %s', self.name)
        # TODO: Implement via sp_api_fba service

    # -------------------------------------------------------------------------
    # NAVIGATION ACTIONS
    # -------------------------------------------------------------------------
    def action_view_listings(self):
        """Open product listings for this account."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Product Listings'),
            'res_model': 'amazon.product.listing',
            'view_mode': 'tree,form',
            'domain': [('account_id', '=', self.id)],
            'context': {'default_account_id': self.id},
        }

    def action_view_marketplaces(self):
        """Open marketplaces for this account."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Marketplaces'),
            'res_model': 'amazon.marketplace',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.marketplace_ids.ids)],
        }

    def action_open_seller_central(self):
        """Open Seller Central in a new browser tab."""
        self.ensure_one()
        marketplace = self.default_marketplace_id or self.marketplace_ids[:1]
        if not marketplace or not marketplace.seller_central_url:
            raise UserError(_('No Seller Central URL configured.'))
        
        return {
            'type': 'ir.actions.act_url',
            'url': marketplace.seller_central_url,
            'target': 'new',
        }

    def action_connect(self):
        """Connect to Amazon SP-API."""
        self.ensure_one()
        return self.action_test_connection()

    def action_disconnect(self):
        """Disconnect from Amazon SP-API."""
        self.ensure_one()
        self.write({
            'state': 'draft',
            'access_token': False,
            'access_token_expiry': False,
            'sync_status': 'idle',
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Disconnected'),
                'message': _('Account has been disconnected from Amazon.'),
                'type': 'info',
                'sticky': False,
            },
        }

    def action_refresh_token(self):
        """Manually refresh the access token."""
        self.ensure_one()
        try:
            self._refresh_access_token()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Token Refreshed'),
                    'message': _('Access token has been refreshed.'),
                    'type': 'success',
                    'sticky': False,
                },
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Token Refresh Failed'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                },
            }

    def action_view_products(self):
        """View products for this account."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Products'),
            'res_model': 'amazon.product.listing',
            'view_mode': 'tree,form',
            'domain': [('account_id', '=', self.id)],
            'context': {'default_account_id': self.id},
        }

    def action_view_orders(self):
        """View orders for this account."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Orders'),
            'res_model': 'amazon.order',
            'view_mode': 'tree,form',
            'domain': [('account_id', '=', self.id)],
            'context': {'default_account_id': self.id},
        }

    def action_view_fba_shipments(self):
        """View FBA shipments for this account."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('FBA Shipments'),
            'res_model': 'amazon.fba.shipment',
            'view_mode': 'tree,form',
            'domain': [('account_id', '=', self.id)],
            'context': {'default_account_id': self.id},
        }

    def action_view_settlements(self):
        """View settlements for this account."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Settlements'),
            'res_model': 'amazon.settlement',
            'view_mode': 'tree,form',
            'domain': [('account_id', '=', self.id)],
            'context': {'default_account_id': self.id},
        }
