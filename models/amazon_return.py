# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AmazonReturn(models.Model):
    """Amazon Returns and Refunds.
    
    Handles:
    - Customer-initiated returns (from Returns Reports)
    - Seller-initiated refunds
    - Partial refunds
    - Replacement orders
    - Reimbursements (FBA lost/damaged)
    """
    _name = 'amazon.return'
    _description = 'Amazon Return/Refund'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'return_date desc, id desc'
    _rec_name = 'display_name'

    # ══════════════════════════════════════════════════════════════════════════
    # CORE IDENTIFIERS
    # ══════════════════════════════════════════════════════════════════════════
    
    return_id = fields.Char(
        string='Return ID',
        index=True,
        copy=False,
        help="Amazon Return Authorization ID"
    )
    refund_id = fields.Char(
        string='Refund ID',
        index=True,
        copy=False,
        help="Amazon Refund ID from settlement"
    )
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # RELATIONSHIPS
    # ══════════════════════════════════════════════════════════════════════════
    
    order_id = fields.Many2one(
        comodel_name='amazon.order',
        string='Amazon Order',
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True,
    )
    order_line_id = fields.Many2one(
        comodel_name='amazon.order.line',
        string='Order Line',
        ondelete='set null',
        domain="[('order_id', '=', order_id)]",
    )
    account_id = fields.Many2one(
        comodel_name='amazon.account',
        string='Amazon Account',
        related='order_id.account_id',
        store=True,
    )
    marketplace_id = fields.Many2one(
        comodel_name='amazon.marketplace',
        string='Marketplace',
        related='order_id.marketplace_id',
        store=True,
    )
    sale_order_id = fields.Many2one(
        comodel_name='sale.order',
        string='Sale Order',
        related='order_id.sale_order_id',
        store=True,
    )
    stock_return_picking_id = fields.Many2one(
        comodel_name='stock.picking',
        string='Return Picking',
        ondelete='set null',
        help="Odoo stock return picking"
    )
    credit_note_id = fields.Many2one(
        comodel_name='account.move',
        string='Credit Note',
        ondelete='set null',
        domain="[('move_type', '=', 'out_refund')]",
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='order_id.currency_id',
        store=True,
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # TYPE & STATUS
    # ══════════════════════════════════════════════════════════════════════════
    
    return_type = fields.Selection(
        selection=[
            ('return', 'Customer Return'),
            ('refund', 'Refund Only'),
            ('replacement', 'Replacement'),
            ('reimbursement', 'FBA Reimbursement'),
            ('chargeback', 'Chargeback'),
            ('reversal', 'Chargeback Reversal'),
            ('goodwill', 'Goodwill Refund'),
        ],
        string='Type',
        required=True,
        default='return',
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('authorized', 'Authorized'),
            ('received', 'Received'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
            ('closed', 'Closed'),
        ],
        string='Status',
        default='pending',
        required=True,
        tracking=True,
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # DATES
    # ══════════════════════════════════════════════════════════════════════════
    
    return_date = fields.Datetime(
        string='Return Date',
        required=True,
        default=fields.Datetime.now,
        tracking=True,
        help="Date when return was requested/created"
    )
    authorization_date = fields.Datetime(
        string='Authorization Date',
        help="Date when return was authorized"
    )
    received_date = fields.Datetime(
        string='Received Date',
        help="Date when returned item was received"
    )
    refund_date = fields.Datetime(
        string='Refund Date',
        help="Date when refund was processed"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # PRODUCT INFO
    # ══════════════════════════════════════════════════════════════════════════
    
    asin = fields.Char(
        string='ASIN',
        help="Product ASIN"
    )
    seller_sku = fields.Char(
        string='Seller SKU',
    )
    product_name = fields.Char(
        string='Product Name',
    )
    quantity = fields.Integer(
        string='Quantity',
        default=1,
        required=True,
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # RETURN REASON
    # ══════════════════════════════════════════════════════════════════════════
    
    return_reason_code = fields.Selection(
        selection=[
            # Customer reasons
            ('BUYER_CHANGED_MIND', 'Buyer Changed Mind'),
            ('DAMAGED_BY_CARRIER', 'Damaged by Carrier'),
            ('DAMAGED_BY_FC', 'Damaged by Fulfillment Center'),
            ('DEFECTIVE', 'Defective'),
            ('DIFFERENT_FROM_WEBSITE', 'Different from Website'),
            ('EXPIRED', 'Item Expired'),
            ('FOUND_BETTER_PRICE', 'Found Better Price'),
            ('ITEM_TOO_LARGE', 'Item Too Large'),
            ('ITEM_TOO_SMALL', 'Item Too Small'),
            ('LATE_DELIVERY', 'Late Delivery'),
            ('MISSED_DELIVERY', 'Missed Delivery'),
            ('MISSING_PARTS', 'Missing Parts/Accessories'),
            ('NOT_AS_DESCRIBED', 'Not As Described'),
            ('NOT_COMPATIBLE', 'Not Compatible'),
            ('NOT_NEEDED', 'No Longer Needed'),
            ('ORDERED_WRONG', 'Ordered Wrong Item'),
            ('QUALITY_ISSUE', 'Quality Not as Expected'),
            ('UNAUTHORIZED_PURCHASE', 'Unauthorized Purchase'),
            ('UNWANTED_GIFT', 'Unwanted Gift'),
            ('WRONG_ITEM_SENT', 'Wrong Item Sent'),
            
            # FBA reimbursement reasons
            ('LOST_INBOUND', 'Lost in Inbound Shipment'),
            ('LOST_WAREHOUSE', 'Lost in Warehouse'),
            ('DAMAGED_WAREHOUSE', 'Damaged in Warehouse'),
            ('DISPOSED', 'Disposed by Amazon'),
            ('CUSTOMER_DAMAGED', 'Returned Damaged by Customer'),
            ('CARRIER_DAMAGED', 'Carrier Damaged'),
            
            # Other
            ('OTHER', 'Other'),
        ],
        string='Return Reason',
        help="Reason code for return/refund"
    )
    return_reason_text = fields.Text(
        string='Reason Details',
        help="Customer-provided reason text"
    )
    is_customer_fault = fields.Boolean(
        string='Customer Fault',
        compute='_compute_is_customer_fault',
        store=True,
        help="True if return is due to customer fault (affects restocking)"
    )
    detailed_disposition = fields.Selection(
        selection=[
            ('SELLABLE', 'Sellable'),
            ('CUSTOMER_DAMAGED', 'Customer Damaged'),
            ('CARRIER_DAMAGED', 'Carrier Damaged'),
            ('WAREHOUSE_DAMAGED', 'Warehouse Damaged'),
            ('DEFECTIVE', 'Defective'),
            ('EXPIRED', 'Expired'),
            ('DISPOSED', 'Disposed'),
        ],
        string='Item Disposition',
        help="Condition of returned item"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # REFUND AMOUNTS
    # ══════════════════════════════════════════════════════════════════════════
    
    # What was originally charged
    original_item_price = fields.Monetary(
        string='Original Item Price',
        currency_field='currency_id',
    )
    original_shipping = fields.Monetary(
        string='Original Shipping',
        currency_field='currency_id',
    )
    original_tax = fields.Monetary(
        string='Original Tax',
        currency_field='currency_id',
    )
    
    # What is being refunded
    refund_item_price = fields.Monetary(
        string='Item Refund',
        currency_field='currency_id',
        help="Amount refunded for item price"
    )
    refund_shipping = fields.Monetary(
        string='Shipping Refund',
        currency_field='currency_id',
        help="Amount refunded for shipping"
    )
    refund_tax = fields.Monetary(
        string='Tax Refund',
        currency_field='currency_id',
        help="Tax amount refunded"
    )
    refund_gift_wrap = fields.Monetary(
        string='Gift Wrap Refund',
        currency_field='currency_id',
    )
    refund_promo = fields.Monetary(
        string='Promotion Adjustment',
        currency_field='currency_id',
        help="Adjustment for original promotions"
    )
    refund_total = fields.Monetary(
        string='Total Refund',
        currency_field='currency_id',
        compute='_compute_refund_total',
        store=True,
    )
    
    # Restocking fee (deducted from refund)
    restocking_fee = fields.Monetary(
        string='Restocking Fee',
        currency_field='currency_id',
        help="Fee charged for customer-fault returns"
    )
    
    # Net amount (what seller actually loses/gains)
    net_refund = fields.Monetary(
        string='Net Refund',
        currency_field='currency_id',
        compute='_compute_net_refund',
        store=True,
        help="Total refund minus restocking fee"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # FEE ADJUSTMENTS (credits back to seller)
    # ══════════════════════════════════════════════════════════════════════════
    
    fee_referral_refund = fields.Monetary(
        string='Referral Fee Refund',
        currency_field='currency_id',
        help="Referral fee credited back for refunded item"
    )
    fee_fba_refund = fields.Monetary(
        string='FBA Fee Refund',
        currency_field='currency_id',
        help="FBA fee credited back for refunded item"
    )
    fee_other_refund = fields.Monetary(
        string='Other Fee Refund',
        currency_field='currency_id',
    )
    total_fee_refund = fields.Monetary(
        string='Total Fee Refund',
        currency_field='currency_id',
        compute='_compute_total_fee_refund',
        store=True,
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # FBA REIMBURSEMENT SPECIFIC
    # ══════════════════════════════════════════════════════════════════════════
    
    reimbursement_id = fields.Char(
        string='Reimbursement ID',
        help="Amazon FBA reimbursement case ID"
    )
    reimbursement_amount = fields.Monetary(
        string='Reimbursement Amount',
        currency_field='currency_id',
        help="Amount Amazon reimbursed for lost/damaged FBA inventory"
    )
    fnsku = fields.Char(
        string='FNSKU',
        help="Fulfillment Network SKU for FBA items"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # REPLACEMENT ORDER
    # ══════════════════════════════════════════════════════════════════════════
    
    is_replacement_created = fields.Boolean(
        string='Replacement Created',
        default=False,
    )
    replacement_order_id = fields.Char(
        string='Replacement Order ID',
        help="Amazon Order ID of the replacement order"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # LABELS & TRACKING
    # ══════════════════════════════════════════════════════════════════════════
    
    return_label_url = fields.Char(
        string='Return Label URL',
    )
    return_tracking_number = fields.Char(
        string='Return Tracking',
    )
    return_carrier = fields.Char(
        string='Return Carrier',
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # NOTES
    # ══════════════════════════════════════════════════════════════════════════
    
    internal_notes = fields.Text(
        string='Internal Notes',
    )
    customer_comments = fields.Text(
        string='Customer Comments',
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
    )
    last_sync_date = fields.Datetime(
        string='Last Sync Date',
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # COMPUTED FIELDS
    # ══════════════════════════════════════════════════════════════════════════
    
    amazon_order_ref = fields.Char(
        string='Amazon Order Ref',
        related='order_id.amazon_order_id',
        store=True,
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # SQL CONSTRAINTS
    # ══════════════════════════════════════════════════════════════════════════
    
    _sql_constraints = [
        (
            'return_id_uniq',
            'UNIQUE(return_id)',
            'Return ID must be unique!'
        ),
        (
            'refund_id_uniq',
            'UNIQUE(refund_id)',
            'Refund ID must be unique!'
        ),
    ]
    
    # ══════════════════════════════════════════════════════════════════════════
    # COMPUTE METHODS
    # ══════════════════════════════════════════════════════════════════════════
    
    @api.depends('return_id', 'refund_id', 'order_id.amazon_order_id', 'return_type')
    def _compute_display_name(self):
        for record in self:
            type_labels = {
                'return': 'Return',
                'refund': 'Refund',
                'replacement': 'Replacement',
                'reimbursement': 'Reimbursement',
                'chargeback': 'Chargeback',
                'reversal': 'Reversal',
                'goodwill': 'Goodwill',
            }
            type_label = type_labels.get(record.return_type, 'Return')
            identifier = record.return_id or record.refund_id or record.order_id.amazon_order_id
            record.display_name = f"{type_label}: {identifier}"
    
    @api.depends('return_reason_code')
    def _compute_is_customer_fault(self):
        """Determine if return is customer's fault (affects restocking fee)."""
        customer_fault_reasons = {
            'BUYER_CHANGED_MIND',
            'FOUND_BETTER_PRICE',
            'ITEM_TOO_LARGE',
            'ITEM_TOO_SMALL',
            'NOT_NEEDED',
            'ORDERED_WRONG',
            'UNWANTED_GIFT',
        }
        for record in self:
            record.is_customer_fault = record.return_reason_code in customer_fault_reasons
    
    @api.depends('refund_item_price', 'refund_shipping', 'refund_tax',
                 'refund_gift_wrap', 'refund_promo')
    def _compute_refund_total(self):
        for record in self:
            record.refund_total = sum([
                record.refund_item_price or 0,
                record.refund_shipping or 0,
                record.refund_tax or 0,
                record.refund_gift_wrap or 0,
                record.refund_promo or 0,
            ])
    
    @api.depends('refund_total', 'restocking_fee')
    def _compute_net_refund(self):
        for record in self:
            record.net_refund = (record.refund_total or 0) - (record.restocking_fee or 0)
    
    @api.depends('fee_referral_refund', 'fee_fba_refund', 'fee_other_refund')
    def _compute_total_fee_refund(self):
        for record in self:
            record.total_fee_refund = sum([
                record.fee_referral_refund or 0,
                record.fee_fba_refund or 0,
                record.fee_other_refund or 0,
            ])
    
    # ══════════════════════════════════════════════════════════════════════════
    # STATE TRANSITIONS
    # ══════════════════════════════════════════════════════════════════════════
    
    def action_authorize(self):
        """Authorize the return."""
        for record in self.filtered(lambda r: r.state == 'pending'):
            record.write({
                'state': 'authorized',
                'authorization_date': fields.Datetime.now(),
            })
    
    def action_receive(self):
        """Mark return as received."""
        for record in self.filtered(lambda r: r.state == 'authorized'):
            record.write({
                'state': 'received',
                'received_date': fields.Datetime.now(),
            })
    
    def action_complete(self):
        """Complete the return/refund."""
        for record in self.filtered(lambda r: r.state in ('authorized', 'received')):
            record.write({
                'state': 'completed',
                'refund_date': fields.Datetime.now(),
            })
    
    def action_cancel(self):
        """Cancel the return."""
        for record in self.filtered(lambda r: r.state in ('pending', 'authorized')):
            record.write({'state': 'cancelled'})
    
    def action_close(self):
        """Close the return (final state)."""
        for record in self.filtered(lambda r: r.state == 'completed'):
            record.write({'state': 'closed'})
    
    # ══════════════════════════════════════════════════════════════════════════
    # BUSINESS ACTIONS
    # ══════════════════════════════════════════════════════════════════════════
    
    def action_create_credit_note(self):
        """Create credit note for this return."""
        self.ensure_one()
        
        if self.credit_note_id:
            raise UserError(_("Credit note already exists for this return."))
        
        if not self.sale_order_id:
            raise UserError(_("No linked sale order to create credit note from."))
        
        invoice = self.sale_order_id.invoice_ids.filtered(
            lambda i: i.move_type == 'out_invoice' and i.state == 'posted'
        )[:1]
        
        if not invoice:
            raise UserError(_("No posted invoice found for the sale order."))
        
        # Create reversal (credit note)
        move_reversal = self.env['account.move.reversal'].with_context(
            active_model='account.move',
            active_ids=invoice.ids,
        ).create({
            'reason': f"Amazon Return: {self.display_name}",
            'refund_method': 'refund',
            'journal_id': invoice.journal_id.id,
        })
        
        reversal = move_reversal.reverse_moves()
        credit_note = self.env['account.move'].browse(reversal.get('res_id'))
        
        self.credit_note_id = credit_note
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': credit_note.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    def action_create_stock_return(self):
        """Create stock return picking."""
        self.ensure_one()
        
        if self.stock_return_picking_id:
            raise UserError(_("Stock return already exists."))
        
        if not self.sale_order_id:
            raise UserError(_("No linked sale order."))
        
        # Find the delivery picking
        delivery = self.sale_order_id.picking_ids.filtered(
            lambda p: p.picking_type_code == 'outgoing' and p.state == 'done'
        )[:1]
        
        if not delivery:
            raise UserError(_("No completed delivery found to return."))
        
        # Open return wizard
        return {
            'type': 'ir.actions.act_window',
            'name': _('Return'),
            'res_model': 'stock.return.picking',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'stock.picking',
                'active_id': delivery.id,
                'amazon_return_id': self.id,
            },
        }
    
    def action_view_credit_note(self):
        """View credit note."""
        self.ensure_one()
        if not self.credit_note_id:
            raise UserError(_("No credit note linked."))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.credit_note_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    def action_view_stock_return(self):
        """View stock return picking."""
        self.ensure_one()
        if not self.stock_return_picking_id:
            raise UserError(_("No stock return linked."))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.stock_return_picking_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    def action_issue_refund_amazon(self):
        """Issue refund via Amazon SP-API."""
        self.ensure_one()
        
        if self.state == 'completed':
            raise UserError(_("Refund already processed."))
        
        # TODO: Implement SP-API refund
        raise NotImplementedError("SP-API refund not yet implemented")
    
    # ══════════════════════════════════════════════════════════════════════════
    # IMPORT FROM REPORTS
    # ══════════════════════════════════════════════════════════════════════════
    
    @api.model
    def create_from_return_report(self, account, return_data):
        """Create return record from Amazon Returns Report.
        
        Args:
            account: amazon.account record
            return_data: dict from Returns Report
            
        Returns:
            amazon.return record
        """
        # Find the order
        amazon_order_id = return_data.get('order-id') or return_data.get('AmazonOrderId')
        order = self.env['amazon.order'].search([
            ('amazon_order_id', '=', amazon_order_id),
            ('account_id', '=', account.id),
        ], limit=1)
        
        if not order:
            _logger.warning("Order not found for return: %s", amazon_order_id)
            return False
        
        return_id = return_data.get('return-request-id') or return_data.get('ReturnRequestId')
        
        existing = self.search([('return_id', '=', return_id)], limit=1)
        
        vals = self._prepare_vals_from_report(order, return_data)
        
        if existing:
            existing.write(vals)
            return existing
        else:
            return self.create(vals)
    
    @api.model
    def _prepare_vals_from_report(self, order, data):
        """Transform return report data to model values."""
        
        # Map reason codes
        reason_map = {
            'BUYER_CHANGED_MIND': 'BUYER_CHANGED_MIND',
            'DAMAGED_BY_CARRIER': 'DAMAGED_BY_CARRIER',
            'DEFECTIVE': 'DEFECTIVE',
            'NOT_AS_DESCRIBED': 'NOT_AS_DESCRIBED',
            'WRONG_ITEM_SENT': 'WRONG_ITEM_SENT',
            # Add more mappings as needed
        }
        
        reason_code = data.get('reason') or data.get('ReturnReason', '')
        mapped_reason = reason_map.get(reason_code.upper().replace(' ', '_'), 'OTHER')
        
        vals = {
            'order_id': order.id,
            'return_id': data.get('return-request-id') or data.get('ReturnRequestId'),
            'return_type': 'return',
            'state': 'authorized',
            'return_date': self._parse_datetime(
                data.get('return-request-date') or data.get('ReturnRequestDate')
            ) or fields.Datetime.now(),
            'asin': data.get('asin') or data.get('ASIN'),
            'seller_sku': data.get('sku') or data.get('SellerSKU'),
            'product_name': data.get('product-name') or data.get('Title'),
            'quantity': int(data.get('quantity', 1)),
            'return_reason_code': mapped_reason,
            'return_reason_text': data.get('reason') or data.get('ReturnReason'),
            'customer_comments': data.get('buyer-comments') or data.get('BuyerComments'),
            'detailed_disposition': data.get('detailed-disposition'),
            'sync_status': 'synced',
            'last_sync_date': fields.Datetime.now(),
        }
        
        # Handle refund amounts if present
        if 'refund-amount' in data or 'RefundAmount' in data:
            vals['refund_item_price'] = float(
                data.get('refund-amount') or data.get('RefundAmount', 0)
            )
        
        return vals
    
    @api.model
    def create_from_settlement(self, account, refund_data, order):
        """Create refund record from settlement report.
        
        Args:
            account: amazon.account record
            refund_data: dict from settlement report
            order: amazon.order record
            
        Returns:
            amazon.return record
        """
        refund_id = refund_data.get('transaction-id') or refund_data.get('TransactionId')
        
        existing = self.search([('refund_id', '=', refund_id)], limit=1)
        if existing:
            return existing
        
        vals = {
            'order_id': order.id,
            'refund_id': refund_id,
            'return_type': 'refund',
            'state': 'completed',
            'refund_date': self._parse_datetime(
                refund_data.get('posted-date') or refund_data.get('PostedDate')
            ),
            'asin': refund_data.get('asin') or refund_data.get('ASIN'),
            'seller_sku': refund_data.get('sku') or refund_data.get('SellerSKU'),
            'quantity': int(refund_data.get('quantity-purchased', 1)),
            'refund_item_price': abs(float(refund_data.get('item-price', 0))),
            'refund_shipping': abs(float(refund_data.get('shipping-price', 0))),
            'refund_tax': abs(float(refund_data.get('item-tax', 0))),
            'fee_referral_refund': abs(float(refund_data.get('selling-fees', 0))),
            'fee_fba_refund': abs(float(refund_data.get('fba-fees', 0))),
            'sync_status': 'synced',
            'last_sync_date': fields.Datetime.now(),
        }
        
        return self.create(vals)
    
    @staticmethod
    def _parse_datetime(value):
        """Parse datetime string."""
        if not value:
            return False
        try:
            if isinstance(value, str):
                value = value.replace('Z', '+00:00')
                return datetime.fromisoformat(value.replace('+00:00', ''))
            return value
        except (ValueError, TypeError):
            return False
