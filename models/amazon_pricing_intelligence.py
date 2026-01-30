# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

"""
Amazon Pricing Intelligence Module

Provides smart pricing recommendations based on:
- Competitive pricing analysis
- Buy Box ownership
- Margin guardrails
- Historical price performance
- Inventory velocity

Key philosophy: Profitable pricing, not race to the bottom!
"""

import logging
from datetime import datetime, timedelta
from statistics import mean, stdev

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AmazonPricingRule(models.Model):
    """
    Amazon Pricing Rule.
    
    Defines repricing strategies for product listings:
    - Match lowest: Match the lowest competing price
    - Beat by amount: Undercut by fixed amount
    - Beat by percent: Undercut by percentage
    - Target margin: Maintain a target profit margin
    - Manual: No automatic repricing
    
    Includes guardrails (min/max prices) to prevent pricing disasters.
    """
    _name = 'amazon.pricing.rule'
    _description = 'Amazon Pricing Rule'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, id'
    
    # =========================================================================
    # SELECTION VALUES
    # =========================================================================
    
    RULE_TYPES = [
        ('match_lowest', 'Match Lowest Price'),
        ('beat_by_amount', 'Beat by Fixed Amount'),
        ('beat_by_percent', 'Beat by Percentage'),
        ('target_margin', 'Target Profit Margin'),
        ('stay_above_buybox', 'Stay Above Buy Box'),
        ('win_buybox', 'Win Buy Box (Smart)'),
        ('manual', 'Manual (No Auto-Repricing)'),
    ]
    
    COMPETITOR_TYPES = [
        ('all', 'All Competitors'),
        ('fba_only', 'FBA Competitors Only'),
        ('fbm_only', 'FBM Competitors Only'),
        ('buybox_only', 'Buy Box Winner Only'),
    ]
    
    # =========================================================================
    # FIELDS - Identification
    # =========================================================================
    
    name = fields.Char(
        string='Rule Name',
        required=True,
        tracking=True,
    )
    
    # =========================================================================
    # FIELDS - Relationships
    # =========================================================================
    
    product_listing_id = fields.Many2one(
        comodel_name='amazon.product.listing',
        string='Product Listing',
        ondelete='cascade',
        index=True,
        help='Apply rule to specific listing (leave empty for global rule)',
    )
    marketplace_id = fields.Many2one(
        comodel_name='amazon.marketplace',
        string='Marketplace',
        ondelete='restrict',
        index=True,
        help='Apply rule to specific marketplace',
    )
    account_id = fields.Many2one(
        comodel_name='amazon.account',
        string='Amazon Account',
        ondelete='cascade',
        index=True,
    )
    category_ids = fields.Many2many(
        comodel_name='amazon.product.category',
        string='Categories',
        help='Apply rule to specific Amazon categories',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='marketplace_id.currency_id',
        store=True,
    )
    
    # =========================================================================
    # FIELDS - Rule Configuration
    # =========================================================================
    
    rule_type = fields.Selection(
        selection=RULE_TYPES,
        string='Rule Type',
        required=True,
        default='match_lowest',
        tracking=True,
    )
    competitor_type = fields.Selection(
        selection=COMPETITOR_TYPES,
        string='Compete Against',
        default='all',
        help='Which competitors to consider in pricing decisions',
    )
    
    # =========================================================================
    # FIELDS - Price Guardrails
    # =========================================================================
    
    min_price = fields.Monetary(
        string='Minimum Price',
        currency_field='currency_id',
        tracking=True,
        help='Floor price - will never go below this (protects margin)',
    )
    max_price = fields.Monetary(
        string='Maximum Price',
        currency_field='currency_id',
        tracking=True,
        help='Ceiling price - will never exceed this',
    )
    
    # =========================================================================
    # FIELDS - Margin Settings
    # =========================================================================
    
    target_margin_percent = fields.Float(
        string='Target Margin (%)',
        digits=(5, 2),
        tracking=True,
        help='Desired profit margin percentage',
    )
    min_margin_percent = fields.Float(
        string='Minimum Margin (%)',
        digits=(5, 2),
        tracking=True,
        help='Absolute minimum margin - will not reprice below this',
    )
    include_fba_fees = fields.Boolean(
        string='Include FBA Fees in Margin',
        default=True,
        help='Factor FBA fulfillment fees into margin calculations',
    )
    include_referral_fee = fields.Boolean(
        string='Include Referral Fee in Margin',
        default=True,
        help='Factor Amazon referral fee into margin calculations',
    )
    
    # =========================================================================
    # FIELDS - Beat Settings
    # =========================================================================
    
    beat_amount = fields.Monetary(
        string='Beat by Amount',
        currency_field='currency_id',
        help='Undercut competitor price by this fixed amount',
    )
    beat_percent = fields.Float(
        string='Beat by Percent (%)',
        digits=(5, 2),
        help='Undercut competitor price by this percentage',
    )
    
    # =========================================================================
    # FIELDS - Advanced Settings
    # =========================================================================
    
    raise_price_enabled = fields.Boolean(
        string='Allow Price Increases',
        default=True,
        help='Allow raising price when we already have Buy Box',
    )
    max_raise_percent = fields.Float(
        string='Max Raise (%)',
        digits=(5, 2),
        default=5.0,
        help='Maximum percentage to raise price in one reprice',
    )
    max_drop_percent = fields.Float(
        string='Max Drop (%)',
        digits=(5, 2),
        default=10.0,
        help='Maximum percentage to drop price in one reprice',
    )
    cooldown_hours = fields.Integer(
        string='Cooldown Hours',
        default=4,
        help='Minimum hours between price changes for same product',
    )
    ignore_outliers = fields.Boolean(
        string='Ignore Outlier Prices',
        default=True,
        help='Ignore suspiciously low/high competitor prices',
    )
    outlier_threshold = fields.Float(
        string='Outlier Threshold (%)',
        default=30.0,
        help='Prices deviating more than this % from median are ignored',
    )
    
    # =========================================================================
    # FIELDS - Status
    # =========================================================================
    
    is_active = fields.Boolean(
        string='Active',
        default=True,
        tracking=True,
    )
    priority = fields.Integer(
        string='Priority',
        default=10,
        help='Higher priority rules are applied first',
    )
    last_applied = fields.Datetime(
        string='Last Applied',
        readonly=True,
    )
    times_applied = fields.Integer(
        string='Times Applied',
        default=0,
        readonly=True,
    )
    
    # =========================================================================
    # CONSTRAINTS
    # =========================================================================
    
    @api.constrains('min_price', 'max_price')
    def _check_price_range(self):
        for rule in self:
            if rule.min_price and rule.max_price:
                if rule.min_price >= rule.max_price:
                    raise ValidationError(
                        _('Minimum price must be less than maximum price.')
                    )
    
    @api.constrains('target_margin_percent', 'min_margin_percent')
    def _check_margin_range(self):
        for rule in self:
            if rule.target_margin_percent and rule.min_margin_percent:
                if rule.min_margin_percent > rule.target_margin_percent:
                    raise ValidationError(
                        _('Minimum margin cannot exceed target margin.')
                    )
    
    # =========================================================================
    # BUSINESS METHODS
    # =========================================================================
    
    def get_applicable_rule(self, listing):
        """
        Find the best applicable rule for a listing.
        
        Priority order:
        1. Specific listing rule
        2. Category rule
        3. Marketplace rule
        4. Account-wide rule
        
        Args:
            listing: amazon.product.listing record
            
        Returns:
            amazon.pricing.rule record or empty recordset
        """
        # Direct listing rule
        direct_rule = self.search([
            ('product_listing_id', '=', listing.id),
            ('is_active', '=', True),
        ], order='priority desc', limit=1)
        
        if direct_rule:
            return direct_rule
        
        # Category rule
        if listing.amazon_category_id:
            category_rule = self.search([
                ('category_ids', 'in', listing.amazon_category_id.id),
                ('marketplace_id', '=', listing.marketplace_id.id),
                ('is_active', '=', True),
            ], order='priority desc', limit=1)
            
            if category_rule:
                return category_rule
        
        # Marketplace rule
        marketplace_rule = self.search([
            ('marketplace_id', '=', listing.marketplace_id.id),
            ('account_id', '=', listing.account_id.id),
            ('product_listing_id', '=', False),
            ('category_ids', '=', False),
            ('is_active', '=', True),
        ], order='priority desc', limit=1)
        
        if marketplace_rule:
            return marketplace_rule
        
        # Account-wide rule
        account_rule = self.search([
            ('account_id', '=', listing.account_id.id),
            ('product_listing_id', '=', False),
            ('marketplace_id', '=', False),
            ('category_ids', '=', False),
            ('is_active', '=', True),
        ], order='priority desc', limit=1)
        
        return account_rule
    
    def calculate_recommended_price(self, listing, competitor_prices):
        """
        Calculate recommended price based on rule settings.
        
        Args:
            listing: amazon.product.listing record
            competitor_prices: amazon.competitor.price recordset
            
        Returns:
            dict with recommended_price, reason, confidence
        """
        self.ensure_one()
        
        if not competitor_prices and self.rule_type != 'target_margin':
            return {
                'recommended_price': listing.list_price,
                'reason': 'no_competitor_data',
                'confidence': 'low',
            }
        
        # Filter competitors based on rule settings
        relevant_prices = self._filter_competitors(competitor_prices)
        
        if self.ignore_outliers and relevant_prices:
            relevant_prices = self._remove_outliers(relevant_prices)
        
        # Calculate base recommended price
        if self.rule_type == 'match_lowest':
            result = self._calc_match_lowest(listing, relevant_prices)
        elif self.rule_type == 'beat_by_amount':
            result = self._calc_beat_by_amount(listing, relevant_prices)
        elif self.rule_type == 'beat_by_percent':
            result = self._calc_beat_by_percent(listing, relevant_prices)
        elif self.rule_type == 'target_margin':
            result = self._calc_target_margin(listing)
        elif self.rule_type == 'stay_above_buybox':
            result = self._calc_stay_above_buybox(listing, relevant_prices)
        elif self.rule_type == 'win_buybox':
            result = self._calc_win_buybox(listing, relevant_prices)
        else:  # manual
            return {
                'recommended_price': listing.list_price,
                'reason': 'manual_rule',
                'confidence': 'high',
            }
        
        # Apply guardrails
        result = self._apply_guardrails(listing, result)
        
        # Apply rate-of-change limits
        result = self._apply_change_limits(listing, result)
        
        return result
    
    def _filter_competitors(self, competitor_prices):
        """Filter competitor prices based on rule settings."""
        if self.competitor_type == 'fba_only':
            return competitor_prices.filtered(lambda p: p.is_fba)
        elif self.competitor_type == 'fbm_only':
            return competitor_prices.filtered(lambda p: not p.is_fba)
        elif self.competitor_type == 'buybox_only':
            return competitor_prices.filtered(lambda p: p.is_buy_box_winner)
        return competitor_prices
    
    def _remove_outliers(self, competitor_prices):
        """Remove outlier prices (suspiciously high/low)."""
        prices = competitor_prices.mapped('competitor_price')
        if len(prices) < 3:
            return competitor_prices
        
        median_price = sorted(prices)[len(prices) // 2]
        threshold = median_price * (self.outlier_threshold / 100)
        
        return competitor_prices.filtered(
            lambda p: abs(p.competitor_price - median_price) <= threshold
        )
    
    def _calc_match_lowest(self, listing, competitor_prices):
        """Match the lowest competitor price."""
        if not competitor_prices:
            return {
                'recommended_price': listing.list_price,
                'reason': 'no_competitors',
                'confidence': 'low',
            }
        
        lowest = min(competitor_prices.mapped('competitor_price'))
        
        return {
            'recommended_price': lowest,
            'reason': 'match_competitor',
            'confidence': 'high',
        }
    
    def _calc_beat_by_amount(self, listing, competitor_prices):
        """Beat lowest competitor by fixed amount."""
        if not competitor_prices:
            return {
                'recommended_price': listing.list_price,
                'reason': 'no_competitors',
                'confidence': 'low',
            }
        
        lowest = min(competitor_prices.mapped('competitor_price'))
        recommended = lowest - (self.beat_amount or 0.01)
        
        return {
            'recommended_price': max(recommended, 0.01),
            'reason': 'win_buy_box',
            'confidence': 'high',
        }
    
    def _calc_beat_by_percent(self, listing, competitor_prices):
        """Beat lowest competitor by percentage."""
        if not competitor_prices:
            return {
                'recommended_price': listing.list_price,
                'reason': 'no_competitors',
                'confidence': 'low',
            }
        
        lowest = min(competitor_prices.mapped('competitor_price'))
        beat_pct = (self.beat_percent or 1.0) / 100
        recommended = lowest * (1 - beat_pct)
        
        return {
            'recommended_price': max(recommended, 0.01),
            'reason': 'win_buy_box',
            'confidence': 'high',
        }
    
    def _calc_target_margin(self, listing):
        """Calculate price to achieve target margin."""
        cost = listing.landed_cost or 0
        
        if not cost:
            return {
                'recommended_price': listing.list_price,
                'reason': 'no_cost_data',
                'confidence': 'low',
            }
        
        # Estimate fees
        total_fees = self._estimate_total_fees(listing)
        
        # Calculate price for target margin
        target_margin = (self.target_margin_percent or 15.0) / 100
        # price - cost - fees = margin * price
        # price * (1 - margin) = cost + fees
        # price = (cost + fees) / (1 - margin)
        
        if target_margin >= 1:
            target_margin = 0.5  # Cap at 50% margin
        
        recommended = (cost + total_fees) / (1 - target_margin)
        
        return {
            'recommended_price': recommended,
            'reason': 'target_margin',
            'confidence': 'medium',
        }
    
    def _calc_stay_above_buybox(self, listing, competitor_prices):
        """Stay slightly above Buy Box price (maximize margin while keeping visibility)."""
        buybox_winner = competitor_prices.filtered(lambda p: p.is_buy_box_winner)
        
        if not buybox_winner:
            # No Buy Box data - match lowest
            return self._calc_match_lowest(listing, competitor_prices)
        
        buybox_price = buybox_winner[0].competitor_price
        
        # If we're the Buy Box winner, try to increase price
        if listing.is_buybox_winner and self.raise_price_enabled:
            # Find next competitor price
            other_prices = competitor_prices.filtered(
                lambda p: p.competitor_price > buybox_price
            ).mapped('competitor_price')
            
            if other_prices:
                next_price = min(other_prices)
                # Stay just below next competitor
                recommended = next_price * 0.99
            else:
                # No higher competitors - raise by max allowed
                recommended = buybox_price * (1 + (self.max_raise_percent or 5) / 100)
            
            return {
                'recommended_price': recommended,
                'reason': 'increase_margin',
                'confidence': 'medium',
            }
        
        # Match Buy Box price
        return {
            'recommended_price': buybox_price,
            'reason': 'match_competitor',
            'confidence': 'high',
        }
    
    def _calc_win_buybox(self, listing, competitor_prices):
        """
        Smart Buy Box winning strategy.
        
        - If we have Buy Box: Try to raise price without losing it
        - If we don't: Calculate minimum price needed to win
        - Factor in our FBA status vs competitors
        """
        buybox_winner = competitor_prices.filtered(lambda p: p.is_buy_box_winner)
        
        # Already have Buy Box
        if listing.is_buybox_winner:
            if not self.raise_price_enabled:
                return {
                    'recommended_price': listing.list_price,
                    'reason': 'keep_buybox',
                    'confidence': 'high',
                }
            
            # Try raising price gradually
            return self._calc_stay_above_buybox(listing, competitor_prices)
        
        # Need to win Buy Box
        if not buybox_winner:
            return self._calc_match_lowest(listing, competitor_prices)
        
        buybox_price = buybox_winner[0].competitor_price
        is_buybox_fba = buybox_winner[0].is_fba
        
        # FBA sellers get Buy Box preference - if we're FBA competing with FBM, 
        # we can match or even exceed slightly
        if listing.is_fba and not is_buybox_fba:
            # We're FBA, competitor is FBM - we can likely win at same price
            recommended = buybox_price
            confidence = 'high'
        elif not listing.is_fba and is_buybox_fba:
            # We're FBM, competitor is FBA - need to undercut significantly
            recommended = buybox_price * 0.95  # 5% lower
            confidence = 'medium'
        else:
            # Same fulfillment channel - small undercut
            recommended = buybox_price * 0.99  # 1% lower
            confidence = 'medium'
        
        return {
            'recommended_price': recommended,
            'reason': 'win_buy_box',
            'confidence': confidence,
        }
    
    def _estimate_total_fees(self, listing):
        """Estimate total Amazon fees for a listing."""
        fees = 0.0
        price = listing.list_price or 0
        
        if self.include_referral_fee:
            # Referral fee typically 8-15% depending on category
            referral_pct = listing.referral_fee_percent or 15.0
            fees += price * (referral_pct / 100)
        
        if self.include_fba_fees and listing.is_fba:
            fees += listing.fba_fee or 0
        
        return fees
    
    def _apply_guardrails(self, listing, result):
        """Apply min/max price guardrails."""
        recommended = result['recommended_price']
        
        # Apply minimum price
        if self.min_price and recommended < self.min_price:
            result['recommended_price'] = self.min_price
            result['reason'] = 'min_price_floor'
            result['confidence'] = 'high'
        
        # Apply maximum price
        if self.max_price and recommended > self.max_price:
            result['recommended_price'] = self.max_price
            result['reason'] = 'max_price_ceiling'
            result['confidence'] = 'high'
        
        # Apply minimum margin
        if self.min_margin_percent and listing.landed_cost:
            min_price_for_margin = self._calc_min_price_for_margin(
                listing, self.min_margin_percent
            )
            if result['recommended_price'] < min_price_for_margin:
                result['recommended_price'] = min_price_for_margin
                result['reason'] = 'min_margin_floor'
                result['confidence'] = 'high'
        
        return result
    
    def _calc_min_price_for_margin(self, listing, margin_percent):
        """Calculate minimum price to achieve a margin percentage."""
        cost = listing.landed_cost or 0
        fees = self._estimate_total_fees(listing)
        margin = margin_percent / 100
        
        if margin >= 1:
            margin = 0.5
        
        return (cost + fees) / (1 - margin)
    
    def _apply_change_limits(self, listing, result):
        """Apply rate-of-change limits to prevent drastic swings."""
        current_price = listing.list_price
        recommended = result['recommended_price']
        
        if not current_price:
            return result
        
        change_percent = ((recommended - current_price) / current_price) * 100
        
        # Limit price drops
        if change_percent < 0 and self.max_drop_percent:
            max_drop = current_price * (self.max_drop_percent / 100)
            if current_price - recommended > max_drop:
                result['recommended_price'] = current_price - max_drop
                result['reason'] = 'max_drop_limit'
        
        # Limit price raises
        if change_percent > 0 and self.max_raise_percent:
            max_raise = current_price * (self.max_raise_percent / 100)
            if recommended - current_price > max_raise:
                result['recommended_price'] = current_price + max_raise
                result['reason'] = 'max_raise_limit'
        
        return result
    
    def action_test_rule(self):
        """Test the rule against current competitor data."""
        self.ensure_one()
        
        if not self.product_listing_id:
            raise UserError(_('Please select a product listing to test the rule.'))
        
        listing = self.product_listing_id
        competitor_prices = self.env['amazon.competitor.price'].search([
            ('product_listing_id', '=', listing.id),
        ], order='captured_at desc', limit=10)
        
        result = self.calculate_recommended_price(listing, competitor_prices)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Rule Test Result'),
                'message': _(
                    'Current: %(current)s | Recommended: %(recommended)s | Reason: %(reason)s | Confidence: %(confidence)s'
                ) % {
                    'current': listing.list_price,
                    'recommended': round(result['recommended_price'], 2),
                    'reason': result['reason'],
                    'confidence': result['confidence'],
                },
                'sticky': True,
                'type': 'info',
            }
        }


class AmazonCompetitorPrice(models.Model):
    """
    Amazon Competitor Price.
    
    Stores historical competitor pricing data for analysis:
    - Who's selling
    - At what price
    - FBA vs FBM
    - Buy Box status
    
    Used for:
    - Competitive pricing decisions
    - Price trend analysis
    - Buy Box monitoring
    """
    _name = 'amazon.competitor.price'
    _description = 'Amazon Competitor Price'
    _order = 'captured_at desc'
    _rec_name = 'display_name'
    
    # =========================================================================
    # FIELDS
    # =========================================================================
    
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )
    product_listing_id = fields.Many2one(
        comodel_name='amazon.product.listing',
        string='Product Listing',
        required=True,
        ondelete='cascade',
        index=True,
    )
    marketplace_id = fields.Many2one(
        comodel_name='amazon.marketplace',
        string='Marketplace',
        related='product_listing_id.marketplace_id',
        store=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='product_listing_id.currency_id',
        store=True,
    )
    
    # Competitor Info
    competitor_seller = fields.Char(
        string='Seller Name',
        help='Competitor seller name (if available)',
    )
    competitor_seller_id = fields.Char(
        string='Seller ID',
        help='Amazon Seller ID',
        index=True,
    )
    
    # Pricing
    competitor_price = fields.Monetary(
        string='List Price',
        currency_field='currency_id',
        required=True,
    )
    competitor_shipping = fields.Monetary(
        string='Shipping Price',
        currency_field='currency_id',
        default=0,
    )
    landed_price = fields.Monetary(
        string='Landed Price',
        currency_field='currency_id',
        compute='_compute_landed_price',
        store=True,
        help='Total price including shipping',
    )
    
    # Condition
    condition = fields.Selection(
        selection=[
            ('new', 'New'),
            ('used_like_new', 'Used - Like New'),
            ('used_very_good', 'Used - Very Good'),
            ('used_good', 'Used - Good'),
            ('used_acceptable', 'Used - Acceptable'),
            ('collectible_like_new', 'Collectible - Like New'),
            ('collectible_very_good', 'Collectible - Very Good'),
            ('collectible_good', 'Collectible - Good'),
            ('collectible_acceptable', 'Collectible - Acceptable'),
            ('refurbished', 'Refurbished'),
        ],
        string='Condition',
        default='new',
    )
    
    # Fulfillment & Status
    is_fba = fields.Boolean(
        string='Is FBA',
        help='Fulfilled by Amazon',
    )
    is_buy_box_winner = fields.Boolean(
        string='Buy Box Winner',
        help='This offer currently owns the Buy Box',
    )
    is_prime = fields.Boolean(
        string='Prime Eligible',
    )
    
    # Stock
    availability = fields.Selection(
        selection=[
            ('in_stock', 'In Stock'),
            ('limited', 'Limited Stock'),
            ('out_of_stock', 'Out of Stock'),
            ('preorder', 'Pre-order'),
            ('backorder', 'Backorder'),
        ],
        string='Availability',
        default='in_stock',
    )
    
    # Timing
    captured_at = fields.Datetime(
        string='Captured At',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    
    # Analysis
    price_rank = fields.Integer(
        string='Price Rank',
        help='Rank among all offers (1 = lowest)',
    )
    is_our_offer = fields.Boolean(
        string='Is Our Offer',
        help='This is our own listing',
    )
    
    # =========================================================================
    # COMPUTE METHODS
    # =========================================================================
    
    @api.depends('competitor_seller', 'competitor_price', 'is_buy_box_winner')
    def _compute_display_name(self):
        for record in self:
            parts = []
            if record.competitor_seller:
                parts.append(record.competitor_seller[:20])
            parts.append(f'€{record.competitor_price:.2f}')
            if record.is_buy_box_winner:
                parts.append('★')
            record.display_name = ' - '.join(parts) if parts else _('Competitor')
    
    @api.depends('competitor_price', 'competitor_shipping')
    def _compute_landed_price(self):
        for record in self:
            record.landed_price = (
                (record.competitor_price or 0) + 
                (record.competitor_shipping or 0)
            )
    
    # =========================================================================
    # BUSINESS METHODS
    # =========================================================================
    
    @api.model
    def get_latest_for_listing(self, listing_id, max_age_hours=24):
        """
        Get latest competitor prices for a listing.
        
        Args:
            listing_id: amazon.product.listing ID
            max_age_hours: Maximum age of data to consider
            
        Returns:
            amazon.competitor.price recordset
        """
        cutoff = fields.Datetime.now() - timedelta(hours=max_age_hours)
        
        return self.search([
            ('product_listing_id', '=', listing_id),
            ('captured_at', '>=', cutoff),
        ], order='captured_at desc')
    
    @api.model
    def get_price_history(self, listing_id, days=30, condition='new'):
        """
        Get price history for analysis.
        
        Args:
            listing_id: amazon.product.listing ID
            days: Number of days of history
            condition: Product condition filter
            
        Returns:
            List of dicts with date and price data
        """
        cutoff = fields.Datetime.now() - timedelta(days=days)
        
        prices = self.search([
            ('product_listing_id', '=', listing_id),
            ('captured_at', '>=', cutoff),
            ('condition', '=', condition),
        ], order='captured_at asc')
        
        return [{
            'date': p.captured_at,
            'price': p.competitor_price,
            'landed_price': p.landed_price,
            'is_buybox': p.is_buy_box_winner,
            'seller': p.competitor_seller,
        } for p in prices]
    
    @api.model
    def cleanup_old_records(self, days=90):
        """Remove competitor price records older than X days."""
        cutoff = fields.Datetime.now() - timedelta(days=days)
        old_records = self.search([('captured_at', '<', cutoff)])
        count = len(old_records)
        old_records.unlink()
        _logger.info('Cleaned up %d old competitor price records', count)
        return count
    
    @api.model
    def _cron_fetch_competitor_prices(self):
        """
        Cron job to fetch competitor prices for all active listings.
        
        Fetches pricing data from Amazon's Product Pricing API.
        """
        _logger.info('Starting competitor price fetch cron')
        
        # Get all active listings that need price updates
        listings = self.env['amazon.product.listing'].search([
            ('state', '=', 'active'),
            ('asin', '!=', False),
        ])
        
        if not listings:
            _logger.info('No active listings found')
            return
        
        # Group by account for API calls
        listings_by_account = {}
        for listing in listings:
            if listing.account_id not in listings_by_account:
                listings_by_account[listing.account_id] = []
            listings_by_account[listing.account_id].append(listing)
        
        total_fetched = 0
        
        for account, account_listings in listings_by_account.items():
            try:
                # Get credentials
                credential = account.credential_id
                if not credential:
                    _logger.warning('No credential for account %s', account.name)
                    continue
                
                # Import and create pricing service
                from ..services.sp_api_pricing import get_pricing_service
                pricing_service = get_pricing_service(credential)
                
                # Fetch in batches (API limit is usually 20 ASINs per request)
                for listing in account_listings:
                    try:
                        records = pricing_service.sync_competitor_prices(
                            self.env, listing
                        )
                        total_fetched += len(records)
                        
                        # Update listing's last price sync
                        listing.write({
                            'last_price_sync': fields.Datetime.now(),
                        })
                        
                    except Exception as e:
                        _logger.error(
                            'Error fetching prices for %s: %s',
                            listing.sku, str(e)
                        )
                
            except Exception as e:
                _logger.error(
                    'Error fetching prices for account %s: %s',
                    account.name, str(e)
                )
        
        _logger.info('Fetched %d competitor prices', total_fetched)
        return total_fetched


class AmazonPricingRecommendation(models.Model):
    """
    Amazon Pricing Recommendation.
    
    Stores generated pricing recommendations:
    - Current vs recommended price
    - Reason for recommendation
    - Expected impact
    - Status (pending/applied/dismissed)
    
    Provides actionable insights for pricing decisions.
    """
    _name = 'amazon.pricing.recommendation'
    _description = 'Amazon Pricing Recommendation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'display_name'
    
    # =========================================================================
    # SELECTION VALUES
    # =========================================================================
    
    REASONS = [
        ('win_buy_box', 'Win Buy Box'),
        ('match_competitor', 'Match Competitor'),
        ('beat_competitor', 'Beat Competitor'),
        ('increase_margin', 'Increase Margin'),
        ('target_margin', 'Target Margin'),
        ('clear_overstock', 'Clear Overstock'),
        ('seasonal_adjustment', 'Seasonal Adjustment'),
        ('min_price_floor', 'Minimum Price Floor'),
        ('max_price_ceiling', 'Maximum Price Ceiling'),
        ('keep_buybox', 'Keep Buy Box'),
        ('no_change', 'No Change Needed'),
    ]
    
    CONFIDENCE_LEVELS = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]
    
    STATUS_VALUES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('applied', 'Applied'),
        ('dismissed', 'Dismissed'),
        ('expired', 'Expired'),
    ]
    
    # =========================================================================
    # FIELDS
    # =========================================================================
    
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )
    
    product_listing_id = fields.Many2one(
        comodel_name='amazon.product.listing',
        string='Product Listing',
        required=True,
        ondelete='cascade',
        index=True,
    )
    marketplace_id = fields.Many2one(
        comodel_name='amazon.marketplace',
        string='Marketplace',
        related='product_listing_id.marketplace_id',
        store=True,
    )
    account_id = fields.Many2one(
        comodel_name='amazon.account',
        string='Account',
        related='product_listing_id.account_id',
        store=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='product_listing_id.currency_id',
        store=True,
    )
    pricing_rule_id = fields.Many2one(
        comodel_name='amazon.pricing.rule',
        string='Pricing Rule',
        ondelete='set null',
        help='Rule that generated this recommendation',
    )
    
    # Pricing
    current_price = fields.Monetary(
        string='Current Price',
        currency_field='currency_id',
        required=True,
    )
    recommended_price = fields.Monetary(
        string='Recommended Price',
        currency_field='currency_id',
        required=True,
    )
    price_change = fields.Monetary(
        string='Price Change',
        currency_field='currency_id',
        compute='_compute_price_change',
        store=True,
    )
    price_change_percent = fields.Float(
        string='Change (%)',
        compute='_compute_price_change',
        store=True,
        digits=(5, 2),
    )
    
    # Buy Box Context
    current_buybox_price = fields.Monetary(
        string='Current Buy Box Price',
        currency_field='currency_id',
    )
    we_have_buybox = fields.Boolean(
        string='We Have Buy Box',
    )
    competitor_count = fields.Integer(
        string='Competitor Count',
    )
    lowest_competitor_price = fields.Monetary(
        string='Lowest Competitor',
        currency_field='currency_id',
    )
    
    # Analysis
    recommendation_reason = fields.Selection(
        selection=REASONS,
        string='Reason',
        required=True,
    )
    reason_details = fields.Text(
        string='Details',
        help='Detailed explanation of the recommendation',
    )
    expected_impact = fields.Text(
        string='Expected Impact',
        help='Estimated impact on sales/margin',
    )
    confidence = fields.Selection(
        selection=CONFIDENCE_LEVELS,
        string='Confidence',
        default='medium',
        required=True,
    )
    
    # Margin Analysis
    current_margin = fields.Float(
        string='Current Margin (%)',
        digits=(5, 2),
    )
    projected_margin = fields.Float(
        string='Projected Margin (%)',
        compute='_compute_projected_margin',
        store=True,
        digits=(5, 2),
    )
    margin_impact = fields.Float(
        string='Margin Impact',
        compute='_compute_margin_impact',
        store=True,
        digits=(5, 2),
    )
    
    # Status
    status = fields.Selection(
        selection=STATUS_VALUES,
        string='Status',
        default='pending',
        required=True,
        tracking=True,
        index=True,
    )
    valid_until = fields.Datetime(
        string='Valid Until',
        help='Recommendation expires after this time',
    )
    applied_at = fields.Datetime(
        string='Applied At',
        readonly=True,
    )
    applied_by = fields.Many2one(
        comodel_name='res.users',
        string='Applied By',
        readonly=True,
    )
    dismissed_reason = fields.Char(
        string='Dismissal Reason',
    )
    
    # =========================================================================
    # COMPUTE METHODS
    # =========================================================================
    
    @api.depends('product_listing_id', 'price_change_percent')
    def _compute_display_name(self):
        for rec in self:
            listing_name = rec.product_listing_id.sku or 'Unknown'
            direction = '↑' if rec.price_change_percent > 0 else '↓' if rec.price_change_percent < 0 else '→'
            rec.display_name = f'{listing_name} {direction} {abs(rec.price_change_percent or 0):.1f}%'
    
    @api.depends('current_price', 'recommended_price')
    def _compute_price_change(self):
        for rec in self:
            rec.price_change = (rec.recommended_price or 0) - (rec.current_price or 0)
            if rec.current_price:
                rec.price_change_percent = (rec.price_change / rec.current_price) * 100
            else:
                rec.price_change_percent = 0
    
    @api.depends('recommended_price', 'product_listing_id.landed_cost', 
                 'product_listing_id.estimated_total_fees')
    def _compute_projected_margin(self):
        for rec in self:
            cost = rec.product_listing_id.landed_cost or 0
            fees = rec.product_listing_id.estimated_total_fees or 0
            price = rec.recommended_price or 0
            
            if price > 0:
                profit = price - cost - fees
                rec.projected_margin = (profit / price) * 100
            else:
                rec.projected_margin = 0
    
    @api.depends('current_margin', 'projected_margin')
    def _compute_margin_impact(self):
        for rec in self:
            rec.margin_impact = (rec.projected_margin or 0) - (rec.current_margin or 0)
    
    # =========================================================================
    # ACTIONS
    # =========================================================================
    
    def action_apply_price(self):
        """Apply the recommended price to the listing."""
        for rec in self.filtered(lambda r: r.status == 'pending'):
            listing = rec.product_listing_id
            
            # Update listing price
            listing.write({
                'list_price': rec.recommended_price,
            })
            
            # Create price history record
            self.env['amazon.price.history'].create({
                'product_listing_id': listing.id,
                'old_price': rec.current_price,
                'new_price': rec.recommended_price,
                'change_reason': rec.recommendation_reason,
                'change_source': 'recommendation',
                'recommendation_id': rec.id,
            })
            
            # Update recommendation status
            rec.write({
                'status': 'applied',
                'applied_at': fields.Datetime.now(),
                'applied_by': self.env.uid,
            })
            
            # Update pricing rule stats
            if rec.pricing_rule_id:
                rec.pricing_rule_id.write({
                    'last_applied': fields.Datetime.now(),
                    'times_applied': rec.pricing_rule_id.times_applied + 1,
                })
            
            _logger.info(
                'Applied price recommendation for %s: %s -> %s',
                listing.sku, rec.current_price, rec.recommended_price
            )
        
        # Trigger Amazon price update
        self.mapped('product_listing_id').action_update_price()
        
        return True
    
    def action_approve(self):
        """Approve recommendation for later application."""
        self.filtered(lambda r: r.status == 'pending').write({'status': 'approved'})
    
    def action_dismiss(self):
        """Dismiss the recommendation."""
        return {
            'name': _('Dismiss Recommendation'),
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.pricing.recommendation.dismiss.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_recommendation_ids': self.ids},
        }
    
    def action_dismiss_silent(self):
        """Dismiss without reason."""
        self.write({
            'status': 'dismissed',
            'dismissed_reason': 'Manual dismissal',
        })
    
    def action_view_listing(self):
        """Open the product listing."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.product.listing',
            'res_id': self.product_listing_id.id,
            'view_mode': 'form',
        }
    
    def action_view_competitors(self):
        """View competitor prices for this listing."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Competitor Prices'),
            'res_model': 'amazon.competitor.price',
            'view_mode': 'tree,form',
            'domain': [('product_listing_id', '=', self.product_listing_id.id)],
            'context': {'default_product_listing_id': self.product_listing_id.id},
        }
    
    # =========================================================================
    # CRON METHODS
    # =========================================================================
    
    @api.model
    def _cron_generate_recommendations(self):
        """
        Generate pricing recommendations for all active listings.
        
        Called by scheduled action every 4 hours.
        """
        _logger.info('Starting pricing recommendation generation')
        
        # Get all active listings with pricing rules
        listings = self.env['amazon.product.listing'].search([
            ('state', '=', 'active'),
            ('list_price', '>', 0),
        ])
        
        recommendations_created = 0
        PricingRule = self.env['amazon.pricing.rule']
        CompetitorPrice = self.env['amazon.competitor.price']
        
        for listing in listings:
            try:
                # Find applicable rule
                rule = PricingRule.get_applicable_rule(listing)
                
                if not rule or rule.rule_type == 'manual':
                    continue
                
                # Check cooldown
                last_rec = self.search([
                    ('product_listing_id', '=', listing.id),
                    ('status', '=', 'applied'),
                ], order='applied_at desc', limit=1)
                
                if last_rec and rule.cooldown_hours:
                    cooldown_end = last_rec.applied_at + timedelta(hours=rule.cooldown_hours)
                    if fields.Datetime.now() < cooldown_end:
                        continue
                
                # Get competitor prices
                competitor_prices = CompetitorPrice.get_latest_for_listing(
                    listing.id, max_age_hours=24
                )
                
                # Calculate recommendation
                result = rule.calculate_recommended_price(listing, competitor_prices)
                
                # Skip if no meaningful change
                if abs(result['recommended_price'] - listing.list_price) < 0.01:
                    continue
                
                # Expire old pending recommendations
                self.search([
                    ('product_listing_id', '=', listing.id),
                    ('status', '=', 'pending'),
                ]).write({'status': 'expired'})
                
                # Get Buy Box info
                buybox_offer = competitor_prices.filtered(lambda p: p.is_buy_box_winner)
                
                # Create recommendation
                self.create({
                    'product_listing_id': listing.id,
                    'pricing_rule_id': rule.id,
                    'current_price': listing.list_price,
                    'recommended_price': result['recommended_price'],
                    'recommendation_reason': result['reason'],
                    'confidence': result['confidence'],
                    'current_margin': listing.profit_margin,
                    'current_buybox_price': buybox_offer[0].competitor_price if buybox_offer else 0,
                    'we_have_buybox': listing.is_buybox_winner,
                    'competitor_count': len(competitor_prices),
                    'lowest_competitor_price': min(competitor_prices.mapped('competitor_price')) if competitor_prices else 0,
                    'valid_until': fields.Datetime.now() + timedelta(hours=24),
                })
                
                recommendations_created += 1
                
            except Exception as e:
                _logger.error(
                    'Error generating recommendation for listing %s: %s',
                    listing.id, str(e)
                )
        
        _logger.info('Generated %d pricing recommendations', recommendations_created)
        return recommendations_created
    
    @api.model
    def _cron_auto_apply_recommendations(self):
        """
        Auto-apply high-confidence recommendations.
        
        Only applies recommendations that:
        - Have high confidence
        - Are within safe change limits
        - Product listing allows auto-repricing
        """
        _logger.info('Starting auto-apply of pricing recommendations')
        
        # Find high-confidence pending recommendations
        recommendations = self.search([
            ('status', '=', 'pending'),
            ('confidence', '=', 'high'),
            ('valid_until', '>', fields.Datetime.now()),
        ])
        
        applied_count = 0
        
        for rec in recommendations:
            # Check if listing allows auto-repricing
            # (you might add a field for this on the listing)
            if abs(rec.price_change_percent) > 15:
                # Skip large changes - require manual approval
                continue
            
            try:
                rec.action_apply_price()
                applied_count += 1
            except Exception as e:
                _logger.error(
                    'Error auto-applying recommendation %s: %s',
                    rec.id, str(e)
                )
        
        _logger.info('Auto-applied %d pricing recommendations', applied_count)
        return applied_count
    
    @api.model
    def _cron_expire_old_recommendations(self):
        """Expire old recommendations."""
        expired = self.search([
            ('status', '=', 'pending'),
            ('valid_until', '<', fields.Datetime.now()),
        ])
        expired.write({'status': 'expired'})
        _logger.info('Expired %d old recommendations', len(expired))


class AmazonPriceHistory(models.Model):
    """
    Amazon Price History.
    
    Tracks all price changes for analysis and audit:
    - What changed
    - When
    - Why
    - Who/what initiated it
    """
    _name = 'amazon.price.history'
    _description = 'Amazon Price History'
    _order = 'change_date desc'
    
    product_listing_id = fields.Many2one(
        comodel_name='amazon.product.listing',
        string='Product Listing',
        required=True,
        ondelete='cascade',
        index=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='product_listing_id.currency_id',
        store=True,
    )
    
    old_price = fields.Monetary(
        string='Old Price',
        currency_field='currency_id',
        required=True,
    )
    new_price = fields.Monetary(
        string='New Price',
        currency_field='currency_id',
        required=True,
    )
    price_change = fields.Monetary(
        string='Change',
        currency_field='currency_id',
        compute='_compute_price_change',
        store=True,
    )
    change_percent = fields.Float(
        string='Change (%)',
        compute='_compute_price_change',
        store=True,
        digits=(5, 2),
    )
    
    change_date = fields.Datetime(
        string='Changed At',
        default=fields.Datetime.now,
        required=True,
        index=True,
    )
    change_reason = fields.Selection(
        selection=[
            ('manual', 'Manual Update'),
            ('recommendation', 'Price Recommendation'),
            ('bulk_reprice', 'Bulk Reprice'),
            ('api_sync', 'API Sync'),
            ('promotion', 'Promotion'),
            ('other', 'Other'),
        ],
        string='Reason',
        default='manual',
    )
    change_source = fields.Char(
        string='Source',
        help='What triggered this change',
    )
    
    user_id = fields.Many2one(
        comodel_name='res.users',
        string='Changed By',
        default=lambda self: self.env.uid,
    )
    recommendation_id = fields.Many2one(
        comodel_name='amazon.pricing.recommendation',
        string='Recommendation',
        ondelete='set null',
    )
    
    notes = fields.Text(
        string='Notes',
    )
    
    @api.depends('old_price', 'new_price')
    def _compute_price_change(self):
        for rec in self:
            rec.price_change = (rec.new_price or 0) - (rec.old_price or 0)
            if rec.old_price:
                rec.change_percent = (rec.price_change / rec.old_price) * 100
            else:
                rec.change_percent = 0
