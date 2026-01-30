# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AmazonFBAShipment(models.Model):
    """
    Amazon FBA Inbound Shipment.
    
    Manages the creation, tracking, and reconciliation of shipments
    sent to Amazon Fulfillment Centers.
    """
    _name = 'amazon.fba.shipment'
    _description = 'Amazon FBA Inbound Shipment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'display_name'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    
    # Identification
    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
        tracking=True,
    )
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )
    amazon_shipment_id = fields.Char(
        string='Amazon Shipment ID',
        index=True,
        copy=False,
        tracking=True,
        help='The unique identifier assigned by Amazon for this shipment.',
    )
    amazon_shipment_name = fields.Char(
        string='Amazon Shipment Name',
        tracking=True,
    )
    
    # Relationships
    account_id = fields.Many2one(
        'amazon.account',
        string='Amazon Account',
        required=True,
        ondelete='restrict',
        tracking=True,
    )
    marketplace_id = fields.Many2one(
        'amazon.marketplace',
        string='Marketplace',
        required=True,
        ondelete='restrict',
        tracking=True,
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Source Warehouse',
        required=True,
        ondelete='restrict',
        tracking=True,
        help='The warehouse from which inventory will be shipped.',
    )
    picking_ids = fields.One2many(
        'stock.picking',
        'amazon_fba_shipment_id',
        string='Transfers',
    )
    item_ids = fields.One2many(
        'amazon.fba.shipment.item',
        'shipment_id',
        string='Shipment Items',
        copy=True,
    )
    
    # Fulfillment Center
    destination_fc_id = fields.Char(
        string='Fulfillment Center ID',
        tracking=True,
        help='The Amazon Fulfillment Center code (e.g., FRA1, LBA2).',
    )
    destination_address = fields.Text(
        string='Destination Address',
        compute='_compute_destination_address',
        store=True,
    )
    destination_country_id = fields.Many2one(
        'res.country',
        string='Destination Country',
    )
    
    # Status & Workflow
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('working', 'Working'),
            ('ready_to_ship', 'Ready to Ship'),
            ('shipped', 'Shipped'),
            ('in_transit', 'In Transit'),
            ('delivered', 'Delivered'),
            ('checked_in', 'Checked In'),
            ('receiving', 'Receiving'),
            ('closed', 'Closed'),
            ('cancelled', 'Cancelled'),
            ('deleted', 'Deleted'),
            ('error', 'Error'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        index=True,
    )
    amazon_status = fields.Char(
        string='Amazon Status',
        readonly=True,
        help='Raw status from Amazon SP-API.',
    )
    
    # Shipment Details
    shipment_type = fields.Selection(
        selection=[
            ('sp', 'Small Parcel'),
            ('ltl', 'Less Than Truckload'),
            ('ftl', 'Full Truckload'),
        ],
        string='Shipment Type',
        default='sp',
        required=True,
        tracking=True,
    )
    label_prep_type = fields.Selection(
        selection=[
            ('no_label', 'No Label'),
            ('seller_label', 'Seller Label'),
            ('amazon_label', 'Amazon Label'),
        ],
        string='Label Prep',
        default='seller_label',
        required=True,
    )
    packing_type = fields.Selection(
        selection=[
            ('individual', 'Individual Products'),
            ('case_packed', 'Case-Packed Products'),
        ],
        string='Packing Type',
        default='individual',
    )
    
    # Carrier & Tracking
    carrier_id = fields.Many2one(
        'delivery.carrier',
        string='Carrier',
    )
    carrier_name = fields.Char(
        string='Carrier Name',
        help='Amazon carrier name if not mapped to Odoo carrier.',
    )
    tracking_numbers = fields.Text(
        string='Tracking Numbers',
        help='One tracking number per line.',
    )
    pro_number = fields.Char(
        string='PRO Number',
        help='Progressive number for LTL/FTL shipments.',
    )
    
    # Box/Package Information
    box_count = fields.Integer(
        string='Number of Boxes',
        compute='_compute_box_count',
        store=True,
    )
    total_weight = fields.Float(
        string='Total Weight (kg)',
        digits='Stock Weight',
    )
    total_volume = fields.Float(
        string='Total Volume (m³)',
        digits=(16, 4),
    )
    
    # Dates
    ship_date = fields.Date(
        string='Ship Date',
        tracking=True,
    )
    estimated_arrival_date = fields.Date(
        string='Estimated Arrival',
    )
    actual_arrival_date = fields.Date(
        string='Actual Arrival',
    )
    closed_date = fields.Datetime(
        string='Closed Date',
        readonly=True,
    )
    
    # Quantities
    item_count = fields.Integer(
        string='Number of SKUs',
        compute='_compute_quantities',
        store=True,
    )
    total_quantity = fields.Integer(
        string='Total Units',
        compute='_compute_quantities',
        store=True,
    )
    received_quantity = fields.Integer(
        string='Received Units',
        compute='_compute_quantities',
        store=True,
    )
    quantity_difference = fields.Integer(
        string='Quantity Difference',
        compute='_compute_quantities',
        store=True,
        help='Difference between shipped and received quantities.',
    )
    
    # Fees & Costs
    estimated_fee = fields.Monetary(
        string='Estimated Fee',
        currency_field='currency_id',
    )
    actual_fee = fields.Monetary(
        string='Actual Fee',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='marketplace_id.currency_id',
        store=True,
    )
    
    # Notes
    notes = fields.Text(
        string='Internal Notes',
    )
    amazon_notes = fields.Text(
        string='Amazon Notes',
        readonly=True,
    )
    
    # Technical
    last_sync_date = fields.Datetime(
        string='Last Synced',
        readonly=True,
    )
    sync_error = fields.Text(
        string='Sync Error',
        readonly=True,
    )
    inbound_plan_id = fields.Char(
        string='Inbound Plan ID',
        help='Amazon Inbound Plan ID (new 2024 Send to Amazon workflow).',
    )
    
    # -------------------------------------------------------------------------
    # COMPUTES
    # -------------------------------------------------------------------------
    
    @api.depends('name', 'amazon_shipment_id', 'amazon_shipment_name')
    def _compute_display_name(self):
        for shipment in self:
            parts = [shipment.name]
            if shipment.amazon_shipment_id:
                parts.append(f'[{shipment.amazon_shipment_id}]')
            if shipment.amazon_shipment_name:
                parts.append(shipment.amazon_shipment_name)
            shipment.display_name = ' '.join(parts)
    
    @api.depends('destination_fc_id', 'destination_country_id')
    def _compute_destination_address(self):
        """Compute destination address from FC data."""
        for shipment in self:
            if shipment.destination_fc_id:
                # In production, this would fetch from Amazon or a local cache
                shipment.destination_address = f"Amazon Fulfillment Center {shipment.destination_fc_id}"
            else:
                shipment.destination_address = False
    
    @api.depends('tracking_numbers')
    def _compute_box_count(self):
        for shipment in self:
            if shipment.tracking_numbers:
                shipment.box_count = len([
                    t for t in shipment.tracking_numbers.split('\n') if t.strip()
                ])
            else:
                shipment.box_count = 0
    
    @api.depends('item_ids', 'item_ids.quantity', 'item_ids.received_quantity')
    def _compute_quantities(self):
        for shipment in self:
            items = shipment.item_ids
            shipment.item_count = len(items)
            shipment.total_quantity = sum(items.mapped('quantity'))
            shipment.received_quantity = sum(items.mapped('received_quantity'))
            shipment.quantity_difference = shipment.received_quantity - shipment.total_quantity
    
    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------
    
    _sql_constraints = [
        (
            'amazon_shipment_id_unique',
            'UNIQUE(amazon_shipment_id)',
            'Amazon Shipment ID must be unique!'
        ),
    ]
    
    @api.constrains('item_ids')
    def _check_items(self):
        for shipment in self:
            if shipment.state not in ('draft', 'cancelled') and not shipment.item_ids:
                raise ValidationError(_('A shipment must have at least one item.'))
    
    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'amazon.fba.shipment'
                ) or _('New')
        return super().create(vals_list)
    
    def unlink(self):
        for shipment in self:
            if shipment.state not in ('draft', 'cancelled', 'deleted'):
                raise UserError(_(
                    'Cannot delete shipment %s. Only draft or cancelled shipments can be deleted.',
                    shipment.display_name
                ))
        return super().unlink()
    
    def copy(self, default=None):
        default = dict(default or {})
        default.update({
            'amazon_shipment_id': False,
            'amazon_shipment_name': False,
            'state': 'draft',
            'tracking_numbers': False,
            'ship_date': False,
            'estimated_arrival_date': False,
            'actual_arrival_date': False,
            'closed_date': False,
            'last_sync_date': False,
            'sync_error': False,
        })
        return super().copy(default)
    
    # -------------------------------------------------------------------------
    # ACTIONS - Workflow
    # -------------------------------------------------------------------------
    
    def action_confirm(self):
        """Confirm the shipment and create it in Amazon."""
        for shipment in self:
            if shipment.state != 'draft':
                raise UserError(_('Only draft shipments can be confirmed.'))
            if not shipment.item_ids:
                raise UserError(_('Please add items to the shipment.'))
            
            # In production: Create shipment plan via SP-API
            shipment._create_amazon_shipment()
            shipment.write({'state': 'working'})
        return True
    
    def action_ready_to_ship(self):
        """Mark shipment as ready to ship."""
        for shipment in self:
            if shipment.state != 'working':
                raise UserError(_('Shipment must be in working state.'))
            shipment.write({'state': 'ready_to_ship'})
        return True
    
    def action_ship(self):
        """Mark shipment as shipped and update Amazon."""
        for shipment in self:
            if shipment.state not in ('working', 'ready_to_ship'):
                raise UserError(_('Shipment must be ready to ship.'))
            if not shipment.tracking_numbers and shipment.shipment_type == 'sp':
                raise UserError(_('Please enter tracking numbers before shipping.'))
            
            # In production: Update shipment status in Amazon
            shipment._update_amazon_shipment_status('shipped')
            shipment.write({
                'state': 'shipped',
                'ship_date': shipment.ship_date or fields.Date.today(),
            })
        return True
    
    def action_cancel(self):
        """Cancel the shipment."""
        for shipment in self:
            if shipment.state in ('closed', 'cancelled', 'deleted'):
                raise UserError(_('Cannot cancel a closed or already cancelled shipment.'))
            
            # Cancel any related stock pickings
            shipment.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel')
            ).action_cancel()
            
            # In production: Cancel in Amazon if it exists there
            if shipment.amazon_shipment_id:
                shipment._cancel_amazon_shipment()
            
            shipment.write({'state': 'cancelled'})
        return True
    
    def action_set_to_draft(self):
        """Reset a cancelled shipment to draft."""
        for shipment in self:
            if shipment.state != 'cancelled':
                raise UserError(_('Only cancelled shipments can be reset to draft.'))
            shipment.write({
                'state': 'draft',
                'amazon_shipment_id': False,
                'sync_error': False,
            })
        return True
    
    def action_close(self):
        """Close a received shipment."""
        for shipment in self:
            if shipment.state not in ('receiving', 'checked_in', 'delivered'):
                raise UserError(_('Shipment must be in receiving state to close.'))
            shipment.write({
                'state': 'closed',
                'closed_date': fields.Datetime.now(),
            })
            # Post message about quantity differences
            if shipment.quantity_difference != 0:
                shipment.message_post(
                    body=_(
                        'Shipment closed with quantity difference: %s units '
                        '(shipped: %s, received: %s)',
                        shipment.quantity_difference,
                        shipment.total_quantity,
                        shipment.received_quantity,
                    ),
                    message_type='notification',
                )
        return True
    
    # -------------------------------------------------------------------------
    # ACTIONS - Operations
    # -------------------------------------------------------------------------
    
    def action_sync_from_amazon(self):
        """Sync shipment status and details from Amazon."""
        for shipment in self:
            if not shipment.amazon_shipment_id:
                raise UserError(_('No Amazon shipment ID to sync.'))
            shipment._sync_from_amazon()
        return True
    
    def action_create_picking(self):
        """Create stock picking for this FBA shipment."""
        self.ensure_one()
        if not self.item_ids:
            raise UserError(_('Please add items before creating a transfer.'))
        
        # Get FBA warehouse (destination)
        fba_warehouse = self._get_fba_warehouse()
        if not fba_warehouse:
            raise UserError(_(
                'No FBA warehouse configured for marketplace %s.',
                self.marketplace_id.display_name
            ))
        
        picking_type = self.warehouse_id.out_type_id
        
        picking_vals = {
            'picking_type_id': picking_type.id,
            'location_id': self.warehouse_id.lot_stock_id.id,
            'location_dest_id': fba_warehouse.lot_stock_id.id,
            'origin': self.name,
            'amazon_fba_shipment_id': self.id,
            'move_ids': [(0, 0, {
                'name': item.product_id.display_name,
                'product_id': item.product_id.id,
                'product_uom_qty': item.quantity,
                'product_uom': item.product_id.uom_id.id,
                'location_id': self.warehouse_id.lot_stock_id.id,
                'location_dest_id': fba_warehouse.lot_stock_id.id,
            }) for item in self.item_ids],
        }
        
        picking = self.env['stock.picking'].create(picking_vals)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfer'),
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'view_mode': 'form',
        }
    
    def action_view_pickings(self):
        """View related stock pickings."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfers'),
            'res_model': 'stock.picking',
            'domain': [('amazon_fba_shipment_id', '=', self.id)],
            'view_mode': 'tree,form',
            'context': {'default_amazon_fba_shipment_id': self.id},
        }
    
    def action_view_items(self):
        """View shipment items."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Shipment Items'),
            'res_model': 'amazon.fba.shipment.item',
            'domain': [('shipment_id', '=', self.id)],
            'view_mode': 'tree,form',
            'context': {'default_shipment_id': self.id},
        }
    
    def action_print_labels(self):
        """Print shipping labels for this shipment."""
        self.ensure_one()
        # In production: Fetch labels from Amazon and return report action
        raise UserError(_('Label printing not yet implemented.'))
    
    def action_open_in_amazon(self):
        """Open shipment in Amazon Seller Central."""
        self.ensure_one()
        if not self.amazon_shipment_id:
            raise UserError(_('No Amazon shipment ID available.'))
        
        # Build Seller Central URL based on marketplace
        base_urls = {
            'DE': 'https://sellercentral.amazon.de',
            'UK': 'https://sellercentral.amazon.co.uk',
            'FR': 'https://sellercentral.amazon.fr',
            'US': 'https://sellercentral.amazon.com',
            # Add more as needed
        }
        base_url = base_urls.get(
            self.marketplace_id.code,
            'https://sellercentral.amazon.com'
        )
        url = f"{base_url}/fba/inbound-queue/summary?shipmentId={self.amazon_shipment_id}"
        
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }
    
    # -------------------------------------------------------------------------
    # AMAZON SP-API INTEGRATION
    # -------------------------------------------------------------------------
    
    def _get_sp_api_client(self):
        """Get the SP-API client for this shipment's account."""
        self.ensure_one()
        # This would return the SP-API service instance
        # return self.account_id._get_sp_api_client()
        return None  # Placeholder
    
    def _create_amazon_shipment(self):
        """Create the shipment in Amazon via SP-API."""
        self.ensure_one()
        _logger.info('Creating Amazon shipment for %s', self.name)
        
        # Prepare shipment data
        items = []
        for item in self.item_ids:
            if not item.amazon_sku:
                raise UserError(_(
                    'Product %s has no Amazon SKU.',
                    item.product_id.display_name
                ))
            items.append({
                'SellerSKU': item.amazon_sku,
                'Quantity': item.quantity,
                'QuantityInCase': item.quantity_in_case or 0,
                'PrepDetailsList': item._get_prep_details(),
            })
        
        # In production: Call SP-API to create inbound shipment plan
        # client = self._get_sp_api_client()
        # response = client.fba_inbound.create_inbound_shipment_plan(...)
        
        _logger.info('Amazon shipment created (simulated)')
        return True
    
    def _update_amazon_shipment_status(self, status):
        """Update the shipment status in Amazon."""
        self.ensure_one()
        _logger.info(
            'Updating Amazon shipment %s to status: %s',
            self.amazon_shipment_id, status
        )
        # In production: Call SP-API to update shipment
        return True
    
    def _cancel_amazon_shipment(self):
        """Cancel the shipment in Amazon."""
        self.ensure_one()
        if self.amazon_shipment_id:
            _logger.info('Cancelling Amazon shipment %s', self.amazon_shipment_id)
            # In production: Call SP-API to cancel
        return True
    
    def _sync_from_amazon(self):
        """Sync shipment details from Amazon."""
        self.ensure_one()
        _logger.info('Syncing shipment %s from Amazon', self.amazon_shipment_id)
        
        try:
            # In production: Fetch from SP-API
            # client = self._get_sp_api_client()
            # response = client.fba_inbound.get_shipment(self.amazon_shipment_id)
            
            # Example status mapping
            amazon_to_odoo_status = {
                'WORKING': 'working',
                'READY_TO_SHIP': 'ready_to_ship',
                'SHIPPED': 'shipped',
                'IN_TRANSIT': 'in_transit',
                'DELIVERED': 'delivered',
                'CHECKED_IN': 'checked_in',
                'RECEIVING': 'receiving',
                'CLOSED': 'closed',
                'CANCELLED': 'cancelled',
                'DELETED': 'deleted',
                'ERROR': 'error',
            }
            
            # Update would happen here
            self.write({
                'last_sync_date': fields.Datetime.now(),
                'sync_error': False,
            })
            
        except Exception as e:
            _logger.exception('Error syncing shipment %s', self.name)
            self.write({
                'sync_error': str(e),
                'last_sync_date': fields.Datetime.now(),
            })
            raise UserError(_('Sync failed: %s', str(e)))
        
        return True
    
    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------
    
    def _get_fba_warehouse(self):
        """Get the FBA warehouse for this shipment's marketplace."""
        self.ensure_one()
        return self.env['stock.warehouse'].search([
            ('is_amazon_fba', '=', True),
            ('amazon_marketplace_id', '=', self.marketplace_id.id),
        ], limit=1) or self.env['stock.warehouse'].search([
            ('is_amazon_fba', '=', True),
        ], limit=1)
    
    # -------------------------------------------------------------------------
    # CRON JOBS
    # -------------------------------------------------------------------------
    
    @api.model
    def _cron_sync_shipments(self):
        """Scheduled action to sync all active shipments."""
        _logger.info('Starting FBA shipment sync cron job')
        
        active_states = [
            'working', 'ready_to_ship', 'shipped', 
            'in_transit', 'delivered', 'checked_in', 'receiving'
        ]
        shipments = self.search([
            ('state', 'in', active_states),
            ('amazon_shipment_id', '!=', False),
        ])
        
        errors = []
        for shipment in shipments:
            try:
                shipment._sync_from_amazon()
            except Exception as e:
                errors.append(f'{shipment.name}: {str(e)}')
                _logger.warning('Failed to sync shipment %s: %s', shipment.name, e)
        
        _logger.info(
            'FBA shipment sync completed. Synced: %d, Errors: %d',
            len(shipments), len(errors)
        )
        
        return True
    
    @api.model
    def _update_or_create_from_amazon(self, account_id, marketplace_id, data):
        """
        Update or create shipment record from Amazon data.

        :param account_id: amazon.account ID
        :param marketplace_id: amazon.marketplace ID
        :param data: Dict with shipment data from Amazon
        :return: amazon.fba.shipment record
        """
        amazon_shipment_id = data.get('ShipmentId')
        if not amazon_shipment_id:
            return False

        existing = self.search([
            ('account_id', '=', account_id),
            ('amazon_shipment_id', '=', amazon_shipment_id),
        ], limit=1)

        # Status mapping
        status_map = {
            'WORKING': 'working',
            'READY_TO_SHIP': 'ready_to_ship',
            'SHIPPED': 'shipped',
            'IN_TRANSIT': 'in_transit',
            'DELIVERED': 'delivered',
            'CHECKED_IN': 'checked_in',
            'RECEIVING': 'receiving',
            'CLOSED': 'closed',
            'CANCELLED': 'cancelled',
            'DELETED': 'deleted',
            'ERROR': 'error',
        }
        amazon_status = data.get('ShipmentStatus')
        odoo_state = status_map.get(amazon_status, 'draft')

        # Prep type mapping
        prep_map = {
            'NO_LABEL': 'no_label',
            'SELLER_LABEL': 'seller_label',
            'AMAZON_LABEL': 'amazon_label',
        }
        prep_type = prep_map.get(data.get('LabelPrepType'), 'seller_label')

        vals = {
            'amazon_shipment_name': data.get('ShipmentName'),
            'destination_fc_id': data.get('DestinationFulfillmentCenterId'),
            'amazon_status': amazon_status,
            'label_prep_type': prep_type,
            'packing_type': 'case_packed' if data.get('AreCasesRequired') else 'individual',
            'last_sync_date': fields.Datetime.now(),
            'sync_error': False,
        }

        # Only update state if it moved forward or changed significantly
        # (avoid resetting local state if Odoo has more detailed tracking)
        if existing:
            # Maybe we only update state if Amazon state is different
            if existing.amazon_status != amazon_status:
                vals['state'] = odoo_state

            existing.write(vals)
            return existing
        else:
            vals.update({
                'account_id': account_id,
                'marketplace_id': marketplace_id,
                'amazon_shipment_id': amazon_shipment_id,
                'state': odoo_state,
                'warehouse_id': self._get_default_warehouse(account_id, marketplace_id),
                'shipment_type': 'sp', # Default, API doesn't always provide this in summary
            })
            return self.create(vals)

    @api.model
    def _get_default_warehouse(self, account_id, marketplace_id):
        """Get default warehouse for new shipments."""
        account = self.env['amazon.account'].browse(account_id)
        if account.warehouse_id:
            return account.warehouse_id.id

        # Fallback to any FBA warehouse
        warehouse = self.env['stock.warehouse'].search([
            ('is_amazon_fba', '=', True),
            ('amazon_marketplace_id', '=', marketplace_id),
        ], limit=1)

        if not warehouse:
            warehouse = self.env['stock.warehouse'].search([
                ('company_id', '=', account.company_id.id),
            ], limit=1)

        return warehouse.id if warehouse else False

    @api.model
    def _cron_check_shipment_alerts(self):
        """Check for shipments requiring attention."""
        _logger.info('Checking FBA shipment alerts')
        
        # Find shipments shipped but not received after X days
        alert_threshold = datetime.now() - timedelta(days=14)
        stuck_shipments = self.search([
            ('state', '=', 'shipped'),
            ('ship_date', '<', alert_threshold.date()),
        ])
        
        for shipment in stuck_shipments:
            shipment.message_post(
                body=_(
                    'Alert: Shipment %s was shipped on %s but has not '
                    'been received yet. Please check with Amazon.',
                    shipment.name, shipment.ship_date
                ),
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )
        
        return True
