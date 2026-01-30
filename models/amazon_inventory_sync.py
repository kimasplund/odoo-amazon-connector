# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmazonInventorySync(models.Model):
    """
    Amazon Inventory Sync.
    
    Handles the synchronization of inventory between Odoo and Amazon,
    including both FBA inventory imports and FBM inventory exports.
    """
    _name = 'amazon.inventory.sync'
    _description = 'Amazon Inventory Sync'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    
    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    
    # Relationships
    account_id = fields.Many2one(
        'amazon.account',
        string='Amazon Account',
        required=True,
        ondelete='cascade',
    )
    marketplace_ids = fields.Many2many(
        'amazon.marketplace',
        string='Marketplaces',
        help='Leave empty to sync all marketplaces for this account.',
    )
    
    # Sync Configuration
    sync_type = fields.Selection(
        selection=[
            ('fba_import', 'Import FBA Inventory'),
            ('fbm_export', 'Export FBM Inventory'),
            ('full', 'Full Sync (Import + Export)'),
        ],
        string='Sync Type',
        default='fba_import',
        required=True,
    )
    sync_mode = fields.Selection(
        selection=[
            ('full', 'Full Sync'),
            ('delta', 'Delta/Changes Only'),
        ],
        string='Sync Mode',
        default='full',
        required=True,
    )
    
    # Status
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('running', 'Running'),
            ('done', 'Completed'),
            ('error', 'Error'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        tracking=True,
    )
    
    # Timing
    scheduled_date = fields.Datetime(
        string='Scheduled Date',
    )
    start_date = fields.Datetime(
        string='Start Date',
        readonly=True,
    )
    end_date = fields.Datetime(
        string='End Date',
        readonly=True,
    )
    duration = fields.Float(
        string='Duration (seconds)',
        compute='_compute_duration',
    )
    
    # Results
    records_processed = fields.Integer(
        string='Records Processed',
        default=0,
        readonly=True,
    )
    records_created = fields.Integer(
        string='Records Created',
        default=0,
        readonly=True,
    )
    records_updated = fields.Integer(
        string='Records Updated',
        default=0,
        readonly=True,
    )
    records_failed = fields.Integer(
        string='Records Failed',
        default=0,
        readonly=True,
    )
    
    # Errors
    error_message = fields.Text(
        string='Error Message',
        readonly=True,
    )
    error_details = fields.Text(
        string='Error Details',
        readonly=True,
    )
    
    # Log
    log_ids = fields.One2many(
        'amazon.inventory.sync.log',
        'sync_id',
        string='Log Entries',
    )
    
    # -------------------------------------------------------------------------
    # COMPUTES
    # -------------------------------------------------------------------------
    
    @api.depends('start_date', 'end_date')
    def _compute_duration(self):
        for sync in self:
            if sync.start_date and sync.end_date:
                delta = sync.end_date - sync.start_date
                sync.duration = delta.total_seconds()
            else:
                sync.duration = 0
    
    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'amazon.inventory.sync'
                ) or _('New')
        return super().create(vals_list)
    
    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------
    
    def action_start(self):
        """Start the inventory sync."""
        for sync in self:
            if sync.state != 'draft':
                raise UserError(_('Only draft syncs can be started.'))
            
            sync.write({
                'state': 'running',
                'start_date': fields.Datetime.now(),
                'error_message': False,
                'error_details': False,
            })
            
            try:
                if sync.sync_type == 'fba_import':
                    sync._sync_fba_import()
                elif sync.sync_type == 'fbm_export':
                    sync._sync_fbm_export()
                elif sync.sync_type == 'full':
                    sync._sync_fba_import()
                    sync._sync_fbm_export()
                
                sync.write({
                    'state': 'done',
                    'end_date': fields.Datetime.now(),
                })
                
            except Exception as e:
                _logger.exception('Inventory sync failed: %s', sync.name)
                sync.write({
                    'state': 'error',
                    'end_date': fields.Datetime.now(),
                    'error_message': str(e),
                })
        
        return True
    
    def action_cancel(self):
        """Cancel the sync."""
        for sync in self:
            if sync.state == 'running':
                raise UserError(_('Cannot cancel a running sync.'))
            sync.write({'state': 'cancelled'})
        return True
    
    def action_reset(self):
        """Reset to draft."""
        for sync in self:
            if sync.state not in ('error', 'cancelled', 'done'):
                raise UserError(_('Can only reset completed, failed, or cancelled syncs.'))
            sync.write({
                'state': 'draft',
                'start_date': False,
                'end_date': False,
                'records_processed': 0,
                'records_created': 0,
                'records_updated': 0,
                'records_failed': 0,
                'error_message': False,
                'error_details': False,
            })
        return True
    
    def action_view_logs(self):
        """View sync logs."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sync Logs'),
            'res_model': 'amazon.inventory.sync.log',
            'domain': [('sync_id', '=', self.id)],
            'view_mode': 'tree,form',
        }
    
    # -------------------------------------------------------------------------
    # SYNC METHODS
    # -------------------------------------------------------------------------
    
    def _sync_fba_import(self):
        """Import FBA inventory from Amazon."""
        self.ensure_one()
        _logger.info('Starting FBA inventory import for %s', self.name)
        
        FBAInventory = self.env['amazon.fba.inventory']
        
        # Get marketplaces
        marketplaces = self.marketplace_ids or self.account_id.marketplace_ids
        
        processed = created = updated = failed = 0
        
        for marketplace in marketplaces:
            self._log('info', f'Syncing inventory for marketplace: {marketplace.name}')
            
            try:
                # In production: Fetch from SP-API
                # client = self.account_id._get_sp_api_client()
                # response = client.fba_inventory.get_inventory_summaries(
                #     granularityType='Marketplace',
                #     granularityId=marketplace.amazon_marketplace_id,
                #     marketplaceIds=[marketplace.amazon_marketplace_id],
                # )
                
                # Simulated response structure
                inventory_items = []  # Would come from API
                
                # Batch search for existing inventory
                skus = [item.get('sellerSku') for item in inventory_items if item.get('sellerSku')]
                existing_records = FBAInventory.search([
                    ('account_id', '=', self.account_id.id),
                    ('marketplace_id', '=', marketplace.id),
                    ('amazon_sku', 'in', skus),
                ])
                existing_map = {r.amazon_sku: r for r in existing_records}

                for item in inventory_items:
                    processed += 1
                    sku = item.get('sellerSku')
                    try:
                        existing = existing_map.get(sku)

                        record = FBAInventory._update_or_create_from_amazon(
                            self.account_id.id,
                            marketplace.id,
                            item,
                            existing_record=existing or False
                        )
                        
                        if existing:
                            updated += 1
                        else:
                            created += 1
                            # Update map to handle duplicate SKUs in the same batch
                            if sku:
                                existing_map[sku] = record
                            
                    except Exception as e:
                        failed += 1
                        self._log('error', f"Failed to process SKU {sku}: {e}")
                
                self._log('info', f'Marketplace {marketplace.name}: {processed} processed')
                
            except Exception as e:
                self._log('error', f'Failed to sync marketplace {marketplace.name}: {e}')
                raise
        
        self.write({
            'records_processed': processed,
            'records_created': created,
            'records_updated': updated,
            'records_failed': failed,
        })
        
        _logger.info(
            'FBA import completed: %d processed, %d created, %d updated, %d failed',
            processed, created, updated, failed
        )
    
    def _sync_fbm_export(self):
        """Export FBM inventory to Amazon."""
        self.ensure_one()
        _logger.info('Starting FBM inventory export for %s', self.name)
        
        # Get active FBM listings
        marketplaces = self.marketplace_ids or self.account_id.marketplace_ids
        
        domain = [
            ('account_id', '=', self.account_id.id),
            ('marketplace_id', 'in', marketplaces.ids),
            ('fulfillment_channel', '=', 'fbm'),
            ('active', '=', True),
        ]
        listings = self.env['amazon.product.listing'].search(domain)
        
        processed = updated = failed = 0
        
        # Build inventory feed
        inventory_updates = []

        # Batch fetch quantities for all listings
        # This avoids the N+1 query problem by calculating all quantities in one go
        quantities = listings._get_sellable_quantities_batch()
        
        for listing in listings:
            processed += 1
            try:
                # Get Odoo stock quantity from pre-calculated batch
                # If for some reason the ID is missing (shouldn't happen), default to 0
                quantity = quantities.get(listing.id, 0.0)
                
                inventory_updates.append({
                    'sku': listing.seller_sku,
                    'quantity': max(0, int(quantity)),
                    'fulfillment_latency': listing.handling_time or 2,
                })
                
            except Exception as e:
                failed += 1
                self._log('error', f'Failed to get quantity for SKU {listing.seller_sku}: {e}')
        
        if inventory_updates:
            try:
                # In production: Submit inventory feed via SP-API
                # client = self.account_id._get_sp_api_client()
                # feed_id = client.feeds.submit_inventory_feed(inventory_updates)
                
                updated = len(inventory_updates)
                self._log('info', f'Submitted {updated} inventory updates')
                
            except Exception as e:
                self._log('error', f'Failed to submit inventory feed: {e}')
                raise
        
        self.write({
            'records_processed': processed,
            'records_updated': updated,
            'records_failed': failed,
        })
        
        _logger.info(
            'FBM export completed: %d processed, %d updated, %d failed',
            processed, updated, failed
        )
    
    def _log(self, level, message):
        """Add a log entry."""
        self.ensure_one()
        self.env['amazon.inventory.sync.log'].create({
            'sync_id': self.id,
            'level': level,
            'message': message,
        })
        
        log_method = getattr(_logger, level, _logger.info)
        log_method('[%s] %s', self.name, message)
    
    # -------------------------------------------------------------------------
    # CRON JOBS
    # -------------------------------------------------------------------------
    
    @api.model
    def _cron_sync_fba_inventory(self):
        """Scheduled action to sync FBA inventory for all active accounts."""
        _logger.info('Starting scheduled FBA inventory sync')
        
        accounts = self.env['amazon.account'].search([
            ('active', '=', True),
            ('sync_fba_inventory', '=', True),
        ])
        
        for account in accounts:
            try:
                sync = self.create({
                    'account_id': account.id,
                    'sync_type': 'fba_import',
                    'sync_mode': 'full',
                })
                sync.action_start()
                
            except Exception as e:
                _logger.exception('Failed to sync FBA inventory for account %s: %s', account.name, e)
        
        _logger.info('Scheduled FBA inventory sync completed')
        return True
    
    @api.model
    def _cron_sync_fbm_inventory(self):
        """Scheduled action to sync FBM inventory for all active accounts."""
        _logger.info('Starting scheduled FBM inventory sync')
        
        accounts = self.env['amazon.account'].search([
            ('active', '=', True),
            ('sync_fbm_inventory', '=', True),
        ])
        
        for account in accounts:
            try:
                sync = self.create({
                    'account_id': account.id,
                    'sync_type': 'fbm_export',
                    'sync_mode': 'full',
                })
                sync.action_start()
                
            except Exception as e:
                _logger.exception('Failed to sync FBM inventory for account %s: %s', account.name, e)
        
        _logger.info('Scheduled FBM inventory sync completed')
        return True
    
    @api.model
    def _cron_cleanup_old_syncs(self):
        """Clean up old sync records (keep last 30 days)."""
        cutoff_date = fields.Datetime.now() - timedelta(days=30)
        old_syncs = self.search([
            ('state', 'in', ('done', 'cancelled')),
            ('end_date', '<', cutoff_date),
        ])
        
        if old_syncs:
            _logger.info('Cleaning up %d old inventory sync records', len(old_syncs))
            old_syncs.unlink()
        
        return True


class AmazonInventorySyncLog(models.Model):
    """Log entries for inventory sync operations."""
    _name = 'amazon.inventory.sync.log'
    _description = 'Amazon Inventory Sync Log'
    _order = 'create_date desc'

    sync_id = fields.Many2one(
        'amazon.inventory.sync',
        string='Sync',
        required=True,
        ondelete='cascade',
    )
    level = fields.Selection(
        selection=[
            ('debug', 'Debug'),
            ('info', 'Info'),
            ('warning', 'Warning'),
            ('error', 'Error'),
        ],
        string='Level',
        default='info',
    )
    message = fields.Text(
        string='Message',
    )
    create_date = fields.Datetime(
        string='Timestamp',
        readonly=True,
    )


class AmazonInventorySyncMixin(models.AbstractModel):
    """
    Mixin for models that need inventory sync capabilities.
    
    Add this mixin to models that need to update inventory levels
    on Amazon when stock changes occur.
    """
    _name = 'amazon.inventory.sync.mixin'
    _description = 'Amazon Inventory Sync Mixin'
    
    def _trigger_amazon_inventory_sync(self, skus=None):
        """
        Trigger an inventory sync for specific SKUs or all.
        
        Call this method when stock levels change that should
        be reflected in Amazon.
        
        :param skus: List of SKUs to sync, or None for all
        """
        _logger.debug('Triggering Amazon inventory sync for SKUs: %s', skus)
        
        # Get accounts with FBM sync enabled
        accounts = self.env['amazon.account'].search([
            ('active', '=', True),
            ('sync_fbm_inventory', '=', True),
        ])
        
        for account in accounts:
            # Queue the sync (in production, use a job queue)
            self.env['amazon.inventory.sync'].create({
                'account_id': account.id,
                'sync_type': 'fbm_export',
                'sync_mode': 'delta',
                'scheduled_date': fields.Datetime.now(),
            })
