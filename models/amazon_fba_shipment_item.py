# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class AmazonFBAShipmentItem(models.Model):
    """
    Amazon FBA Shipment Item.
    
    Represents a line item in an FBA inbound shipment with product,
    quantity, prep instructions, and receiving status.
    """
    _name = 'amazon.fba.shipment.item'
    _description = 'Amazon FBA Shipment Item'
    _order = 'sequence, id'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    
    # Relationships
    shipment_id = fields.Many2one(
        'amazon.fba.shipment',
        string='Shipment',
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        ondelete='restrict',
        domain="[('type', '=', 'product')]",
    )
    product_template_id = fields.Many2one(
        'product.template',
        string='Product Template',
        related='product_id.product_tmpl_id',
        store=True,
    )
    
    # Related from shipment
    account_id = fields.Many2one(
        related='shipment_id.account_id',
        store=True,
    )
    marketplace_id = fields.Many2one(
        related='shipment_id.marketplace_id',
        store=True,
    )
    shipment_state = fields.Selection(
        related='shipment_id.state',
        store=True,
        string='Shipment Status',
    )
    
    # Product Details
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    amazon_sku = fields.Char(
        string='Amazon SKU',
        required=True,
        index=True,
    )
    amazon_asin = fields.Char(
        string='ASIN',
    )
    amazon_fnsku = fields.Char(
        string='FNSKU',
        help='Fulfillment Network Stock Keeping Unit.',
    )
    product_name = fields.Char(
        string='Product Name',
        compute='_compute_product_info',
        store=True,
    )
    product_barcode = fields.Char(
        string='Barcode',
        related='product_id.barcode',
    )
    
    # Quantities
    quantity = fields.Integer(
        string='Quantity to Ship',
        required=True,
        default=1,
    )
    quantity_in_case = fields.Integer(
        string='Units per Case',
        default=0,
        help='Number of units per case for case-packed products.',
    )
    case_count = fields.Integer(
        string='Number of Cases',
        compute='_compute_case_count',
        store=True,
    )
    received_quantity = fields.Integer(
        string='Received Quantity',
        default=0,
        readonly=True,
    )
    quantity_difference = fields.Integer(
        string='Quantity Difference',
        compute='_compute_quantity_difference',
        store=True,
    )
    
    # Prep & Labeling
    prep_owner = fields.Selection(
        selection=[
            ('amazon', 'Amazon'),
            ('seller', 'Seller'),
        ],
        string='Prep Owner',
        default='seller',
    )
    label_owner = fields.Selection(
        selection=[
            ('amazon', 'Amazon'),
            ('seller', 'Seller'),
        ],
        string='Label Owner',
        default='seller',
    )
    prep_instruction_ids = fields.Many2many(
        'amazon.fba.prep.instruction',
        string='Prep Instructions',
    )
    prep_notes = fields.Text(
        string='Prep Notes',
    )
    
    # Condition
    condition = fields.Selection(
        selection=[
            ('new', 'New'),
            ('renewed', 'Renewed'),
            ('used_like_new', 'Used - Like New'),
            ('used_very_good', 'Used - Very Good'),
            ('used_good', 'Used - Good'),
            ('used_acceptable', 'Used - Acceptable'),
            ('collectible_like_new', 'Collectible - Like New'),
            ('collectible_very_good', 'Collectible - Very Good'),
            ('collectible_good', 'Collectible - Good'),
            ('collectible_acceptable', 'Collectible - Acceptable'),
        ],
        string='Condition',
        default='new',
    )
    
    # Expiration (for perishables)
    expiration_date = fields.Date(
        string='Expiration Date',
    )
    manufacture_date = fields.Date(
        string='Manufacture Date',
    )
    
    # Hazmat
    is_hazmat = fields.Boolean(
        string='Hazmat',
        default=False,
    )
    hazmat_type = fields.Selection(
        selection=[
            ('none', 'None'),
            ('limited_quantity', 'Limited Quantity'),
            ('standard', 'Standard Hazmat'),
        ],
        string='Hazmat Type',
        default='none',
    )
    
    # Notes
    notes = fields.Text(
        string='Notes',
    )
    amazon_notes = fields.Text(
        string='Amazon Notes',
        readonly=True,
    )
    
    # -------------------------------------------------------------------------
    # COMPUTES
    # -------------------------------------------------------------------------
    
    @api.depends('product_id', 'product_id.name')
    def _compute_product_info(self):
        for item in self:
            item.product_name = item.product_id.display_name if item.product_id else ''
    
    @api.depends('quantity', 'quantity_in_case')
    def _compute_case_count(self):
        for item in self:
            if item.quantity_in_case > 0:
                item.case_count = item.quantity // item.quantity_in_case
            else:
                item.case_count = 0
    
    @api.depends('quantity', 'received_quantity')
    def _compute_quantity_difference(self):
        for item in self:
            item.quantity_difference = item.received_quantity - item.quantity
    
    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------
    
    @api.constrains('quantity')
    def _check_quantity(self):
        for item in self:
            if item.quantity <= 0:
                raise ValidationError(_('Quantity must be greater than zero.'))
    
    @api.constrains('quantity', 'quantity_in_case')
    def _check_case_packing(self):
        for item in self:
            if item.quantity_in_case > 0:
                if item.quantity % item.quantity_in_case != 0:
                    raise ValidationError(_(
                        'For case-packed products, total quantity (%s) '
                        'must be divisible by units per case (%s).',
                        item.quantity, item.quantity_in_case
                    ))
    
    @api.constrains('expiration_date')
    def _check_expiration_date(self):
        for item in self:
            if item.expiration_date:
                if item.expiration_date < fields.Date.today():
                    raise ValidationError(_(
                        'Expiration date cannot be in the past.'
                    ))
    
    _sql_constraints = [
        (
            'shipment_sku_unique',
            'UNIQUE(shipment_id, amazon_sku)',
            'Each SKU can only appear once per shipment!'
        ),
    ]
    
    # -------------------------------------------------------------------------
    # ONCHANGE
    # -------------------------------------------------------------------------
    
    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Auto-fill Amazon SKU and other details from product."""
        if self.product_id:
            # Try to get SKU from amazon.product.listing if exists
            listing = self.env['amazon.product.listing'].search([
                ('product_id', '=', self.product_id.id),
                ('marketplace_id', '=', self.marketplace_id.id),
            ], limit=1)
            
            if listing:
                self.amazon_sku = listing.seller_sku
                self.amazon_asin = listing.asin
                self.amazon_fnsku = listing.fnsku
            else:
                # Fallback to product default_code
                self.amazon_sku = self.product_id.default_code or ''
            
            # Check for hazmat
            if hasattr(self.product_id, 'is_hazmat'):
                self.is_hazmat = self.product_id.is_hazmat
    
    # -------------------------------------------------------------------------
    # METHODS
    # -------------------------------------------------------------------------
    
    def _get_prep_details(self):
        """Get prep details for Amazon SP-API."""
        self.ensure_one()
        prep_list = []
        
        for prep in self.prep_instruction_ids:
            prep_list.append({
                'PrepInstruction': prep.code,
                'PrepOwner': self.prep_owner.upper() if self.prep_owner else 'SELLER',
            })
        
        return prep_list
    
    def action_view_product(self):
        """Open the product form view."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Product'),
            'res_model': 'product.product',
            'res_id': self.product_id.id,
            'view_mode': 'form',
        }
    
    def action_view_listing(self):
        """Open the Amazon listing for this product."""
        self.ensure_one()
        listing = self.env['amazon.product.listing'].search([
            ('product_id', '=', self.product_id.id),
            ('marketplace_id', '=', self.marketplace_id.id),
        ], limit=1)
        
        if listing:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Amazon Listing'),
                'res_model': 'amazon.product.listing',
                'res_id': listing.id,
                'view_mode': 'form',
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Listing'),
                    'message': _('No Amazon listing found for this product.'),
                    'type': 'warning',
                }
            }


class AmazonFBAPrepInstruction(models.Model):
    """
    Amazon FBA Prep Instruction.
    
    Master data for FBA prep instructions (e.g., Polybagging, Bubble wrap).
    """
    _name = 'amazon.fba.prep.instruction'
    _description = 'Amazon FBA Prep Instruction'
    _order = 'name'

    name = fields.Char(
        string='Name',
        required=True,
        translate=True,
    )
    code = fields.Char(
        string='Amazon Code',
        required=True,
        help='The prep instruction code used by Amazon SP-API.',
    )
    description = fields.Text(
        string='Description',
        translate=True,
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    
    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Prep instruction code must be unique!'),
    ]
