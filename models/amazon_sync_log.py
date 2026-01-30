# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

from odoo import api, fields, models, _


class AmazonSyncLog(models.Model):
    """Amazon Synchronization Log.
    
    Tracks all synchronization operations between Odoo and Amazon SP-API.
    Provides audit trail and debugging information.
    """
    _name = 'amazon.sync.log'
    _description = 'Amazon Sync Log'
    _order = 'create_date desc'
    _rec_name = 'operation'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    account_id = fields.Many2one(
        comodel_name='amazon.account',
        string='Account',
        required=True,
        ondelete='cascade',
        index=True,
        help='Amazon account this sync log belongs to',
    )
    marketplace_id = fields.Many2one(
        comodel_name='amazon.marketplace',
        string='Marketplace',
        ondelete='set null',
        index=True,
        help='Marketplace involved in this operation',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='account_id.company_id',
        store=True,
    )

    # Operation Details
    operation = fields.Selection(
        selection=[
            ('product_sync', 'Product Sync'),
            ('product_import', 'Product Import'),
            ('product_export', 'Product Export'),
            ('order_sync', 'Order Sync'),
            ('order_import', 'Order Import'),
            ('order_update', 'Order Update'),
            ('inventory_sync', 'Inventory Sync'),
            ('inventory_update', 'Inventory Update'),
            ('price_sync', 'Price Sync'),
            ('price_update', 'Price Update'),
            ('fba_sync', 'FBA Sync'),
            ('fba_shipment', 'FBA Shipment'),
            ('settlement_import', 'Settlement Import'),
            ('feed_submit', 'Feed Submit'),
            ('feed_result', 'Feed Result'),
            ('token_refresh', 'Token Refresh'),
            ('connection_test', 'Connection Test'),
            ('other', 'Other'),
        ],
        string='Operation',
        required=True,
        index=True,
        help='Type of sync operation',
    )
    status = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('running', 'Running'),
            ('success', 'Success'),
            ('warning', 'Warning'),
            ('error', 'Error'),
        ],
        string='Status',
        default='pending',
        required=True,
        index=True,
        help='Operation status',
    )
    
    # Results
    message = fields.Text(
        string='Message',
        help='Status message or error description',
    )
    record_count = fields.Integer(
        string='Records',
        default=0,
        help='Number of records processed',
    )
    created_count = fields.Integer(
        string='Created',
        default=0,
        help='Number of records created',
    )
    updated_count = fields.Integer(
        string='Updated',
        default=0,
        help='Number of records updated',
    )
    error_count = fields.Integer(
        string='Errors',
        default=0,
        help='Number of errors encountered',
    )
    
    # Timing
    start_time = fields.Datetime(
        string='Start Time',
        help='When the operation started',
    )
    end_time = fields.Datetime(
        string='End Time',
        help='When the operation finished',
    )
    duration = fields.Float(
        string='Duration (s)',
        compute='_compute_duration',
        store=True,
        help='Operation duration in seconds',
    )
    
    # Technical Data (for debugging)
    request_data = fields.Text(
        string='Request Data',
        groups='base.group_no_one',
        help='Raw API request data (JSON)',
    )
    response_data = fields.Text(
        string='Response Data',
        groups='base.group_no_one',
        help='Raw API response data (JSON)',
    )
    traceback = fields.Text(
        string='Traceback',
        groups='base.group_no_one',
        help='Python traceback if error occurred',
    )
    
    # Reference to processed records
    model_name = fields.Char(
        string='Model',
        help='Name of the Odoo model affected',
    )
    record_ids = fields.Char(
        string='Record IDs',
        help='Comma-separated list of affected record IDs',
    )

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    @api.depends('start_time', 'end_time')
    def _compute_duration(self):
        for log in self:
            if log.start_time and log.end_time:
                delta = log.end_time - log.start_time
                log.duration = delta.total_seconds()
            else:
                log.duration = 0.0

    # -------------------------------------------------------------------------
    # CRUD METHODS
    # -------------------------------------------------------------------------
    @api.autovacuum
    def _gc_old_logs(self):
        """Garbage collect old log entries (keep last 90 days)."""
        from datetime import timedelta
        limit_date = fields.Datetime.now() - timedelta(days=90)
        old_logs = self.search([('create_date', '<', limit_date)])
        old_logs.unlink()

    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------
    @api.model
    def create_log(self, account_id, operation, **kwargs):
        """Create a new sync log entry.
        
        Args:
            account_id: Amazon account ID
            operation: Operation type
            **kwargs: Additional log fields
            
        Returns:
            New amazon.sync.log record
        """
        vals = {
            'account_id': account_id,
            'operation': operation,
            'start_time': fields.Datetime.now(),
            'status': 'running',
        }
        vals.update(kwargs)
        return self.create(vals)

    def complete(self, status='success', message=None, **kwargs):
        """Mark the log as complete.
        
        Args:
            status: Final status (success, warning, error)
            message: Status message
            **kwargs: Additional fields to update
        """
        vals = {
            'status': status,
            'end_time': fields.Datetime.now(),
        }
        if message:
            vals['message'] = message
        vals.update(kwargs)
        self.write(vals)

    def log_error(self, message, traceback=None):
        """Log an error status.
        
        Args:
            message: Error message
            traceback: Python traceback string
        """
        self.write({
            'status': 'error',
            'message': message,
            'traceback': traceback,
            'end_time': fields.Datetime.now(),
        })

    def action_view_records(self):
        """View the records affected by this sync operation."""
        self.ensure_one()
        if not self.model_name or not self.record_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Records'),
                    'message': _('No records are linked to this log entry.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        
        record_ids = [int(x) for x in self.record_ids.split(',') if x.strip()]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Affected Records'),
            'res_model': self.model_name,
            'view_mode': 'tree,form',
            'domain': [('id', 'in', record_ids)],
        }
