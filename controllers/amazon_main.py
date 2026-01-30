# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

"""
Amazon Connector Main Controller

Provides main routes for:
- Dashboard data endpoints
- Status and health checks
- Quick action endpoints
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from odoo import http, SUPERUSER_ID, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class AmazonMainController(http.Controller):
    """Main controller for Amazon Connector functionality."""
    
    # =========================================================================
    # ENHANCED DASHBOARD ENDPOINTS
    # =========================================================================
    
    @http.route(
        '/amazon/dashboard/kpis',
        type='json',
        auth='user',
        methods=['POST']
    )
    def get_dashboard_kpis(self, account_id=None, date_from=None, date_to=None, **kwargs):
        """
        Get comprehensive KPI data for the smart dashboard.
        
        Args:
            account_id: Optional specific account ID
            date_from: Start date (default: 30 days ago)
            date_to: End date (default: today)
            
        Returns:
            Dict with all KPI values
        """
        try:
            Dashboard = request.env['amazon.dashboard']
            
            # Parse dates if provided as strings
            if date_from and isinstance(date_from, str):
                date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            if date_to and isinstance(date_to, str):
                date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            
            kpis = Dashboard.get_kpi_data(
                account_id=int(account_id) if account_id else None,
                date_from=date_from,
                date_to=date_to,
            )
            
            return {'success': True, 'data': kpis}
            
        except Exception as e:
            _logger.exception("Error getting dashboard KPIs: %s", str(e))
            return {'success': False, 'error': str(e)}
    
    @http.route(
        '/amazon/dashboard/alerts',
        type='json',
        auth='user',
        methods=['POST']
    )
    def get_dashboard_alerts(self, account_id=None, limit=20, **kwargs):
        """
        Get priority alerts for the dashboard.
        
        Args:
            account_id: Optional account filter
            limit: Max number of alerts to return
            
        Returns:
            List of alert objects sorted by severity
        """
        try:
            Dashboard = request.env['amazon.dashboard']
            
            alerts = Dashboard.get_alerts(
                account_id=int(account_id) if account_id else None,
                limit=int(limit),
            )
            
            return {'success': True, 'data': alerts}
            
        except Exception as e:
            _logger.exception("Error getting dashboard alerts: %s", str(e))
            return {'success': False, 'error': str(e)}
    
    @http.route(
        '/amazon/dashboard/recommendations',
        type='json',
        auth='user',
        methods=['POST']
    )
    def get_dashboard_recommendations(self, account_id=None, limit=10, **kwargs):
        """
        Get actionable recommendations.
        
        Args:
            account_id: Optional account filter
            limit: Max recommendations to return
            
        Returns:
            List of recommendation objects
        """
        try:
            Dashboard = request.env['amazon.dashboard']
            
            recommendations = Dashboard.get_recommendations(
                account_id=int(account_id) if account_id else None,
                limit=int(limit),
            )
            
            return {'success': True, 'data': recommendations}
            
        except Exception as e:
            _logger.exception("Error getting recommendations: %s", str(e))
            return {'success': False, 'error': str(e)}
    
    @http.route(
        '/amazon/dashboard/charts/revenue',
        type='json',
        auth='user',
        methods=['POST']
    )
    def get_revenue_chart(self, account_id=None, period='month', **kwargs):
        """
        Get revenue chart data.
        
        Args:
            account_id: Optional account filter
            period: 'week', 'month', 'quarter', 'year'
            
        Returns:
            Chart.js compatible data structure
        """
        try:
            Dashboard = request.env['amazon.dashboard']
            
            data = Dashboard.get_revenue_chart_data(
                account_id=int(account_id) if account_id else None,
                period=period,
            )
            
            return {'success': True, 'data': data}
            
        except Exception as e:
            _logger.exception("Error getting revenue chart: %s", str(e))
            return {'success': False, 'error': str(e)}
    
    @http.route(
        '/amazon/dashboard/charts/marketplace',
        type='json',
        auth='user',
        methods=['POST']
    )
    def get_marketplace_chart(self, account_id=None, date_from=None, date_to=None, **kwargs):
        """Get marketplace distribution chart data."""
        try:
            Dashboard = request.env['amazon.dashboard']
            
            if date_from and isinstance(date_from, str):
                date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            if date_to and isinstance(date_to, str):
                date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            
            data = Dashboard.get_marketplace_chart_data(
                account_id=int(account_id) if account_id else None,
                date_from=date_from,
                date_to=date_to,
            )
            
            return {'success': True, 'data': data}
            
        except Exception as e:
            _logger.exception("Error getting marketplace chart: %s", str(e))
            return {'success': False, 'error': str(e)}
    
    @http.route(
        '/amazon/dashboard/charts/fulfillment',
        type='json',
        auth='user',
        methods=['POST']
    )
    def get_fulfillment_chart(self, account_id=None, date_from=None, date_to=None, **kwargs):
        """Get FBA vs FBM chart data."""
        try:
            Dashboard = request.env['amazon.dashboard']
            
            if date_from and isinstance(date_from, str):
                date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            if date_to and isinstance(date_to, str):
                date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            
            data = Dashboard.get_fulfillment_chart_data(
                account_id=int(account_id) if account_id else None,
                date_from=date_from,
                date_to=date_to,
            )
            
            return {'success': True, 'data': data}
            
        except Exception as e:
            _logger.exception("Error getting fulfillment chart: %s", str(e))
            return {'success': False, 'error': str(e)}
    
    @http.route(
        '/amazon/dashboard/top-products',
        type='json',
        auth='user',
        methods=['POST']
    )
    def get_top_products(self, account_id=None, limit=10, date_from=None, date_to=None, **kwargs):
        """Get top selling products."""
        try:
            Dashboard = request.env['amazon.dashboard']
            
            if date_from and isinstance(date_from, str):
                date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            if date_to and isinstance(date_to, str):
                date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            
            data = Dashboard.get_top_products(
                account_id=int(account_id) if account_id else None,
                limit=int(limit),
                date_from=date_from,
                date_to=date_to,
            )
            
            return {'success': True, 'data': data}
            
        except Exception as e:
            _logger.exception("Error getting top products: %s", str(e))
            return {'success': False, 'error': str(e)}
    
    @http.route(
        '/amazon/dashboard/underperformers',
        type='json',
        auth='user',
        methods=['POST']
    )
    def get_underperformers(self, account_id=None, limit=10, date_from=None, date_to=None, **kwargs):
        """Get underperforming products."""
        try:
            Dashboard = request.env['amazon.dashboard']
            
            if date_from and isinstance(date_from, str):
                date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            if date_to and isinstance(date_to, str):
                date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            
            data = Dashboard.get_underperformers(
                account_id=int(account_id) if account_id else None,
                limit=int(limit),
                date_from=date_from,
                date_to=date_to,
            )
            
            return {'success': True, 'data': data}
            
        except Exception as e:
            _logger.exception("Error getting underperformers: %s", str(e))
            return {'success': False, 'error': str(e)}
    
    @http.route(
        '/amazon/dashboard/inventory-health',
        type='json',
        auth='user',
        methods=['POST']
    )
    def get_inventory_health(self, account_id=None, **kwargs):
        """Get detailed inventory health score."""
        try:
            Dashboard = request.env['amazon.dashboard']
            
            data = Dashboard.get_inventory_health_score(
                account_id=int(account_id) if account_id else None,
            )
            
            return {'success': True, 'data': data}
            
        except Exception as e:
            _logger.exception("Error getting inventory health: %s", str(e))
            return {'success': False, 'error': str(e)}
    
    # =========================================================================
    # LEGACY DASHBOARD ENDPOINT (backwards compatible)
    # =========================================================================
    
    @http.route(
        '/amazon/dashboard/data',
        type='json',
        auth='user',
        methods=['POST']
    )
    def get_dashboard_data(self, account_id=None, date_from=None, date_to=None, **kwargs):
        """
        Get dashboard data for the Amazon Connector.
        
        Args:
            account_id: Optional specific account ID
            date_from: Start date for metrics (default: 30 days ago)
            date_to: End date for metrics (default: today)
            
        Returns:
            Dict with dashboard metrics
        """
        try:
            env = request.env
            
            # Default date range
            if not date_to:
                date_to = datetime.now(timezone.utc).date()
            if not date_from:
                date_from = date_to - timedelta(days=30)
            
            # Build domain
            domain = [('active', '=', True)]
            if account_id:
                domain.append(('id', '=', int(account_id)))
            
            accounts = env['amazon.account'].search(domain)
            
            if not accounts:
                return {'error': 'No accounts found'}
            
            # Collect metrics
            metrics = {
                'orders': self._get_order_metrics(accounts, date_from, date_to),
                'inventory': self._get_inventory_metrics(accounts),
                'listings': self._get_listing_metrics(accounts),
                'revenue': self._get_revenue_metrics(accounts, date_from, date_to),
                'sync_status': self._get_sync_status(accounts),
            }
            
            return {
                'success': True,
                'data': metrics,
                'date_range': {
                    'from': str(date_from),
                    'to': str(date_to),
                },
            }
            
        except Exception as e:
            _logger.exception("Error getting dashboard data: %s", str(e))
            return {'error': str(e)}
    
    def _get_order_metrics(self, accounts, date_from, date_to):
        """Get order-related metrics."""
        env = request.env
        
        account_ids = accounts.ids
        base_domain = [
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(date_from)),
            ('purchase_date', '<=', str(date_to)),
        ]
        
        orders = env['amazon.order'].search(base_domain)
        
        return {
            'total': len(orders),
            'pending': len(orders.filtered(lambda o: o.status == 'Pending')),
            'unshipped': len(orders.filtered(lambda o: o.status == 'Unshipped')),
            'shipped': len(orders.filtered(lambda o: o.status == 'Shipped')),
            'canceled': len(orders.filtered(lambda o: o.status == 'Canceled')),
            'fba': len(orders.filtered(lambda o: o.fulfillment_channel == 'AFN')),
            'fbm': len(orders.filtered(lambda o: o.fulfillment_channel == 'MFN')),
        }
    
    def _get_inventory_metrics(self, accounts):
        """Get inventory-related metrics."""
        env = request.env
        
        account_ids = accounts.ids
        
        # FBA inventory
        fba_inventory = env['amazon.fba.inventory'].search([
            ('account_id', 'in', account_ids),
        ])
        
        low_stock = fba_inventory.filtered(
            lambda i: i.fulfillable_quantity <= i.reorder_point and i.reorder_point > 0
        )
        out_of_stock = fba_inventory.filtered(
            lambda i: i.fulfillable_quantity == 0
        )
        
        return {
            'total_fba_skus': len(fba_inventory),
            'total_fba_units': sum(fba_inventory.mapped('fulfillable_quantity')),
            'low_stock_count': len(low_stock),
            'out_of_stock_count': len(out_of_stock),
            'inbound_units': sum(fba_inventory.mapped('inbound_quantity')),
        }
    
    def _get_listing_metrics(self, accounts):
        """Get listing-related metrics."""
        env = request.env
        
        account_ids = accounts.ids
        
        listings = env['amazon.product.listing'].search([
            ('account_id', 'in', account_ids),
        ])
        
        return {
            'total': len(listings),
            'active': len(listings.filtered(lambda l: l.status == 'ACTIVE')),
            'inactive': len(listings.filtered(lambda l: l.status == 'INACTIVE')),
            'suppressed': len(listings.filtered(lambda l: l.status == 'SUPPRESSED')),
            'with_issues': len(listings.filtered(lambda l: l.issue_count > 0)),
            'buy_box_winners': len(listings.filtered(lambda l: l.is_buy_box_winner)),
        }
    
    def _get_revenue_metrics(self, accounts, date_from, date_to):
        """Get revenue-related metrics."""
        env = request.env
        
        account_ids = accounts.ids
        
        orders = env['amazon.order'].search([
            ('account_id', 'in', account_ids),
            ('purchase_date', '>=', str(date_from)),
            ('purchase_date', '<=', str(date_to)),
            ('status', 'not in', ['Canceled', 'Pending']),
        ])
        
        total_revenue = sum(orders.mapped('order_total'))
        
        # Calculate by marketplace
        by_marketplace = {}
        for order in orders:
            mp_name = order.marketplace_id.name
            if mp_name not in by_marketplace:
                by_marketplace[mp_name] = 0
            by_marketplace[mp_name] += order.order_total
        
        return {
            'total': total_revenue,
            'by_marketplace': by_marketplace,
            'order_count': len(orders),
            'average_order_value': total_revenue / len(orders) if orders else 0,
        }
    
    def _get_sync_status(self, accounts):
        """Get synchronization status."""
        statuses = []
        
        for account in accounts:
            statuses.append({
                'account_id': account.id,
                'account_name': account.name,
                'last_order_sync': str(account.last_order_sync) if account.last_order_sync else None,
                'last_inventory_sync': str(account.last_inventory_sync) if account.last_inventory_sync else None,
                'authorization_status': account.authorization_status,
                'is_healthy': account.authorization_status == 'authorized',
            })
        
        return statuses
    
    @http.route(
        '/amazon/health',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False
    )
    def health_check(self):
        """
        Simple health check endpoint for monitoring.
        
        Returns HTTP 200 if the connector is operational.
        """
        try:
            env = request.env(user=SUPERUSER_ID)
            
            # Check that required models exist
            required_models = [
                'amazon.account',
                'amazon.order',
                'amazon.product.listing',
            ]
            
            for model in required_models:
                if model not in env:
                    return request.make_response(
                        json.dumps({
                            'status': 'error',
                            'message': f'Model {model} not found',
                        }),
                        headers={'Content-Type': 'application/json'},
                        status=500
                    )
            
            # Count active accounts
            account_count = env['amazon.account'].search_count([('active', '=', True)])
            
            return request.make_response(
                json.dumps({
                    'status': 'ok',
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'active_accounts': account_count,
                }),
                headers={'Content-Type': 'application/json'}
            )
            
        except Exception as e:
            _logger.exception("Health check failed: %s", str(e))
            return request.make_response(
                json.dumps({
                    'status': 'error',
                    'message': str(e),
                }),
                headers={'Content-Type': 'application/json'},
                status=500
            )
    
    @http.route(
        '/amazon/sync/trigger',
        type='json',
        auth='user',
        methods=['POST']
    )
    def trigger_sync(self, account_id=None, sync_type='all', **kwargs):
        """
        Manually trigger a synchronization.
        
        Args:
            account_id: Account ID to sync (or all if not specified)
            sync_type: Type of sync ('orders', 'inventory', 'listings', 'all')
            
        Returns:
            Dict with sync status
        """
        try:
            # Check user permissions
            if not request.env.user.has_group('amazon_connector.group_amazon_user'):
                return {'error': 'Insufficient permissions'}
            
            env = request.env
            
            # Get accounts
            if account_id:
                accounts = env['amazon.account'].browse(int(account_id))
            else:
                accounts = env['amazon.account'].search([('active', '=', True)])
            
            if not accounts:
                return {'error': 'No accounts found'}
            
            results = []
            
            for account in accounts:
                result = {'account': account.name, 'syncs': []}
                
                if sync_type in ('orders', 'all'):
                    try:
                        account._sync_orders()
                        result['syncs'].append({'type': 'orders', 'status': 'success'})
                    except Exception as e:
                        result['syncs'].append({'type': 'orders', 'status': 'error', 'error': str(e)})
                
                if sync_type in ('inventory', 'all'):
                    try:
                        account._sync_inventory()
                        result['syncs'].append({'type': 'inventory', 'status': 'success'})
                    except Exception as e:
                        result['syncs'].append({'type': 'inventory', 'status': 'error', 'error': str(e)})
                
                if sync_type in ('listings', 'all'):
                    try:
                        account._sync_listings()
                        result['syncs'].append({'type': 'listings', 'status': 'success'})
                    except Exception as e:
                        result['syncs'].append({'type': 'listings', 'status': 'error', 'error': str(e)})
                
                results.append(result)
            
            return {
                'success': True,
                'results': results,
            }
            
        except Exception as e:
            _logger.exception("Error triggering sync: %s", str(e))
            return {'error': str(e)}
    
    @http.route(
        '/amazon/account/<int:account_id>/status',
        type='json',
        auth='user',
        methods=['GET']
    )
    def get_account_status(self, account_id, **kwargs):
        """
        Get detailed status for a specific account.
        
        Args:
            account_id: Account ID
            
        Returns:
            Dict with account status details
        """
        try:
            account = request.env['amazon.account'].browse(account_id)
            
            if not account.exists():
                return {'error': 'Account not found'}
            
            return {
                'success': True,
                'account': {
                    'id': account.id,
                    'name': account.name,
                    'seller_id': account.seller_id,
                    'authorization_status': account.authorization_status,
                    'authorized_date': str(account.authorized_date) if account.authorized_date else None,
                    'last_order_sync': str(account.last_order_sync) if account.last_order_sync else None,
                    'last_inventory_sync': str(account.last_inventory_sync) if account.last_inventory_sync else None,
                    'marketplaces': [
                        {'id': m.id, 'name': m.name, 'country_code': m.country_code}
                        for m in account.marketplace_ids
                    ],
                    'is_sandbox': account.is_sandbox,
                    'active': account.active,
                },
            }
            
        except Exception as e:
            _logger.exception("Error getting account status: %s", str(e))
            return {'error': str(e)}
