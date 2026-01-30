# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmazonDemandHistory(models.Model):
    """
    Amazon Demand History.
    
    Stores daily/weekly sales snapshots for trend analysis and forecasting.
    This data is used by the forecasting algorithms to predict future demand.
    """
    _name = 'amazon.demand.history'
    _description = 'Amazon Demand History'
    _order = 'date desc, product_id'
    _rec_name = 'display_name'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )
    
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
    
    # Time dimension
    date = fields.Date(
        string='Date',
        required=True,
        index=True,
        help='Date of the sales snapshot (daily granularity).',
    )
    week_number = fields.Integer(
        string='Week Number',
        compute='_compute_time_dimensions',
        store=True,
    )
    month = fields.Integer(
        string='Month',
        compute='_compute_time_dimensions',
        store=True,
    )
    year = fields.Integer(
        string='Year',
        compute='_compute_time_dimensions',
        store=True,
    )
    day_of_week = fields.Integer(
        string='Day of Week',
        compute='_compute_time_dimensions',
        store=True,
        help='0=Monday, 6=Sunday',
    )
    is_weekend = fields.Boolean(
        string='Is Weekend',
        compute='_compute_time_dimensions',
        store=True,
    )
    
    # Sales data
    units_sold = fields.Integer(
        string='Units Sold',
        default=0,
        help='Number of units sold on this date.',
    )
    units_ordered = fields.Integer(
        string='Units Ordered',
        default=0,
        help='Number of units ordered (may include pending).',
    )
    units_returned = fields.Integer(
        string='Units Returned',
        default=0,
        help='Number of units returned on this date.',
    )
    net_units = fields.Integer(
        string='Net Units',
        compute='_compute_net_units',
        store=True,
        help='Units sold minus returns.',
    )
    
    # Revenue data
    revenue = fields.Monetary(
        string='Revenue',
        currency_field='currency_id',
        default=0.0,
        help='Total revenue from sales on this date.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='marketplace_id.currency_id',
        store=True,
    )
    average_selling_price = fields.Monetary(
        string='Avg. Selling Price',
        currency_field='currency_id',
        compute='_compute_average_price',
        store=True,
    )
    
    # Inventory snapshots
    inventory_available = fields.Integer(
        string='Inventory Available',
        default=0,
        help='Inventory level at end of day.',
    )
    inventory_inbound = fields.Integer(
        string='Inventory Inbound',
        default=0,
        help='Inbound inventory at end of day.',
    )
    
    # Status flags
    is_stockout = fields.Boolean(
        string='Was Stockout',
        default=False,
        help='True if product was out of stock during this day.',
    )
    stockout_hours = fields.Float(
        string='Stockout Hours',
        default=0.0,
        help='Estimated hours out of stock (affects demand estimation).',
    )
    
    # Data quality
    data_source = fields.Selection(
        selection=[
            ('orders', 'From Orders'),
            ('reports', 'From Reports'),
            ('estimated', 'Estimated'),
            ('manual', 'Manual Entry'),
        ],
        string='Data Source',
        default='orders',
    )
    confidence_score = fields.Float(
        string='Confidence Score',
        default=1.0,
        help='1.0 = high confidence, lower values for estimated data.',
    )
    
    # -------------------------------------------------------------------------
    # COMPUTES
    # -------------------------------------------------------------------------
    
    @api.depends('product_id', 'marketplace_id', 'date')
    def _compute_display_name(self):
        for record in self:
            parts = []
            if record.product_id:
                parts.append(record.product_id.default_code or record.product_id.name[:20])
            if record.marketplace_id:
                parts.append(record.marketplace_id.code)
            if record.date:
                parts.append(str(record.date))
            record.display_name = ' - '.join(parts) or _('New')
    
    @api.depends('date')
    def _compute_time_dimensions(self):
        for record in self:
            if record.date:
                record.week_number = record.date.isocalendar()[1]
                record.month = record.date.month
                record.year = record.date.year
                record.day_of_week = record.date.weekday()
                record.is_weekend = record.day_of_week >= 5
            else:
                record.week_number = 0
                record.month = 0
                record.year = 0
                record.day_of_week = 0
                record.is_weekend = False
    
    @api.depends('units_sold', 'units_returned')
    def _compute_net_units(self):
        for record in self:
            record.net_units = record.units_sold - record.units_returned
    
    @api.depends('revenue', 'units_sold')
    def _compute_average_price(self):
        for record in self:
            if record.units_sold > 0:
                record.average_selling_price = record.revenue / record.units_sold
            else:
                record.average_selling_price = 0.0
    
    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------
    
    _sql_constraints = [
        (
            'unique_product_marketplace_date',
            'UNIQUE(product_id, marketplace_id, date)',
            'Only one demand history record per product/marketplace/date!'
        ),
    ]
    
    # -------------------------------------------------------------------------
    # CRUD OVERRIDES
    # -------------------------------------------------------------------------
    
    @api.model_create_multi
    def create(self, vals_list):
        """Set confidence score based on data source."""
        for vals in vals_list:
            if 'confidence_score' not in vals and 'data_source' in vals:
                source = vals['data_source']
                vals['confidence_score'] = {
                    'orders': 1.0,
                    'reports': 0.95,
                    'estimated': 0.7,
                    'manual': 0.8,
                }.get(source, 1.0)
        return super().create(vals_list)
    
    # -------------------------------------------------------------------------
    # DATA COLLECTION METHODS
    # -------------------------------------------------------------------------
    
    @api.model
    def _collect_demand_from_orders(self, account_id, marketplace_id, date):
        """
        Collect demand data from Amazon orders for a specific date.
        
        :param account_id: amazon.account ID
        :param marketplace_id: amazon.marketplace ID
        :param date: date object
        :return: dict with demand data
        """
        Order = self.env['amazon.order']
        OrderLine = self.env['amazon.order.line']
        
        # Get orders for the date
        date_start = datetime.combine(date, datetime.min.time())
        date_end = datetime.combine(date, datetime.max.time())
        
        orders = Order.search([
            ('account_id', '=', account_id),
            ('marketplace_id', '=', marketplace_id),
            ('purchase_date', '>=', date_start),
            ('purchase_date', '<=', date_end),
            ('order_status', 'not in', ['canceled', 'pending']),
        ])
        
        # Aggregate by product
        product_data = {}
        for order in orders:
            for line in order.order_line_ids:
                if not line.product_id:
                    continue
                    
                product_id = line.product_id.id
                if product_id not in product_data:
                    product_data[product_id] = {
                        'units_sold': 0,
                        'units_ordered': 0,
                        'revenue': 0.0,
                    }
                
                qty = line.quantity_ordered or 0
                product_data[product_id]['units_sold'] += qty
                product_data[product_id]['units_ordered'] += qty
                product_data[product_id]['revenue'] += line.item_price or 0.0
        
        return product_data
    
    @api.model
    def _collect_returns_for_date(self, account_id, marketplace_id, date):
        """
        Collect return data for a specific date.
        
        :param account_id: amazon.account ID
        :param marketplace_id: amazon.marketplace ID
        :param date: date object
        :return: dict mapping product_id to return quantity
        """
        Return = self.env['amazon.return']
        
        returns = Return.search([
            ('account_id', '=', account_id),
            ('marketplace_id', '=', marketplace_id),
            ('return_date', '>=', date),
            ('return_date', '<', date + timedelta(days=1)),
        ])
        
        product_returns = {}
        for ret in returns:
            if ret.product_id:
                product_id = ret.product_id.id
                product_returns[product_id] = product_returns.get(product_id, 0) + (ret.quantity or 1)
        
        return product_returns
    
    @api.model
    def _update_or_create_history(self, account_id, marketplace_id, product_id, date, data):
        """
        Update or create a demand history record.
        
        :param account_id: amazon.account ID
        :param marketplace_id: amazon.marketplace ID
        :param product_id: product.product ID
        :param date: date object
        :param data: dict with demand data
        :return: amazon.demand.history record
        """
        existing = self.search([
            ('account_id', '=', account_id),
            ('marketplace_id', '=', marketplace_id),
            ('product_id', '=', product_id),
            ('date', '=', date),
        ], limit=1)
        
        vals = {
            'account_id': account_id,
            'marketplace_id': marketplace_id,
            'product_id': product_id,
            'date': date,
            'units_sold': data.get('units_sold', 0),
            'units_ordered': data.get('units_ordered', 0),
            'units_returned': data.get('units_returned', 0),
            'revenue': data.get('revenue', 0.0),
            'inventory_available': data.get('inventory_available', 0),
            'inventory_inbound': data.get('inventory_inbound', 0),
            'is_stockout': data.get('is_stockout', False),
            'data_source': data.get('data_source', 'orders'),
        }
        
        if existing:
            existing.write(vals)
            return existing
        else:
            return self.create(vals)
    
    # -------------------------------------------------------------------------
    # CRON METHODS
    # -------------------------------------------------------------------------
    
    @api.model
    def _cron_collect_demand_history(self):
        """
        Cron job to collect demand history from orders.
        Collects data for yesterday (to ensure all orders are processed).
        """
        _logger.info('Starting demand history collection cron')
        
        yesterday = fields.Date.today() - timedelta(days=1)
        
        # Get all active accounts
        Account = self.env['amazon.account']
        accounts = Account.search([('state', '=', 'active')])
        
        for account in accounts:
            for marketplace in account.marketplace_ids:
                try:
                    self._collect_daily_history(account.id, marketplace.id, yesterday)
                except Exception as e:
                    _logger.exception(
                        'Error collecting demand history for account %s, marketplace %s: %s',
                        account.name, marketplace.code, str(e)
                    )
        
        _logger.info('Completed demand history collection cron')
    
    def _collect_daily_history(self, account_id, marketplace_id, date):
        """
        Collect and store demand history for a specific date.
        """
        # Get order data
        product_data = self._collect_demand_from_orders(account_id, marketplace_id, date)
        
        # Get return data
        product_returns = self._collect_returns_for_date(account_id, marketplace_id, date)
        
        # Merge returns into product data
        for product_id, returns in product_returns.items():
            if product_id not in product_data:
                product_data[product_id] = {
                    'units_sold': 0,
                    'units_ordered': 0,
                    'revenue': 0.0,
                }
            product_data[product_id]['units_returned'] = returns
        
        # Get inventory snapshots if available
        FBAInventory = self.env['amazon.fba.inventory']
        inventory_records = FBAInventory.search([
            ('account_id', '=', account_id),
            ('marketplace_id', '=', marketplace_id),
        ])
        
        inventory_map = {}
        for inv in inventory_records:
            if inv.product_id:
                inventory_map[inv.product_id.id] = {
                    'inventory_available': inv.quantity_available,
                    'inventory_inbound': inv.quantity_inbound_total,
                    'is_stockout': inv.quantity_available == 0,
                }
        
        # Create/update history records
        for product_id, data in product_data.items():
            if product_id in inventory_map:
                data.update(inventory_map[product_id])
            
            self._update_or_create_history(
                account_id, marketplace_id, product_id, date, data
            )
        
        # Also create records for products with inventory but no sales
        for product_id, inv_data in inventory_map.items():
            if product_id not in product_data:
                data = {
                    'units_sold': 0,
                    'units_ordered': 0,
                    'revenue': 0.0,
                    **inv_data,
                }
                self._update_or_create_history(
                    account_id, marketplace_id, product_id, date, data
                )
    
    # -------------------------------------------------------------------------
    # ANALYSIS METHODS
    # -------------------------------------------------------------------------
    
    @api.model
    def get_sales_history(self, product_id, marketplace_id, days=90):
        """
        Get sales history for a product.
        
        :param product_id: product.product ID
        :param marketplace_id: amazon.marketplace ID
        :param days: number of days to look back
        :return: list of dicts with date and units_sold
        """
        start_date = fields.Date.today() - timedelta(days=days)
        
        records = self.search([
            ('product_id', '=', product_id),
            ('marketplace_id', '=', marketplace_id),
            ('date', '>=', start_date),
        ], order='date asc')
        
        return [{
            'date': r.date,
            'units_sold': r.units_sold,
            'net_units': r.net_units,
            'revenue': r.revenue,
            'is_stockout': r.is_stockout,
            'confidence_score': r.confidence_score,
        } for r in records]
    
    @api.model
    def get_weekly_aggregates(self, product_id, marketplace_id, weeks=13):
        """
        Get weekly sales aggregates for trend analysis.
        
        :param product_id: product.product ID
        :param marketplace_id: amazon.marketplace ID
        :param weeks: number of weeks to look back
        :return: list of dicts with week data
        """
        start_date = fields.Date.today() - timedelta(weeks=weeks)
        
        self.env.cr.execute("""
            SELECT 
                year,
                week_number,
                SUM(units_sold) as total_units,
                SUM(net_units) as net_units,
                SUM(revenue) as total_revenue,
                COUNT(*) as days_with_data,
                SUM(CASE WHEN is_stockout THEN 1 ELSE 0 END) as stockout_days,
                AVG(confidence_score) as avg_confidence
            FROM amazon_demand_history
            WHERE product_id = %s
              AND marketplace_id = %s
              AND date >= %s
            GROUP BY year, week_number
            ORDER BY year, week_number
        """, (product_id, marketplace_id, start_date))
        
        results = []
        for row in self.env.cr.dictfetchall():
            results.append({
                'year': row['year'],
                'week_number': row['week_number'],
                'total_units': row['total_units'] or 0,
                'net_units': row['net_units'] or 0,
                'total_revenue': row['total_revenue'] or 0.0,
                'days_with_data': row['days_with_data'],
                'stockout_days': row['stockout_days'] or 0,
                'avg_confidence': row['avg_confidence'] or 1.0,
                # Adjust for stockouts (estimate lost sales)
                'adjusted_units': self._adjust_for_stockouts(
                    row['total_units'] or 0,
                    row['stockout_days'] or 0,
                    row['days_with_data']
                ),
            })
        
        return results
    
    @api.model
    def _adjust_for_stockouts(self, units_sold, stockout_days, total_days):
        """
        Adjust sales figures to estimate demand during stockouts.
        
        Uses average daily sales from in-stock days to estimate
        what would have sold during stockout periods.
        """
        if stockout_days == 0 or total_days == stockout_days:
            return units_sold
        
        in_stock_days = total_days - stockout_days
        if in_stock_days > 0:
            avg_daily = units_sold / in_stock_days
            estimated_lost = avg_daily * stockout_days
            return units_sold + estimated_lost
        
        return units_sold
    
    @api.model
    def get_same_period_last_year(self, product_id, marketplace_id, target_date, days=30):
        """
        Get sales data from the same period last year (for seasonality).
        
        :param product_id: product.product ID
        :param marketplace_id: amazon.marketplace ID
        :param target_date: date to compare
        :param days: window size
        :return: dict with sales summary
        """
        # Same period last year
        last_year_start = target_date - timedelta(days=365 + days//2)
        last_year_end = target_date - timedelta(days=365 - days//2)
        
        records = self.search([
            ('product_id', '=', product_id),
            ('marketplace_id', '=', marketplace_id),
            ('date', '>=', last_year_start),
            ('date', '<=', last_year_end),
        ])
        
        if not records:
            return None
        
        return {
            'total_units': sum(records.mapped('units_sold')),
            'avg_daily': sum(records.mapped('units_sold')) / len(records) if records else 0,
            'days_with_data': len(records),
            'stockout_days': len(records.filtered('is_stockout')),
        }
