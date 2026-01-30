# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

"""
Amazon Dashboard Helper Model

Provides intelligent KPI calculations, alerts, and recommendations
for the Amazon Connector dashboard.
"""

import logging
from datetime import datetime, timedelta
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.tools import float_round

_logger = logging.getLogger(__name__)


class AmazonDashboard(models.AbstractModel):
    """Helper model for Amazon Dashboard computations.
    
    This is an abstract model (no database table) that provides
    methods for computing dashboard KPIs, alerts, and recommendations.
    """
    _name = 'amazon.dashboard'
    _description = 'Amazon Dashboard Helper'

    # =========================================================================
    # KPI DATA
    # =========================================================================
    
    @api.model
    def get_kpi_data(self, account_id=None, date_from=None, date_to=None):
        """
        Get comprehensive KPI data for the dashboard.
        
        Args:
            account_id: Optional account ID to filter (None = all accounts)
            date_from: Start date (default: 30 days ago)
            date_to: End date (default: today)
            
        Returns:
            Dict with all KPI values
        """
        today = fields.Date.today()
        if not date_to:
            date_to = today
        if not date_from:
            date_from = today - timedelta(days=30)
        
        # Get accounts
        domain = [('active', '=', True)]
        if account_id:
            domain.append(('id', '=', account_id))
        accounts = self.env['amazon.account'].search(domain)
        account_ids = accounts.ids
        
        if not account_ids:
            return self._empty_kpi_response()
        
        # Compute all KPIs
        revenue_kpis = self._compute_revenue_kpis(account_ids, today, date_from, date_to)
        order_kpis = self._compute_order_kpis(account_ids, today)
        inventory_kpis = self._compute_inventory_kpis(account_ids)
        listing_kpis = self._compute_listing_kpis(account_ids)
        performance_kpis = self._compute_performance_kpis(account_ids, date_from, date_to)
        
        return {
            **revenue_kpis,
            **order_kpis,
            **inventory_kpis,
            **listing_kpis,
            **performance_kpis,
            'date_from': str(date_from),
            'date_to': str(date_to),
        }
    
    def _empty_kpi_response(self):
        """Return empty KPI response when no accounts found."""
        return {
            'revenue_today': 0,
            'revenue_week': 0,
            'revenue_month': 0,
            'revenue_trend': 'stable',
            'revenue_trend_pct': 0,
            'orders_today': 0,
            'orders_week': 0,
            'orders_month': 0,
            'orders_pending_shipment': 0,
            'orders_trend': 'stable',
            'orders_trend_pct': 0,
            'buy_box_percentage': 0,
            'inventory_health_score': 0,
            'stockout_risk_count': 0,
            'overstock_count': 0,
            'low_stock_count': 0,
            'returns_rate': 0,
            'average_order_value': 0,
            'units_sold_today': 0,
            'units_sold_week': 0,
            'top_sellers': [],
            'underperformers': [],
        }
    
    def _compute_revenue_kpis(self, account_ids, today, date_from, date_to):
        """Compute revenue-related KPIs."""
        AmazonOrder = self.env['amazon.order']
        
        # Today's revenue
        today_orders = AmazonOrder.search([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(today)),
            ('order_status', 'not in', ['canceled', 'pending']),
        ])
        revenue_today = sum(today_orders.mapped('order_total'))
        
        # This week's revenue
        week_start = today - timedelta(days=today.weekday())
        week_orders = AmazonOrder.search([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(week_start)),
            ('order_status', 'not in', ['canceled', 'pending']),
        ])
        revenue_week = sum(week_orders.mapped('order_total'))
        
        # This month's revenue
        month_start = today.replace(day=1)
        month_orders = AmazonOrder.search([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(month_start)),
            ('order_status', 'not in', ['canceled', 'pending']),
        ])
        revenue_month = sum(month_orders.mapped('order_total'))
        
        # Previous month for comparison
        prev_month_end = month_start - timedelta(days=1)
        prev_month_start = prev_month_end.replace(day=1)
        prev_month_orders = AmazonOrder.search([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(prev_month_start)),
            ('purchase_date', '<=', str(prev_month_end)),
            ('order_status', 'not in', ['canceled', 'pending']),
        ])
        revenue_prev_month = sum(prev_month_orders.mapped('order_total'))
        
        # Calculate trend
        if revenue_prev_month > 0:
            trend_pct = ((revenue_month - revenue_prev_month) / revenue_prev_month) * 100
        else:
            trend_pct = 100 if revenue_month > 0 else 0
        
        if trend_pct > 5:
            trend = 'up'
        elif trend_pct < -5:
            trend = 'down'
        else:
            trend = 'stable'
        
        # Average order value
        period_orders = AmazonOrder.search([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(date_from)),
            ('purchase_date', '<=', str(date_to)),
            ('order_status', 'not in', ['canceled', 'pending']),
        ])
        total_revenue = sum(period_orders.mapped('order_total'))
        aov = total_revenue / len(period_orders) if period_orders else 0
        
        return {
            'revenue_today': float_round(revenue_today, precision_digits=2),
            'revenue_week': float_round(revenue_week, precision_digits=2),
            'revenue_month': float_round(revenue_month, precision_digits=2),
            'revenue_trend': trend,
            'revenue_trend_pct': float_round(trend_pct, precision_digits=1),
            'average_order_value': float_round(aov, precision_digits=2),
        }
    
    def _compute_order_kpis(self, account_ids, today):
        """Compute order-related KPIs."""
        AmazonOrder = self.env['amazon.order']
        
        # Today's orders
        orders_today = AmazonOrder.search_count([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(today)),
        ])
        
        # This week's orders
        week_start = today - timedelta(days=today.weekday())
        orders_week = AmazonOrder.search_count([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(week_start)),
        ])
        
        # This month's orders
        month_start = today.replace(day=1)
        orders_month = AmazonOrder.search_count([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(month_start)),
        ])
        
        # Previous week for trend
        prev_week_start = week_start - timedelta(days=7)
        prev_week_end = week_start - timedelta(days=1)
        orders_prev_week = AmazonOrder.search_count([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(prev_week_start)),
            ('purchase_date', '<=', str(prev_week_end)),
        ])
        
        # Calculate trend
        if orders_prev_week > 0:
            trend_pct = ((orders_week - orders_prev_week) / orders_prev_week) * 100
        else:
            trend_pct = 100 if orders_week > 0 else 0
        
        if trend_pct > 5:
            trend = 'up'
        elif trend_pct < -5:
            trend = 'down'
        else:
            trend = 'stable'
        
        # Pending shipment (FBM orders that need shipping)
        orders_pending = AmazonOrder.search_count([
            ('account_id', 'in', account_ids),
            ('order_status', 'in', ['unshipped', 'pending']),
            ('fulfillment_channel', '=', 'MFN'),
        ])
        
        # Units sold (from order lines)
        today_order_ids = AmazonOrder.search([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(today)),
            ('order_status', 'not in', ['canceled']),
        ]).ids
        if today_order_ids:
            self.env.cr.execute("""
                SELECT COALESCE(SUM(quantity), 0)
                FROM amazon_order_line
                WHERE order_id IN %s
            """, (tuple(today_order_ids),))
            units_today = self.env.cr.fetchone()[0] or 0
        else:
            units_today = 0
        
        week_order_ids = AmazonOrder.search([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(week_start)),
            ('order_status', 'not in', ['canceled']),
        ]).ids
        if week_order_ids:
            self.env.cr.execute("""
                SELECT COALESCE(SUM(quantity), 0)
                FROM amazon_order_line
                WHERE order_id IN %s
            """, (tuple(week_order_ids),))
            units_week = self.env.cr.fetchone()[0] or 0
        else:
            units_week = 0
        
        return {
            'orders_today': orders_today,
            'orders_week': orders_week,
            'orders_month': orders_month,
            'orders_pending_shipment': orders_pending,
            'orders_trend': trend,
            'orders_trend_pct': float_round(trend_pct, precision_digits=1),
            'units_sold_today': int(units_today),
            'units_sold_week': int(units_week),
        }
    
    def _compute_inventory_kpis(self, account_ids):
        """Compute inventory health KPIs."""
        FBAInventory = self.env['amazon.fba.inventory']
        
        inventory = FBAInventory.search([('account_id', 'in', account_ids)])
        
        # Count issues
        stockout_risk = 0
        overstock = 0
        low_stock = 0
        total_skus = len(inventory)
        healthy_skus = 0
        
        for item in inventory:
            available = item.quantity_available
            restock_level = item.restock_level or 10  # Default minimum
            
            if available == 0:
                stockout_risk += 1
            elif available <= restock_level:
                low_stock += 1
            elif hasattr(item, 'days_of_supply') and item.days_of_supply and item.days_of_supply > 180:
                overstock += 1
            else:
                healthy_skus += 1
        
        # Calculate health score (0-100)
        if total_skus > 0:
            # Weight: stockouts are worst (-40), low stock (-20), overstock (-10)
            penalty = (stockout_risk * 40 + low_stock * 20 + overstock * 10) / total_skus
            health_score = max(0, min(100, 100 - penalty))
        else:
            health_score = 100  # No inventory = perfect score (nothing to manage)
        
        return {
            'inventory_health_score': int(health_score),
            'stockout_risk_count': stockout_risk,
            'overstock_count': overstock,
            'low_stock_count': low_stock,
            'total_fba_skus': total_skus,
        }
    
    def _compute_listing_kpis(self, account_ids):
        """Compute listing/Buy Box KPIs."""
        Listing = self.env['amazon.product.listing']
        
        active_listings = Listing.search([
            ('account_id', 'in', account_ids),
            ('state', '=', 'active'),
        ])
        
        total_active = len(active_listings)
        buybox_winners = len(active_listings.filtered(lambda l: l.is_buybox_winner))
        
        buybox_pct = (buybox_winners / total_active * 100) if total_active > 0 else 0
        
        return {
            'buy_box_percentage': float_round(buybox_pct, precision_digits=1),
            'total_active_listings': total_active,
            'buybox_winners': buybox_winners,
        }
    
    def _compute_performance_kpis(self, account_ids, date_from, date_to):
        """Compute performance KPIs (returns rate, etc.)."""
        AmazonOrder = self.env['amazon.order']
        AmazonReturn = self.env['amazon.return']
        
        # Orders in period
        orders = AmazonOrder.search([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(date_from)),
            ('purchase_date', '<=', str(date_to)),
            ('order_status', 'not in', ['canceled']),
        ])
        total_orders = len(orders)
        
        # Returns in period
        returns = AmazonReturn.search([
            ('account_id', 'in', account_ids),
            ('return_date', '>=', str(date_from)),
            ('return_date', '<=', str(date_to)),
        ])
        total_returns = len(returns)
        
        returns_rate = (total_returns / total_orders * 100) if total_orders > 0 else 0
        
        return {
            'returns_rate': float_round(returns_rate, precision_digits=2),
            'total_returns': total_returns,
        }
    
    # =========================================================================
    # ALERTS
    # =========================================================================
    
    @api.model
    def get_alerts(self, account_id=None, limit=20):
        """
        Get priority alerts for the dashboard.
        
        Returns alerts sorted by severity (critical > warning > info).
        """
        alerts = []
        
        # Get accounts
        domain = [('active', '=', True)]
        if account_id:
            domain.append(('id', '=', account_id))
        accounts = self.env['amazon.account'].search(domain)
        account_ids = accounts.ids
        
        if not account_ids:
            return []
        
        # Check for critical issues
        alerts.extend(self._check_authorization_alerts(accounts))
        alerts.extend(self._check_stockout_alerts(account_ids))
        alerts.extend(self._check_pending_orders_alerts(account_ids))
        alerts.extend(self._check_buybox_alerts(account_ids))
        alerts.extend(self._check_listing_issues_alerts(account_ids))
        alerts.extend(self._check_returns_alerts(account_ids))
        
        # Sort by severity (critical first)
        severity_order = {'critical': 0, 'warning': 1, 'info': 2}
        alerts.sort(key=lambda a: (severity_order.get(a['severity'], 3), -a.get('count', 0)))
        
        return alerts[:limit]
    
    def _check_authorization_alerts(self, accounts):
        """Check for account authorization issues."""
        alerts = []
        for account in accounts:
            if account.authorization_status != 'authorized':
                alerts.append({
                    'id': f'auth_{account.id}',
                    'type': 'authorization',
                    'severity': 'critical',
                    'title': _('Account Authorization Issue'),
                    'message': _('Account "%s" needs re-authorization') % account.name,
                    'action_type': 'open_account',
                    'action_data': {'account_id': account.id},
                    'count': 1,
                })
        return alerts
    
    def _check_stockout_alerts(self, account_ids):
        """Check for stockout and low stock alerts."""
        alerts = []
        FBAInventory = self.env['amazon.fba.inventory']
        
        # Stockouts
        stockouts = FBAInventory.search([
            ('account_id', 'in', account_ids),
            ('quantity_available', '=', 0),
        ])
        if stockouts:
            alerts.append({
                'id': 'stockout',
                'type': 'inventory',
                'severity': 'critical',
                'title': _('Products Out of Stock'),
                'message': _('%d products are out of stock at FBA') % len(stockouts),
                'action_type': 'view_inventory',
                'action_data': {'filter': 'stockout'},
                'count': len(stockouts),
                'items': [{'sku': s.amazon_sku, 'name': s.product_name} for s in stockouts[:5]],
            })
        
        # Low stock
        low_stock = FBAInventory.search([
            ('account_id', 'in', account_ids),
            ('quantity_available', '>', 0),
            ('quantity_available', '<=', 10),  # Default threshold
        ])
        if low_stock:
            alerts.append({
                'id': 'low_stock',
                'type': 'inventory',
                'severity': 'warning',
                'title': _('Low Stock Warning'),
                'message': _('%d products have low FBA inventory') % len(low_stock),
                'action_type': 'view_inventory',
                'action_data': {'filter': 'low_stock'},
                'count': len(low_stock),
                'items': [{'sku': s.amazon_sku, 'name': s.product_name, 'qty': s.quantity_available} for s in low_stock[:5]],
            })
        
        return alerts
    
    def _check_pending_orders_alerts(self, account_ids):
        """Check for orders pending shipment."""
        alerts = []
        AmazonOrder = self.env['amazon.order']
        
        pending = AmazonOrder.search([
            ('account_id', 'in', account_ids),
            ('order_status', '=', 'unshipped'),
            ('fulfillment_channel', '=', 'MFN'),
        ])
        
        # Urgent: orders older than 24 hours
        urgent_cutoff = datetime.now() - timedelta(hours=24)
        urgent = pending.filtered(lambda o: o.purchase_date and o.purchase_date < urgent_cutoff)
        
        if urgent:
            alerts.append({
                'id': 'urgent_ship',
                'type': 'orders',
                'severity': 'critical',
                'title': _('Orders Need Immediate Shipment'),
                'message': _('%d FBM orders are overdue for shipping') % len(urgent),
                'action_type': 'view_orders',
                'action_data': {'filter': 'urgent_ship'},
                'count': len(urgent),
            })
        elif pending:
            alerts.append({
                'id': 'pending_ship',
                'type': 'orders',
                'severity': 'warning',
                'title': _('Orders Awaiting Shipment'),
                'message': _('%d FBM orders need to be shipped') % len(pending),
                'action_type': 'view_orders',
                'action_data': {'filter': 'pending_ship'},
                'count': len(pending),
            })
        
        return alerts
    
    def _check_buybox_alerts(self, account_ids):
        """Check for Buy Box losses."""
        alerts = []
        Listing = self.env['amazon.product.listing']
        
        # Active listings without Buy Box
        lost_buybox = Listing.search([
            ('account_id', 'in', account_ids),
            ('state', '=', 'active'),
            ('is_buybox_winner', '=', False),
        ])
        
        if len(lost_buybox) > 5:  # Only alert if significant
            alerts.append({
                'id': 'buybox_lost',
                'type': 'listings',
                'severity': 'warning',
                'title': _('Buy Box Not Winning'),
                'message': _('%d active listings don\'t have the Buy Box') % len(lost_buybox),
                'action_type': 'view_listings',
                'action_data': {'filter': 'no_buybox'},
                'count': len(lost_buybox),
            })
        
        return alerts
    
    def _check_listing_issues_alerts(self, account_ids):
        """Check for listing quality issues."""
        alerts = []
        Listing = self.env['amazon.product.listing']
        
        # Suppressed listings
        suppressed = Listing.search([
            ('account_id', 'in', account_ids),
            ('state', '=', 'suppressed'),
        ])
        if suppressed:
            alerts.append({
                'id': 'suppressed',
                'type': 'listings',
                'severity': 'critical',
                'title': _('Suppressed Listings'),
                'message': _('%d listings are suppressed by Amazon') % len(suppressed),
                'action_type': 'view_listings',
                'action_data': {'filter': 'suppressed'},
                'count': len(suppressed),
            })
        
        # Listings with quality issues
        with_issues = Listing.search([
            ('account_id', 'in', account_ids),
            ('state', '=', 'active'),
            ('listing_issues', '!=', False),
        ])
        if with_issues:
            alerts.append({
                'id': 'listing_issues',
                'type': 'listings',
                'severity': 'warning',
                'title': _('Listing Quality Issues'),
                'message': _('%d listings have quality issues to fix') % len(with_issues),
                'action_type': 'view_listings',
                'action_data': {'filter': 'issues'},
                'count': len(with_issues),
            })
        
        return alerts
    
    def _check_returns_alerts(self, account_ids):
        """Check for high return rates or pending returns."""
        alerts = []
        AmazonReturn = self.env['amazon.return']
        
        # Recent returns (last 7 days)
        week_ago = fields.Date.today() - timedelta(days=7)
        recent_returns = AmazonReturn.search([
            ('account_id', 'in', account_ids),
            ('return_date', '>=', str(week_ago)),
            ('state', '=', 'pending'),
        ])
        
        if recent_returns:
            alerts.append({
                'id': 'pending_returns',
                'type': 'returns',
                'severity': 'info',
                'title': _('Pending Returns'),
                'message': _('%d returns need processing') % len(recent_returns),
                'action_type': 'view_returns',
                'action_data': {'filter': 'pending'},
                'count': len(recent_returns),
            })
        
        return alerts
    
    # =========================================================================
    # RECOMMENDATIONS
    # =========================================================================
    
    @api.model
    def get_recommendations(self, account_id=None, limit=10):
        """
        Get actionable recommendations.
        
        Returns suggestions for improving sales and operations.
        """
        recommendations = []
        
        # Get accounts
        domain = [('active', '=', True)]
        if account_id:
            domain.append(('id', '=', account_id))
        accounts = self.env['amazon.account'].search(domain)
        account_ids = accounts.ids
        
        if not account_ids:
            return []
        
        recommendations.extend(self._recommend_restock(account_ids))
        recommendations.extend(self._recommend_pricing(account_ids))
        recommendations.extend(self._recommend_listings(account_ids))
        recommendations.extend(self._recommend_fba_shipments(account_ids))
        
        # Sort by priority
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        recommendations.sort(key=lambda r: priority_order.get(r['priority'], 3))
        
        return recommendations[:limit]
    
    def _recommend_restock(self, account_ids):
        """Generate restock recommendations."""
        recommendations = []
        FBAInventory = self.env['amazon.fba.inventory']
        
        # Low stock items that have sales velocity
        low_stock = FBAInventory.search([
            ('account_id', 'in', account_ids),
            ('quantity_available', '<=', 20),
            ('quantity_available', '>', 0),
        ])
        
        if low_stock:
            recommendations.append({
                'id': 'restock_fba',
                'type': 'inventory',
                'priority': 'high',
                'title': _('Create FBA Replenishment Shipment'),
                'description': _('%d products are running low at FBA. Consider creating a new inbound shipment.') % len(low_stock),
                'action_type': 'create_fba_shipment',
                'action_label': _('Create Shipment'),
                'impact': _('Prevent stockouts'),
                'items': [{'sku': s.amazon_sku, 'name': s.product_name, 'qty': s.quantity_available} for s in low_stock[:5]],
            })
        
        return recommendations
    
    def _recommend_pricing(self, account_ids):
        """Generate pricing recommendations."""
        recommendations = []
        Listing = self.env['amazon.product.listing']
        
        # Listings not winning Buy Box
        no_buybox = Listing.search([
            ('account_id', 'in', account_ids),
            ('state', '=', 'active'),
            ('is_buybox_winner', '=', False),
        ], limit=20)
        
        if no_buybox:
            recommendations.append({
                'id': 'pricing_buybox',
                'type': 'pricing',
                'priority': 'medium',
                'title': _('Review Pricing for Buy Box'),
                'description': _('Review pricing on %d listings to improve Buy Box win rate.') % len(no_buybox),
                'action_type': 'view_listings',
                'action_label': _('Review Listings'),
                'impact': _('Increase sales'),
            })
        
        return recommendations
    
    def _recommend_listings(self, account_ids):
        """Generate listing optimization recommendations."""
        recommendations = []
        Listing = self.env['amazon.product.listing']
        
        # Listings with low quality score
        poor_quality = Listing.search([
            ('account_id', 'in', account_ids),
            ('state', '=', 'active'),
            ('listing_quality_score', '<', 70),
            ('listing_quality_score', '>', 0),
        ], limit=10)
        
        if poor_quality:
            recommendations.append({
                'id': 'listing_quality',
                'type': 'listings',
                'priority': 'medium',
                'title': _('Improve Listing Quality'),
                'description': _('%d listings have quality scores below 70%%. Improve images, titles, and descriptions.') % len(poor_quality),
                'action_type': 'view_listings',
                'action_label': _('View Listings'),
                'impact': _('Better visibility'),
            })
        
        return recommendations
    
    def _recommend_fba_shipments(self, account_ids):
        """Generate FBA shipment recommendations."""
        recommendations = []
        FBAShipment = self.env['amazon.fba.shipment']
        
        # Draft shipments not yet sent
        draft_shipments = FBAShipment.search([
            ('account_id', 'in', account_ids),
            ('state', '=', 'draft'),
        ])
        
        if draft_shipments:
            recommendations.append({
                'id': 'ship_fba',
                'type': 'inventory',
                'priority': 'high',
                'title': _('Complete FBA Shipments'),
                'description': _('%d FBA shipments are in draft status. Complete and ship to restock inventory.') % len(draft_shipments),
                'action_type': 'view_fba_shipments',
                'action_label': _('View Shipments'),
                'impact': _('Restock FBA'),
            })
        
        return recommendations
    
    # =========================================================================
    # CHART DATA
    # =========================================================================
    
    @api.model
    def get_revenue_chart_data(self, account_id=None, period='month'):
        """
        Get revenue data for charts.
        
        Args:
            account_id: Optional account filter
            period: 'week', 'month', 'quarter', 'year'
            
        Returns:
            Dict with labels and values for charting
        """
        today = fields.Date.today()
        
        # Determine date range and grouping
        if period == 'week':
            date_from = today - timedelta(days=6)
            group_by = 'day'
        elif period == 'month':
            date_from = today - timedelta(days=29)
            group_by = 'day'
        elif period == 'quarter':
            date_from = today - timedelta(days=89)
            group_by = 'week'
        else:  # year
            date_from = today - timedelta(days=364)
            group_by = 'month'
        
        # Get accounts
        domain = [('active', '=', True)]
        if account_id:
            domain.append(('id', '=', account_id))
        accounts = self.env['amazon.account'].search(domain)
        account_ids = accounts.ids
        
        if not account_ids:
            return {'labels': [], 'datasets': []}
        
        # Query revenue data
        AmazonOrder = self.env['amazon.order']
        orders = AmazonOrder.search([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(date_from)),
            ('order_status', 'not in', ['canceled', 'pending']),
        ])
        
        # Group by date
        data = defaultdict(float)
        for order in orders:
            if order.purchase_date:
                if group_by == 'day':
                    key = order.purchase_date.strftime('%Y-%m-%d')
                elif group_by == 'week':
                    key = order.purchase_date.strftime('%Y-W%W')
                else:
                    key = order.purchase_date.strftime('%Y-%m')
                data[key] += order.order_total
        
        # Generate all labels in range
        labels = []
        current = date_from
        while current <= today:
            if group_by == 'day':
                labels.append(current.strftime('%Y-%m-%d'))
                current += timedelta(days=1)
            elif group_by == 'week':
                labels.append(current.strftime('%Y-W%W'))
                current += timedelta(weeks=1)
            else:
                labels.append(current.strftime('%Y-%m'))
                # Move to next month
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_labels = []
        for label in labels:
            if label not in seen:
                seen.add(label)
                unique_labels.append(label)
        
        values = [float_round(data.get(label, 0), precision_digits=2) for label in unique_labels]
        
        return {
            'labels': unique_labels,
            'datasets': [{
                'label': _('Revenue'),
                'data': values,
                'borderColor': '#FF9900',
                'backgroundColor': 'rgba(255, 153, 0, 0.1)',
                'fill': True,
            }],
        }
    
    @api.model
    def get_marketplace_chart_data(self, account_id=None, date_from=None, date_to=None):
        """Get revenue by marketplace for pie chart."""
        today = fields.Date.today()
        if not date_to:
            date_to = today
        if not date_from:
            date_from = today - timedelta(days=30)
        
        domain = [('active', '=', True)]
        if account_id:
            domain.append(('id', '=', account_id))
        accounts = self.env['amazon.account'].search(domain)
        account_ids = accounts.ids
        
        if not account_ids:
            return {'labels': [], 'datasets': []}
        
        AmazonOrder = self.env['amazon.order']
        orders = AmazonOrder.search([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(date_from)),
            ('purchase_date', '<=', str(date_to)),
            ('order_status', 'not in', ['canceled', 'pending']),
        ])
        
        # Group by marketplace
        by_marketplace = defaultdict(float)
        for order in orders:
            mp_name = order.marketplace_id.name if order.marketplace_id else 'Unknown'
            by_marketplace[mp_name] += order.order_total
        
        labels = list(by_marketplace.keys())
        values = [float_round(by_marketplace[mp], precision_digits=2) for mp in labels]
        
        # Amazon-themed colors
        colors = ['#FF9900', '#232F3E', '#37475A', '#146EB4', '#FFA41C', '#FF6138']
        
        return {
            'labels': labels,
            'datasets': [{
                'data': values,
                'backgroundColor': colors[:len(labels)],
            }],
        }
    
    @api.model
    def get_fulfillment_chart_data(self, account_id=None, date_from=None, date_to=None):
        """Get FBA vs FBM split for donut chart."""
        today = fields.Date.today()
        if not date_to:
            date_to = today
        if not date_from:
            date_from = today - timedelta(days=30)
        
        domain = [('active', '=', True)]
        if account_id:
            domain.append(('id', '=', account_id))
        accounts = self.env['amazon.account'].search(domain)
        account_ids = accounts.ids
        
        if not account_ids:
            return {'labels': [], 'datasets': []}
        
        AmazonOrder = self.env['amazon.order']
        
        fba_orders = AmazonOrder.search([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(date_from)),
            ('purchase_date', '<=', str(date_to)),
            ('order_status', 'not in', ['canceled', 'pending']),
            ('fulfillment_channel', '=', 'AFN'),
        ])
        fba_revenue = sum(fba_orders.mapped('order_total'))
        
        fbm_orders = AmazonOrder.search([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(date_from)),
            ('purchase_date', '<=', str(date_to)),
            ('order_status', 'not in', ['canceled', 'pending']),
            ('fulfillment_channel', '=', 'MFN'),
        ])
        fbm_revenue = sum(fbm_orders.mapped('order_total'))
        
        return {
            'labels': ['FBA', 'FBM'],
            'datasets': [{
                'data': [float_round(fba_revenue, 2), float_round(fbm_revenue, 2)],
                'backgroundColor': ['#FF9900', '#232F3E'],
            }],
        }
    
    # =========================================================================
    # TOP/BOTTOM PRODUCTS
    # =========================================================================
    
    @api.model
    def get_top_products(self, account_id=None, limit=10, date_from=None, date_to=None):
        """Get top selling products by revenue."""
        today = fields.Date.today()
        if not date_to:
            date_to = today
        if not date_from:
            date_from = today - timedelta(days=30)
        
        domain = [('active', '=', True)]
        if account_id:
            domain.append(('id', '=', account_id))
        accounts = self.env['amazon.account'].search(domain)
        account_ids = accounts.ids
        
        if not account_ids:
            return []
        
        # Query aggregated data
        self.env.cr.execute("""
            SELECT 
                ol.sku,
                ol.product_name,
                SUM(ol.quantity) as total_qty,
                SUM(ol.item_price * ol.quantity) as total_revenue
            FROM amazon_order_line ol
            JOIN amazon_order o ON o.id = ol.order_id
            WHERE o.account_id = ANY(%s)
              AND o.purchase_date >= %s
              AND o.purchase_date <= %s
              AND o.order_status NOT IN ('canceled', 'pending')
            GROUP BY ol.sku, ol.product_name
            ORDER BY total_revenue DESC
            LIMIT %s
        """, (account_ids, str(date_from), str(date_to), limit))
        
        results = self.env.cr.fetchall()
        
        return [{
            'sku': row[0],
            'name': row[1] or row[0],
            'quantity': int(row[2] or 0),
            'revenue': float_round(row[3] or 0, precision_digits=2),
        } for row in results]
    
    @api.model
    def get_underperformers(self, account_id=None, limit=10, date_from=None, date_to=None):
        """Get products with declining sales or poor performance."""
        today = fields.Date.today()
        if not date_to:
            date_to = today
        if not date_from:
            date_from = today - timedelta(days=30)
        
        # Calculate the previous period
        period_length = (date_to - date_from).days
        prev_date_to = date_from - timedelta(days=1)
        prev_date_from = prev_date_to - timedelta(days=period_length)
        
        domain = [('active', '=', True)]
        if account_id:
            domain.append(('id', '=', account_id))
        accounts = self.env['amazon.account'].search(domain)
        account_ids = accounts.ids
        
        if not account_ids:
            return []
        
        # Get current period sales
        self.env.cr.execute("""
            SELECT 
                ol.sku,
                ol.product_name,
                SUM(ol.quantity) as total_qty
            FROM amazon_order_line ol
            JOIN amazon_order o ON o.id = ol.order_id
            WHERE o.account_id = ANY(%s)
              AND o.purchase_date >= %s
              AND o.purchase_date <= %s
              AND o.order_status NOT IN ('canceled', 'pending')
            GROUP BY ol.sku, ol.product_name
        """, (account_ids, str(date_from), str(date_to)))
        current = {row[0]: {'name': row[1], 'qty': row[2]} for row in self.env.cr.fetchall()}
        
        # Get previous period sales
        self.env.cr.execute("""
            SELECT 
                ol.sku,
                SUM(ol.quantity) as total_qty
            FROM amazon_order_line ol
            JOIN amazon_order o ON o.id = ol.order_id
            WHERE o.account_id = ANY(%s)
              AND o.purchase_date >= %s
              AND o.purchase_date <= %s
              AND o.order_status NOT IN ('canceled', 'pending')
            GROUP BY ol.sku
        """, (account_ids, str(prev_date_from), str(prev_date_to)))
        previous = {row[0]: row[1] for row in self.env.cr.fetchall()}
        
        # Find decliners
        decliners = []
        for sku, data in current.items():
            prev_qty = previous.get(sku, 0)
            if prev_qty > 0:
                change_pct = ((data['qty'] - prev_qty) / prev_qty) * 100
                if change_pct < -20:  # Declined by more than 20%
                    decliners.append({
                        'sku': sku,
                        'name': data['name'] or sku,
                        'current_qty': int(data['qty']),
                        'previous_qty': int(prev_qty),
                        'change_pct': float_round(change_pct, precision_digits=1),
                    })
        
        # Sort by biggest decline
        decliners.sort(key=lambda x: x['change_pct'])
        
        return decliners[:limit]
    
    @api.model
    def get_inventory_health_score(self, account_id=None):
        """
        Calculate detailed inventory health score with breakdown.
        
        Weighted score based on:
        - Stockouts: -40 points per % of SKUs
        - Low stock: -20 points per % of SKUs  
        - Overstock: -10 points per % of SKUs
        - Stranded inventory: -15 points per % of SKUs
        """
        domain = [('active', '=', True)]
        if account_id:
            domain.append(('id', '=', account_id))
        accounts = self.env['amazon.account'].search(domain)
        account_ids = accounts.ids
        
        if not account_ids:
            return {'score': 100, 'breakdown': {}}
        
        FBAInventory = self.env['amazon.fba.inventory']
        inventory = FBAInventory.search([('account_id', 'in', account_ids)])
        
        total = len(inventory)
        if total == 0:
            return {'score': 100, 'breakdown': {'message': 'No FBA inventory'}}
        
        stockouts = len(inventory.filtered(lambda i: i.quantity_available == 0))
        low_stock = len(inventory.filtered(lambda i: 0 < i.quantity_available <= (i.restock_level or 10)))
        overstock = len(inventory.filtered(lambda i: hasattr(i, 'days_of_supply') and i.days_of_supply and i.days_of_supply > 180))
        stranded = len(inventory.filtered(lambda i: i.quantity_unfulfillable > 0))
        
        # Calculate penalties
        stockout_penalty = (stockouts / total) * 40
        low_stock_penalty = (low_stock / total) * 20
        overstock_penalty = (overstock / total) * 10
        stranded_penalty = (stranded / total) * 15
        
        total_penalty = stockout_penalty + low_stock_penalty + overstock_penalty + stranded_penalty
        score = max(0, min(100, 100 - total_penalty))
        
        return {
            'score': int(score),
            'breakdown': {
                'total_skus': total,
                'stockouts': stockouts,
                'low_stock': low_stock,
                'overstock': overstock,
                'stranded': stranded,
                'penalties': {
                    'stockout': float_round(stockout_penalty, 1),
                    'low_stock': float_round(low_stock_penalty, 1),
                    'overstock': float_round(overstock_penalty, 1),
                    'stranded': float_round(stranded_penalty, 1),
                },
            },
        }
