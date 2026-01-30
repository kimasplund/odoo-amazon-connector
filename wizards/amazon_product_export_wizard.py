# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AmazonProductExportWizard(models.TransientModel):
    """
    Wizard for exporting Odoo products to Amazon marketplaces.
    Supports bulk export with progress tracking.
    """
    _name = 'amazon.product.export.wizard'
    _description = 'Export Products to Amazon'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    
    # Account & Marketplace Selection
    account_id = fields.Many2one(
        'amazon.account',
        string='Amazon Account',
        required=True,
        default=lambda self: self._default_account_id(),
        help='Select the Amazon Seller Central account to export to.',
    )
    marketplace_ids = fields.Many2many(
        'amazon.marketplace',
        string='Marketplaces',
        required=True,
        domain="[('account_ids', 'in', account_id)]",
        help='Select target marketplaces for product listing.',
    )
    
    # Product Selection
    product_ids = fields.Many2many(
        'product.template',
        string='Products to Export',
        required=True,
        domain="[('sale_ok', '=', True), ('type', '!=', 'service')]",
        help='Select products to export to Amazon.',
    )
    product_count = fields.Integer(
        string='Product Count',
        compute='_compute_product_count',
    )
    
    # Export Options
    export_mode = fields.Selection([
        ('create', 'Create New Listings'),
        ('update', 'Update Existing Listings'),
        ('both', 'Create or Update (Smart Mode)'),
    ], string='Export Mode', default='both', required=True,
       help='Create: Only create new listings\n'
            'Update: Only update existing listings\n'
            'Smart Mode: Create new or update existing automatically')
    
    update_price = fields.Boolean(
        string='Update Price',
        default=True,
        help='Include price in the export.',
    )
    update_inventory = fields.Boolean(
        string='Update Inventory',
        default=True,
        help='Include inventory quantity in the export.',
    )
    update_images = fields.Boolean(
        string='Update Images',
        default=False,
        help='Upload product images to Amazon (slower).',
    )
    update_description = fields.Boolean(
        string='Update Description',
        default=True,
        help='Include product title, bullets, and description.',
    )
    
    # SKU Options
    sku_mode = fields.Selection([
        ('default_code', 'Use Internal Reference'),
        ('barcode', 'Use Barcode/EAN'),
        ('custom', 'Custom SKU Field'),
    ], string='SKU Source', default='default_code', required=True,
       help='How to generate Amazon SKU from Odoo product.')
    
    # Price Options
    price_mode = fields.Selection([
        ('list_price', 'Sales Price'),
        ('pricelist', 'Specific Pricelist'),
    ], string='Price Source', default='list_price',
       help='Which price to use for Amazon listing.')
    pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Pricelist',
        help='Pricelist to use when Price Source is "Specific Pricelist".',
    )
    price_margin = fields.Float(
        string='Price Margin (%)',
        default=0.0,
        help='Add percentage margin to the price.',
    )
    
    # Fulfillment Options
    fulfillment_channel = fields.Selection([
        ('MFN', 'Merchant Fulfilled (FBM)'),
        ('AFN', 'Amazon Fulfilled (FBA)'),
    ], string='Fulfillment Channel', default='MFN', required=True,
       help='MFN: You ship the products\nAFN: Amazon ships from FBA inventory')
    
    # Progress Tracking
    state = fields.Selection([
        ('draft', 'Configuration'),
        ('confirm', 'Confirm'),
        ('progress', 'In Progress'),
        ('done', 'Completed'),
        ('error', 'Error'),
    ], string='State', default='draft')
    
    progress_percent = fields.Float(
        string='Progress',
        default=0.0,
    )
    progress_current = fields.Integer(
        string='Current',
        default=0,
    )
    progress_total = fields.Integer(
        string='Total',
        default=0,
    )
    progress_message = fields.Char(
        string='Status Message',
    )
    
    # Results
    result_success_count = fields.Integer(
        string='Successful',
        default=0,
    )
    result_error_count = fields.Integer(
        string='Failed',
        default=0,
    )
    result_skip_count = fields.Integer(
        string='Skipped',
        default=0,
    )
    result_log = fields.Text(
        string='Export Log',
    )
    result_line_ids = fields.One2many(
        'amazon.product.export.wizard.line',
        'wizard_id',
        string='Export Results',
    )
    
    # -------------------------------------------------------------------------
    # DEFAULT METHODS
    # -------------------------------------------------------------------------
    
    def _default_account_id(self):
        """Return the default Amazon account (first active one)."""
        return self.env['amazon.account'].search([
            ('active', '=', True),
        ], limit=1)
    
    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    
    @api.depends('product_ids')
    def _compute_product_count(self):
        for wizard in self:
            wizard.product_count = len(wizard.product_ids)
    
    # -------------------------------------------------------------------------
    # ONCHANGE METHODS
    # -------------------------------------------------------------------------
    
    @api.onchange('account_id')
    def _onchange_account_id(self):
        """Reset marketplace selection when account changes."""
        self.marketplace_ids = False
        if self.account_id:
            # Auto-select all marketplaces for the account
            self.marketplace_ids = self.account_id.marketplace_ids
    
    @api.onchange('price_mode')
    def _onchange_price_mode(self):
        """Clear pricelist when not using pricelist mode."""
        if self.price_mode != 'pricelist':
            self.pricelist_id = False
    
    # -------------------------------------------------------------------------
    # CONSTRAINT METHODS
    # -------------------------------------------------------------------------
    
    @api.constrains('price_margin')
    def _check_price_margin(self):
        for wizard in self:
            if wizard.price_margin < -100:
                raise ValidationError(_('Price margin cannot be less than -100%.'))
    
    # -------------------------------------------------------------------------
    # ACTION METHODS
    # -------------------------------------------------------------------------
    
    def action_confirm(self):
        """Move to confirmation step."""
        self.ensure_one()
        
        if not self.product_ids:
            raise UserError(_('Please select at least one product to export.'))
        
        if not self.marketplace_ids:
            raise UserError(_('Please select at least one marketplace.'))
        
        # Validate products have required data
        invalid_products = self._validate_products()
        if invalid_products:
            product_names = ', '.join(invalid_products[:5])
            if len(invalid_products) > 5:
                product_names += f' (+{len(invalid_products) - 5} more)'
            raise UserError(_(
                'The following products are missing required data (SKU/Internal Reference):\n%s',
                product_names
            ))
        
        self.state = 'confirm'
        return self._return_wizard()
    
    def action_back(self):
        """Go back to configuration step."""
        self.ensure_one()
        self.state = 'draft'
        return self._return_wizard()
    
    def action_export(self):
        """
        Execute the product export to Amazon.
        Uses background job for large exports.
        """
        self.ensure_one()
        
        self.state = 'progress'
        self.progress_total = len(self.product_ids) * len(self.marketplace_ids)
        self.progress_current = 0
        self.progress_percent = 0.0
        self.progress_message = _('Starting export...')
        self.result_success_count = 0
        self.result_error_count = 0
        self.result_skip_count = 0
        self.result_log = ''
        
        # Clear previous result lines
        self.result_line_ids.unlink()
        
        # For small exports, run synchronously
        # For large exports (>50 products), use background job
        if self.progress_total <= 50:
            self._execute_export()
        else:
            # Schedule background job
            self.env['ir.cron'].sudo()._trigger(
                'amazon_connector.ir_cron_amazon_product_export'
            )
            self.progress_message = _('Export queued for background processing...')
        
        return self._return_wizard()
    
    def action_view_results(self):
        """View detailed export results."""
        self.ensure_one()
        return {
            'name': _('Export Results'),
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.product.export.wizard.line',
            'view_mode': 'list',
            'domain': [('wizard_id', '=', self.id)],
            'context': {'create': False},
        }
    
    def action_retry_failed(self):
        """Retry only the failed products."""
        self.ensure_one()
        failed_lines = self.result_line_ids.filtered(
            lambda l: l.state == 'error'
        )
        if not failed_lines:
            raise UserError(_('No failed products to retry.'))
        
        # Get failed product IDs
        failed_product_ids = failed_lines.mapped('product_id').ids
        
        # Create new wizard with failed products
        new_wizard = self.copy({
            'product_ids': [(6, 0, failed_product_ids)],
            'state': 'draft',
            'result_line_ids': False,
        })
        
        return {
            'name': _('Retry Failed Export'),
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.product.export.wizard',
            'view_mode': 'form',
            'res_id': new_wizard.id,
            'target': 'new',
        }
    
    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------
    
    def _validate_products(self):
        """
        Validate products have required data for export.
        Returns list of invalid product names.
        """
        invalid = []
        for product in self.product_ids:
            sku = self._get_product_sku(product)
            if not sku:
                invalid.append(product.display_name)
        return invalid
    
    def _get_product_sku(self, product):
        """Get SKU for product based on sku_mode."""
        if self.sku_mode == 'default_code':
            return product.default_code
        elif self.sku_mode == 'barcode':
            return product.barcode
        elif self.sku_mode == 'custom':
            return getattr(product, 'amazon_sku', None) or product.default_code
        return None
    
    def _get_product_price(self, product, marketplace):
        """Get price for product based on price_mode and marketplace."""
        if self.price_mode == 'pricelist' and self.pricelist_id:
            price = self.pricelist_id._get_product_price(
                product, 1.0, currency=marketplace.currency_id
            )
        else:
            price = product.list_price
            # Convert currency if needed
            if product.currency_id != marketplace.currency_id:
                price = product.currency_id._convert(
                    price,
                    marketplace.currency_id,
                    self.env.company,
                    fields.Date.today(),
                )
        
        # Apply margin
        if self.price_margin:
            price *= (1 + self.price_margin / 100)
        
        return round(price, 2)
    
    def _execute_export(self):
        """Execute the actual export process."""
        self.ensure_one()
        log_lines = []
        
        # Get SP-API client
        try:
            sp_api = self.account_id._get_sp_api_client()
        except Exception as e:
            self.state = 'error'
            self.progress_message = _('Failed to connect to Amazon: %s', str(e))
            return
        
        for product in self.product_ids:
            for marketplace in self.marketplace_ids:
                self.progress_current += 1
                self.progress_percent = (self.progress_current / self.progress_total) * 100
                self.progress_message = _('Exporting %s to %s...', 
                                         product.display_name, 
                                         marketplace.name)
                
                result_line = self.env['amazon.product.export.wizard.line'].create({
                    'wizard_id': self.id,
                    'product_id': product.id,
                    'marketplace_id': marketplace.id,
                    'state': 'pending',
                })
                
                try:
                    # Check if listing exists
                    existing_listing = self.env['amazon.product.listing'].search([
                        ('product_tmpl_id', '=', product.id),
                        ('marketplace_id', '=', marketplace.id),
                        ('account_id', '=', self.account_id.id),
                    ], limit=1)
                    
                    # Skip based on export mode
                    if self.export_mode == 'create' and existing_listing:
                        result_line.write({
                            'state': 'skipped',
                            'message': _('Listing already exists'),
                        })
                        self.result_skip_count += 1
                        continue
                    
                    if self.export_mode == 'update' and not existing_listing:
                        result_line.write({
                            'state': 'skipped',
                            'message': _('No existing listing to update'),
                        })
                        self.result_skip_count += 1
                        continue
                    
                    # Prepare listing data
                    listing_data = self._prepare_listing_data(product, marketplace)
                    
                    # Submit to Amazon via SP-API
                    if existing_listing:
                        response = sp_api.update_listing(
                            marketplace.marketplace_id,
                            existing_listing.seller_sku,
                            listing_data,
                        )
                    else:
                        response = sp_api.create_listing(
                            marketplace.marketplace_id,
                            listing_data,
                        )
                    
                    # Create or update local listing record
                    listing_vals = {
                        'product_tmpl_id': product.id,
                        'marketplace_id': marketplace.id,
                        'account_id': self.account_id.id,
                        'seller_sku': listing_data['sku'],
                        'fulfillment_channel': self.fulfillment_channel,
                        'status': 'active',
                        'last_sync_date': fields.Datetime.now(),
                    }
                    
                    if existing_listing:
                        existing_listing.write(listing_vals)
                    else:
                        self.env['amazon.product.listing'].create(listing_vals)
                    
                    result_line.write({
                        'state': 'success',
                        'message': _('Exported successfully'),
                        'sku': listing_data['sku'],
                    })
                    self.result_success_count += 1
                    log_lines.append(f"✓ {product.display_name} → {marketplace.name}")
                    
                except Exception as e:
                    _logger.exception('Error exporting product %s to %s', 
                                    product.display_name, marketplace.name)
                    result_line.write({
                        'state': 'error',
                        'message': str(e)[:500],
                    })
                    self.result_error_count += 1
                    log_lines.append(f"✗ {product.display_name} → {marketplace.name}: {e}")
        
        # Update final state
        self.state = 'done' if self.result_error_count == 0 else 'error'
        self.progress_percent = 100.0
        self.progress_message = _(
            'Export completed: %d successful, %d failed, %d skipped',
            self.result_success_count,
            self.result_error_count,
            self.result_skip_count,
        )
        self.result_log = '\n'.join(log_lines)
    
    def _prepare_listing_data(self, product, marketplace):
        """Prepare product data for Amazon listing API."""
        sku = self._get_product_sku(product)
        
        data = {
            'sku': sku,
            'fulfillment_channel': self.fulfillment_channel,
        }
        
        if self.update_description:
            data.update({
                'title': product.name[:200],  # Amazon limit
                'description': product.description_sale or product.description or '',
                'bullet_points': self._get_bullet_points(product),
            })
        
        if self.update_price:
            data['price'] = {
                'amount': self._get_product_price(product, marketplace),
                'currency': marketplace.currency_id.name,
            }
        
        if self.update_inventory and self.fulfillment_channel == 'MFN':
            data['inventory'] = {
                'quantity': int(product.qty_available),
            }
        
        if self.update_images and product.image_1920:
            data['images'] = [{
                'type': 'MAIN',
                'url': self._get_image_url(product),
            }]
        
        # Add identifiers
        if product.barcode:
            data['product_id'] = product.barcode
            data['product_id_type'] = 'EAN'
        
        return data
    
    def _get_bullet_points(self, product):
        """Extract bullet points from product."""
        # Check for amazon-specific bullet points field
        if hasattr(product, 'amazon_bullet_points') and product.amazon_bullet_points:
            return product.amazon_bullet_points.split('\n')[:5]
        
        # Fall back to description parsing
        if product.description_sale:
            lines = [l.strip() for l in product.description_sale.split('\n') if l.strip()]
            return lines[:5]
        
        return []
    
    def _get_image_url(self, product):
        """Get public URL for product image."""
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return f"{base_url}/web/image/product.template/{product.id}/image_1920"
    
    def _return_wizard(self):
        """Return action to keep wizard open."""
        return {
            'name': _('Export Products to Amazon'),
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.product.export.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }


class AmazonProductExportWizardLine(models.TransientModel):
    """Individual product export result line."""
    _name = 'amazon.product.export.wizard.line'
    _description = 'Product Export Result Line'
    
    wizard_id = fields.Many2one(
        'amazon.product.export.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
    )
    marketplace_id = fields.Many2one(
        'amazon.marketplace',
        string='Marketplace',
        required=True,
    )
    sku = fields.Char(string='SKU')
    state = fields.Selection([
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('error', 'Error'),
        ('skipped', 'Skipped'),
    ], string='Status', default='pending')
    message = fields.Char(string='Message')
