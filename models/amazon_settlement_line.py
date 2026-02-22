# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

import logging
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmazonSettlementLine(models.Model):
    """
    Amazon Settlement Line Model.
    
    Individual line items from Amazon settlement reports including:
    - Order payments (product price, shipping, gift wrap)
    - Refunds and chargebacks
    - FBA fees (fulfillment, storage, removal)
    - Referral fees
    - Advertising costs
    - Promotions
    - Other adjustments
    """
    _name = 'amazon.settlement.line'
    _description = 'Amazon Settlement Line'
    _order = 'posted_date desc, id desc'
    
    # ==========================================
    # SELECTION VALUES
    # ==========================================
    
    TRANSACTION_TYPES = [
        ('Order', 'Order'),
        ('Refund', 'Refund'),
        ('ServiceFee', 'Service Fee'),
        ('Adjustment', 'Adjustment'),
        ('Transfer', 'Transfer'),
        ('FBAInventoryFee', 'FBA Inventory Fee'),
        ('ChargeBack', 'Chargeback'),
        ('Liquidation', 'Liquidation'),
        ('CouponRedemption', 'Coupon Redemption'),
        ('Other', 'Other'),
    ]
    
    AMOUNT_TYPES = [
        # Order-related
        ('ItemPrice', 'Item Price'),
        ('Principal', 'Principal'),
        ('Shipping', 'Shipping'),
        ('ShippingTax', 'Shipping Tax'),
        ('GiftWrap', 'Gift Wrap'),
        ('GiftWrapTax', 'Gift Wrap Tax'),
        ('ItemTax', 'Item Tax'),
        
        # Fees
        ('ItemFees', 'Item Fees'),
        ('Fee', 'Fee'),
        ('Commission', 'Commission'),
        ('RefundCommission', 'Refund Commission'),
        ('FBAPerUnitFulfillmentFee', 'FBA Per Unit Fee'),
        ('FBAWeightBasedFee', 'FBA Weight Fee'),
        ('FBAPickAndPackFee', 'FBA Pick & Pack'),
        ('FBAPerOrderFulfillmentFee', 'FBA Per Order Fee'),
        ('ShippingChargeback', 'Shipping Chargeback'),
        ('VariableClosingFee', 'Variable Closing Fee'),
        ('FixedClosingFee', 'Fixed Closing Fee'),
        ('FBAInboundTransportationFee', 'FBA Inbound Transport'),
        ('FBAStorageFee', 'FBA Storage Fee'),
        ('FBALongTermStorageFee', 'FBA Long-Term Storage'),
        ('FBARemovalFee', 'FBA Removal Fee'),
        ('FBADisposalFee', 'FBA Disposal Fee'),
        ('FBAInboundDefectFee', 'FBA Inbound Defect Fee'),
        
        # Promotions
        ('Promotion', 'Promotion'),
        ('PromotionalRebates', 'Promotional Rebates'),
        ('CouponRedemptionFee', 'Coupon Fee'),
        
        # Adjustments
        ('Adjustment', 'Adjustment'),
        ('RetroCharge', 'Retro Charge'),
        ('REVERSAL_REIMBURSEMENT', 'Reversal Reimbursement'),
        ('COMPENSATED_CLAWBACK', 'Compensated Clawback'),
        ('Reimbursement', 'Reimbursement'),
        
        # Other
        ('Other', 'Other'),
        ('Unknown', 'Unknown'),
    ]
    
    FEE_CATEGORIES = [
        ('fulfillment', 'Fulfillment'),
        ('referral', 'Referral'),
        ('storage', 'Storage'),
        ('advertising', 'Advertising'),
        ('closing', 'Closing'),
        ('subscription', 'Subscription'),
        ('other', 'Other'),
    ]
    
    # ==========================================
    # FIELDS
    # ==========================================
    
    name = fields.Char(
        string='Description',
        compute='_compute_name',
        store=True,
    )
    settlement_id = fields.Many2one(
        'amazon.settlement',
        string='Settlement',
        required=True,
        ondelete='cascade',
        index=True,
    )
    account_id = fields.Many2one(
        'amazon.account',
        string='Amazon Account',
        related='settlement_id.account_id',
        store=True,
        readonly=True,
    )
    marketplace_id = fields.Many2one(
        'amazon.marketplace',
        string='Marketplace',
        related='settlement_id.marketplace_id',
        store=True,
        readonly=True,
    )
    
    # Order reference
    order_id_text = fields.Char(
        string='Amazon Order ID',
        index=True,
        help='Amazon Order ID from settlement report',
    )
    amazon_order_id = fields.Many2one(
        'amazon.order',
        string='Linked Order',
        ondelete='set null',
        index=True,
        help='Linked Amazon Order in Odoo',
    )
    amazon_order_line_id = fields.Many2one(
        'amazon.order.line',
        string='Order Line',
        ondelete='set null',
        help='Linked Amazon Order Line (for per-item fees)',
    )
    
    # Item reference
    sku = fields.Char(
        string='SKU',
        index=True,
    )
    asin = fields.Char(
        string='ASIN',
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        compute='_compute_product_id',
        store=True,
    )
    quantity = fields.Integer(
        string='Quantity',
        default=0,
    )
    
    # Transaction details
    transaction_type = fields.Selection(
        selection=TRANSACTION_TYPES,
        string='Transaction Type',
        required=True,
        index=True,
    )
    amount_type = fields.Selection(
        selection=AMOUNT_TYPES,
        string='Amount Type',
        required=True,
        index=True,
    )
    amount_description = fields.Char(
        string='Amount Description',
        help='Original description from Amazon',
    )
    
    # Financial
    amount = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
        required=True,
        help='Positive = credit, Negative = debit',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    
    # Fee categorization
    fee_category = fields.Selection(
        selection=FEE_CATEGORIES,
        string='Fee Category',
        compute='_compute_fee_category',
        store=True,
    )
    is_fee = fields.Boolean(
        string='Is Fee',
        compute='_compute_is_fee',
        store=True,
    )
    
    # Dates
    posted_date = fields.Datetime(
        string='Posted Date',
        help='When the transaction was posted by Amazon',
    )
    
    # Metadata
    merchant_adjustment_id = fields.Char(
        string='Adjustment ID',
        help='Amazon adjustment/merchant ID',
    )
    fulfillment_channel = fields.Selection([
        ('MFN', 'Merchant Fulfilled'),
        ('AFN', 'Amazon Fulfilled (FBA)'),
    ], string='Fulfillment Channel')
    
    # Related fee record (for detailed fee tracking)
    fee_id = fields.Many2one(
        'amazon.fee',
        string='Fee Record',
        ondelete='set null',
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='settlement_id.company_id',
        store=True,
        readonly=True,
    )
    
    # ==========================================
    # COMPUTE METHODS
    # ==========================================
    
    @api.depends('transaction_type', 'amount_type', 'order_id_text', 'sku')
    def _compute_name(self):
        for record in self:
            parts = []
            if record.transaction_type:
                parts.append(dict(self.TRANSACTION_TYPES).get(
                    record.transaction_type, record.transaction_type
                ))
            if record.amount_type:
                parts.append(dict(self.AMOUNT_TYPES).get(
                    record.amount_type, record.amount_type
                ))
            if record.order_id_text:
                parts.append(f'[{record.order_id_text}]')
            if record.sku:
                parts.append(f'SKU: {record.sku}')
            
            record.name = ' - '.join(parts) if parts else _('Settlement Line')
    
    @api.depends('sku', 'asin', 'settlement_id.account_id')
    def _compute_product_id(self):
        """Link settlement line to product based on SKU or ASIN."""
        AmazonProduct = self.env.get('amazon.product.listing')
        
        for record in self:
            product = None
            
            if not AmazonProduct:
                record.product_id = False
                continue
            
            # Try SKU first
            if record.sku:
                listing = AmazonProduct.search([
                    ('seller_sku', '=', record.sku),
                    ('account_id', '=', record.settlement_id.account_id.id),
                ], limit=1)
                if listing:
                    product = listing.product_id
            
            # Fall back to ASIN
            if not product and record.asin:
                listing = AmazonProduct.search([
                    ('asin', '=', record.asin),
                    ('account_id', '=', record.settlement_id.account_id.id),
                ], limit=1)
                if listing:
                    product = listing.product_id
            
            record.product_id = product
    
    @api.depends('amount_type', 'transaction_type')
    def _compute_fee_category(self):
        """Categorize fees for reporting."""
        fulfillment_types = (
            'FBAPerUnitFulfillmentFee', 'FBAWeightBasedFee', 
            'FBAPickAndPackFee', 'FBAPerOrderFulfillmentFee',
            'FBAInboundTransportationFee', 'ShippingChargeback',
        )
        storage_types = (
            'FBAStorageFee', 'FBALongTermStorageFee',
        )
        referral_types = (
            'Commission', 'RefundCommission',
        )
        closing_types = (
            'VariableClosingFee', 'FixedClosingFee',
        )
        
        for record in self:
            if record.amount_type in fulfillment_types:
                record.fee_category = 'fulfillment'
            elif record.amount_type in storage_types:
                record.fee_category = 'storage'
            elif record.amount_type in referral_types:
                record.fee_category = 'referral'
            elif record.amount_type in closing_types:
                record.fee_category = 'closing'
            elif record.transaction_type == 'ServiceFee':
                record.fee_category = 'other'
            else:
                record.fee_category = False
    
    @api.depends('amount_type', 'transaction_type')
    def _compute_is_fee(self):
        """Determine if this line represents a fee."""
        fee_amount_types = (
            'ItemFees', 'Fee', 'Commission', 'RefundCommission',
            'FBAPerUnitFulfillmentFee', 'FBAWeightBasedFee',
            'FBAPickAndPackFee', 'FBAPerOrderFulfillmentFee',
            'ShippingChargeback', 'VariableClosingFee', 'FixedClosingFee',
            'FBAInboundTransportationFee', 'FBAStorageFee',
            'FBALongTermStorageFee', 'FBARemovalFee', 'FBADisposalFee',
            'FBAInboundDefectFee', 'CouponRedemptionFee',
        )
        
        for record in self:
            record.is_fee = (
                record.amount_type in fee_amount_types or
                record.transaction_type in ('ServiceFee', 'FBAInventoryFee')
            )
    
    # ==========================================
    # IMPORT METHODS
    # ==========================================
    
    @api.model
    def import_lines(self, settlement, rows):
        """
        Import settlement line items from Amazon report data.
        
        Args:
            settlement: amazon.settlement record
            rows: list of dicts with settlement row data
            
        Returns:
            Created amazon.settlement.line records
        """
        lines_vals = []
        for row in rows:
            try:
                line_data = self._prepare_line_data(settlement, row)
                if line_data:
                    lines_vals.append(line_data)
            except Exception as e:
                _logger.exception('Failed to prepare settlement line data: %s', e)
                continue

        lines = self.create(lines_vals)

        # Create fee records for fee lines
        # Optimization: use batch creation if possible, otherwise loop
        fee_lines = lines.filtered('is_fee')
        if fee_lines:
            # Check if batch method exists (future-proofing)
            if hasattr(self.env['amazon.fee'], 'create_from_settlement_lines'):
                self.env['amazon.fee'].create_from_settlement_lines(fee_lines)
            else:
                for line in fee_lines:
                    try:
                        self.env['amazon.fee'].create_from_settlement_line(line)
                    except Exception as e:
                        _logger.exception('Failed to create fee for line %s: %s', line.id, e)

        return lines
    
    @api.model
    def _prepare_line_data(self, settlement, row):
        """
        Prepare line data from Amazon settlement row.
        
        Expected row format (from SP-API settlement report):
        {
            'orderAmazonOrderId': '123-456-789',
            'sku': 'PROD-001',
            'asin': 'B00XXXXX',
            'quantity': 1,
            'transactionType': 'Order',
            'amountType': 'ItemPrice',
            'amountDescription': 'Principal',
            'amount': {'currencyCode': 'EUR', 'currencyAmount': '19.99'},
            'postedDateTime': '2024-01-15T10:30:00Z',
            'fulfillmentId': 'AFN',
            'merchantAdjustmentId': None,
        }
        """
        # Get currency
        amount_data = row.get('amount', {})
        currency_code = amount_data.get('currencyCode', 'EUR')
        currency = self.env['res.currency'].search([
            ('name', '=', currency_code)
        ], limit=1)
        
        if not currency:
            _logger.warning('Currency %s not found, using settlement currency', currency_code)
            currency = settlement.currency_id
        
        # Parse amount
        try:
            amount = float(amount_data.get('currencyAmount', 0))
        except (ValueError, TypeError):
            amount = 0.0
        
        # Skip zero-amount lines (optional)
        # if amount == 0:
        #     return None
        
        # Parse transaction type
        transaction_type = row.get('transactionType', 'Other')
        if transaction_type not in dict(self.TRANSACTION_TYPES):
            transaction_type = 'Other'
        
        # Parse amount type
        amount_type = row.get('amountType', 'Unknown')
        if amount_type not in dict(self.AMOUNT_TYPES):
            # Try amountDescription as fallback
            amount_type = row.get('amountDescription', 'Unknown')
            if amount_type not in dict(self.AMOUNT_TYPES):
                amount_type = 'Other'
        
        # Parse posted date
        posted_date = self._parse_date(row.get('postedDateTime'))
        
        # Parse fulfillment channel
        fulfillment_id = row.get('fulfillmentId', '')
        if fulfillment_id.upper() in ('AFN', 'AMAZON'):
            fulfillment_channel = 'AFN'
        elif fulfillment_id.upper() in ('MFN', 'MERCHANT'):
            fulfillment_channel = 'MFN'
        else:
            fulfillment_channel = None
        
        return {
            'settlement_id': settlement.id,
            'order_id_text': row.get('amazonOrderId') or row.get('orderAmazonOrderId'),
            'sku': row.get('sku'),
            'asin': row.get('asin'),
            'quantity': int(row.get('quantity', 0) or 0),
            'transaction_type': transaction_type,
            'amount_type': amount_type,
            'amount_description': row.get('amountDescription'),
            'amount': amount,
            'currency_id': currency.id,
            'posted_date': posted_date,
            'fulfillment_channel': fulfillment_channel,
            'merchant_adjustment_id': row.get('merchantAdjustmentId'),
        }
    
    @api.model
    def _parse_date(self, date_str):
        """Parse Amazon date string."""
        if not date_str:
            return None
        
        formats = [
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%dT%H:%M:%S.%fZ',
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%d',
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str.replace('+00:00', 'Z'), fmt)
            except ValueError:
                continue
        
        return None
    
    # ==========================================
    # BUSINESS METHODS
    # ==========================================
    
    def action_view_order(self):
        """Open the linked Amazon order."""
        self.ensure_one()
        if not self.amazon_order_id:
            raise UserError(_('No order linked to this settlement line.'))
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.order',
            'res_id': self.amazon_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    def action_link_order(self):
        """Manually link to an Amazon order."""
        self.ensure_one()
        if not self.order_id_text:
            raise UserError(_('No order ID on this settlement line.'))
        
        # Search for matching order
        order = self.env['amazon.order'].search([
            ('amazon_order_id', '=', self.order_id_text),
        ], limit=1)
        
        if order:
            self.amazon_order_id = order.id
        else:
            raise UserError(_(
                'No Amazon order found with ID: %s'
            ) % self.order_id_text)
        
        return True
    
    def get_fee_breakdown(self):
        """
        Get fee breakdown for reporting.
        
        Returns dict with fee totals by category.
        """
        self.ensure_one()
        
        if not self.is_fee:
            return {}
        
        return {
            'category': self.fee_category,
            'type': self.amount_type,
            'description': self.amount_description,
            'amount': self.amount,
            'currency': self.currency_id.name,
        }
