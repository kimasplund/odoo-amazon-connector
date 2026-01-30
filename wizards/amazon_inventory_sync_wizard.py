# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AmazonInventorySyncWizard(models.TransientModel):
    """
    Wizard for manual inventory synchronization with Amazon.
    Push Odoo stock levels to Amazon for FBM products.
    """
    _name = 'amazon.inventory.sync.wizard'
    _description = 'Sync Inventory to Amazon'

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
        help='Select marketplaces to sync inventory to.',
    )
    
    # Sync Options
    sync_mode = fields.Selection([
        ('all', 'All Products'),
        ('selected', 'Selected Products'),
        ('changed', 'Changed Since Last Sync'),
        ('low_stock', 'Low Stock Only'),
    ], string='Sync Mode', default='changed', required=True,
       help='All: Sync all products with Amazon listings\n'
            'Selected: Only sync selected products\n'
            'Changed: Only products with inventory changes\n'
            'Low Stock: Products below safety stock')
    
    product_ids = fields.Many2many(
        'product.template',
        string='Products',
        domain="[('sale_ok', '=', True)]",
        help='Products to sync (for Selected mode).',
    )
    
    # Warehouse Options
    warehouse_ids = fields.Many2many(
        'stock.warehouse',
        string='Warehouses',
        help='Warehouses to sum inventory from. Leave empty for all.',
    )
    
    # Quantity Options
    quantity_type = fields.Selection([
        ('available', 'Available Quantity'),
        ('on_hand', 'On Hand Quantity'),
        ('forecasted', 'Forecasted Quantity'),
    ], string='Quantity Type', default='available', required=True,
       help='Which quantity to send to Amazon.')
    
    use_safety_stock = fields.Boolean(
        string='Apply Safety Stock',
        default=True,
        help='Subtract safety stock from quantity.',
    )
    safety_stock_percentage = fields.Float(
        string='Safety Stock (%)',
        default=0.0,
        help='Additional safety stock as percentage.',
    )
    minimum_quantity = fields.Integer(
        string='Minimum Quantity',
        default=0,
        help='Never send quantity below this (e.g., to avoid 0 stock).',
    )
    maximum_quantity = fields.Integer(
        string='Maximum Quantity',
        default=0,
        help='Cap quantity at this value (0 = no cap).',
    )
    
    # Lead Time
    handling_time = fields.Integer(
        string='Handling Time (days)',
        default=0,
        help='Days needed to ship. Set to 0 to keep current Amazon value.',
    )
    
    # FBM/FBA Filter
    fulfillment_channel = fields.Selection([
        ('MFN', 'Merchant Fulfilled (FBM) Only'),
        ('all', 'All Channels'),
    ], string='Channel Filter', default='MFN',
       help='FBM Only: Only sync FBM listings (makes sense for inventory push)\n'
            'All: Include FBA listings (mostly informational)')
    
    # Preview & Progress
    state = fields.Selection([
        ('draft', 'Configuration'),
        ('preview', 'Preview'),
        ('syncing', 'Syncing'),
        ('done', 'Completed'),
        ('error', 'Error'),
    ], string='State', default='draft')
    
    progress_percent = fields.Float(string='Progress', default=0.0)
    progress_message = fields.Char(string='Status')
    
    # Preview Lines
    line_ids = fields.One2many(
        'amazon.inventory.sync.wizard.line',
        'wizard_id',
        string='Products to Sync',
    )
    line_count = fields.Integer(
        string='Product Count',
        compute='_compute_line_stats',
    )
    line_total_qty = fields.Integer(
        string='Total Quantity',
        compute='_compute_line_stats',
    )
    
    # Results
    result_synced = fields.Integer(string='Products Synced', default=0)
    result_errors = fields.Integer(string='Errors', default=0)
    result_unchanged = fields.Integer(string='Unchanged', default=0)
    result_log = fields.Text(string='Sync Log')
    
    # -------------------------------------------------------------------------
    # DEFAULT METHODS
    # -------------------------------------------------------------------------
    
    def _default_account_id(self):
        return self.env['amazon.account'].search([('active', '=', True)], limit=1)
    
    @api.model
    def default_get(self, fields_list):
        """Pre-populate from context."""
        res = super().default_get(fields_list)
        
        if self._context.get('active_model') == 'product.template':
            product_ids = self._context.get('active_ids', [])
            if product_ids:
                res['sync_mode'] = 'selected'
                res['product_ids'] = [(6, 0, product_ids)]
        
        return res
    
    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    
    @api.depends('line_ids', 'line_ids.quantity_to_sync')
    def _compute_line_stats(self):
        for wizard in self:
            wizard.line_count = len(wizard.line_ids)
            wizard.line_total_qty = sum(wizard.line_ids.mapped('quantity_to_sync'))
    
    # -------------------------------------------------------------------------
    # ONCHANGE METHODS
    # -------------------------------------------------------------------------
    
    @api.onchange('account_id')
    def _onchange_account_id(self):
        self.marketplace_ids = False
        if self.account_id:
            self.marketplace_ids = self.account_id.marketplace_ids
    
    @api.onchange('sync_mode')
    def _onchange_sync_mode(self):
        if self.sync_mode != 'selected':
            self.product_ids = False
    
    # -------------------------------------------------------------------------
    # CONSTRAINT METHODS
    # -------------------------------------------------------------------------
    
    @api.constrains('safety_stock_percentage')
    def _check_safety_stock(self):
        for wizard in self:
            if wizard.safety_stock_percentage < 0 or wizard.safety_stock_percentage > 100:
                raise ValidationError(_('Safety stock percentage must be between 0 and 100.'))
    
    # -------------------------------------------------------------------------
    # ACTION METHODS
    # -------------------------------------------------------------------------
    
    def action_preview(self):
        """Generate preview of inventory to sync."""
        self.ensure_one()
        
        if self.sync_mode == 'selected' and not self.product_ids:
            raise UserError(_('Please select products to sync.'))
        
        if not self.marketplace_ids:
            raise UserError(_('Please select at least one marketplace.'))
        
        self.progress_message = _('Building inventory preview...')
        self.line_ids.unlink()
        
        # Get listings to sync
        listings = self._get_listings_to_sync()
        
        if not listings:
            raise UserError(_('No products with Amazon listings found for the selected criteria.'))
        
        # Create preview lines
        for listing in listings:
            self._create_preview_line(listing)
        
        self.state = 'preview'
        self.progress_message = _('%d products ready to sync', len(self.line_ids))
        
        return self._return_wizard()
    
    def action_sync(self):
        """Execute inventory sync to Amazon."""
        self.ensure_one()
        
        lines_to_sync = self.line_ids.filtered(lambda l: l.selected and l.needs_sync)
        if not lines_to_sync:
            raise UserError(_('No products need synchronization.'))
        
        self.state = 'syncing'
        self.result_synced = 0
        self.result_errors = 0
        self.result_unchanged = 0
        log_lines = []
        
        try:
            sp_api = self.account_id._get_sp_api_client()
            
            # Group by marketplace for batch submission
            marketplace_groups = {}
            for line in lines_to_sync:
                mp_id = line.marketplace_id.id
                if mp_id not in marketplace_groups:
                    marketplace_groups[mp_id] = []
                marketplace_groups[mp_id].append(line)
            
            total_lines = len(lines_to_sync)
            processed = 0
            
            for marketplace_id, lines in marketplace_groups.items():
                marketplace = self.env['amazon.marketplace'].browse(marketplace_id)
                
                # Prepare inventory feed
                inventory_items = []
                for line in lines:
                    item = {
                        'sku': line.seller_sku,
                        'quantity': line.quantity_to_sync,
                    }
                    if self.handling_time > 0:
                        item['handling_time'] = self.handling_time
                    inventory_items.append(item)
                
                self.progress_message = _('Submitting to %s...', marketplace.name)
                
                try:
                    # Submit inventory feed
                    feed_response = sp_api.submit_inventory_feed(
                        marketplace_id=marketplace.marketplace_id,
                        inventory_items=inventory_items,
                    )
                    
                    feed_id = feed_response.get('feed_id')
                    
                    # Mark lines as synced
                    for line in lines:
                        processed += 1
                        self.progress_percent = (processed / total_lines) * 100
                        
                        line.write({
                            'sync_status': 'success',
                            'sync_message': _('Feed submitted: %s', feed_id),
                        })
                        
                        # Update listing last sync
                        line.listing_id.write({
                            'last_inventory_sync': fields.Datetime.now(),
                            'quantity_amazon': line.quantity_to_sync,
                        })
                        
                        self.result_synced += 1
                        log_lines.append(f"✓ {line.seller_sku}: {line.quantity_to_sync} → {marketplace.name}")
                    
                except Exception as e:
                    _logger.exception('Error submitting inventory to %s', marketplace.name)
                    for line in lines:
                        line.write({
                            'sync_status': 'error',
                            'sync_message': str(e)[:200],
                        })
                        self.result_errors += 1
                        log_lines.append(f"✗ {line.seller_sku}: {e}")
            
            self.state = 'done'
            self.progress_percent = 100.0
            self.progress_message = _(
                'Completed: %d synced, %d unchanged, %d errors',
                self.result_synced, self.result_unchanged, self.result_errors
            )
            
        except Exception as e:
            _logger.exception('Error during inventory sync')
            self.state = 'error'
            self.progress_message = _('Error: %s', str(e))
        
        self.result_log = '\n'.join(log_lines)
        return self._return_wizard()
    
    def action_select_all(self):
        """Select all lines."""
        self.line_ids.write({'selected': True})
        return self._return_wizard()
    
    def action_select_none(self):
        """Deselect all lines."""
        self.line_ids.write({'selected': False})
        return self._return_wizard()
    
    def action_select_changed(self):
        """Select only changed lines."""
        self.line_ids.write({'selected': False})
        self.line_ids.filtered(lambda l: l.needs_sync).write({'selected': True})
        return self._return_wizard()
    
    def action_back(self):
        """Go back to configuration."""
        self.state = 'draft'
        return self._return_wizard()
    
    def action_refresh(self):
        """Refresh preview with current stock levels."""
        return self.action_preview()
    
    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------
    
    def _get_listings_to_sync(self):
        """Get Amazon listings to sync based on criteria."""
        Listing = self.env['amazon.product.listing']
        
        domain = [
            ('account_id', '=', self.account_id.id),
            ('marketplace_id', 'in', self.marketplace_ids.ids),
            ('status', '=', 'active'),
        ]
        
        if self.fulfillment_channel == 'MFN':
            domain.append(('fulfillment_channel', '=', 'MFN'))
        
        if self.sync_mode == 'selected':
            domain.append(('product_tmpl_id', 'in', self.product_ids.ids))
        
        listings = Listing.search(domain)
        
        if self.sync_mode == 'changed':
            # Filter to listings where stock changed
            listings = listings.filtered(lambda l: self._has_stock_changed(l))
        
        if self.sync_mode == 'low_stock':
            # Filter to low stock items
            listings = listings.filtered(lambda l: self._is_low_stock(l))
        
        return listings
    
    def _has_stock_changed(self, listing):
        """Check if stock has changed since last sync."""
        current_qty = self._get_quantity(listing.product_tmpl_id)
        amazon_qty = listing.quantity_amazon or 0
        return current_qty != amazon_qty
    
    def _is_low_stock(self, listing):
        """Check if product is low on stock."""
        product = listing.product_tmpl_id
        current_qty = self._get_quantity(product)
        safety_stock = getattr(product, 'amazon_safety_stock', 0) or 0
        return current_qty <= safety_stock
    
    def _get_quantity(self, product):
        """Get quantity for product based on settings."""
        context = {}
        if self.warehouse_ids:
            context['warehouse'] = self.warehouse_ids.ids
        
        product = product.with_context(**context)
        
        if self.quantity_type == 'available':
            qty = product.qty_available - product.outgoing_qty
        elif self.quantity_type == 'on_hand':
            qty = product.qty_available
        else:  # forecasted
            qty = product.virtual_available
        
        return max(0, int(qty))
    
    def _calculate_sync_quantity(self, product, current_amazon_qty=0):
        """Calculate the quantity to sync to Amazon."""
        base_qty = self._get_quantity(product)
        
        # Apply safety stock
        if self.use_safety_stock:
            safety = getattr(product, 'amazon_safety_stock', 0) or 0
            base_qty -= safety
        
        # Apply percentage safety stock
        if self.safety_stock_percentage:
            base_qty -= int(base_qty * self.safety_stock_percentage / 100)
        
        # Apply minimum
        if self.minimum_quantity:
            base_qty = max(base_qty, self.minimum_quantity)
        else:
            base_qty = max(base_qty, 0)
        
        # Apply maximum
        if self.maximum_quantity:
            base_qty = min(base_qty, self.maximum_quantity)
        
        return int(base_qty)
    
    def _create_preview_line(self, listing):
        """Create preview line for a listing."""
        product = listing.product_tmpl_id
        odoo_qty = self._get_quantity(product)
        sync_qty = self._calculate_sync_quantity(product, listing.quantity_amazon or 0)
        amazon_qty = listing.quantity_amazon or 0
        
        needs_sync = sync_qty != amazon_qty
        
        return self.env['amazon.inventory.sync.wizard.line'].create({
            'wizard_id': self.id,
            'selected': needs_sync,
            'listing_id': listing.id,
            'product_id': product.id,
            'seller_sku': listing.seller_sku,
            'marketplace_id': listing.marketplace_id.id,
            'quantity_odoo': odoo_qty,
            'quantity_amazon': amazon_qty,
            'quantity_to_sync': sync_qty,
            'needs_sync': needs_sync,
        })
    
    def _return_wizard(self):
        """Return action to keep wizard open."""
        return {
            'name': _('Sync Inventory to Amazon'),
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.inventory.sync.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }


class AmazonInventorySyncWizardLine(models.TransientModel):
    """Inventory sync preview line."""
    _name = 'amazon.inventory.sync.wizard.line'
    _description = 'Inventory Sync Preview Line'
    _order = 'needs_sync desc, seller_sku'
    
    wizard_id = fields.Many2one(
        'amazon.inventory.sync.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    selected = fields.Boolean(string='Sync', default=True)
    
    # Product & Listing
    listing_id = fields.Many2one(
        'amazon.product.listing',
        string='Listing',
        required=True,
    )
    product_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
    )
    seller_sku = fields.Char(string='SKU', required=True)
    marketplace_id = fields.Many2one(
        'amazon.marketplace',
        string='Marketplace',
        required=True,
    )
    
    # Quantities
    quantity_odoo = fields.Integer(string='Odoo Qty')
    quantity_amazon = fields.Integer(string='Amazon Qty')
    quantity_to_sync = fields.Integer(string='Sync Qty')
    quantity_diff = fields.Integer(
        string='Difference',
        compute='_compute_quantity_diff',
    )
    
    # Status
    needs_sync = fields.Boolean(string='Needs Sync')
    sync_status = fields.Selection([
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('error', 'Error'),
    ], string='Status', default='pending')
    sync_message = fields.Char(string='Message')
    
    @api.depends('quantity_to_sync', 'quantity_amazon')
    def _compute_quantity_diff(self):
        for line in self:
            line.quantity_diff = line.quantity_to_sync - line.quantity_amazon
    
    @api.onchange('quantity_to_sync')
    def _onchange_quantity_to_sync(self):
        """Recalculate needs_sync when quantity is manually changed."""
        self.needs_sync = self.quantity_to_sync != self.quantity_amazon
