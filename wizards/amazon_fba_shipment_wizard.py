# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

import logging
import base64
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AmazonFBAShipmentWizard(models.TransientModel):
    """
    Wizard for creating FBA inbound shipments.
    Guides user through the shipment creation process with Amazon.
    """
    _name = 'amazon.fba.shipment.wizard'
    _description = 'Create FBA Inbound Shipment'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    
    # Account & Marketplace
    account_id = fields.Many2one(
        'amazon.account',
        string='Amazon Account',
        required=True,
        default=lambda self: self._default_account_id(),
    )
    marketplace_id = fields.Many2one(
        'amazon.marketplace',
        string='Destination Marketplace',
        required=True,
        domain="[('account_ids', 'in', account_id)]",
    )
    
    # Ship From Address
    ship_from_address_id = fields.Many2one(
        'res.partner',
        string='Ship From Address',
        required=True,
        domain="[('type', '=', 'other')]",
        help='Warehouse or location shipping the products.',
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Source Warehouse',
        help='Warehouse to pick products from.',
    )
    
    # Shipment Details
    shipment_name = fields.Char(
        string='Shipment Name',
        required=True,
        default=lambda self: _('FBA Shipment %s') % fields.Date.today(),
    )
    label_prep_preference = fields.Selection([
        ('SELLER_LABEL', 'Seller Labels (You label)'),
        ('AMAZON_LABEL_ONLY', 'Amazon Labels Only'),
        ('AMAZON_LABEL_PREFERRED', 'Amazon Labels Preferred'),
    ], string='Label Prep', default='SELLER_LABEL', required=True,
       help='Who should label the products.')
    
    packing_type = fields.Selection([
        ('INDIVIDUAL', 'Individual Products'),
        ('CASE_PACKED', 'Case Packed'),
    ], string='Packing Type', default='INDIVIDUAL', required=True,
       help='Individual: Different products in boxes\n'
            'Case Packed: Same product in each box')
    
    # Products
    line_ids = fields.One2many(
        'amazon.fba.shipment.wizard.line',
        'wizard_id',
        string='Products',
    )
    line_count = fields.Integer(
        string='Product Count',
        compute='_compute_line_stats',
    )
    total_quantity = fields.Integer(
        string='Total Quantity',
        compute='_compute_line_stats',
    )
    
    # State Management
    state = fields.Selection([
        ('draft', 'Select Products'),
        ('plan', 'Review Plan'),
        ('confirm', 'Confirm Shipment'),
        ('labels', 'Print Labels'),
        ('done', 'Done'),
        ('error', 'Error'),
    ], string='State', default='draft')
    
    # Plan Results (from Amazon)
    shipment_plan_ids = fields.One2many(
        'amazon.fba.shipment.wizard.plan',
        'wizard_id',
        string='Shipment Plans',
    )
    selected_plan_id = fields.Many2one(
        'amazon.fba.shipment.wizard.plan',
        string='Selected Plan',
    )
    
    # Created Shipment
    created_shipment_id = fields.Many2one(
        'amazon.fba.shipment',
        string='Created Shipment',
        readonly=True,
    )
    
    # Labels
    label_data = fields.Binary(string='Labels PDF')
    label_filename = fields.Char(string='Label Filename')
    
    # Messages
    status_message = fields.Char(string='Status')
    error_message = fields.Text(string='Error Details')
    
    # -------------------------------------------------------------------------
    # DEFAULT METHODS
    # -------------------------------------------------------------------------
    
    def _default_account_id(self):
        return self.env['amazon.account'].search([('active', '=', True)], limit=1)
    
    @api.model
    def default_get(self, fields_list):
        """Pre-populate products from context."""
        res = super().default_get(fields_list)
        
        if self._context.get('active_model') == 'product.template':
            product_ids = self._context.get('active_ids', [])
            if product_ids:
                lines = []
                for product_id in product_ids:
                    product = self.env['product.template'].browse(product_id)
                    if product.exists():
                        lines.append((0, 0, {
                            'product_id': product_id,
                            'quantity': 1,
                        }))
                if lines:
                    res['line_ids'] = lines
        
        return res
    
    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    
    @api.depends('line_ids', 'line_ids.quantity')
    def _compute_line_stats(self):
        for wizard in self:
            wizard.line_count = len(wizard.line_ids)
            wizard.total_quantity = sum(wizard.line_ids.mapped('quantity'))
    
    # -------------------------------------------------------------------------
    # ONCHANGE METHODS
    # -------------------------------------------------------------------------
    
    @api.onchange('account_id')
    def _onchange_account_id(self):
        self.marketplace_id = False
        if self.account_id and self.account_id.marketplace_ids:
            # Default to first marketplace
            self.marketplace_id = self.account_id.marketplace_ids[0]
    
    @api.onchange('warehouse_id')
    def _onchange_warehouse_id(self):
        if self.warehouse_id and self.warehouse_id.partner_id:
            self.ship_from_address_id = self.warehouse_id.partner_id
    
    # -------------------------------------------------------------------------
    # CONSTRAINT METHODS
    # -------------------------------------------------------------------------
    
    @api.constrains('line_ids')
    def _check_line_ids(self):
        for wizard in self:
            if wizard.state != 'draft':
                continue
            for line in wizard.line_ids:
                if line.quantity <= 0:
                    raise ValidationError(
                        _('Quantity must be greater than 0 for %s.') % line.product_id.name
                    )
    
    # -------------------------------------------------------------------------
    # ACTION METHODS
    # -------------------------------------------------------------------------
    
    def action_add_products(self):
        """Open product selection."""
        self.ensure_one()
        return {
            'name': _('Add Products'),
            'type': 'ir.actions.act_window',
            'res_model': 'product.template',
            'view_mode': 'list',
            'target': 'new',
            'domain': [
                ('sale_ok', '=', True),
                ('type', '!=', 'service'),
            ],
            'context': {
                'create': False,
                'fba_wizard_id': self.id,
            },
        }
    
    def action_create_plan(self):
        """Submit products to Amazon and get shipment plan."""
        self.ensure_one()
        
        if not self.line_ids:
            raise UserError(_('Please add at least one product.'))
        
        # Validate products have SKUs
        missing_sku = self.line_ids.filtered(lambda l: not l.seller_sku)
        if missing_sku:
            product_names = ', '.join(missing_sku.mapped('product_id.name'))
            raise UserError(_(
                'The following products do not have Amazon SKUs:\n%s\n\n'
                'Please create Amazon listings first.',
                product_names
            ))
        
        self.status_message = _('Creating shipment plan with Amazon...')
        self.shipment_plan_ids.unlink()
        
        try:
            sp_api = self.account_id._get_sp_api_client()
            
            # Prepare inbound shipment plan request
            items = []
            for line in self.line_ids:
                items.append({
                    'sku': line.seller_sku,
                    'asin': line.asin,
                    'quantity': line.quantity,
                    'condition': 'NewItem',
                    'prep_details': {
                        'prep_instruction': 'NoPrep',
                        'prep_owner': 'SELLER' if self.label_prep_preference == 'SELLER_LABEL' else 'AMAZON',
                    },
                })
            
            ship_from = {
                'name': self.ship_from_address_id.name,
                'address_line_1': self.ship_from_address_id.street or '',
                'address_line_2': self.ship_from_address_id.street2 or '',
                'city': self.ship_from_address_id.city or '',
                'state_or_province': self.ship_from_address_id.state_id.code or '',
                'postal_code': self.ship_from_address_id.zip or '',
                'country_code': self.ship_from_address_id.country_id.code or '',
            }
            
            # Create inbound shipment plan
            plan_response = sp_api.create_inbound_shipment_plan(
                marketplace_id=self.marketplace_id.marketplace_id,
                ship_from_address=ship_from,
                items=items,
                label_prep_preference=self.label_prep_preference,
            )
            
            # Process shipment plans
            for plan_data in plan_response.get('shipment_plans', []):
                self.env['amazon.fba.shipment.wizard.plan'].create({
                    'wizard_id': self.id,
                    'shipment_id_amazon': plan_data.get('shipment_id'),
                    'destination_fc': plan_data.get('destination_fulfillment_center_id'),
                    'label_prep_type': plan_data.get('label_prep_type'),
                    'item_count': len(plan_data.get('items', [])),
                    'items_json': str(plan_data.get('items', [])),
                })
            
            if not self.shipment_plan_ids:
                raise UserError(_('Amazon did not return any shipment plans.'))
            
            # Auto-select first plan
            self.selected_plan_id = self.shipment_plan_ids[0]
            self.state = 'plan'
            self.status_message = _('Shipment plan created. Review and confirm.')
            
        except Exception as e:
            _logger.exception('Error creating FBA shipment plan')
            self.state = 'error'
            self.error_message = str(e)
            self.status_message = _('Error creating plan')
        
        return self._return_wizard()
    
    def action_confirm_shipment(self):
        """Confirm the selected shipment plan with Amazon."""
        self.ensure_one()
        
        if not self.selected_plan_id:
            raise UserError(_('Please select a shipment plan.'))
        
        self.status_message = _('Confirming shipment with Amazon...')
        
        try:
            sp_api = self.account_id._get_sp_api_client()
            
            # Confirm inbound shipment
            response = sp_api.create_inbound_shipment(
                shipment_id=self.selected_plan_id.shipment_id_amazon,
                shipment_name=self.shipment_name,
                marketplace_id=self.marketplace_id.marketplace_id,
            )
            
            # Create local shipment record
            shipment = self.env['amazon.fba.shipment'].create({
                'name': self.shipment_name,
                'account_id': self.account_id.id,
                'marketplace_id': self.marketplace_id.id,
                'amazon_shipment_id': self.selected_plan_id.shipment_id_amazon,
                'destination_fc': self.selected_plan_id.destination_fc,
                'status': 'WORKING',
                'ship_from_address_id': self.ship_from_address_id.id,
                'label_prep_type': self.label_prep_preference,
            })
            
            # Create shipment items
            for line in self.line_ids:
                self.env['amazon.fba.shipment.item'].create({
                    'shipment_id': shipment.id,
                    'product_id': line.product_id.id,
                    'seller_sku': line.seller_sku,
                    'quantity_shipped': line.quantity,
                })
            
            self.created_shipment_id = shipment.id
            self.state = 'confirm'
            self.status_message = _('Shipment confirmed! You can now print labels.')
            
        except Exception as e:
            _logger.exception('Error confirming FBA shipment')
            self.state = 'error'
            self.error_message = str(e)
            self.status_message = _('Error confirming shipment')
        
        return self._return_wizard()
    
    def action_get_labels(self):
        """Fetch shipping labels from Amazon."""
        self.ensure_one()
        
        if not self.created_shipment_id:
            raise UserError(_('No shipment to get labels for.'))
        
        self.status_message = _('Fetching labels from Amazon...')
        
        try:
            sp_api = self.account_id._get_sp_api_client()
            
            # Get package labels
            labels_response = sp_api.get_labels(
                shipment_id=self.created_shipment_id.amazon_shipment_id,
                page_type='PackageLabel_Plain_Paper',
                label_type='BARCODE_2D',
            )
            
            if labels_response.get('pdf'):
                self.label_data = base64.b64encode(labels_response['pdf'])
                self.label_filename = f'fba_labels_{self.created_shipment_id.amazon_shipment_id}.pdf'
            
            # Get item labels if seller labeling
            if self.label_prep_preference == 'SELLER_LABEL':
                item_labels = sp_api.get_unique_item_labels(
                    shipment_id=self.created_shipment_id.amazon_shipment_id,
                    page_type='PackageLabel_Plain_Paper',
                )
                # Store or combine with package labels
            
            self.state = 'labels'
            self.status_message = _('Labels ready. Print and apply to boxes.')
            
        except Exception as e:
            _logger.exception('Error fetching FBA labels')
            self.error_message = str(e)
            self.status_message = _('Error fetching labels: %s', str(e))
        
        return self._return_wizard()
    
    def action_print_labels(self):
        """Download the labels PDF."""
        self.ensure_one()
        
        if not self.label_data:
            raise UserError(_('No labels available. Please fetch labels first.'))
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/amazon.fba.shipment.wizard/{self.id}/label_data/{self.label_filename}?download=true',
            'target': 'new',
        }
    
    def action_done(self):
        """Complete the wizard and open the shipment."""
        self.ensure_one()
        
        if self.created_shipment_id:
            return {
                'name': _('FBA Shipment'),
                'type': 'ir.actions.act_window',
                'res_model': 'amazon.fba.shipment',
                'view_mode': 'form',
                'res_id': self.created_shipment_id.id,
            }
        
        return {'type': 'ir.actions.act_window_close'}
    
    def action_back(self):
        """Go back to previous step."""
        self.ensure_one()
        
        state_order = ['draft', 'plan', 'confirm', 'labels', 'done']
        current_idx = state_order.index(self.state) if self.state in state_order else 0
        
        if current_idx > 0:
            self.state = state_order[current_idx - 1]
        
        return self._return_wizard()
    
    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------
    
    def _return_wizard(self):
        """Return action to keep wizard open."""
        return {
            'name': _('Create FBA Inbound Shipment'),
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.fba.shipment.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }


class AmazonFBAShipmentWizardLine(models.TransientModel):
    """Product line for FBA shipment wizard."""
    _name = 'amazon.fba.shipment.wizard.line'
    _description = 'FBA Shipment Wizard Line'
    
    wizard_id = fields.Many2one(
        'amazon.fba.shipment.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        ondelete='cascade',
    )
    quantity = fields.Integer(
        string='Quantity',
        required=True,
        default=1,
    )
    
    # Amazon Data (computed from listing)
    seller_sku = fields.Char(
        string='SKU',
        compute='_compute_amazon_data',
        store=True,
    )
    asin = fields.Char(
        string='ASIN',
        compute='_compute_amazon_data',
        store=True,
    )
    fnsku = fields.Char(
        string='FNSKU',
        compute='_compute_amazon_data',
        store=True,
    )
    
    # Stock Info
    available_qty = fields.Float(
        string='Available',
        compute='_compute_available_qty',
    )
    
    @api.depends('product_id', 'wizard_id.account_id', 'wizard_id.marketplace_id')
    def _compute_amazon_data(self):
        # Reset all lines first
        for line in self:
            line.seller_sku = ''
            line.asin = ''
            line.fnsku = ''
            
        # Filter valid lines
        valid_lines = self.filtered(lambda l: l.product_id and l.wizard_id.account_id)
        if not valid_lines:
            return

        # Collect distinct criteria
        product_ids = valid_lines.mapped('product_id').ids
        account_ids = valid_lines.mapped('wizard_id.account_id').ids

        # Batch query all potential listings
        listings = self.env['amazon.product.listing'].search([
            ('product_tmpl_id', 'in', product_ids),
            ('account_id', 'in', account_ids),
        ])

        # Build lookup dictionaries
        # 1. Exact AFN match per (product_tmpl_id, account_id, marketplace_id)
        afn_listings = {}
        # 2. Fallback match per (product_tmpl_id, account_id)
        any_listings = {}

        for listing in listings:
            key_any = (listing.product_tmpl_id.id, listing.account_id.id)
            if key_any not in any_listings:
                any_listings[key_any] = listing
                
            if listing.fulfillment_channel == 'AFN' and listing.marketplace_id:
                key_afn = (listing.product_tmpl_id.id, listing.account_id.id, listing.marketplace_id.id)
                if key_afn not in afn_listings:
                    afn_listings[key_afn] = listing

        for line in valid_lines:
            key_afn = (line.product_id.id, line.wizard_id.account_id.id, line.wizard_id.marketplace_id.id)
            key_any = (line.product_id.id, line.wizard_id.account_id.id)

            listing = afn_listings.get(key_afn)
            if listing:
                line.seller_sku = listing.seller_sku
                line.asin = listing.asin
                line.fnsku = listing.fnsku
            else:
                any_listing = any_listings.get(key_any)
                if any_listing:
                    line.seller_sku = any_listing.seller_sku
                    line.asin = any_listing.asin
    
    @api.depends('product_id', 'wizard_id.warehouse_id')
    def _compute_available_qty(self):
        for line in self:
            if line.product_id and line.wizard_id.warehouse_id:
                line.available_qty = line.product_id.with_context(
                    warehouse=line.wizard_id.warehouse_id.id
                ).qty_available
            else:
                line.available_qty = line.product_id.qty_available if line.product_id else 0


class AmazonFBAShipmentWizardPlan(models.TransientModel):
    """Shipment plan option from Amazon."""
    _name = 'amazon.fba.shipment.wizard.plan'
    _description = 'FBA Shipment Plan'
    
    wizard_id = fields.Many2one(
        'amazon.fba.shipment.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    shipment_id_amazon = fields.Char(string='Shipment ID')
    destination_fc = fields.Char(string='Destination FC')
    label_prep_type = fields.Char(string='Label Prep Type')
    item_count = fields.Integer(string='Items')
    items_json = fields.Text(string='Items Data')
    
    def name_get(self):
        return [(p.id, f'{p.destination_fc} ({p.item_count} items)') for p in self]
