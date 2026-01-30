# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class StockWarehouse(models.Model):
    """
    Extend stock.warehouse for Amazon FBA support.
    
    FBA warehouses represent virtual inventory locations for
    Amazon Fulfillment Centers. Stock at these locations is
    managed by Amazon, not the seller.
    """
    _inherit = 'stock.warehouse'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    
    # Amazon FBA Configuration
    is_amazon_fba = fields.Boolean(
        string='Is Amazon FBA Warehouse',
        default=False,
        help='Check if this warehouse represents Amazon FBA inventory.',
    )
    amazon_account_id = fields.Many2one(
        'amazon.account',
        string='Amazon Account',
        ondelete='set null',
        help='The Amazon seller account this FBA warehouse belongs to.',
    )
    amazon_marketplace_id = fields.Many2one(
        'amazon.marketplace',
        string='Amazon Marketplace',
        ondelete='set null',
        help='The primary marketplace for this FBA warehouse.',
    )
    amazon_fc_code = fields.Char(
        string='Fulfillment Center Code',
        help='Amazon FC code (e.g., FRA1, LBA2). Leave empty for aggregated FBA inventory.',
    )
    
    # FBA Warehouse Settings
    fba_warehouse_type = fields.Selection(
        selection=[
            ('aggregated', 'Aggregated (All FCs)'),
            ('country', 'Country-Level'),
            ('single_fc', 'Single Fulfillment Center'),
        ],
        string='FBA Warehouse Type',
        default='aggregated',
        help=(
            'Aggregated: Combined inventory across all FCs.\n'
            'Country-Level: Inventory for a specific country.\n'
            'Single FC: Inventory at one fulfillment center.'
        ),
    )
    fba_country_id = fields.Many2one(
        'res.country',
        string='FBA Country',
        help='For country-level FBA warehouses.',
    )
    
    # Inventory Sync Settings
    sync_fba_inventory = fields.Boolean(
        string='Sync FBA Inventory',
        default=True,
        help='Automatically sync inventory levels from Amazon.',
    )
    last_inventory_sync = fields.Datetime(
        string='Last Inventory Sync',
        readonly=True,
    )
    
    # Display
    amazon_warehouse_badge = fields.Char(
        string='Badge',
        compute='_compute_amazon_warehouse_badge',
    )
    
    # -------------------------------------------------------------------------
    # COMPUTES
    # -------------------------------------------------------------------------
    
    @api.depends('is_amazon_fba', 'amazon_marketplace_id', 'amazon_fc_code')
    def _compute_amazon_warehouse_badge(self):
        for warehouse in self:
            if warehouse.is_amazon_fba:
                parts = ['FBA']
                if warehouse.amazon_marketplace_id:
                    parts.append(warehouse.amazon_marketplace_id.code)
                if warehouse.amazon_fc_code:
                    parts.append(warehouse.amazon_fc_code)
                warehouse.amazon_warehouse_badge = ' - '.join(parts)
            else:
                warehouse.amazon_warehouse_badge = ''
    
    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------
    
    @api.constrains('is_amazon_fba', 'amazon_account_id')
    def _check_fba_account(self):
        for warehouse in self:
            if warehouse.is_amazon_fba and not warehouse.amazon_account_id:
                raise ValidationError(_(
                    'FBA warehouses must be linked to an Amazon account.'
                ))
    
    @api.constrains('is_amazon_fba', 'fba_warehouse_type', 'amazon_fc_code')
    def _check_fba_fc_code(self):
        for warehouse in self:
            if warehouse.is_amazon_fba and warehouse.fba_warehouse_type == 'single_fc':
                if not warehouse.amazon_fc_code:
                    raise ValidationError(_(
                        'Single FC warehouses must have a Fulfillment Center Code.'
                    ))
    
    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------
    
    @api.model_create_multi
    def create(self, vals_list):
        warehouses = super().create(vals_list)
        for warehouse in warehouses:
            if warehouse.is_amazon_fba:
                warehouse._configure_fba_warehouse()
        return warehouses
    
    def write(self, vals):
        result = super().write(vals)
        if vals.get('is_amazon_fba'):
            for warehouse in self:
                warehouse._configure_fba_warehouse()
        return result
    
    # -------------------------------------------------------------------------
    # CONFIGURATION
    # -------------------------------------------------------------------------
    
    def _configure_fba_warehouse(self):
        """Configure warehouse settings for FBA use."""
        self.ensure_one()
        _logger.info('Configuring FBA warehouse: %s', self.name)
        
        # FBA warehouses typically don't need certain operations
        # since Amazon handles fulfillment
        
        # Set location as internal (virtual storage)
        if self.lot_stock_id:
            self.lot_stock_id.write({
                'usage': 'internal',
                'comment': _('Amazon FBA Inventory Location'),
            })
        
        return True
    
    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------
    
    def action_sync_fba_inventory(self):
        """Manually trigger FBA inventory sync for this warehouse."""
        self.ensure_one()
        if not self.is_amazon_fba:
            raise ValidationError(_('This is not an FBA warehouse.'))
        
        # Create and run inventory sync
        sync = self.env['amazon.inventory.sync'].create({
            'account_id': self.amazon_account_id.id,
            'marketplace_ids': [(4, self.amazon_marketplace_id.id)] if self.amazon_marketplace_id else False,
            'sync_type': 'fba_import',
            'sync_mode': 'full',
        })
        sync.action_start()
        
        self.write({'last_inventory_sync': fields.Datetime.now()})
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Inventory Sync'),
            'res_model': 'amazon.inventory.sync',
            'res_id': sync.id,
            'view_mode': 'form',
        }
    
    def action_view_fba_inventory(self):
        """View FBA inventory for this warehouse."""
        self.ensure_one()
        if not self.is_amazon_fba:
            raise ValidationError(_('This is not an FBA warehouse.'))
        
        domain = [('account_id', '=', self.amazon_account_id.id)]
        if self.amazon_marketplace_id:
            domain.append(('marketplace_id', '=', self.amazon_marketplace_id.id))
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('FBA Inventory'),
            'res_model': 'amazon.fba.inventory',
            'domain': domain,
            'view_mode': 'tree,form',
            'context': {
                'default_account_id': self.amazon_account_id.id,
                'default_marketplace_id': self.amazon_marketplace_id.id if self.amazon_marketplace_id else False,
            },
        }
    
    def action_view_fba_shipments(self):
        """View FBA shipments to this warehouse."""
        self.ensure_one()
        if not self.is_amazon_fba:
            raise ValidationError(_('This is not an FBA warehouse.'))
        
        domain = [('account_id', '=', self.amazon_account_id.id)]
        if self.amazon_marketplace_id:
            domain.append(('marketplace_id', '=', self.amazon_marketplace_id.id))
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('FBA Shipments'),
            'res_model': 'amazon.fba.shipment',
            'domain': domain,
            'view_mode': 'tree,form',
        }
    
    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------
    
    @api.model
    def get_fba_warehouse(self, account_id, marketplace_id=None):
        """
        Get the FBA warehouse for a given account/marketplace.
        
        :param account_id: amazon.account ID
        :param marketplace_id: optional amazon.marketplace ID
        :return: stock.warehouse record or False
        """
        domain = [
            ('is_amazon_fba', '=', True),
            ('amazon_account_id', '=', account_id),
        ]
        
        if marketplace_id:
            # First try marketplace-specific warehouse
            warehouse = self.search(
                domain + [('amazon_marketplace_id', '=', marketplace_id)],
                limit=1
            )
            if warehouse:
                return warehouse
        
        # Fallback to aggregated warehouse for this account
        return self.search(domain, limit=1) or False
    
    @api.model
    def create_fba_warehouse_for_account(self, account):
        """
        Create a default FBA warehouse for an Amazon account.
        
        :param account: amazon.account record
        :return: stock.warehouse record
        """
        # Check if one already exists
        existing = self.search([
            ('is_amazon_fba', '=', True),
            ('amazon_account_id', '=', account.id),
            ('fba_warehouse_type', '=', 'aggregated'),
        ], limit=1)
        
        if existing:
            return existing
        
        # Get company
        company = account.company_id or self.env.company
        
        # Create warehouse
        warehouse = self.create({
            'name': f'Amazon FBA - {account.name}',
            'code': f'FBA{account.id}',
            'company_id': company.id,
            'is_amazon_fba': True,
            'amazon_account_id': account.id,
            'fba_warehouse_type': 'aggregated',
        })
        
        _logger.info('Created FBA warehouse %s for account %s', warehouse.name, account.name)
        return warehouse


class StockPicking(models.Model):
    """Extend stock.picking for Amazon FBA shipment linking."""
    _inherit = 'stock.picking'

    amazon_fba_shipment_id = fields.Many2one(
        'amazon.fba.shipment',
        string='Amazon FBA Shipment',
        ondelete='set null',
        index=True,
    )
    is_amazon_fba_transfer = fields.Boolean(
        string='Is FBA Transfer',
        compute='_compute_is_amazon_fba_transfer',
        store=True,
    )
    
    @api.depends('amazon_fba_shipment_id')
    def _compute_is_amazon_fba_transfer(self):
        for picking in self:
            picking.is_amazon_fba_transfer = bool(picking.amazon_fba_shipment_id)
    
    def action_view_fba_shipment(self):
        """Open the related FBA shipment."""
        self.ensure_one()
        if not self.amazon_fba_shipment_id:
            return False
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('FBA Shipment'),
            'res_model': 'amazon.fba.shipment',
            'res_id': self.amazon_fba_shipment_id.id,
            'view_mode': 'form',
        }


class StockQuant(models.Model):
    """
    Extend stock.quant for Amazon FBA inventory tracking.
    
    Provides utilities for comparing Odoo stock with Amazon
    FBA inventory levels.
    """
    _inherit = 'stock.quant'
    
    @api.model
    def get_fba_inventory_comparison(self, account_id, marketplace_id=None):
        """
        Compare Odoo FBA stock quantities with Amazon FBA inventory.
        
        Returns discrepancies between what Odoo shows and what
        Amazon reports for FBA inventory.
        
        :param account_id: amazon.account ID
        :param marketplace_id: optional amazon.marketplace ID
        :return: List of discrepancy dicts
        """
        warehouse = self.env['stock.warehouse'].get_fba_warehouse(
            account_id, marketplace_id
        )
        
        if not warehouse:
            return []
        
        # Get Odoo quants for FBA location
        quants = self.search([
            ('location_id', 'child_of', warehouse.lot_stock_id.id),
            ('quantity', '>', 0),
        ])
        
        # Get Amazon FBA inventory
        domain = [('account_id', '=', account_id)]
        if marketplace_id:
            domain.append(('marketplace_id', '=', marketplace_id))
        
        fba_inventory = self.env['amazon.fba.inventory'].search(domain)
        
        # Build comparison
        discrepancies = []
        
        amazon_by_product = {inv.product_id.id: inv for inv in fba_inventory if inv.product_id}
        odoo_by_product = {}
        
        for quant in quants:
            if quant.product_id.id not in odoo_by_product:
                odoo_by_product[quant.product_id.id] = 0
            odoo_by_product[quant.product_id.id] += quant.quantity
        
        # Find discrepancies
        all_products = set(amazon_by_product.keys()) | set(odoo_by_product.keys())
        
        for product_id in all_products:
            amazon_qty = amazon_by_product.get(product_id, False)
            amazon_qty = amazon_qty.quantity_available if amazon_qty else 0
            odoo_qty = odoo_by_product.get(product_id, 0)
            
            if amazon_qty != odoo_qty:
                product = self.env['product.product'].browse(product_id)
                discrepancies.append({
                    'product_id': product_id,
                    'product_name': product.display_name,
                    'odoo_quantity': odoo_qty,
                    'amazon_quantity': amazon_qty,
                    'difference': amazon_qty - odoo_qty,
                })
        
        return discrepancies
