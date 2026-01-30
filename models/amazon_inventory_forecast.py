# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging
import math
from datetime import datetime, timedelta
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmazonInventoryForecast(models.Model):
    """
    Amazon Inventory Forecast.
    
    Provides predictive inventory intelligence including:
    - Sales velocity calculation (7/30/90 day)
    - Demand forecasting with trend and seasonality
    - Restock recommendations with lead time consideration
    - Stockout risk assessment
    - Overstock detection
    """
    _name = 'amazon.inventory.forecast'
    _description = 'Amazon Inventory Forecast'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'stockout_risk_score desc, product_id'
    _rec_name = 'display_name'

    # -------------------------------------------------------------------------
    # FIELDS - Core
    # -------------------------------------------------------------------------
    
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )
    active = fields.Boolean(default=True)
    
    # Relationships
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        ondelete='cascade',
        index=True,
    )
    marketplace_id = fields.Many2one(
        'amazon.marketplace',
        string='Marketplace',
        required=True,
        ondelete='cascade',
        index=True,
    )
    account_id = fields.Many2one(
        'amazon.account',
        string='Amazon Account',
        required=True,
        ondelete='cascade',
        index=True,
    )
    fba_inventory_id = fields.Many2one(
        'amazon.fba.inventory',
        string='FBA Inventory Record',
        compute='_compute_fba_inventory',
        store=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='marketplace_id.currency_id',
        store=True,
    )
    
    # Product info (for quick display)
    product_sku = fields.Char(
        string='SKU',
        related='product_id.default_code',
        store=True,
    )
    product_name = fields.Char(
        string='Product Name',
        related='product_id.name',
        store=True,
    )
    
    # -------------------------------------------------------------------------
    # FIELDS - Current Inventory
    # -------------------------------------------------------------------------
    
    current_stock = fields.Integer(
        string='Current Stock',
        help='Current available inventory at FBA.',
    )
    current_reserved = fields.Integer(
        string='Reserved',
        help='Inventory reserved for orders.',
    )
    current_inbound = fields.Integer(
        string='Inbound',
        help='Total inbound inventory.',
    )
    total_available = fields.Integer(
        string='Total Available',
        compute='_compute_total_available',
        store=True,
        help='Current stock + inbound.',
    )
    
    # -------------------------------------------------------------------------
    # FIELDS - Sales Velocity
    # -------------------------------------------------------------------------
    
    sales_velocity_7d = fields.Float(
        string='7-Day Velocity',
        digits=(16, 2),
        help='Average units sold per day over last 7 days.',
    )
    sales_velocity_30d = fields.Float(
        string='30-Day Velocity',
        digits=(16, 2),
        help='Average units sold per day over last 30 days.',
    )
    sales_velocity_90d = fields.Float(
        string='90-Day Velocity',
        digits=(16, 2),
        help='Average units sold per day over last 90 days.',
    )
    weighted_velocity = fields.Float(
        string='Weighted Velocity',
        digits=(16, 2),
        compute='_compute_weighted_velocity',
        store=True,
        help='Weighted average velocity (recent data weighted higher).',
    )
    
    velocity_trend = fields.Selection(
        selection=[
            ('increasing', 'Increasing ↑'),
            ('stable', 'Stable →'),
            ('decreasing', 'Decreasing ↓'),
        ],
        string='Velocity Trend',
        help='Sales trend direction based on weekly data.',
    )
    velocity_trend_percent = fields.Float(
        string='Trend %',
        digits=(16, 1),
        help='Weekly growth/decline percentage.',
    )
    
    seasonality_factor = fields.Float(
        string='Seasonality Factor',
        digits=(16, 2),
        default=1.0,
        help='Multiplier from same period last year (1.0 = no seasonality data).',
    )
    seasonality_confidence = fields.Selection(
        selection=[
            ('none', 'No Data'),
            ('low', 'Low (< 30 days)'),
            ('medium', 'Medium (30-180 days)'),
            ('high', 'High (> 180 days)'),
        ],
        string='Seasonality Confidence',
        default='none',
    )
    
    # -------------------------------------------------------------------------
    # FIELDS - Forecasts
    # -------------------------------------------------------------------------
    
    forecasted_demand_30d = fields.Integer(
        string='30-Day Forecast',
        help='Predicted demand for next 30 days.',
    )
    forecasted_demand_60d = fields.Integer(
        string='60-Day Forecast',
        help='Predicted demand for next 60 days.',
    )
    forecasted_demand_90d = fields.Integer(
        string='90-Day Forecast',
        help='Predicted demand for next 90 days.',
    )
    
    forecast_confidence = fields.Selection(
        selection=[
            ('low', 'Low'),
            ('medium', 'Medium'),
            ('high', 'High'),
        ],
        string='Forecast Confidence',
        default='low',
        help='Confidence level based on data quality and variance.',
    )
    forecast_variance = fields.Float(
        string='Forecast Variance',
        digits=(16, 2),
        help='Coefficient of variation in historical data.',
    )
    
    last_forecast_date = fields.Datetime(
        string='Last Forecast Date',
        help='When the forecast was last computed.',
    )
    data_points_available = fields.Integer(
        string='Data Points',
        help='Number of days with sales data.',
    )
    
    # -------------------------------------------------------------------------
    # FIELDS - Restock Recommendations
    # -------------------------------------------------------------------------
    
    # Configuration
    lead_time_days = fields.Integer(
        string='Lead Time (Days)',
        default=14,
        help='Days from restock decision to FBA availability.',
    )
    safety_stock_days = fields.Integer(
        string='Safety Stock (Days)',
        default=7,
        help='Buffer stock in days of supply.',
    )
    target_stock_days = fields.Integer(
        string='Target Stock (Days)',
        default=60,
        help='Target days of supply after restock.',
    )
    
    # Computed recommendations
    recommended_restock_qty = fields.Integer(
        string='Recommended Restock Qty',
        compute='_compute_restock_recommendation',
        store=True,
    )
    recommended_restock_date = fields.Date(
        string='Restock By',
        compute='_compute_restock_recommendation',
        store=True,
    )
    
    # -------------------------------------------------------------------------
    # FIELDS - Stockout Risk
    # -------------------------------------------------------------------------
    
    days_until_stockout = fields.Integer(
        string='Days Until Stockout',
        compute='_compute_stockout_risk',
        store=True,
        help='Estimated days until out of stock.',
    )
    estimated_stockout_date = fields.Date(
        string='Est. Stockout Date',
        compute='_compute_stockout_risk',
        store=True,
    )
    stockout_risk = fields.Selection(
        selection=[
            ('none', 'None'),
            ('low', 'Low'),
            ('medium', 'Medium'),
            ('high', 'High'),
            ('critical', 'Critical'),
        ],
        string='Stockout Risk',
        compute='_compute_stockout_risk',
        store=True,
    )
    stockout_risk_score = fields.Integer(
        string='Risk Score',
        compute='_compute_stockout_risk',
        store=True,
        help='Numeric risk score for sorting (0-100).',
    )
    
    # -------------------------------------------------------------------------
    # FIELDS - Overstock Detection
    # -------------------------------------------------------------------------
    
    days_of_supply = fields.Float(
        string='Days of Supply',
        digits=(16, 1),
        compute='_compute_overstock',
        store=True,
        help='Current inventory / daily velocity.',
    )
    is_overstock = fields.Boolean(
        string='Is Overstock',
        compute='_compute_overstock',
        store=True,
        help='True if > 180 days of supply.',
    )
    overstock_threshold_days = fields.Integer(
        string='Overstock Threshold',
        default=180,
        help='Days of supply considered overstock.',
    )
    recommended_removal_qty = fields.Integer(
        string='Recommended Removal',
        compute='_compute_overstock',
        store=True,
        help='Units to remove to reach optimal inventory.',
    )
    estimated_storage_cost = fields.Monetary(
        string='Est. Storage Cost',
        currency_field='currency_id',
        compute='_compute_overstock',
        store=True,
        help='Estimated monthly storage cost.',
    )
    
    # -------------------------------------------------------------------------
    # FIELDS - Historical Performance
    # -------------------------------------------------------------------------
    
    total_sales_90d = fields.Integer(
        string='Total Sales (90d)',
        help='Total units sold in last 90 days.',
    )
    total_revenue_90d = fields.Monetary(
        string='Total Revenue (90d)',
        currency_field='currency_id',
        help='Total revenue in last 90 days.',
    )
    stockout_days_90d = fields.Integer(
        string='Stockout Days (90d)',
        help='Days out of stock in last 90 days.',
    )
    
    # -------------------------------------------------------------------------
    # COMPUTES
    # -------------------------------------------------------------------------
    
    @api.depends('product_id', 'marketplace_id')
    def _compute_display_name(self):
        for record in self:
            parts = []
            if record.product_sku:
                parts.append(record.product_sku)
            elif record.product_id:
                parts.append(record.product_id.name[:30])
            if record.marketplace_id:
                parts.append(f'[{record.marketplace_id.code}]')
            record.display_name = ' '.join(parts) or _('New Forecast')
    
    @api.depends('product_id', 'marketplace_id', 'account_id')
    def _compute_fba_inventory(self):
        FBAInventory = self.env['amazon.fba.inventory']
        for record in self:
            if record.product_id and record.marketplace_id and record.account_id:
                inventory = FBAInventory.search([
                    ('product_id', '=', record.product_id.id),
                    ('marketplace_id', '=', record.marketplace_id.id),
                    ('account_id', '=', record.account_id.id),
                ], limit=1)
                record.fba_inventory_id = inventory.id if inventory else False
            else:
                record.fba_inventory_id = False
    
    @api.depends('current_stock', 'current_inbound')
    def _compute_total_available(self):
        for record in self:
            record.total_available = record.current_stock + record.current_inbound
    
    @api.depends('sales_velocity_7d', 'sales_velocity_30d', 'sales_velocity_90d')
    def _compute_weighted_velocity(self):
        """
        Compute weighted velocity giving more weight to recent data.
        Weights: 7d=50%, 30d=30%, 90d=20%
        """
        for record in self:
            v7 = record.sales_velocity_7d or 0
            v30 = record.sales_velocity_30d or 0
            v90 = record.sales_velocity_90d or 0
            
            # If no short-term data, fall back to longer term
            if v7 == 0 and v30 == 0:
                record.weighted_velocity = v90
            elif v7 == 0:
                record.weighted_velocity = v30 * 0.6 + v90 * 0.4
            else:
                record.weighted_velocity = v7 * 0.5 + v30 * 0.3 + v90 * 0.2
    
    @api.depends(
        'weighted_velocity', 'velocity_trend_percent', 'seasonality_factor',
        'lead_time_days', 'safety_stock_days', 'target_stock_days',
        'current_stock', 'current_inbound'
    )
    def _compute_restock_recommendation(self):
        """
        Calculate recommended restock quantity and date.
        
        Formula:
        - stockout_date = today + (current_stock / velocity)
        - restock_order_date = stockout_date - lead_time - safety_buffer
        - restock_qty = (lead_time + safety_days + target_days) * velocity - current_stock - inbound
        """
        today = fields.Date.today()
        
        for record in self:
            velocity = record.weighted_velocity
            
            if velocity <= 0:
                record.recommended_restock_qty = 0
                record.recommended_restock_date = False
                continue
            
            # Apply trend adjustment (limit to ±30%)
            trend_factor = 1.0
            if record.velocity_trend_percent:
                trend_factor = 1.0 + max(-0.3, min(0.3, record.velocity_trend_percent / 100))
            
            # Apply seasonality
            season_factor = record.seasonality_factor or 1.0
            
            # Adjusted velocity for forecasting
            adjusted_velocity = velocity * trend_factor * season_factor
            
            # Calculate when we'll run out
            total_stock = record.current_stock + record.current_inbound
            if adjusted_velocity > 0:
                days_to_stockout = total_stock / adjusted_velocity
            else:
                days_to_stockout = 999
            
            # Calculate restock date (when we need to place the order)
            restock_trigger_days = days_to_stockout - record.lead_time_days - record.safety_stock_days
            
            if restock_trigger_days <= 0:
                # Need to restock now!
                record.recommended_restock_date = today
            elif restock_trigger_days < 365:
                record.recommended_restock_date = today + timedelta(days=int(restock_trigger_days))
            else:
                record.recommended_restock_date = False
            
            # Calculate restock quantity
            # Target: have target_stock_days of supply after restock arrives
            total_days_needed = record.lead_time_days + record.safety_stock_days + record.target_stock_days
            target_inventory = int(math.ceil(total_days_needed * adjusted_velocity))
            
            restock_qty = max(0, target_inventory - total_stock)
            
            # Round to reasonable quantities (optional: could use supplier MOQ)
            if restock_qty > 0 and restock_qty < 10:
                restock_qty = 10  # Minimum order
            elif restock_qty > 0:
                restock_qty = int(math.ceil(restock_qty / 10) * 10)  # Round up to 10s
            
            record.recommended_restock_qty = restock_qty
    
    @api.depends('weighted_velocity', 'current_stock', 'current_inbound', 'lead_time_days')
    def _compute_stockout_risk(self):
        """
        Calculate stockout risk based on days of supply vs lead time.
        
        Risk levels:
        - Critical: < lead_time days
        - High: < lead_time + 7 days
        - Medium: < lead_time + 14 days
        - Low: < lead_time + 30 days
        - None: > lead_time + 30 days
        """
        today = fields.Date.today()
        
        for record in self:
            velocity = record.weighted_velocity
            total_stock = record.current_stock + record.current_inbound
            
            if velocity <= 0:
                # No sales = no stockout risk (but might be dead stock)
                record.days_until_stockout = 9999
                record.estimated_stockout_date = False
                record.stockout_risk = 'none'
                record.stockout_risk_score = 0
                continue
            
            days_until = total_stock / velocity
            record.days_until_stockout = int(days_until)
            
            if days_until < 9999:
                record.estimated_stockout_date = today + timedelta(days=int(days_until))
            else:
                record.estimated_stockout_date = False
            
            lead_time = record.lead_time_days or 14
            
            # Determine risk level
            if days_until <= lead_time:
                record.stockout_risk = 'critical'
                record.stockout_risk_score = 100
            elif days_until <= lead_time + 7:
                record.stockout_risk = 'high'
                record.stockout_risk_score = 80
            elif days_until <= lead_time + 14:
                record.stockout_risk = 'medium'
                record.stockout_risk_score = 60
            elif days_until <= lead_time + 30:
                record.stockout_risk = 'low'
                record.stockout_risk_score = 30
            else:
                record.stockout_risk = 'none'
                record.stockout_risk_score = 0
    
    @api.depends('weighted_velocity', 'current_stock', 'overstock_threshold_days', 'target_stock_days')
    def _compute_overstock(self):
        """
        Calculate overstock metrics.
        """
        for record in self:
            velocity = record.weighted_velocity
            
            if velocity <= 0:
                # No velocity - can't compute days of supply
                record.days_of_supply = 9999 if record.current_stock > 0 else 0
                record.is_overstock = record.current_stock > 0
                record.recommended_removal_qty = record.current_stock if record.current_stock > 10 else 0
                record.estimated_storage_cost = 0
                continue
            
            record.days_of_supply = record.current_stock / velocity
            
            threshold = record.overstock_threshold_days or 180
            record.is_overstock = record.days_of_supply > threshold
            
            if record.is_overstock:
                # Recommend removing excess above target + buffer
                target_days = record.target_stock_days or 60
                optimal_stock = int(math.ceil((target_days + 30) * velocity))  # +30 buffer
                record.recommended_removal_qty = max(0, record.current_stock - optimal_stock)
            else:
                record.recommended_removal_qty = 0
            
            # Estimate storage cost (simplified: $0.75/unit/month for standard)
            record.estimated_storage_cost = record.current_stock * 0.75
    
    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------
    
    _sql_constraints = [
        (
            'unique_product_marketplace_account',
            'UNIQUE(product_id, marketplace_id, account_id)',
            'Forecast record must be unique per product/marketplace/account!'
        ),
    ]
    
    # -------------------------------------------------------------------------
    # FORECASTING METHODS
    # -------------------------------------------------------------------------
    
    def compute_sales_velocity(self):
        """
        Compute sales velocity from order history.
        """
        self.ensure_one()
        DemandHistory = self.env['amazon.demand.history']
        today = fields.Date.today()
        
        # Get historical data
        history = DemandHistory.search([
            ('product_id', '=', self.product_id.id),
            ('marketplace_id', '=', self.marketplace_id.id),
            ('date', '>=', today - timedelta(days=90)),
        ], order='date desc')
        
        if not history:
            _logger.info('No demand history for forecast %s', self.display_name)
            return
        
        # Calculate velocities for different periods
        sales_7d = sum(h.net_units for h in history if h.date >= today - timedelta(days=7))
        sales_30d = sum(h.net_units for h in history if h.date >= today - timedelta(days=30))
        sales_90d = sum(h.net_units for h in history)
        
        days_7 = len([h for h in history if h.date >= today - timedelta(days=7)])
        days_30 = len([h for h in history if h.date >= today - timedelta(days=30)])
        days_90 = len(history)
        
        vals = {
            'sales_velocity_7d': sales_7d / max(days_7, 1),
            'sales_velocity_30d': sales_30d / max(days_30, 1),
            'sales_velocity_90d': sales_90d / max(days_90, 1),
            'total_sales_90d': sales_90d,
            'total_revenue_90d': sum(history.mapped('revenue')),
            'stockout_days_90d': len(history.filtered('is_stockout')),
            'data_points_available': days_90,
        }
        
        self.write(vals)
        return vals
    
    def compute_velocity_trend(self):
        """
        Compute velocity trend using linear regression on weekly data.
        """
        self.ensure_one()
        DemandHistory = self.env['amazon.demand.history']
        
        # Get weekly aggregates
        weekly_data = DemandHistory.get_weekly_aggregates(
            self.product_id.id,
            self.marketplace_id.id,
            weeks=8
        )
        
        if len(weekly_data) < 4:
            self.write({
                'velocity_trend': 'stable',
                'velocity_trend_percent': 0,
            })
            return
        
        # Simple linear regression on weekly sales
        n = len(weekly_data)
        x_vals = list(range(n))
        y_vals = [w['adjusted_units'] for w in weekly_data]
        
        x_mean = sum(x_vals) / n
        y_mean = sum(y_vals) / n
        
        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
        denominator = sum((x - x_mean) ** 2 for x in x_vals)
        
        if denominator == 0:
            slope = 0
        else:
            slope = numerator / denominator
        
        # Calculate trend percentage (weekly growth rate)
        if y_mean > 0:
            trend_percent = (slope / y_mean) * 100
        else:
            trend_percent = 0
        
        # Determine trend direction
        if trend_percent > 5:
            trend = 'increasing'
        elif trend_percent < -5:
            trend = 'decreasing'
        else:
            trend = 'stable'
        
        self.write({
            'velocity_trend': trend,
            'velocity_trend_percent': trend_percent,
        })
    
    def compute_seasonality(self):
        """
        Compute seasonality factor by comparing to same period last year.
        """
        self.ensure_one()
        DemandHistory = self.env['amazon.demand.history']
        today = fields.Date.today()
        
        # Get last year's data for same period
        last_year_data = DemandHistory.get_same_period_last_year(
            self.product_id.id,
            self.marketplace_id.id,
            today,
            days=30
        )
        
        if not last_year_data or last_year_data['days_with_data'] < 14:
            self.write({
                'seasonality_factor': 1.0,
                'seasonality_confidence': 'none',
            })
            return
        
        # Get current period data
        current_data = DemandHistory.search([
            ('product_id', '=', self.product_id.id),
            ('marketplace_id', '=', self.marketplace_id.id),
            ('date', '>=', today - timedelta(days=30)),
            ('date', '<=', today),
        ])
        
        if not current_data:
            self.write({
                'seasonality_factor': 1.0,
                'seasonality_confidence': 'none',
            })
            return
        
        current_avg = sum(current_data.mapped('units_sold')) / len(current_data)
        last_year_avg = last_year_data['avg_daily']
        
        if last_year_avg > 0:
            seasonality = current_avg / last_year_avg
            # Clamp to reasonable range
            seasonality = max(0.5, min(2.0, seasonality))
        else:
            seasonality = 1.0
        
        # Determine confidence
        data_points = last_year_data['days_with_data']
        if data_points >= 180:
            confidence = 'high'
        elif data_points >= 30:
            confidence = 'medium'
        else:
            confidence = 'low'
        
        self.write({
            'seasonality_factor': seasonality,
            'seasonality_confidence': confidence,
        })
    
    def generate_forecast(self):
        """
        Generate demand forecasts for 30/60/90 days.
        
        Algorithm:
        1. Get base velocity (weighted)
        2. Apply trend adjustment
        3. Apply seasonality
        4. Calculate variance for confidence
        """
        self.ensure_one()
        
        # First compute velocity and trend if not recent
        if not self.last_forecast_date or \
           self.last_forecast_date < datetime.now() - timedelta(hours=12):
            self.compute_sales_velocity()
            self.compute_velocity_trend()
            self.compute_seasonality()
        
        velocity = self.weighted_velocity
        
        if velocity <= 0:
            self.write({
                'forecasted_demand_30d': 0,
                'forecasted_demand_60d': 0,
                'forecasted_demand_90d': 0,
                'forecast_confidence': 'low',
                'last_forecast_date': fields.Datetime.now(),
            })
            return
        
        # Apply trend (compound over time, limited)
        trend_factor_30d = 1.0 + max(-0.15, min(0.15, self.velocity_trend_percent / 100))
        trend_factor_60d = trend_factor_30d ** 1.5
        trend_factor_90d = trend_factor_30d ** 2.0
        
        # Apply seasonality
        season = self.seasonality_factor or 1.0
        
        # Calculate forecasts
        forecast_30d = int(round(velocity * 30 * trend_factor_30d * season))
        forecast_60d = int(round(velocity * 60 * trend_factor_60d * season))
        forecast_90d = int(round(velocity * 90 * trend_factor_90d * season))
        
        # Calculate confidence based on data quality
        confidence = self._calculate_forecast_confidence()
        variance = self._calculate_forecast_variance()
        
        self.write({
            'forecasted_demand_30d': forecast_30d,
            'forecasted_demand_60d': forecast_60d,
            'forecasted_demand_90d': forecast_90d,
            'forecast_confidence': confidence,
            'forecast_variance': variance,
            'last_forecast_date': fields.Datetime.now(),
        })
    
    def _calculate_forecast_confidence(self):
        """
        Determine forecast confidence based on data quality.
        """
        self.ensure_one()
        
        # Factors affecting confidence
        data_points = self.data_points_available or 0
        stockout_rate = self.stockout_days_90d / max(data_points, 1) if data_points > 0 else 1
        has_seasonality = self.seasonality_confidence not in ('none', 'low')
        
        score = 0
        
        # Data points (max 40 points)
        if data_points >= 60:
            score += 40
        elif data_points >= 30:
            score += 25
        elif data_points >= 14:
            score += 15
        else:
            score += 5
        
        # Low stockout rate (max 30 points)
        if stockout_rate < 0.05:
            score += 30
        elif stockout_rate < 0.15:
            score += 20
        elif stockout_rate < 0.30:
            score += 10
        
        # Seasonality data (max 30 points)
        if has_seasonality:
            score += 30
        elif self.seasonality_confidence == 'low':
            score += 15
        
        if score >= 70:
            return 'high'
        elif score >= 40:
            return 'medium'
        else:
            return 'low'
    
    def _calculate_forecast_variance(self):
        """
        Calculate coefficient of variation in daily sales.
        """
        self.ensure_one()
        DemandHistory = self.env['amazon.demand.history']
        today = fields.Date.today()
        
        history = DemandHistory.search([
            ('product_id', '=', self.product_id.id),
            ('marketplace_id', '=', self.marketplace_id.id),
            ('date', '>=', today - timedelta(days=30)),
        ])
        
        if len(history) < 7:
            return 1.0  # High variance (no data)
        
        sales = [h.net_units for h in history]
        mean = sum(sales) / len(sales)
        
        if mean == 0:
            return 1.0
        
        variance = sum((x - mean) ** 2 for x in sales) / len(sales)
        std_dev = math.sqrt(variance)
        
        # Coefficient of variation
        cv = std_dev / mean
        
        return min(cv, 2.0)  # Cap at 2.0
    
    def calculate_restock_recommendation(self):
        """
        Public method to trigger restock calculation.
        The actual calculation is done in _compute_restock_recommendation.
        """
        self.ensure_one()
        # Touch fields to trigger recompute
        self.modified(['weighted_velocity', 'current_stock', 'current_inbound'])
        self.recompute()
        
        # Create suggestion if needed
        if self.recommended_restock_qty > 0:
            self._create_restock_suggestion()
    
    def _create_restock_suggestion(self):
        """
        Create a restock suggestion record.
        """
        self.ensure_one()
        Suggestion = self.env['amazon.restock.suggestion']
        
        # Check for existing pending suggestion
        existing = Suggestion.search([
            ('forecast_id', '=', self.id),
            ('status', '=', 'pending'),
            ('suggestion_type', '=', 'restock'),
        ], limit=1)
        
        if existing:
            # Update existing
            existing.write({
                'current_stock': self.current_stock,
                'forecasted_demand': self.forecasted_demand_30d,
                'recommended_qty': self.recommended_restock_qty,
                'estimated_stockout_date': self.estimated_stockout_date,
                'suggested_action_date': self.recommended_restock_date,
            })
            return existing
        
        # Determine priority
        if self.stockout_risk == 'critical':
            priority = 'critical'
        elif self.stockout_risk == 'high':
            priority = 'high'
        elif self.stockout_risk == 'medium':
            priority = 'medium'
        else:
            priority = 'low'
        
        # Create reason text
        reason = self._generate_restock_reason()
        
        return Suggestion.create({
            'forecast_id': self.id,
            'product_id': self.product_id.id,
            'marketplace_id': self.marketplace_id.id,
            'account_id': self.account_id.id,
            'suggestion_type': 'restock',
            'priority': priority,
            'current_stock': self.current_stock,
            'forecasted_demand': self.forecasted_demand_30d,
            'recommended_qty': self.recommended_restock_qty,
            'estimated_stockout_date': self.estimated_stockout_date,
            'suggested_action_date': self.recommended_restock_date,
            'reason': reason,
        })
    
    def _generate_restock_reason(self):
        """
        Generate human-readable reason for restock recommendation.
        """
        self.ensure_one()
        
        parts = []
        
        if self.stockout_risk == 'critical':
            parts.append(f"🚨 CRITICAL: Only {self.days_until_stockout} days of stock remaining!")
        elif self.stockout_risk == 'high':
            parts.append(f"⚠️ HIGH RISK: {self.days_until_stockout} days until stockout.")
        elif self.stockout_risk == 'medium':
            parts.append(f"📊 Stock running low: {self.days_until_stockout} days remaining.")
        
        parts.append(f"Current velocity: {self.weighted_velocity:.1f} units/day")
        
        if self.velocity_trend == 'increasing':
            parts.append(f"📈 Sales trending UP ({self.velocity_trend_percent:+.1f}%/week)")
        elif self.velocity_trend == 'decreasing':
            parts.append(f"📉 Sales trending DOWN ({self.velocity_trend_percent:+.1f}%/week)")
        
        if self.seasonality_factor > 1.1:
            parts.append(f"🎄 Seasonality: Demand {((self.seasonality_factor - 1) * 100):.0f}% higher than normal")
        elif self.seasonality_factor < 0.9:
            parts.append(f"📅 Seasonality: Demand {((1 - self.seasonality_factor) * 100):.0f}% lower than normal")
        
        parts.append(f"Recommended: Order {self.recommended_restock_qty} units by {self.recommended_restock_date}")
        
        return '\n'.join(parts)
    
    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------
    
    def action_refresh_forecast(self):
        """
        Manually refresh forecast.
        """
        self.ensure_one()
        self._sync_inventory_data()
        self.generate_forecast()
        self.calculate_restock_recommendation()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Forecast Updated'),
                'message': _('Forecast for %s has been refreshed.') % self.display_name,
                'type': 'success',
                'sticky': False,
            }
        }
    
    def action_view_demand_history(self):
        """
        View demand history for this product.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Demand History'),
            'res_model': 'amazon.demand.history',
            'view_mode': 'tree,graph',
            'domain': [
                ('product_id', '=', self.product_id.id),
                ('marketplace_id', '=', self.marketplace_id.id),
            ],
            'context': {
                'default_product_id': self.product_id.id,
                'default_marketplace_id': self.marketplace_id.id,
            },
        }
    
    def action_create_restock_suggestion(self):
        """
        Create a restock suggestion.
        """
        self.ensure_one()
        suggestion = self._create_restock_suggestion()
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Restock Suggestion'),
            'res_model': 'amazon.restock.suggestion',
            'res_id': suggestion.id,
            'view_mode': 'form',
        }
    
    def _sync_inventory_data(self):
        """
        Sync current inventory levels from FBA inventory.
        """
        self.ensure_one()
        if self.fba_inventory_id:
            self.write({
                'current_stock': self.fba_inventory_id.quantity_available,
                'current_reserved': self.fba_inventory_id.quantity_reserved,
                'current_inbound': self.fba_inventory_id.quantity_inbound_total,
            })
    
    # -------------------------------------------------------------------------
    # CRON METHODS
    # -------------------------------------------------------------------------
    
    @api.model
    def _cron_update_forecasts(self):
        """
        Daily cron to update all forecasts.
        """
        _logger.info('Starting forecast update cron')
        
        forecasts = self.search([('active', '=', True)])
        total = len(forecasts)
        
        for idx, forecast in enumerate(forecasts):
            try:
                forecast._sync_inventory_data()
                forecast.generate_forecast()
                forecast.calculate_restock_recommendation()
                
                if idx % 100 == 0:
                    _logger.info('Processed %d/%d forecasts', idx, total)
                    self.env.cr.commit()
                    
            except Exception as e:
                _logger.exception('Error updating forecast %s: %s', forecast.display_name, str(e))
        
        _logger.info('Completed forecast update cron (%d forecasts)', total)
    
    @api.model
    def _cron_create_missing_forecasts(self):
        """
        Create forecast records for products that don't have one.
        """
        _logger.info('Creating missing forecast records')
        
        FBAInventory = self.env['amazon.fba.inventory']
        
        # Find FBA inventory without forecasts
        self.env.cr.execute("""
            SELECT DISTINCT 
                i.product_id, 
                i.marketplace_id, 
                i.account_id
            FROM amazon_fba_inventory i
            LEFT JOIN amazon_inventory_forecast f
                ON f.product_id = i.product_id
                AND f.marketplace_id = i.marketplace_id
                AND f.account_id = i.account_id
            WHERE i.product_id IS NOT NULL
              AND f.id IS NULL
        """)
        
        missing = self.env.cr.fetchall()
        
        for product_id, marketplace_id, account_id in missing:
            try:
                self.create({
                    'product_id': product_id,
                    'marketplace_id': marketplace_id,
                    'account_id': account_id,
                })
            except Exception as e:
                _logger.warning('Could not create forecast for product %s: %s', product_id, str(e))
        
        _logger.info('Created %d missing forecast records', len(missing))
