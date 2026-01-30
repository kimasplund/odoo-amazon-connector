# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmazonProductImportWizard(models.TransientModel):
    """
    Wizard for importing Amazon product listings to Odoo.
    Pulls listings from Amazon and creates/updates Odoo products.
    """
    _name = 'amazon.product.import.wizard'
    _description = 'Import Products from Amazon'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    
    # Account & Marketplace Selection
    account_id = fields.Many2one(
        'amazon.account',
        string='Amazon Account',
        required=True,
        default=lambda self: self._default_account_id(),
        help='Select the Amazon Seller Central account to import from.',
    )
    marketplace_ids = fields.Many2many(
        'amazon.marketplace',
        string='Marketplaces',
        required=True,
        domain="[('account_ids', 'in', account_id)]",
        help='Select marketplaces to import listings from.',
    )
    
    # Import Options
    import_mode = fields.Selection([
        ('all', 'All Listings'),
        ('active', 'Active Listings Only'),
        ('new', 'Only New (Not in Odoo)'),
        ('specific', 'Specific SKUs'),
    ], string='Import Mode', default='active', required=True,
       help='All: Import all listings\n'
            'Active: Only active listings\n'
            'New: Only listings not yet in Odoo\n'
            'Specific: Import specific SKUs')
    
    specific_skus = fields.Text(
        string='SKUs',
        help='Enter SKUs to import, one per line.',
    )
    
    # Product Creation Options
    create_products = fields.Boolean(
        string='Create New Products',
        default=True,
        help='Create Odoo products for listings that do not match existing products.',
    )
    update_products = fields.Boolean(
        string='Update Existing Products',
        default=False,
        help='Update Odoo product data (name, description) from Amazon.',
    )
    
    # Matching Options
    match_by = fields.Selection([
        ('sku', 'SKU → Internal Reference'),
        ('barcode', 'ASIN/EAN → Barcode'),
        ('both', 'Both (SKU first, then Barcode)'),
    ], string='Match Products By', default='both', required=True,
       help='How to match Amazon listings to existing Odoo products.')
    
    # Category Options
    product_category_id = fields.Many2one(
        'product.category',
        string='Default Category',
        help='Category for newly created products.',
    )
    map_categories = fields.Boolean(
        string='Map Amazon Categories',
        default=False,
        help='Attempt to map Amazon browse nodes to Odoo categories.',
    )
    
    # Price Options
    import_prices = fields.Boolean(
        string='Import Prices',
        default=True,
        help='Update product sales price from Amazon listing price.',
    )
    price_markup = fields.Float(
        string='Price Markup (%)',
        default=0.0,
        help='Apply markup to imported prices (use negative for markdown).',
    )
    
    # Inventory Options
    import_inventory = fields.Boolean(
        string='Import Inventory',
        default=False,
        help='Import inventory levels (requires inventory adjustment).',
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Target Warehouse',
        help='Warehouse for inventory import.',
    )
    
    # Image Options
    import_images = fields.Boolean(
        string='Import Images',
        default=True,
        help='Download and set product images from Amazon.',
    )
    
    # State & Progress
    state = fields.Selection([
        ('draft', 'Configuration'),
        ('fetching', 'Fetching Listings'),
        ('preview', 'Preview'),
        ('importing', 'Importing'),
        ('done', 'Completed'),
        ('error', 'Error'),
    ], string='State', default='draft')
    
    progress_percent = fields.Float(string='Progress', default=0.0)
    progress_message = fields.Char(string='Status')
    
    # Preview Data
    preview_line_ids = fields.One2many(
        'amazon.product.import.wizard.line',
        'wizard_id',
        string='Listings to Import',
    )
    preview_total = fields.Integer(
        string='Total Found',
        compute='_compute_preview_stats',
    )
    preview_new = fields.Integer(
        string='New Products',
        compute='_compute_preview_stats',
    )
    preview_existing = fields.Integer(
        string='Existing Products',
        compute='_compute_preview_stats',
    )
    
    # Results
    result_created = fields.Integer(string='Products Created', default=0)
    result_updated = fields.Integer(string='Products Updated', default=0)
    result_linked = fields.Integer(string='Listings Linked', default=0)
    result_errors = fields.Integer(string='Errors', default=0)
    result_log = fields.Text(string='Import Log')
    
    # -------------------------------------------------------------------------
    # DEFAULT METHODS
    # -------------------------------------------------------------------------
    
    def _default_account_id(self):
        return self.env['amazon.account'].search([('active', '=', True)], limit=1)
    
    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    
    @api.depends('preview_line_ids', 'preview_line_ids.action')
    def _compute_preview_stats(self):
        for wizard in self:
            lines = wizard.preview_line_ids
            wizard.preview_total = len(lines)
            wizard.preview_new = len(lines.filtered(lambda l: l.action == 'create'))
            wizard.preview_existing = len(lines.filtered(lambda l: l.action in ('link', 'update')))
    
    # -------------------------------------------------------------------------
    # ONCHANGE METHODS
    # -------------------------------------------------------------------------
    
    @api.onchange('account_id')
    def _onchange_account_id(self):
        self.marketplace_ids = False
        if self.account_id:
            self.marketplace_ids = self.account_id.marketplace_ids
    
    @api.onchange('import_mode')
    def _onchange_import_mode(self):
        if self.import_mode != 'specific':
            self.specific_skus = False
    
    @api.onchange('import_inventory')
    def _onchange_import_inventory(self):
        if self.import_inventory and not self.warehouse_id:
            self.warehouse_id = self.env['stock.warehouse'].search([], limit=1)
    
    # -------------------------------------------------------------------------
    # ACTION METHODS
    # -------------------------------------------------------------------------
    
    def action_fetch_listings(self):
        """Fetch listings from Amazon and show preview."""
        self.ensure_one()
        
        if self.import_mode == 'specific' and not self.specific_skus:
            raise UserError(_('Please enter SKUs to import.'))
        
        self.state = 'fetching'
        self.progress_message = _('Connecting to Amazon...')
        self.preview_line_ids.unlink()
        
        try:
            sp_api = self.account_id._get_sp_api_client()
            all_listings = []
            
            for marketplace in self.marketplace_ids:
                self.progress_message = _('Fetching from %s...', marketplace.name)
                
                # Get listings based on import mode
                if self.import_mode == 'specific':
                    skus = [s.strip() for s in self.specific_skus.split('\n') if s.strip()]
                    listings = sp_api.get_listings_by_skus(
                        marketplace.marketplace_id, skus
                    )
                else:
                    listings = sp_api.get_all_listings(
                        marketplace.marketplace_id,
                        status='active' if self.import_mode == 'active' else None,
                    )
                
                for listing in listings:
                    listing['marketplace_id'] = marketplace.id
                    all_listings.append(listing)
            
            # Process listings and create preview lines
            for listing in all_listings:
                self._create_preview_line(listing)
            
            # Filter for "new only" mode
            if self.import_mode == 'new':
                self.preview_line_ids.filtered(
                    lambda l: l.action != 'create'
                ).unlink()
            
            self.state = 'preview'
            self.progress_message = _('Found %d listings', len(self.preview_line_ids))
            
        except Exception as e:
            _logger.exception('Error fetching Amazon listings')
            self.state = 'error'
            self.progress_message = _('Error: %s', str(e))
        
        return self._return_wizard()
    
    def action_import(self):
        """Import selected listings."""
        self.ensure_one()
        
        lines_to_import = self.preview_line_ids.filtered(lambda l: l.selected)
        if not lines_to_import:
            raise UserError(_('Please select at least one listing to import.'))
        
        self.state = 'importing'
        self.result_created = 0
        self.result_updated = 0
        self.result_linked = 0
        self.result_errors = 0
        log_lines = []
        
        total = len(lines_to_import)
        for idx, line in enumerate(lines_to_import, 1):
            self.progress_percent = (idx / total) * 100
            self.progress_message = _('Importing %s (%d/%d)...', line.sku, idx, total)
            
            try:
                result = self._import_listing_line(line)
                log_lines.append(f"✓ {line.sku}: {result}")
            except Exception as e:
                _logger.exception('Error importing %s', line.sku)
                self.result_errors += 1
                line.state = 'error'
                line.message = str(e)[:200]
                log_lines.append(f"✗ {line.sku}: {e}")
        
        self.state = 'done'
        self.progress_percent = 100.0
        self.progress_message = _(
            'Completed: %d created, %d updated, %d linked, %d errors',
            self.result_created, self.result_updated, 
            self.result_linked, self.result_errors
        )
        self.result_log = '\n'.join(log_lines)
        
        return self._return_wizard()
    
    def action_select_all(self):
        """Select all preview lines."""
        self.preview_line_ids.write({'selected': True})
        return self._return_wizard()
    
    def action_select_none(self):
        """Deselect all preview lines."""
        self.preview_line_ids.write({'selected': False})
        return self._return_wizard()
    
    def action_select_new_only(self):
        """Select only new products."""
        self.preview_line_ids.write({'selected': False})
        self.preview_line_ids.filtered(
            lambda l: l.action == 'create'
        ).write({'selected': True})
        return self._return_wizard()
    
    def action_back(self):
        """Go back to configuration."""
        self.state = 'draft'
        return self._return_wizard()
    
    def action_view_products(self):
        """View imported products."""
        products = self.preview_line_ids.filtered(
            lambda l: l.state == 'done' and l.product_id
        ).mapped('product_id')
        
        return {
            'name': _('Imported Products'),
            'type': 'ir.actions.act_window',
            'res_model': 'product.template',
            'view_mode': 'list,form',
            'domain': [('id', 'in', products.ids)],
        }
    
    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------
    
    def _create_preview_line(self, listing_data):
        """Create a preview line from Amazon listing data."""
        sku = listing_data.get('sku', '')
        asin = listing_data.get('asin', '')
        
        # Try to match existing product
        product = self._find_matching_product(listing_data)
        
        if product:
            action = 'update' if self.update_products else 'link'
        elif self.create_products:
            action = 'create'
        else:
            action = 'skip'
        
        return self.env['amazon.product.import.wizard.line'].create({
            'wizard_id': self.id,
            'selected': action != 'skip',
            'sku': sku,
            'asin': asin,
            'marketplace_id': listing_data['marketplace_id'],
            'title': listing_data.get('title', '')[:256],
            'price': listing_data.get('price', 0.0),
            'currency': listing_data.get('currency', 'EUR'),
            'quantity': listing_data.get('quantity', 0),
            'fulfillment': listing_data.get('fulfillment_channel', 'MFN'),
            'status': listing_data.get('status', 'active'),
            'product_id': product.id if product else False,
            'action': action,
            'image_url': listing_data.get('image_url', ''),
        })
    
    def _find_matching_product(self, listing_data):
        """Find existing Odoo product matching the listing."""
        Product = self.env['product.template']
        sku = listing_data.get('sku', '')
        asin = listing_data.get('asin', '')
        ean = listing_data.get('ean', '')
        
        product = None
        
        if self.match_by in ('sku', 'both') and sku:
            product = Product.search([('default_code', '=', sku)], limit=1)
        
        if not product and self.match_by in ('barcode', 'both'):
            if ean:
                product = Product.search([('barcode', '=', ean)], limit=1)
            if not product and asin:
                product = Product.search([('barcode', '=', asin)], limit=1)
        
        return product
    
    def _import_listing_line(self, line):
        """Import a single listing line."""
        Product = self.env['product.template']
        Listing = self.env['amazon.product.listing']
        
        if line.action == 'create':
            # Create new product
            product_vals = self._prepare_product_vals(line)
            product = Product.create(product_vals)
            line.product_id = product.id
            self.result_created += 1
            result_msg = _('Product created')
            
        elif line.action == 'update':
            # Update existing product
            product = line.product_id
            product_vals = self._prepare_product_vals(line, update=True)
            product.write(product_vals)
            self.result_updated += 1
            result_msg = _('Product updated')
            
        elif line.action == 'link':
            product = line.product_id
            result_msg = _('Linked to existing')
            
        else:
            line.state = 'skipped'
            return _('Skipped')
        
        # Create/update listing record
        listing_vals = {
            'product_tmpl_id': line.product_id.id,
            'account_id': self.account_id.id,
            'marketplace_id': line.marketplace_id.id,
            'seller_sku': line.sku,
            'asin': line.asin,
            'fulfillment_channel': line.fulfillment,
            'status': line.status,
            'last_sync_date': fields.Datetime.now(),
        }
        
        existing_listing = Listing.search([
            ('seller_sku', '=', line.sku),
            ('marketplace_id', '=', line.marketplace_id.id),
            ('account_id', '=', self.account_id.id),
        ], limit=1)
        
        if existing_listing:
            existing_listing.write(listing_vals)
        else:
            Listing.create(listing_vals)
            self.result_linked += 1
        
        line.state = 'done'
        line.message = result_msg
        return result_msg
    
    def _prepare_product_vals(self, line, update=False):
        """Prepare product values from listing line."""
        vals = {}
        
        if not update or self.update_products:
            vals['name'] = line.title or line.sku
        
        if not update:
            vals['default_code'] = line.sku
            vals['type'] = 'consu'
            vals['sale_ok'] = True
            vals['purchase_ok'] = True
            
            if self.product_category_id:
                vals['categ_id'] = self.product_category_id.id
        
        if self.import_prices and line.price:
            price = line.price
            if self.price_markup:
                price *= (1 + self.price_markup / 100)
            vals['list_price'] = price
        
        if self.import_images and line.image_url:
            try:
                import base64
                import requests
                response = requests.get(line.image_url, timeout=10)
                if response.status_code == 200:
                    vals['image_1920'] = base64.b64encode(response.content)
            except Exception as e:
                _logger.warning('Failed to download image for %s: %s', line.sku, e)
        
        return vals
    
    def _return_wizard(self):
        """Return action to keep wizard open."""
        return {
            'name': _('Import Products from Amazon'),
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.product.import.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }


class AmazonProductImportWizardLine(models.TransientModel):
    """Preview line for product import."""
    _name = 'amazon.product.import.wizard.line'
    _description = 'Product Import Preview Line'
    _order = 'action, sku'
    
    wizard_id = fields.Many2one(
        'amazon.product.import.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    selected = fields.Boolean(string='Import', default=True)
    
    # Amazon Data
    sku = fields.Char(string='SKU', required=True)
    asin = fields.Char(string='ASIN')
    marketplace_id = fields.Many2one('amazon.marketplace', string='Marketplace')
    title = fields.Char(string='Title')
    price = fields.Float(string='Price')
    currency = fields.Char(string='Currency')
    quantity = fields.Integer(string='Qty')
    fulfillment = fields.Selection([
        ('MFN', 'FBM'),
        ('AFN', 'FBA'),
    ], string='Fulfillment')
    status = fields.Char(string='Status')
    image_url = fields.Char(string='Image URL')
    
    # Matching
    product_id = fields.Many2one('product.template', string='Matched Product')
    action = fields.Selection([
        ('create', 'Create New'),
        ('update', 'Update Existing'),
        ('link', 'Link Only'),
        ('skip', 'Skip'),
    ], string='Action', default='create')
    
    # Result
    state = fields.Selection([
        ('pending', 'Pending'),
        ('done', 'Done'),
        ('error', 'Error'),
        ('skipped', 'Skipped'),
    ], string='Status', default='pending')
    message = fields.Char(string='Message')
