# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmazonFee(models.Model):
    """
    Amazon Fee Tracking Model.
    
    Centralizes all Amazon fee data for analysis and reporting:
    - FBA fulfillment fees
    - Referral fees (commissions)
    - Storage fees
    - Advertising costs
    - Closing fees
    - Other platform fees
    
    Fees can be linked to orders/products for profitability analysis.
    """
    _name = 'amazon.fee'
    _description = 'Amazon Fee'
    _order = 'date desc, id desc'
    
    # ==========================================
    # SELECTION VALUES
    # ==========================================
    
    FEE_TYPES = [
        # Fulfillment (FBA)
        ('fba_fulfillment', 'FBA Fulfillment'),
        ('fba_pick_pack', 'FBA Pick & Pack'),
        ('fba_weight', 'FBA Weight-Based'),
        ('fba_per_order', 'FBA Per Order'),
        ('fba_inbound', 'FBA Inbound Transportation'),
        ('fba_removal', 'FBA Removal'),
        ('fba_disposal', 'FBA Disposal'),
        ('fba_defect', 'FBA Inbound Defect'),
        
        # Storage
        ('storage_monthly', 'Monthly Storage'),
        ('storage_long_term', 'Long-Term Storage'),
        ('storage_overage', 'Storage Overage'),
        
        # Referral / Commission
        ('referral', 'Referral Fee'),
        ('referral_refund', 'Refund Referral'),
        
        # Closing
        ('closing_variable', 'Variable Closing'),
        ('closing_fixed', 'Fixed Closing'),
        
        # Shipping
        ('shipping', 'Shipping'),
        ('shipping_chargeback', 'Shipping Chargeback'),
        
        # Advertising
        ('advertising_sp', 'Sponsored Products'),
        ('advertising_sb', 'Sponsored Brands'),
        ('advertising_sd', 'Sponsored Display'),
        ('advertising_other', 'Other Advertising'),
        
        # Other
        ('subscription', 'Subscription'),
        ('coupon', 'Coupon Redemption'),
        ('service', 'Service Fee'),
        ('other', 'Other'),
    ]
    
    FEE_CATEGORIES = [
        ('fulfillment', 'Fulfillment'),
        ('storage', 'Storage'),
        ('referral', 'Referral'),
        ('closing', 'Closing'),
        ('shipping', 'Shipping'),
        ('advertising', 'Advertising'),
        ('subscription', 'Subscription'),
        ('other', 'Other'),
    ]
    
    # ==========================================
    # FIELDS
    # ==========================================
    
    name = fields.Char(
        string='Description',
        required=True,
    )
    fee_type = fields.Selection(
        selection=FEE_TYPES,
        string='Fee Type',
        required=True,
        index=True,
    )
    category = fields.Selection(
        selection=FEE_CATEGORIES,
        string='Category',
        compute='_compute_category',
        store=True,
        index=True,
    )
    
    # Relationships
    account_id = fields.Many2one(
        'amazon.account',
        string='Amazon Account',
        required=True,
        ondelete='cascade',
        index=True,
    )
    marketplace_id = fields.Many2one(
        'amazon.marketplace',
        string='Marketplace',
        ondelete='restrict',
    )
    amazon_order_id = fields.Many2one(
        'amazon.order',
        string='Order',
        ondelete='set null',
        index=True,
    )
    amazon_order_line_id = fields.Many2one(
        'amazon.order.line',
        string='Order Line',
        ondelete='set null',
        help='Specific order line this fee applies to',
    )
    settlement_line_id = fields.Many2one(
        'amazon.settlement.line',
        string='Settlement Line',
        ondelete='set null',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        ondelete='set null',
        index=True,
    )
    
    # Item identifiers
    sku = fields.Char(
        string='SKU',
        index=True,
    )
    asin = fields.Char(
        string='ASIN',
        index=True,
    )
    fnsku = fields.Char(
        string='FNSKU',
        help='Fulfillment Network SKU (FBA)',
    )
    
    # Quantity (for per-unit fees)
    quantity = fields.Integer(
        string='Quantity',
        default=1,
    )
    
    # Financial
    amount = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
        required=True,
        help='Fee amount (usually negative/expense)',
    )
    amount_per_unit = fields.Monetary(
        string='Per Unit',
        currency_field='currency_id',
        compute='_compute_per_unit',
        store=True,
        help='Fee amount per unit',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    
    # Dates
    date = fields.Date(
        string='Date',
        required=True,
        index=True,
        default=fields.Date.today,
    )
    posted_datetime = fields.Datetime(
        string='Posted Date/Time',
    )
    
    # Reference
    amazon_reference = fields.Char(
        string='Amazon Reference',
        help='Amazon transaction/adjustment ID',
    )
    
    # Weight/dimensions (for weight-based fees)
    weight = fields.Float(
        string='Weight (kg)',
        digits='Stock Weight',
    )
    dimension_length = fields.Float(
        string='Length (cm)',
    )
    dimension_width = fields.Float(
        string='Width (cm)',
    )
    dimension_height = fields.Float(
        string='Height (cm)',
    )
    size_tier = fields.Char(
        string='Size Tier',
        help='Amazon size tier classification',
    )
    
    # Notes
    notes = fields.Text(
        string='Notes',
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    
    active = fields.Boolean(default=True)
    
    # ==========================================
    # COMPUTE METHODS
    # ==========================================
    
    @api.depends('fee_type')
    def _compute_category(self):
        """Map fee type to category."""
        type_to_category = {
            'fba_fulfillment': 'fulfillment',
            'fba_pick_pack': 'fulfillment',
            'fba_weight': 'fulfillment',
            'fba_per_order': 'fulfillment',
            'fba_inbound': 'fulfillment',
            'fba_removal': 'fulfillment',
            'fba_disposal': 'fulfillment',
            'fba_defect': 'fulfillment',
            'storage_monthly': 'storage',
            'storage_long_term': 'storage',
            'storage_overage': 'storage',
            'referral': 'referral',
            'referral_refund': 'referral',
            'closing_variable': 'closing',
            'closing_fixed': 'closing',
            'shipping': 'shipping',
            'shipping_chargeback': 'shipping',
            'advertising_sp': 'advertising',
            'advertising_sb': 'advertising',
            'advertising_sd': 'advertising',
            'advertising_other': 'advertising',
            'subscription': 'subscription',
            'coupon': 'other',
            'service': 'other',
            'other': 'other',
        }
        
        for record in self:
            record.category = type_to_category.get(record.fee_type, 'other')
    
    @api.depends('amount', 'quantity')
    def _compute_per_unit(self):
        for record in self:
            if record.quantity and record.quantity > 0:
                record.amount_per_unit = record.amount / record.quantity
            else:
                record.amount_per_unit = record.amount
    
    # ==========================================
    # BUSINESS METHODS
    # ==========================================
    
    @api.model
    def create_from_settlement_line(self, line):
        """
        Create fee record from settlement line.
        
        Args:
            line: amazon.settlement.line record
            
        Returns:
            amazon.fee record
        """
        if not line.is_fee:
            return self.env['amazon.fee']
        
        fee_type = self._map_amount_type_to_fee_type(line.amount_type)
        
        fee = self.create({
            'name': line.name or line.amount_description or dict(self.FEE_TYPES).get(fee_type, 'Fee'),
            'fee_type': fee_type,
            'account_id': line.settlement_id.account_id.id,
            'marketplace_id': line.settlement_id.marketplace_id.id,
            'amazon_order_id': line.amazon_order_id.id if line.amazon_order_id else False,
            'amazon_order_line_id': line.amazon_order_line_id.id if line.amazon_order_line_id else False,
            'settlement_line_id': line.id,
            'product_id': line.product_id.id if line.product_id else False,
            'sku': line.sku,
            'asin': line.asin,
            'quantity': line.quantity or 1,
            'amount': line.amount,
            'currency_id': line.currency_id.id,
            'date': (line.posted_date.date() if line.posted_date 
                    else line.settlement_id.deposit_date 
                    or fields.Date.today()),
            'posted_datetime': line.posted_date,
            'amazon_reference': line.merchant_adjustment_id,
        })
        
        # Link back to settlement line
        line.fee_id = fee.id
        
        return fee

    @api.model
    def create_from_settlement_lines(self, lines):
        """
        Batch create fee records from settlement lines.

        Args:
            lines: amazon.settlement.line recordset

        Returns:
            amazon.fee recordset
        """
        lines = lines.filtered('is_fee')
        if not lines:
            return self.env['amazon.fee']

        fees_vals = []
        for line in lines:
            fee_type = self._map_amount_type_to_fee_type(line.amount_type)

            fees_vals.append({
                'name': line.name or line.amount_description or dict(self.FEE_TYPES).get(fee_type, 'Fee'),
                'fee_type': fee_type,
                'account_id': line.settlement_id.account_id.id,
                'marketplace_id': line.settlement_id.marketplace_id.id,
                'amazon_order_id': line.amazon_order_id.id if line.amazon_order_id else False,
                'amazon_order_line_id': line.amazon_order_line_id.id if line.amazon_order_line_id else False,
                'settlement_line_id': line.id,
                'product_id': line.product_id.id if line.product_id else False,
                'sku': line.sku,
                'asin': line.asin,
                'quantity': line.quantity or 1,
                'amount': line.amount,
                'currency_id': line.currency_id.id,
                'date': (line.posted_date.date() if line.posted_date
                        else line.settlement_id.deposit_date
                        or fields.Date.today()),
                'posted_datetime': line.posted_date,
                'amazon_reference': line.merchant_adjustment_id,
            })

        fees = self.create(fees_vals)

        # Link back to settlement lines
        for line, fee in zip(lines, fees):
            line.fee_id = fee.id

        return fees
    
    @api.model
    def _map_amount_type_to_fee_type(self, amount_type):
        """Map Amazon amount type to fee type."""
        mapping = {
            'FBAPerUnitFulfillmentFee': 'fba_fulfillment',
            'FBAPickAndPackFee': 'fba_pick_pack',
            'FBAWeightBasedFee': 'fba_weight',
            'FBAPerOrderFulfillmentFee': 'fba_per_order',
            'FBAInboundTransportationFee': 'fba_inbound',
            'FBARemovalFee': 'fba_removal',
            'FBADisposalFee': 'fba_disposal',
            'FBAInboundDefectFee': 'fba_defect',
            'FBAStorageFee': 'storage_monthly',
            'FBALongTermStorageFee': 'storage_long_term',
            'Commission': 'referral',
            'RefundCommission': 'referral_refund',
            'VariableClosingFee': 'closing_variable',
            'FixedClosingFee': 'closing_fixed',
            'ShippingChargeback': 'shipping_chargeback',
            'ItemFees': 'referral',  # Usually referral fees
            'Fee': 'other',
            'CouponRedemptionFee': 'coupon',
        }
        
        return mapping.get(amount_type, 'other')
    
    @api.model
    def create_from_fba_estimate(self, order_line, fee_data):
        """
        Create estimated fee record from FBA fee preview.
        
        Used when calculating expected fees before actual settlement.
        
        Args:
            order_line: amazon.order.line record
            fee_data: dict with fee information
        """
        return self.create({
            'name': fee_data.get('name', 'Estimated FBA Fee'),
            'fee_type': fee_data.get('fee_type', 'fba_fulfillment'),
            'account_id': order_line.order_id.account_id.id,
            'marketplace_id': order_line.order_id.marketplace_id.id,
            'amazon_order_id': order_line.order_id.id,
            'amazon_order_line_id': order_line.id,
            'product_id': order_line.product_id.id,
            'sku': order_line.sku,
            'asin': order_line.asin,
            'quantity': order_line.quantity,
            'amount': fee_data.get('amount', 0),
            'currency_id': fee_data.get('currency_id', order_line.currency_id.id),
            'date': fields.Date.today(),
            'notes': 'Estimated fee (not from settlement)',
        })
    
    def link_to_order_line(self):
        """
        Attempt to link fee to order line based on SKU matching.
        """
        fees = self.filtered(lambda f: f.amazon_order_id and f.sku and not f.amazon_order_line_id)
        if not fees:
            return

        # Pre-fetch lines for all related orders to avoid N+1 queries
        # Map: (order_id, seller_sku) -> line_id
        orders = fees.mapped('amazon_order_id')
        # Note: amazon.order.line uses 'seller_sku', not 'sku'
        lines = self.env['amazon.order.line'].search([
            ('order_id', 'in', orders.ids),
            ('seller_sku', '!=', False),
        ])

        # Build map favoring the first line found (standard Odoo sort order)
        line_map = {}
        for line in lines:
            key = (line.order_id.id, line.seller_sku)
            if key not in line_map:
                line_map[key] = line.id

        # Group fees by target line to batch writes
        fees_by_line = {}
        for fee in fees:
            key = (fee.amazon_order_id.id, fee.sku)
            if key in line_map:
                line_id = line_map[key]
                if line_id not in fees_by_line:
                    fees_by_line[line_id] = self.env['amazon.fee']
                fees_by_line[line_id] |= fee

        # Batch update
        for line_id, fees_subset in fees_by_line.items():
            fees_subset.write({'amazon_order_line_id': line_id})
    
    # ==========================================
    # REPORTING METHODS
    # ==========================================
    
    @api.model
    def get_fee_summary(self, account_id=None, date_from=None, date_to=None, 
                        marketplace_id=None, group_by='category'):
        """
        Get fee summary for reporting.
        
        Args:
            account_id: Filter by Amazon account
            date_from: Start date
            date_to: End date
            marketplace_id: Filter by marketplace
            group_by: 'category', 'fee_type', 'product', 'month'
            
        Returns:
            List of dicts with fee totals
        """
        domain = [('active', '=', True)]
        
        if account_id:
            domain.append(('account_id', '=', account_id))
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        if marketplace_id:
            domain.append(('marketplace_id', '=', marketplace_id))
        
        fees = self.search(domain)
        
        if group_by == 'category':
            return self._group_fees_by_category(fees)
        elif group_by == 'fee_type':
            return self._group_fees_by_type(fees)
        elif group_by == 'product':
            return self._group_fees_by_product(fees)
        elif group_by == 'month':
            return self._group_fees_by_month(fees)
        else:
            return [{
                'total': sum(fees.mapped('amount')),
                'count': len(fees),
            }]
    
    def _group_fees_by_category(self, fees):
        """Group fees by category."""
        result = {}
        for fee in fees:
            cat = fee.category or 'other'
            if cat not in result:
                result[cat] = {'category': cat, 'amount': 0, 'count': 0}
            result[cat]['amount'] += fee.amount
            result[cat]['count'] += 1
        return list(result.values())
    
    def _group_fees_by_type(self, fees):
        """Group fees by fee type."""
        result = {}
        for fee in fees:
            ft = fee.fee_type
            if ft not in result:
                result[ft] = {
                    'fee_type': ft, 
                    'fee_type_label': dict(self.FEE_TYPES).get(ft, ft),
                    'amount': 0, 
                    'count': 0
                }
            result[ft]['amount'] += fee.amount
            result[ft]['count'] += 1
        return list(result.values())
    
    def _group_fees_by_product(self, fees):
        """Group fees by product."""
        result = {}
        for fee in fees:
            key = fee.product_id.id if fee.product_id else 0
            if key not in result:
                result[key] = {
                    'product_id': key,
                    'product_name': fee.product_id.display_name if fee.product_id else 'Unknown',
                    'sku': fee.sku,
                    'amount': 0,
                    'count': 0
                }
            result[key]['amount'] += fee.amount
            result[key]['count'] += 1
        return sorted(result.values(), key=lambda x: x['amount'])
    
    def _group_fees_by_month(self, fees):
        """Group fees by month."""
        result = {}
        for fee in fees:
            month_key = fee.date.strftime('%Y-%m') if fee.date else 'Unknown'
            if month_key not in result:
                result[month_key] = {'month': month_key, 'amount': 0, 'count': 0}
            result[month_key]['amount'] += fee.amount
            result[month_key]['count'] += 1
        return sorted(result.values(), key=lambda x: x['month'])
    
    @api.model
    def get_product_fee_breakdown(self, product_id, date_from=None, date_to=None):
        """
        Get detailed fee breakdown for a specific product.
        
        Useful for product profitability analysis.
        """
        domain = [
            ('product_id', '=', product_id),
            ('active', '=', True),
        ]
        
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        
        fees = self.search(domain)
        
        breakdown = {
            'total_fees': sum(fees.mapped('amount')),
            'total_quantity': sum(fees.mapped('quantity')),
            'by_category': self._group_fees_by_category(fees),
            'by_type': self._group_fees_by_type(fees),
            'average_per_unit': 0,
        }
        
        if breakdown['total_quantity'] > 0:
            breakdown['average_per_unit'] = (
                breakdown['total_fees'] / breakdown['total_quantity']
            )
        
        return breakdown
    
    # ==========================================
    # IMPORT FROM API
    # ==========================================
    
    @api.model
    def import_storage_fees(self, account, fee_data):
        """
        Import storage fee data from SP-API reports.
        
        Storage fees come from separate reports (FBA Inventory reports).
        """
        fees = self.env['amazon.fee']
        
        for item in fee_data:
            # Find product by FNSKU or ASIN
            product = self._find_product_by_identifiers(
                account, 
                fnsku=item.get('fnsku'),
                asin=item.get('asin'),
                sku=item.get('sku'),
            )
            
            # Determine storage fee type
            is_long_term = item.get('isLongTermStorage', False)
            fee_type = 'storage_long_term' if is_long_term else 'storage_monthly'
            
            fee = self.create({
                'name': f"Storage Fee - {item.get('asin', 'Unknown')}",
                'fee_type': fee_type,
                'account_id': account.id,
                'marketplace_id': self._get_marketplace_from_item(account, item),
                'product_id': product.id if product else False,
                'sku': item.get('sku'),
                'asin': item.get('asin'),
                'fnsku': item.get('fnsku'),
                'quantity': item.get('quantity', 0),
                'amount': -abs(float(item.get('estimatedFee', 0) or item.get('fee', 0))),
                'currency_id': self._get_currency(item.get('currency', 'EUR')).id,
                'date': self._parse_date(item.get('date')) or fields.Date.today(),
                'size_tier': item.get('productSizeTier'),
                'dimension_length': item.get('longestSide'),
                'dimension_width': item.get('medianSide'),
                'dimension_height': item.get('shortestSide'),
                'weight': item.get('weight'),
            })
            fees |= fee
        
        return fees
    
    def _find_product_by_identifiers(self, account, fnsku=None, asin=None, sku=None):
        """Find product by various Amazon identifiers."""
        AmazonProduct = self.env.get('amazon.product.listing')
        if not AmazonProduct:
            return None
        
        listing = None
        
        if sku:
            listing = AmazonProduct.search([
                ('seller_sku', '=', sku),
                ('account_id', '=', account.id),
            ], limit=1)
        
        if not listing and asin:
            listing = AmazonProduct.search([
                ('asin', '=', asin),
                ('account_id', '=', account.id),
            ], limit=1)
        
        if not listing and fnsku:
            listing = AmazonProduct.search([
                ('fnsku', '=', fnsku),
                ('account_id', '=', account.id),
            ], limit=1)
        
        return listing.product_id if listing else None
    
    def _get_marketplace_from_item(self, account, item):
        """Get marketplace from item data."""
        mp_id = item.get('marketplaceId')
        if mp_id:
            marketplace = self.env['amazon.marketplace'].search([
                ('marketplace_id', '=', mp_id)
            ], limit=1)
            if marketplace:
                return marketplace.id
        
        # Fall back to account's primary marketplace
        if account.marketplace_ids:
            return account.marketplace_ids[0].id
        
        return False
    
    def _get_currency(self, currency_code):
        """Get currency by code."""
        return self.env['res.currency'].search([
            ('name', '=', currency_code)
        ], limit=1) or self.env.company.currency_id
    
    def _parse_date(self, date_str):
        """Parse date string."""
        if not date_str:
            return None
        
        if isinstance(date_str, datetime):
            return date_str.date()
        
        formats = ['%Y-%m-%d', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S%z']
        for fmt in formats:
            try:
                return datetime.strptime(str(date_str)[:19], fmt[:19]).date()
            except ValueError:
                continue
        
        return None
