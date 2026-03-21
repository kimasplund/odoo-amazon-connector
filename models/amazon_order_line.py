# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmazonOrderLine(models.Model):
    """Amazon Order Line Item.
    
    Stores individual items from an Amazon order including:
    - Product/SKU information
    - Pricing breakdown (item, shipping, gift wrap)
    - Tax breakdown (item tax, shipping tax, etc.)
    - Amazon fee breakdown (referral, FBA, etc.)
    - Promotion/discount details
    """
    _name = 'amazon.order.line'
    _description = 'Amazon Order Line'
    _order = 'order_id, sequence, id'
    _rec_name = 'display_name'

    # ══════════════════════════════════════════════════════════════════════════
    # CORE IDENTIFIERS
    # ══════════════════════════════════════════════════════════════════════════
    
    order_item_id = fields.Char(
        string='Order Item ID',
        required=True,
        index=True,
        help="Amazon unique identifier for this order item"
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
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
    sale_order_line_id = fields.Many2one(
        comodel_name='sale.order.line',
        string='Sale Order Line',
        ondelete='set null',
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Product',
        ondelete='set null',
        index=True,
    )
    amazon_listing_id = fields.Many2one(
        comodel_name='amazon.product.listing',
        string='Amazon Listing',
        ondelete='set null',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='order_id.currency_id',
        store=True,
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # PRODUCT IDENTIFIERS
    # ══════════════════════════════════════════════════════════════════════════
    
    asin = fields.Char(
        string='ASIN',
        index=True,
        help="Amazon Standard Identification Number"
    )
    seller_sku = fields.Char(
        string='Seller SKU',
        index=True,
        help="Seller-defined Stock Keeping Unit"
    )
    title = fields.Char(
        string='Product Title',
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # QUANTITIES
    # ══════════════════════════════════════════════════════════════════════════
    
    quantity_ordered = fields.Integer(
        string='Qty Ordered',
        default=1,
        required=True,
    )
    quantity_shipped = fields.Integer(
        string='Qty Shipped',
        default=0,
    )
    points_granted_price = fields.Monetary(
        string='Points Value',
        currency_field='currency_id',
        help="Value of Amazon Points granted"
    )
    points_granted_number = fields.Integer(
        string='Points Granted',
        help="Number of Amazon Points granted"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # ITEM PRICING
    # ══════════════════════════════════════════════════════════════════════════
    
    item_price = fields.Monetary(
        string='Item Price',
        currency_field='currency_id',
        help="Total selling price of the item (unit price × quantity)"
    )
    item_price_unit = fields.Monetary(
        string='Unit Price',
        currency_field='currency_id',
        compute='_compute_unit_prices',
        store=True,
        help="Per-unit selling price"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # SHIPPING CHARGES
    # ══════════════════════════════════════════════════════════════════════════
    
    shipping_price = fields.Monetary(
        string='Shipping Price',
        currency_field='currency_id',
        help="Total shipping charge for this item"
    )
    shipping_discount = fields.Monetary(
        string='Shipping Discount',
        currency_field='currency_id',
        help="Shipping discount applied"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # GIFT WRAP
    # ══════════════════════════════════════════════════════════════════════════
    
    gift_wrap_price = fields.Monetary(
        string='Gift Wrap Price',
        currency_field='currency_id',
    )
    gift_message_text = fields.Text(
        string='Gift Message',
    )
    gift_wrap_level = fields.Char(
        string='Gift Wrap Level',
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # PROMOTIONS & DISCOUNTS
    # ══════════════════════════════════════════════════════════════════════════
    
    promotion_discount = fields.Monetary(
        string='Promotion Discount',
        currency_field='currency_id',
        help="Total promotion discount on item price"
    )
    promotion_ids_raw = fields.Char(
        string='Promotion IDs',
        help="Comma-separated list of promotion IDs applied"
    )
    coupon_discount = fields.Monetary(
        string='Coupon Discount',
        currency_field='currency_id',
    )
    cod_fee = fields.Monetary(
        string='COD Fee',
        currency_field='currency_id',
        help="Cash on Delivery fee (Japan)"
    )
    cod_fee_discount = fields.Monetary(
        string='COD Fee Discount',
        currency_field='currency_id',
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # TAX BREAKDOWN
    # ══════════════════════════════════════════════════════════════════════════
    
    item_tax = fields.Monetary(
        string='Item Tax',
        currency_field='currency_id',
        help="Tax collected on item price"
    )
    shipping_tax = fields.Monetary(
        string='Shipping Tax',
        currency_field='currency_id',
    )
    gift_wrap_tax = fields.Monetary(
        string='Gift Wrap Tax',
        currency_field='currency_id',
    )
    promotion_discount_tax = fields.Monetary(
        string='Promotion Tax Adjustment',
        currency_field='currency_id',
    )
    shipping_discount_tax = fields.Monetary(
        string='Shipping Discount Tax',
        currency_field='currency_id',
    )
    total_tax = fields.Monetary(
        string='Total Tax',
        currency_field='currency_id',
        compute='_compute_total_tax',
        store=True,
    )
    
    # Tax collection info
    is_tax_collected_at_source = fields.Boolean(
        string='Tax Collected at Source',
        default=False,
        help="True if marketplace collected and will remit the tax"
    )
    tax_collection_model = fields.Selection(
        selection=[
            ('marketplace_facilitator', 'Marketplace Facilitator'),
            ('seller_liable', 'Seller Liable'),
        ],
        string='Tax Collection Model',
        default='seller_liable',
    )
    tax_rate = fields.Float(
        string='Tax Rate (%)',
        digits=(6, 4),
        help="Applied tax rate as percentage"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # AMAZON FEES BREAKDOWN
    # ══════════════════════════════════════════════════════════════════════════
    
    # These fees are typically received from Settlement Reports, not Order API
    
    fee_referral = fields.Monetary(
        string='Referral Fee',
        currency_field='currency_id',
        help="Amazon referral fee (percentage of sale)"
    )
    fee_fba_fulfillment = fields.Monetary(
        string='FBA Fulfillment Fee',
        currency_field='currency_id',
        help="FBA per-unit fulfillment fee"
    )
    fee_fba_weight_handling = fields.Monetary(
        string='FBA Weight Handling Fee',
        currency_field='currency_id',
    )
    fee_fba_inventory_storage = fields.Monetary(
        string='FBA Storage Fee',
        currency_field='currency_id',
        help="Monthly storage fees"
    )
    fee_variable_closing = fields.Monetary(
        string='Variable Closing Fee',
        currency_field='currency_id',
        help="Media items variable closing fee"
    )
    fee_digital_services = fields.Monetary(
        string='Digital Services Fee',
        currency_field='currency_id',
    )
    fee_subscription = fields.Monetary(
        string='Subscription Fee',
        currency_field='currency_id',
    )
    fee_shipping_chargeback = fields.Monetary(
        string='Shipping Chargeback',
        currency_field='currency_id',
    )
    fee_gift_wrap_chargeback = fields.Monetary(
        string='Gift Wrap Chargeback',
        currency_field='currency_id',
    )
    fee_other = fields.Monetary(
        string='Other Fees',
        currency_field='currency_id',
    )
    total_fees = fields.Monetary(
        string='Total Amazon Fees',
        currency_field='currency_id',
        compute='_compute_total_fees',
        store=True,
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # NET PROCEEDS
    # ══════════════════════════════════════════════════════════════════════════
    
    net_proceeds = fields.Monetary(
        string='Net Proceeds',
        currency_field='currency_id',
        compute='_compute_net_proceeds',
        store=True,
        help="Item price + shipping + gift wrap - fees - promotions"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # FULFILLMENT
    # ══════════════════════════════════════════════════════════════════════════
    
    condition_id = fields.Char(
        string='Condition ID',
        help="Item condition (New, Used, etc.)"
    )
    condition_subtype_id = fields.Char(
        string='Condition Subtype',
        help="More specific condition"
    )
    condition_note = fields.Text(
        string='Condition Note',
    )
    scheduled_delivery_start = fields.Datetime(
        string='Scheduled Delivery Start',
    )
    scheduled_delivery_end = fields.Datetime(
        string='Scheduled Delivery End',
    )
    is_gift = fields.Boolean(
        string='Is Gift',
        default=False,
    )
    is_transparency = fields.Boolean(
        string='Transparency Enabled',
        default=False,
        help="True if item uses Amazon Transparency for serial verification"
    )
    serial_number_required = fields.Boolean(
        string='Serial Number Required',
        default=False,
    )
    ioss_number = fields.Char(
        string='IOSS Number',
        help="Line-level IOSS number for EU imports"
    )
    store_chain_store_id = fields.Char(
        string='Store Chain ID',
        help="Store ID for store pickup orders"
    )
    deemed_reseller_category = fields.Selection(
        selection=[
            ('IOSS', 'IOSS'),
            ('UOSS', 'UOSS'),
        ],
        string='Deemed Reseller Category',
        help="Category for deemed reseller tax collection"
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # STATUS
    # ══════════════════════════════════════════════════════════════════════════
    
    item_status = fields.Selection(
        selection=[
            ('unshipped', 'Unshipped'),
            ('shipped', 'Shipped'),
            ('cancelled', 'Cancelled'),
            ('unfulfillable', 'Unfulfillable'),
        ],
        string='Item Status',
        default='unshipped',
    )
    
    # ══════════════════════════════════════════════════════════════════════════
    # SQL CONSTRAINTS
    # ══════════════════════════════════════════════════════════════════════════
    
    _sql_constraints = [
        (
            'order_item_id_uniq',
            'UNIQUE(order_item_id)',
            'Order Item ID must be unique!'
        ),
    ]
    
    # ══════════════════════════════════════════════════════════════════════════
    # COMPUTE METHODS
    # ══════════════════════════════════════════════════════════════════════════
    
    @api.depends('seller_sku', 'asin', 'title')
    def _compute_display_name(self):
        for line in self:
            parts = []
            if line.seller_sku:
                parts.append(f"[{line.seller_sku}]")
            if line.title:
                # Truncate long titles
                title = line.title[:50] + '...' if len(line.title or '') > 50 else line.title
                parts.append(title)
            elif line.asin:
                parts.append(line.asin)
            line.display_name = ' '.join(parts) or line.order_item_id
    
    @api.depends('item_price', 'quantity_ordered')
    def _compute_unit_prices(self):
        for line in self:
            qty = line.quantity_ordered or 1
            line.item_price_unit = line.item_price / qty if line.item_price else 0
    
    @api.depends('item_tax', 'shipping_tax', 'gift_wrap_tax', 
                 'promotion_discount_tax', 'shipping_discount_tax')
    def _compute_total_tax(self):
        for line in self:
            line.total_tax = (
                (line.item_tax or 0) +
                (line.shipping_tax or 0) +
                (line.gift_wrap_tax or 0) -
                (line.promotion_discount_tax or 0) -
                (line.shipping_discount_tax or 0)
            )
    
    @api.depends('fee_referral', 'fee_fba_fulfillment', 'fee_fba_weight_handling',
                 'fee_fba_inventory_storage', 'fee_variable_closing', 'fee_digital_services',
                 'fee_subscription', 'fee_shipping_chargeback', 'fee_gift_wrap_chargeback',
                 'fee_other')
    def _compute_total_fees(self):
        for line in self:
            line.total_fees = sum([
                line.fee_referral or 0,
                line.fee_fba_fulfillment or 0,
                line.fee_fba_weight_handling or 0,
                line.fee_fba_inventory_storage or 0,
                line.fee_variable_closing or 0,
                line.fee_digital_services or 0,
                line.fee_subscription or 0,
                line.fee_shipping_chargeback or 0,
                line.fee_gift_wrap_chargeback or 0,
                line.fee_other or 0,
            ])
    
    @api.depends('item_price', 'shipping_price', 'gift_wrap_price',
                 'promotion_discount', 'shipping_discount', 'total_fees')
    def _compute_net_proceeds(self):
        for line in self:
            line.net_proceeds = (
                (line.item_price or 0) +
                (line.shipping_price or 0) +
                (line.gift_wrap_price or 0) -
                (line.promotion_discount or 0) -
                (line.shipping_discount or 0) -
                (line.total_fees or 0)
            )
    
    # ══════════════════════════════════════════════════════════════════════════
    # BUSINESS LOGIC
    # ══════════════════════════════════════════════════════════════════════════
    
    def _create_sale_order_line(self, sale_order):
        """Create corresponding sale.order.line.
        
        Args:
            sale_order: sale.order record to add line to
            
        Returns:
            sale.order.line record
        """
        self.ensure_one()
        
        product = self._get_product()
        
        # Determine if we should include shipping/gift wrap as separate lines
        # For now, include in main product price
        vals = {
            'order_id': sale_order.id,
            'product_id': product.id,
            'name': self.title or product.display_name,
            'product_uom_qty': self.quantity_ordered,
            'price_unit': self.item_price_unit,
            'amazon_order_line_id': self.id,
        }
        
        sol = self.env['sale.order.line'].create(vals)
        self.sale_order_line_id = sol
        return sol
    
    def _get_product(self):
        """Get or create product for this line item."""
        self.ensure_one()
        
        if self.product_id:
            return self.product_id
        
        Product = self.env['product.product']
        
        # Try to find by SKU
        if self.seller_sku:
            product = Product.search([
                ('default_code', '=', self.seller_sku)
            ], limit=1)
            if product:
                self.product_id = product
                return product
        
        # Try to find by Amazon listing
        if self.amazon_listing_id and self.amazon_listing_id.product_id:
            self.product_id = self.amazon_listing_id.product_id
            return self.amazon_listing_id.product_id
        
        # Create a placeholder product
        product = Product.create({
            'name': self.title or f'Amazon Item {self.asin}',
            'default_code': self.seller_sku or self.asin,
            'type': 'consu',  # Consumable as default
            'sale_ok': True,
            'purchase_ok': False,
            'list_price': self.item_price_unit or 0,
        })
        self.product_id = product
        return product
    
    def action_view_product(self):
        """Open linked product."""
        self.ensure_one()
        if not self.product_id:
            raise UserError(_("No product linked to this order line."))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.product',
            'res_id': self.product_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    # ══════════════════════════════════════════════════════════════════════════
    # IMPORT FROM SP-API
    # ══════════════════════════════════════════════════════════════════════════
    
    @api.model
    def create_from_spapi(self, order, item_data, product_cache=None, listing_cache=None):
        """Create order line from SP-API OrderItems response.
        
        Args:
            order: amazon.order record
            item_data: dict from SP-API OrderItems API
            product_cache: dict caching product.product records by SKU
            listing_cache: dict caching amazon.product.listing records by SKU
            
        Returns:
            amazon.order.line record
        """
        order_item_id = item_data.get('OrderItemId')
        
        existing = self.search([
            ('order_item_id', '=', order_item_id)
        ], limit=1)
        
        vals = self._prepare_vals_from_spapi(
            order, item_data,
            product_cache=product_cache,
            listing_cache=listing_cache
        )
        
        if existing:
            existing.write(vals)
            return existing
        else:
            return self.create(vals)
    
    @api.model
    def _prepare_vals_from_spapi(self, order, data, product_cache=None, listing_cache=None):
        """Transform SP-API order item data to model values."""
        
        def get_money(field_name, default=0):
            """Extract monetary amount from SP-API Money object."""
            money = data.get(field_name, {})
            return float(money.get('Amount', default)) if money else default
        
        # Try to find product by SKU
        seller_sku = data.get('SellerSKU')
        product = False
        listing = False
        
        if seller_sku:
            if product_cache is not None and seller_sku in product_cache:
                product = product_cache[seller_sku]
            else:
                product = self.env['product.product'].search([
                    ('default_code', '=', seller_sku)
                ], limit=1)
                if product_cache is not None:
                    product_cache[seller_sku] = product

            if listing_cache is not None and seller_sku in listing_cache:
                listing = listing_cache[seller_sku]
            else:
                listing = self.env['amazon.product.listing'].search([
                    ('seller_sku', '=', seller_sku),
                    ('account_id', '=', order.account_id.id),
                ], limit=1)
                if listing_cache is not None:
                    listing_cache[seller_sku] = listing
        
        # Parse promotion IDs
        promotion_ids = data.get('PromotionIds', [])
        promotion_ids_str = ','.join(promotion_ids) if promotion_ids else False
        
        # Determine item status based on quantities
        qty_ordered = data.get('QuantityOrdered', 1)
        qty_shipped = data.get('QuantityShipped', 0)
        if qty_shipped >= qty_ordered:
            item_status = 'shipped'
        elif qty_shipped > 0:
            item_status = 'unshipped'  # Partially shipped still shows unshipped
        else:
            item_status = 'unshipped'
        
        vals = {
            'order_id': order.id,
            'order_item_id': data.get('OrderItemId'),
            'asin': data.get('ASIN'),
            'seller_sku': seller_sku,
            'title': data.get('Title'),
            'quantity_ordered': qty_ordered,
            'quantity_shipped': qty_shipped,
            'item_status': item_status,
            'product_id': product.id if product else False,
            'amazon_listing_id': listing.id if listing else False,
            
            # Prices
            'item_price': get_money('ItemPrice'),
            'shipping_price': get_money('ShippingPrice'),
            'shipping_discount': get_money('ShippingDiscount'),
            'gift_wrap_price': get_money('GiftWrapPrice'),
            'promotion_discount': get_money('PromotionDiscount'),
            'cod_fee': get_money('CODFee'),
            'cod_fee_discount': get_money('CODFeeDiscount'),
            
            # Taxes
            'item_tax': get_money('ItemTax'),
            'shipping_tax': get_money('ShippingTax'),
            'gift_wrap_tax': get_money('GiftWrapTax'),
            'promotion_discount_tax': get_money('PromotionDiscountTax'),
            'shipping_discount_tax': get_money('ShippingDiscountTax'),
            
            # Promotions
            'promotion_ids_raw': promotion_ids_str,
            
            # Condition
            'condition_id': data.get('ConditionId'),
            'condition_subtype_id': data.get('ConditionSubtypeId'),
            'condition_note': data.get('ConditionNote'),
            
            # Gift
            'is_gift': data.get('IsGift', False),
            'gift_message_text': data.get('GiftMessageText'),
            'gift_wrap_level': data.get('GiftWrapLevel'),
            
            # Serial/transparency
            'is_transparency': data.get('IsTransparency', False),
            'serial_number_required': data.get('SerialNumberRequired', False),
            
            # IOSS
            'ioss_number': data.get('IossNumber'),
            'deemed_reseller_category': data.get('DeemedResellerCategory'),
            
            # Scheduled delivery
            'scheduled_delivery_start': self._parse_datetime(
                data.get('ScheduledDeliveryStartDate')
            ),
            'scheduled_delivery_end': self._parse_datetime(
                data.get('ScheduledDeliveryEndDate')
            ),
            
            # Store pickup
            'store_chain_store_id': data.get('StoreChainStoreId'),
            
            # Points
            'points_granted_number': (data.get('PointsGranted', {}) or {}).get('PointsNumber'),
        }
        
        # Handle points monetary value
        points_value = (data.get('PointsGranted', {}) or {}).get('PointsMonetaryValue', {})
        if points_value:
            vals['points_granted_price'] = float(points_value.get('Amount', 0))
        
        # Tax collection responsibility
        tax_collection = data.get('TaxCollection', {})
        if tax_collection.get('Model') == 'MarketplaceFacilitator':
            vals['is_tax_collected_at_source'] = True
            vals['tax_collection_model'] = 'marketplace_facilitator'
        
        return vals
    
    @staticmethod
    def _parse_datetime(value):
        """Parse ISO datetime string."""
        if not value:
            return False
        try:
            if isinstance(value, str):
                value = value.replace('Z', '+00:00')
                return datetime.fromisoformat(value.replace('+00:00', ''))
            return value
        except (ValueError, TypeError):
            return False
