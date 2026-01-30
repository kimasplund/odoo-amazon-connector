# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    """Extend sale.order with Amazon order integration."""
    _inherit = 'sale.order'

    # ══════════════════════════════════════════════════════════════════════════
    # AMAZON INTEGRATION FIELDS
    # ══════════════════════════════════════════════════════════════════════════
    
    amazon_order_id = fields.Many2one(
        comodel_name='amazon.order',
        string='Amazon Order',
        ondelete='set null',
        index=True,
        copy=False,
        help="Linked Amazon order record"
    )
    amazon_order_ref = fields.Char(
        string='Amazon Order Ref',
        index=True,
        copy=False,
        help="Amazon Order ID (e.g., 302-1234567-1234567)"
    )
    is_amazon_order = fields.Boolean(
        string='Is Amazon Order',
        compute='_compute_is_amazon_order',
        store=True,
    )
    amazon_marketplace_id = fields.Many2one(
        comodel_name='amazon.marketplace',
        string='Amazon Marketplace',
        related='amazon_order_id.marketplace_id',
        store=True,
        readonly=True,
    )
    amazon_account_id = fields.Many2one(
        comodel_name='amazon.account',
        string='Amazon Account',
        related='amazon_order_id.account_id',
        store=True,
        readonly=True,
    )
    amazon_fulfillment_channel = fields.Selection(
        selection=[
            ('MFN', 'Merchant Fulfilled (FBM)'),
            ('AFN', 'Amazon Fulfilled (FBA)'),
        ],
        string='Amazon Fulfillment',
        related='amazon_order_id.fulfillment_channel',
        store=True,
        readonly=True,
    )
    amazon_order_status = fields.Selection(
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
        string='Amazon Status',
        related='amazon_order_id.order_status',
        store=True,
        readonly=True,
    )
    amazon_is_prime = fields.Boolean(
        string='Amazon Prime',
        related='amazon_order_id.is_prime',
        store=True,
        readonly=True,
    )
    amazon_is_business = fields.Boolean(
        string='Amazon Business',
        related='amazon_order_id.is_business_order',
        store=True,
        readonly=True,
    )
    amazon_is_fba = fields.Boolean(
        string='FBA Order',
        related='amazon_order_id.is_fba',
        store=True,
        readonly=True,
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # AMAZON SHIPPING TRACKING
    # ══════════════════════════════════════════════════════════════════════════
    
    amazon_carrier_code = fields.Char(
        string='Amazon Carrier Code',
        help="Carrier code for Amazon (e.g., DHL, UPS)"
    )
    amazon_carrier_name = fields.Char(
        string='Amazon Carrier Name',
    )
    amazon_tracking_number = fields.Char(
        string='Amazon Tracking Number',
    )
    amazon_ship_date = fields.Datetime(
        string='Amazon Ship Date',
        help="Date when shipment was confirmed to Amazon"
    )
    amazon_shipment_confirmed = fields.Boolean(
        string='Shipment Confirmed',
        default=False,
        help="True if shipment has been confirmed with Amazon"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # EU VAT FIELDS (from Amazon order)
    # ══════════════════════════════════════════════════════════════════════════
    
    amazon_ioss_number = fields.Char(
        string='IOSS Number',
        related='amazon_order_id.ioss_number',
        readonly=True,
        help="Import One-Stop Shop VAT number"
    )
    amazon_is_ioss = fields.Boolean(
        string='IOSS Order',
        related='amazon_order_id.is_ioss_order',
        readonly=True,
    )
    amazon_buyer_vat = fields.Char(
        string='Buyer VAT',
        related='amazon_order_id.buyer_tax_registration_id',
        readonly=True,
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # COMPUTE METHODS
    # ══════════════════════════════════════════════════════════════════════════
    
    @api.depends('amazon_order_id', 'amazon_order_ref')
    def _compute_is_amazon_order(self):
        for order in self:
            order.is_amazon_order = bool(order.amazon_order_id or order.amazon_order_ref)
    
    # ══════════════════════════════════════════════════════════════════════════
    # AMAZON SHIPMENT CONFIRMATION
    # ══════════════════════════════════════════════════════════════════════════
    
    def action_amazon_confirm_shipment(self):
        """Open wizard to confirm shipment with Amazon."""
        self.ensure_one()
        if not self.amazon_order_id:
            raise UserError(_("This is not an Amazon order."))
        if self.amazon_is_fba:
            raise UserError(_("FBA orders are shipped by Amazon."))
        if self.amazon_shipment_confirmed:
            raise UserError(_("Shipment already confirmed with Amazon."))
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Confirm Amazon Shipment'),
            'res_model': 'amazon.shipment.confirm.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sale_order_id': self.id,
                'default_amazon_order_id': self.amazon_order_id.id,
            },
        }
    
    def amazon_confirm_shipment(self, carrier_code, carrier_name, tracking_number):
        """Confirm shipment with Amazon SP-API.
        
        Args:
            carrier_code: Amazon carrier code (e.g., 'DHL', 'UPS')
            carrier_name: Carrier display name
            tracking_number: Shipping tracking number
        """
        self.ensure_one()
        
        if not self.amazon_order_id:
            raise UserError(_("This is not an Amazon order."))
        
        # Call SP-API to confirm shipment
        account = self.amazon_order_id.account_id
        
        try:
            account._confirm_shipment(
                order_id=self.amazon_order_ref,
                carrier_code=carrier_code,
                tracking_number=tracking_number,
            )
            
            # Update local records
            self.write({
                'amazon_carrier_code': carrier_code,
                'amazon_carrier_name': carrier_name,
                'amazon_tracking_number': tracking_number,
                'amazon_ship_date': fields.Datetime.now(),
                'amazon_shipment_confirmed': True,
            })
            
            # Update Amazon order status
            self.amazon_order_id.write({
                'order_status': 'shipped',
                'number_of_items_shipped': sum(
                    self.amazon_order_id.order_line_ids.mapped('quantity_ordered')
                ),
                'number_of_items_unshipped': 0,
            })
            
            _logger.info(
                "Confirmed Amazon shipment for order %s: %s/%s",
                self.amazon_order_ref, carrier_code, tracking_number
            )
            
        except Exception as e:
            _logger.exception(
                "Failed to confirm Amazon shipment for order %s",
                self.amazon_order_ref
            )
            raise UserError(_(
                "Failed to confirm shipment with Amazon: %s"
            ) % str(e)) from e
    
    # ══════════════════════════════════════════════════════════════════════════
    # SYNC FROM AMAZON
    # ══════════════════════════════════════════════════════════════════════════
    
    def action_sync_amazon_order(self):
        """Refresh order data from Amazon."""
        self.ensure_one()
        if not self.amazon_order_id:
            raise UserError(_("This is not an Amazon order."))
        
        self.amazon_order_id.action_sync_from_amazon()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Amazon Sync"),
                'message': _("Order data refreshed from Amazon."),
                'type': 'success',
                'sticky': False,
            }
        }
    
    # ══════════════════════════════════════════════════════════════════════════
    # VIEW ACTIONS
    # ══════════════════════════════════════════════════════════════════════════
    
    def action_view_amazon_order(self):
        """Open linked Amazon order."""
        self.ensure_one()
        if not self.amazon_order_id:
            raise UserError(_("No Amazon order linked."))
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.order',
            'res_id': self.amazon_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    # ══════════════════════════════════════════════════════════════════════════
    # OVERRIDE STANDARD ACTIONS
    # ══════════════════════════════════════════════════════════════════════════
    
    def action_confirm(self):
        """Override to handle Amazon order specifics."""
        res = super().action_confirm()
        
        for order in self.filtered('is_amazon_order'):
            # For FBA orders, no additional processing needed
            if order.amazon_is_fba:
                _logger.info(
                    "Confirmed FBA Amazon order %s - fulfillment by Amazon",
                    order.amazon_order_ref
                )
            else:
                # FBM orders - prepare for shipping
                _logger.info(
                    "Confirmed FBM Amazon order %s - ready for fulfillment",
                    order.amazon_order_ref
                )
        
        return res
    
    def _action_cancel(self):
        """Override to handle Amazon order cancellation."""
        amazon_orders = self.filtered('is_amazon_order')
        
        for order in amazon_orders:
            if order.amazon_shipment_confirmed:
                raise UserError(_(
                    "Cannot cancel order %s - shipment already confirmed with Amazon. "
                    "Process a return instead."
                ) % order.name)
        
        return super()._action_cancel()


class SaleOrderLine(models.Model):
    """Extend sale.order.line with Amazon order line link."""
    _inherit = 'sale.order.line'

    amazon_order_line_id = fields.Many2one(
        comodel_name='amazon.order.line',
        string='Amazon Order Line',
        ondelete='set null',
        copy=False,
    )
    amazon_asin = fields.Char(
        string='ASIN',
        related='amazon_order_line_id.asin',
        readonly=True,
    )
    amazon_sku = fields.Char(
        string='Amazon SKU',
        related='amazon_order_line_id.seller_sku',
        readonly=True,
    )
    amazon_fees = fields.Monetary(
        string='Amazon Fees',
        related='amazon_order_line_id.total_fees',
        readonly=True,
    )
    amazon_net_proceeds = fields.Monetary(
        string='Net Proceeds',
        related='amazon_order_line_id.net_proceeds',
        readonly=True,
    )
