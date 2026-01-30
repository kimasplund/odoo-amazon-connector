# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

"""
Amazon Bulk Reprice Wizard

Allows repricing multiple products at once with various strategies:
- Match lowest competitor
- Beat by fixed amount
- Beat by percentage
- Target margin
- Apply custom rule

Includes preview before applying changes.
"""

import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AmazonBulkRepriceWizard(models.TransientModel):
    """Wizard for bulk repricing Amazon products."""
    
    _name = 'amazon.bulk.reprice.wizard'
    _description = 'Amazon Bulk Reprice Wizard'
    
    # =========================================================================
    # SELECTION VALUES
    # =========================================================================
    
    STRATEGY_TYPES = [
        ('match_lowest', 'Match Lowest Price'),
        ('beat_by_amount', 'Beat by Fixed Amount'),
        ('beat_by_percent', 'Beat by Percentage'),
        ('target_margin', 'Target Profit Margin'),
        ('fixed_price', 'Set Fixed Price'),
        ('adjust_percent', 'Adjust by Percentage'),
        ('apply_rule', 'Apply Pricing Rule'),
    ]
    
    # =========================================================================
    # FIELDS - Selection
    # =========================================================================
    
    account_id = fields.Many2one(
        comodel_name='amazon.account',
        string='Amazon Account',
        required=True,
        default=lambda self: self._default_account_id(),
    )
    marketplace_id = fields.Many2one(
        comodel_name='amazon.marketplace',
        string='Marketplace',
        domain="[('account_ids', 'in', account_id)]",
    )
    product_listing_ids = fields.Many2many(
        comodel_name='amazon.product.listing',
        string='Product Listings',
        domain="[('account_id', '=', account_id), ('state', '=', 'active')]",
    )
    select_all = fields.Boolean(
        string='Select All Active Listings',
        default=False,
    )
    
    # =========================================================================
    # FIELDS - Strategy
    # =========================================================================
    
    strategy = fields.Selection(
        selection=STRATEGY_TYPES,
        string='Repricing Strategy',
        required=True,
        default='match_lowest',
    )
    pricing_rule_id = fields.Many2one(
        comodel_name='amazon.pricing.rule',
        string='Pricing Rule',
        domain="[('account_id', '=', account_id), ('is_active', '=', True)]",
        help='Apply this pricing rule to selected listings',
    )
    
    # =========================================================================
    # FIELDS - Strategy Parameters
    # =========================================================================
    
    beat_amount = fields.Float(
        string='Beat by Amount',
        digits=(10, 2),
        help='Undercut competitor by this fixed amount',
    )
    beat_percent = fields.Float(
        string='Beat by Percent (%)',
        digits=(5, 2),
        help='Undercut competitor by this percentage',
    )
    target_margin = fields.Float(
        string='Target Margin (%)',
        digits=(5, 2),
        default=15.0,
        help='Desired profit margin percentage',
    )
    fixed_price = fields.Float(
        string='Fixed Price',
        digits=(10, 2),
        help='Set all products to this price',
    )
    adjust_percent = fields.Float(
        string='Adjust by (%)',
        digits=(5, 2),
        help='Increase (positive) or decrease (negative) price by this %',
    )
    
    # =========================================================================
    # FIELDS - Guardrails
    # =========================================================================
    
    apply_min_price = fields.Boolean(
        string='Apply Minimum Price',
        default=True,
        help='Respect each listing\'s minimum price setting',
    )
    apply_max_price = fields.Boolean(
        string='Apply Maximum Price',
        default=True,
        help='Respect each listing\'s maximum price setting',
    )
    global_min_price = fields.Float(
        string='Global Minimum Price',
        digits=(10, 2),
        help='Override: Never go below this price',
    )
    global_max_price = fields.Float(
        string='Global Maximum Price',
        digits=(10, 2),
        help='Override: Never exceed this price',
    )
    min_margin = fields.Float(
        string='Minimum Margin (%)',
        digits=(5, 2),
        default=5.0,
        help='Never reprice below this margin',
    )
    max_change_percent = fields.Float(
        string='Max Change (%)',
        digits=(5, 2),
        default=20.0,
        help='Maximum allowed price change in single reprice',
    )
    
    # =========================================================================
    # FIELDS - Preview
    # =========================================================================
    
    preview_line_ids = fields.One2many(
        comodel_name='amazon.bulk.reprice.wizard.line',
        inverse_name='wizard_id',
        string='Preview',
    )
    total_listings = fields.Integer(
        string='Total Listings',
        compute='_compute_summary',
    )
    listings_to_change = fields.Integer(
        string='Listings to Change',
        compute='_compute_summary',
    )
    avg_change_percent = fields.Float(
        string='Avg Change (%)',
        compute='_compute_summary',
        digits=(5, 2),
    )
    total_price_decrease = fields.Float(
        string='Total Price Decrease',
        compute='_compute_summary',
        digits=(10, 2),
    )
    total_price_increase = fields.Float(
        string='Total Price Increase',
        compute='_compute_summary',
        digits=(10, 2),
    )
    
    # =========================================================================
    # FIELDS - Execution
    # =========================================================================
    
    state = fields.Selection(
        selection=[
            ('config', 'Configuration'),
            ('preview', 'Preview'),
            ('done', 'Done'),
        ],
        string='State',
        default='config',
    )
    error_message = fields.Text(
        string='Errors',
        readonly=True,
    )
    success_count = fields.Integer(
        string='Successful Updates',
        readonly=True,
    )
    error_count = fields.Integer(
        string='Failed Updates',
        readonly=True,
    )
    
    # =========================================================================
    # DEFAULTS
    # =========================================================================
    
    @api.model
    def _default_account_id(self):
        """Default to first active account or from context."""
        if self._context.get('default_account_id'):
            return self._context['default_account_id']
        return self.env['amazon.account'].search([
            ('state', '=', 'active'),
        ], limit=1).id
    
    # =========================================================================
    # COMPUTE
    # =========================================================================
    
    @api.depends('preview_line_ids', 'preview_line_ids.include')
    def _compute_summary(self):
        for wizard in self:
            lines = wizard.preview_line_ids
            included = lines.filtered('include')
            
            wizard.total_listings = len(lines)
            wizard.listings_to_change = len(included)
            
            if included:
                changes = included.mapped('change_percent')
                wizard.avg_change_percent = sum(changes) / len(changes)
                
                wizard.total_price_decrease = sum(
                    l.price_change for l in included if l.price_change < 0
                )
                wizard.total_price_increase = sum(
                    l.price_change for l in included if l.price_change > 0
                )
            else:
                wizard.avg_change_percent = 0
                wizard.total_price_decrease = 0
                wizard.total_price_increase = 0
    
    # =========================================================================
    # ONCHANGE
    # =========================================================================
    
    @api.onchange('select_all', 'account_id', 'marketplace_id')
    def _onchange_select_all(self):
        if self.select_all and self.account_id:
            domain = [
                ('account_id', '=', self.account_id.id),
                ('state', '=', 'active'),
                ('list_price', '>', 0),
            ]
            if self.marketplace_id:
                domain.append(('marketplace_id', '=', self.marketplace_id.id))
            
            self.product_listing_ids = self.env['amazon.product.listing'].search(domain)
    
    @api.onchange('strategy')
    def _onchange_strategy(self):
        """Reset strategy-specific fields when strategy changes."""
        self.beat_amount = 0
        self.beat_percent = 0
        self.fixed_price = 0
        self.adjust_percent = 0
        
        # Set sensible defaults
        if self.strategy == 'beat_by_amount':
            self.beat_amount = 0.01
        elif self.strategy == 'beat_by_percent':
            self.beat_percent = 1.0
        elif self.strategy == 'target_margin':
            self.target_margin = 15.0
    
    # =========================================================================
    # ACTIONS
    # =========================================================================
    
    def action_generate_preview(self):
        """Generate preview of price changes."""
        self.ensure_one()
        
        if not self.product_listing_ids:
            raise UserError(_('Please select at least one product listing.'))
        
        # Clear existing preview lines
        self.preview_line_ids.unlink()
        
        CompetitorPrice = self.env['amazon.competitor.price']
        preview_lines = []
        
        for listing in self.product_listing_ids:
            # Get competitor prices
            competitor_prices = CompetitorPrice.get_latest_for_listing(
                listing.id, max_age_hours=24
            )
            
            # Calculate new price based on strategy
            new_price, reason, warnings = self._calculate_new_price(
                listing, competitor_prices
            )
            
            # Apply guardrails
            new_price, guardrail_warning = self._apply_guardrails(
                listing, new_price
            )
            
            if guardrail_warning:
                warnings.append(guardrail_warning)
            
            # Calculate change
            current_price = listing.list_price or 0
            price_change = new_price - current_price
            change_percent = (price_change / current_price * 100) if current_price else 0
            
            # Determine if we should include by default
            include = True
            if abs(change_percent) < 0.1:  # Less than 0.1% change
                include = False
            if abs(change_percent) > self.max_change_percent:
                include = False
                warnings.append(f'Change exceeds max {self.max_change_percent}%')
            
            preview_lines.append({
                'wizard_id': self.id,
                'product_listing_id': listing.id,
                'current_price': current_price,
                'new_price': new_price,
                'price_change': price_change,
                'change_percent': change_percent,
                'lowest_competitor': min(competitor_prices.mapped('competitor_price')) if competitor_prices else 0,
                'buybox_price': listing.buybox_price or 0,
                'we_have_buybox': listing.is_buybox_winner,
                'reason': reason,
                'warnings': ', '.join(warnings) if warnings else False,
                'include': include,
            })
        
        self.env['amazon.bulk.reprice.wizard.line'].create(preview_lines)
        
        self.state = 'preview'
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
    
    def _calculate_new_price(self, listing, competitor_prices):
        """
        Calculate new price based on selected strategy.
        
        Returns:
            tuple: (new_price, reason, warnings_list)
        """
        warnings = []
        current_price = listing.list_price or 0
        
        if self.strategy == 'match_lowest':
            if not competitor_prices:
                return current_price, 'no_competitors', ['No competitor data']
            
            lowest = min(competitor_prices.mapped('competitor_price'))
            return lowest, 'match_lowest', warnings
        
        elif self.strategy == 'beat_by_amount':
            if not competitor_prices:
                return current_price, 'no_competitors', ['No competitor data']
            
            lowest = min(competitor_prices.mapped('competitor_price'))
            new_price = lowest - self.beat_amount
            return max(new_price, 0.01), 'beat_amount', warnings
        
        elif self.strategy == 'beat_by_percent':
            if not competitor_prices:
                return current_price, 'no_competitors', ['No competitor data']
            
            lowest = min(competitor_prices.mapped('competitor_price'))
            new_price = lowest * (1 - self.beat_percent / 100)
            return max(new_price, 0.01), 'beat_percent', warnings
        
        elif self.strategy == 'target_margin':
            cost = listing.landed_cost
            if not cost:
                warnings.append('No cost data')
                return current_price, 'no_cost', warnings
            
            # Estimate fees
            referral_pct = listing.referral_fee_percent or 15
            fba_fee = listing.fba_fee or 0 if listing.is_fba else 0
            
            # Calculate price for target margin
            margin = self.target_margin / 100
            if margin >= 1:
                margin = 0.5
            
            # price * (1 - margin) = cost + referral + fba_fee
            # price - price*margin = cost + price*referral_pct/100 + fba_fee
            # price * (1 - margin - referral_pct/100) = cost + fba_fee
            effective_rate = 1 - margin - (referral_pct / 100)
            
            if effective_rate <= 0:
                warnings.append('Target margin too high')
                return current_price, 'margin_too_high', warnings
            
            new_price = (cost + fba_fee) / effective_rate
            return new_price, 'target_margin', warnings
        
        elif self.strategy == 'fixed_price':
            return self.fixed_price, 'fixed_price', warnings
        
        elif self.strategy == 'adjust_percent':
            new_price = current_price * (1 + self.adjust_percent / 100)
            return max(new_price, 0.01), 'adjust_percent', warnings
        
        elif self.strategy == 'apply_rule':
            if not self.pricing_rule_id:
                return current_price, 'no_rule', ['No rule selected']
            
            result = self.pricing_rule_id.calculate_recommended_price(
                listing, competitor_prices
            )
            return result['recommended_price'], result['reason'], warnings
        
        return current_price, 'unknown', warnings
    
    def _apply_guardrails(self, listing, price):
        """
        Apply price guardrails.
        
        Returns:
            tuple: (adjusted_price, warning_message_or_none)
        """
        warning = None
        
        # Apply listing min price
        if self.apply_min_price and listing.minimum_price:
            if price < listing.minimum_price:
                price = listing.minimum_price
                warning = 'Adjusted to listing min price'
        
        # Apply listing max price
        if self.apply_max_price and listing.maximum_price:
            if price > listing.maximum_price:
                price = listing.maximum_price
                warning = 'Adjusted to listing max price'
        
        # Apply global min
        if self.global_min_price and price < self.global_min_price:
            price = self.global_min_price
            warning = 'Adjusted to global min price'
        
        # Apply global max
        if self.global_max_price and price > self.global_max_price:
            price = self.global_max_price
            warning = 'Adjusted to global max price'
        
        # Apply minimum margin
        if self.min_margin and listing.landed_cost:
            min_price = self._calc_min_price_for_margin(listing, self.min_margin)
            if price < min_price:
                price = min_price
                warning = f'Adjusted to min margin ({self.min_margin}%)'
        
        return price, warning
    
    def _calc_min_price_for_margin(self, listing, margin_percent):
        """Calculate minimum price to achieve margin."""
        cost = listing.landed_cost or 0
        referral_pct = listing.referral_fee_percent or 15
        fba_fee = listing.fba_fee or 0 if listing.is_fba else 0
        margin = margin_percent / 100
        
        effective_rate = 1 - margin - (referral_pct / 100)
        if effective_rate <= 0:
            effective_rate = 0.5
        
        return (cost + fba_fee) / effective_rate
    
    def action_apply_prices(self):
        """Apply the previewed price changes."""
        self.ensure_one()
        
        lines_to_apply = self.preview_line_ids.filtered('include')
        
        if not lines_to_apply:
            raise UserError(_('No listings selected for repricing.'))
        
        success_count = 0
        error_count = 0
        errors = []
        
        PriceHistory = self.env['amazon.price.history']
        
        for line in lines_to_apply:
            try:
                listing = line.product_listing_id
                
                # Create price history record
                PriceHistory.create({
                    'product_listing_id': listing.id,
                    'old_price': line.current_price,
                    'new_price': line.new_price,
                    'change_reason': 'bulk_reprice',
                    'change_source': f'Bulk reprice: {self.strategy}',
                    'notes': line.reason,
                })
                
                # Update listing price
                listing.write({
                    'list_price': line.new_price,
                })
                
                success_count += 1
                
            except Exception as e:
                error_count += 1
                errors.append(f'{line.product_listing_id.sku}: {str(e)}')
                _logger.error(
                    'Error updating price for %s: %s',
                    line.product_listing_id.sku, str(e)
                )
        
        self.write({
            'state': 'done',
            'success_count': success_count,
            'error_count': error_count,
            'error_message': '\n'.join(errors) if errors else False,
        })
        
        # Trigger Amazon price sync for updated listings
        if success_count > 0:
            listings_to_sync = lines_to_apply.mapped('product_listing_id')
            # Queue the price update to Amazon (implement as needed)
            _logger.info(
                'Bulk reprice complete: %d updated, %d errors',
                success_count, error_count
            )
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
    
    def action_back_to_config(self):
        """Go back to configuration step."""
        self.write({
            'state': 'config',
        })
        self.preview_line_ids.unlink()
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
    
    def action_select_all_preview(self):
        """Select all preview lines."""
        self.preview_line_ids.write({'include': True})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
    
    def action_deselect_all_preview(self):
        """Deselect all preview lines."""
        self.preview_line_ids.write({'include': False})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class AmazonBulkRepriceWizardLine(models.TransientModel):
    """Preview line for bulk reprice wizard."""
    
    _name = 'amazon.bulk.reprice.wizard.line'
    _description = 'Amazon Bulk Reprice Wizard Line'
    _order = 'change_percent desc'
    
    wizard_id = fields.Many2one(
        comodel_name='amazon.bulk.reprice.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    product_listing_id = fields.Many2one(
        comodel_name='amazon.product.listing',
        string='Listing',
        required=True,
    )
    sku = fields.Char(
        related='product_listing_id.sku',
        string='SKU',
    )
    asin = fields.Char(
        related='product_listing_id.asin',
        string='ASIN',
    )
    title = fields.Char(
        related='product_listing_id.title',
        string='Title',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        related='product_listing_id.currency_id',
    )
    
    current_price = fields.Monetary(
        string='Current Price',
        currency_field='currency_id',
    )
    new_price = fields.Monetary(
        string='New Price',
        currency_field='currency_id',
    )
    price_change = fields.Monetary(
        string='Change',
        currency_field='currency_id',
    )
    change_percent = fields.Float(
        string='Change (%)',
        digits=(5, 2),
    )
    
    lowest_competitor = fields.Monetary(
        string='Lowest Competitor',
        currency_field='currency_id',
    )
    buybox_price = fields.Monetary(
        string='Buy Box Price',
        currency_field='currency_id',
    )
    we_have_buybox = fields.Boolean(
        string='We Have BB',
    )
    
    reason = fields.Char(
        string='Reason',
    )
    warnings = fields.Char(
        string='Warnings',
    )
    include = fields.Boolean(
        string='Include',
        default=True,
    )


class AmazonPricingRecommendationDismissWizard(models.TransientModel):
    """Wizard to dismiss pricing recommendations with reason."""
    
    _name = 'amazon.pricing.recommendation.dismiss.wizard'
    _description = 'Dismiss Pricing Recommendation'
    
    recommendation_ids = fields.Many2many(
        comodel_name='amazon.pricing.recommendation',
        relation='amz_price_rec_dismiss_wiz_rel',
        string='Recommendations',
    )
    dismiss_reason = fields.Selection(
        selection=[
            ('price_war', 'Avoiding price war'),
            ('out_of_stock', 'Product out of stock'),
            ('seasonal', 'Seasonal pricing'),
            ('brand_image', 'Maintaining brand image'),
            ('competitor_issue', 'Competitor pricing issue'),
            ('manual_override', 'Manual pricing decision'),
            ('other', 'Other'),
        ],
        string='Reason',
        required=True,
    )
    notes = fields.Text(
        string='Notes',
    )
    
    def action_dismiss(self):
        """Dismiss the recommendations."""
        reason_label = dict(self._fields['dismiss_reason'].selection).get(
            self.dismiss_reason, self.dismiss_reason
        )
        
        dismiss_text = reason_label
        if self.notes:
            dismiss_text += f': {self.notes}'
        
        self.recommendation_ids.write({
            'status': 'dismissed',
            'dismissed_reason': dismiss_text,
        })
        
        return {'type': 'ir.actions.act_window_close'}
