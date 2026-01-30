# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    """
    Extend account.move for Amazon integration.
    
    Links journal entries to Amazon orders, settlements, and
    provides Amazon-specific invoice functionality.
    """
    _inherit = 'account.move'
    
    # ==========================================
    # AMAZON LINK FIELDS
    # ==========================================
    
    amazon_order_id = fields.Many2one(
        'amazon.order',
        string='Amazon Order',
        ondelete='set null',
        index=True,
        help='Linked Amazon order for this invoice',
    )
    amazon_settlement_id = fields.Many2one(
        'amazon.settlement',
        string='Amazon Settlement',
        ondelete='set null',
        index=True,
        help='Linked Amazon settlement for this journal entry',
    )
    
    # Amazon-specific references
    amazon_order_ref = fields.Char(
        string='Amazon Order ID',
        help='Amazon Order ID for reference',
    )
    amazon_invoice_number = fields.Char(
        string='Amazon Invoice Number',
        help='Invoice number as shown on Amazon',
    )
    
    # Amazon invoice flags
    is_amazon_invoice = fields.Boolean(
        string='Is Amazon Invoice',
        compute='_compute_is_amazon',
        store=True,
    )
    is_amazon_settlement_entry = fields.Boolean(
        string='Is Settlement Entry',
        compute='_compute_is_amazon',
        store=True,
    )
    
    # VAT handling for EU sales
    amazon_vat_country_id = fields.Many2one(
        'res.country',
        string='VAT Country',
        help='Country where VAT is due (for EU distance selling)',
    )
    amazon_vat_rate = fields.Float(
        string='VAT Rate (%)',
        help='VAT rate applied by Amazon',
    )
    amazon_vat_calculation_service = fields.Boolean(
        string='VCS Enabled',
        help='Invoice uses Amazon VAT Calculation Service',
    )
    
    # B2B fields
    amazon_is_business_order = fields.Boolean(
        string='Business Order',
        help='B2B order through Amazon Business',
    )
    amazon_buyer_vat = fields.Char(
        string='Buyer VAT Number',
        help='Business buyer VAT number',
    )
    
    # ==========================================
    # COMPUTE METHODS
    # ==========================================
    
    @api.depends('amazon_order_id', 'amazon_settlement_id')
    def _compute_is_amazon(self):
        for record in self:
            record.is_amazon_invoice = bool(record.amazon_order_id)
            record.is_amazon_settlement_entry = bool(record.amazon_settlement_id)
    
    # ==========================================
    # OVERRIDE METHODS
    # ==========================================
    
    @api.model_create_multi
    def create(self, vals_list):
        """
        Override to sync Amazon references on creation.
        """
        for vals in vals_list:
            # If linked to Amazon order, set reference
            if vals.get('amazon_order_id') and not vals.get('amazon_order_ref'):
                order = self.env['amazon.order'].browse(vals['amazon_order_id'])
                if order.exists():
                    vals['amazon_order_ref'] = order.amazon_order_id
        
        return super().create(vals_list)
    
    def _post(self, soft=True):
        """
        Override to handle Amazon-specific post actions.
        """
        res = super()._post(soft=soft)
        
        # Update linked Amazon orders
        for move in self.filtered(lambda m: m.amazon_order_id and m.move_type in ('out_invoice', 'out_refund')):
            move._sync_amazon_order_invoice_status()
        
        return res
    
    def button_cancel(self):
        """
        Override to handle Amazon invoice cancellation.
        """
        res = super().button_cancel()
        
        # Update linked Amazon orders
        for move in self.filtered(lambda m: m.amazon_order_id):
            move._sync_amazon_order_invoice_status()
        
        return res
    
    # ==========================================
    # AMAZON-SPECIFIC METHODS
    # ==========================================
    
    def _sync_amazon_order_invoice_status(self):
        """
        Sync invoice status with Amazon order.
        """
        self.ensure_one()
        
        if not self.amazon_order_id:
            return
        
        order = self.amazon_order_id
        
        # Update order's invoice status based on all linked invoices
        invoices = self.search([
            ('amazon_order_id', '=', order.id),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '!=', 'cancel'),
        ])
        
        if not invoices:
            order.invoice_status = 'to_invoice'
        elif all(inv.payment_state in ('paid', 'in_payment', 'reversed') for inv in invoices):
            order.invoice_status = 'invoiced'
        else:
            order.invoice_status = 'partial'
    
    @api.model
    def create_from_amazon_order(self, amazon_order, invoice_type='out_invoice'):
        """
        Create invoice from Amazon order.
        
        Args:
            amazon_order: amazon.order record
            invoice_type: 'out_invoice' or 'out_refund'
            
        Returns:
            account.move record
        """
        # Validate order
        if not amazon_order.sale_order_id:
            raise UserError(_(
                'Amazon order %s has no linked sale order. '
                'Cannot create invoice.'
            ) % amazon_order.amazon_order_id)
        
        # Get partner
        partner = amazon_order.partner_id
        if not partner:
            raise UserError(_(
                'Amazon order %s has no customer. Cannot create invoice.'
            ) % amazon_order.amazon_order_id)
        
        # Prepare invoice lines
        invoice_lines = []
        for line in amazon_order.order_line_ids:
            invoice_lines.append((0, 0, {
                'product_id': line.product_id.id,
                'name': line.name or line.product_id.display_name,
                'quantity': line.quantity,
                'price_unit': line.unit_price,
                'tax_ids': [(6, 0, line.product_id.taxes_id.ids)],
            }))
        
        # Add shipping line if applicable
        if amazon_order.shipping_price > 0:
            shipping_product = self._get_shipping_product()
            if shipping_product:
                invoice_lines.append((0, 0, {
                    'product_id': shipping_product.id,
                    'name': _('Shipping'),
                    'quantity': 1,
                    'price_unit': amazon_order.shipping_price,
                    'tax_ids': [(6, 0, shipping_product.taxes_id.ids)],
                }))
        
        # Create invoice
        invoice_vals = {
            'move_type': invoice_type,
            'partner_id': partner.id,
            'invoice_date': amazon_order.purchase_date.date() if amazon_order.purchase_date else fields.Date.today(),
            'amazon_order_id': amazon_order.id,
            'amazon_order_ref': amazon_order.amazon_order_id,
            'amazon_is_business_order': amazon_order.is_business_order,
            'amazon_buyer_vat': amazon_order.buyer_tax_registration_id,
            'ref': amazon_order.amazon_order_id,
            'invoice_line_ids': invoice_lines,
            'currency_id': amazon_order.currency_id.id,
        }
        
        # Handle VAT country for EU sales
        if amazon_order.marketplace_id and amazon_order.marketplace_id.country_id:
            invoice_vals['amazon_vat_country_id'] = amazon_order.marketplace_id.country_id.id
        
        invoice = self.create(invoice_vals)
        
        _logger.info(
            'Created invoice %s for Amazon order %s',
            invoice.name, amazon_order.amazon_order_id
        )
        
        return invoice
    
    @api.model
    def create_refund_from_amazon(self, amazon_order, refund_amount, reason=None):
        """
        Create credit note for Amazon refund.
        
        Args:
            amazon_order: amazon.order record
            refund_amount: Amount to refund
            reason: Refund reason
            
        Returns:
            account.move record (credit note)
        """
        # Find original invoice
        original_invoice = self.search([
            ('amazon_order_id', '=', amazon_order.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
        ], limit=1, order='id desc')
        
        if original_invoice:
            # Create reversal
            refund = original_invoice._reverse_moves(
                default_values_list=[{
                    'ref': _('Refund: %s') % amazon_order.amazon_order_id,
                    'amazon_order_id': amazon_order.id,
                }],
                cancel=False
            )
        else:
            # Create standalone credit note
            refund = self.create({
                'move_type': 'out_refund',
                'partner_id': amazon_order.partner_id.id,
                'amazon_order_id': amazon_order.id,
                'amazon_order_ref': amazon_order.amazon_order_id,
                'ref': _('Refund: %s') % amazon_order.amazon_order_id,
                'invoice_line_ids': [(0, 0, {
                    'name': reason or _('Amazon Refund'),
                    'quantity': 1,
                    'price_unit': refund_amount,
                })],
                'currency_id': amazon_order.currency_id.id,
            })
        
        _logger.info(
            'Created refund %s for Amazon order %s',
            refund.name, amazon_order.amazon_order_id
        )
        
        return refund
    
    def _get_shipping_product(self):
        """Get or create shipping product for invoices."""
        # Try to find existing shipping product
        product = self.env['product.product'].search([
            ('default_code', '=', 'AMAZON_SHIPPING'),
        ], limit=1)
        
        if not product:
            # Try by name
            product = self.env['product.product'].search([
                ('name', 'ilike', 'Amazon Shipping'),
            ], limit=1)
        
        if not product:
            # Create shipping product
            product = self.env['product.product'].create({
                'name': 'Amazon Shipping',
                'default_code': 'AMAZON_SHIPPING',
                'type': 'service',
                'sale_ok': False,
                'purchase_ok': False,
                'invoice_policy': 'order',
            })
        
        return product
    
    # ==========================================
    # RECONCILIATION METHODS
    # ==========================================
    
    def reconcile_with_amazon_settlement(self, settlement):
        """
        Reconcile invoice/payment with Amazon settlement.
        
        Links this move to the settlement for tracking.
        """
        self.ensure_one()
        self.amazon_settlement_id = settlement.id
    
    def action_view_amazon_order(self):
        """Open linked Amazon order."""
        self.ensure_one()
        if not self.amazon_order_id:
            raise UserError(_('No Amazon order linked to this invoice.'))
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.order',
            'res_id': self.amazon_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    def action_view_amazon_settlement(self):
        """Open linked Amazon settlement."""
        self.ensure_one()
        if not self.amazon_settlement_id:
            raise UserError(_('No Amazon settlement linked to this entry.'))
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.settlement',
            'res_id': self.amazon_settlement_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    # ==========================================
    # AMAZON VCS (VAT CALCULATION SERVICE)
    # ==========================================
    
    def apply_amazon_vcs_data(self, vcs_data):
        """
        Apply VAT data from Amazon VAT Calculation Service.
        
        VCS provides standardized VAT information for EU invoices.
        
        Args:
            vcs_data: dict with VCS invoice data
        """
        self.ensure_one()
        
        if not vcs_data:
            return
        
        self.write({
            'amazon_vat_calculation_service': True,
            'amazon_invoice_number': vcs_data.get('invoiceNumber'),
            'amazon_vat_rate': vcs_data.get('vatRate'),
        })
        
        # Update VAT country if provided
        if vcs_data.get('vatCountryCode'):
            country = self.env['res.country'].search([
                ('code', '=', vcs_data['vatCountryCode'])
            ], limit=1)
            if country:
                self.amazon_vat_country_id = country.id
        
        # Update partner VAT if provided
        if vcs_data.get('buyerVatNumber') and self.partner_id:
            if not self.partner_id.vat:
                self.partner_id.vat = vcs_data['buyerVatNumber']
            self.amazon_buyer_vat = vcs_data['buyerVatNumber']
    
    # ==========================================
    # REPORTING METHODS
    # ==========================================
    
    @api.model
    def get_amazon_invoice_summary(self, date_from=None, date_to=None, 
                                    account_id=None, marketplace_id=None):
        """
        Get summary of Amazon invoices for reporting.
        
        Returns:
            dict with invoice statistics
        """
        domain = [
            ('is_amazon_invoice', '=', True),
            ('state', '=', 'posted'),
        ]
        
        if date_from:
            domain.append(('invoice_date', '>=', date_from))
        if date_to:
            domain.append(('invoice_date', '<=', date_to))
        if account_id:
            domain.append(('amazon_order_id.account_id', '=', account_id))
        if marketplace_id:
            domain.append(('amazon_order_id.marketplace_id', '=', marketplace_id))
        
        invoices = self.search(domain)
        refunds = invoices.filtered(lambda m: m.move_type == 'out_refund')
        regular = invoices.filtered(lambda m: m.move_type == 'out_invoice')
        
        return {
            'invoice_count': len(regular),
            'invoice_total': sum(regular.mapped('amount_total')),
            'refund_count': len(refunds),
            'refund_total': sum(refunds.mapped('amount_total')),
            'net_total': (
                sum(regular.mapped('amount_total')) - 
                sum(refunds.mapped('amount_total'))
            ),
            'vcs_count': len(invoices.filtered('amazon_vat_calculation_service')),
            'b2b_count': len(invoices.filtered('amazon_is_business_order')),
        }


class AccountMoveLine(models.Model):
    """
    Extend account.move.line for Amazon-specific fields.
    """
    _inherit = 'account.move.line'
    
    amazon_fee_id = fields.Many2one(
        'amazon.fee',
        string='Amazon Fee',
        ondelete='set null',
        help='Linked Amazon fee record',
    )
    amazon_order_line_id = fields.Many2one(
        'amazon.order.line',
        string='Amazon Order Line',
        ondelete='set null',
        help='Linked Amazon order line',
    )
    
    # Fee type for expense categorization
    amazon_fee_type = fields.Selection(
        related='amazon_fee_id.fee_type',
        store=True,
        string='Fee Type',
    )
    amazon_fee_category = fields.Selection(
        related='amazon_fee_id.category',
        store=True,
        string='Fee Category',
    )
