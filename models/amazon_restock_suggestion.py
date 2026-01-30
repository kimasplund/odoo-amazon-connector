# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmazonRestockSuggestion(models.Model):
    """
    Amazon Restock Suggestion.
    
    Actionable recommendations for inventory management including:
    - Restock recommendations (when and how much to order)
    - Removal recommendations (overstock/slow movers)
    - Price adjustment recommendations
    - Promotion recommendations (to move excess stock)
    """
    _name = 'amazon.restock.suggestion'
    _description = 'Amazon Restock Suggestion'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority_sort asc, suggested_action_date asc'
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
    forecast_id = fields.Many2one(
        'amazon.inventory.forecast',
        string='Forecast',
        ondelete='cascade',
    )
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
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='marketplace_id.currency_id',
        store=True,
    )
    fba_shipment_id = fields.Many2one(
        'amazon.fba.shipment',
        string='FBA Shipment',
        help='Created FBA shipment (if restock was accepted).',
    )
    
    # Product info
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
    # FIELDS - Suggestion Type & Priority
    # -------------------------------------------------------------------------
    
    suggestion_type = fields.Selection(
        selection=[
            ('restock', 'Restock'),
            ('removal', 'Removal'),
            ('price_adjust', 'Price Adjustment'),
            ('promotion', 'Run Promotion'),
        ],
        string='Type',
        required=True,
        default='restock',
        index=True,
    )
    
    priority = fields.Selection(
        selection=[
            ('critical', 'Critical'),
            ('high', 'High'),
            ('medium', 'Medium'),
            ('low', 'Low'),
        ],
        string='Priority',
        required=True,
        default='medium',
        index=True,
    )
    priority_sort = fields.Integer(
        string='Priority Sort',
        compute='_compute_priority_sort',
        store=True,
    )
    
    # -------------------------------------------------------------------------
    # FIELDS - Inventory Data
    # -------------------------------------------------------------------------
    
    current_stock = fields.Integer(
        string='Current Stock',
    )
    current_inbound = fields.Integer(
        string='Inbound Stock',
    )
    forecasted_demand = fields.Integer(
        string='Forecasted Demand (30d)',
    )
    recommended_qty = fields.Integer(
        string='Recommended Qty',
        help='Quantity to restock/remove.',
    )
    
    # -------------------------------------------------------------------------
    # FIELDS - Timing
    # -------------------------------------------------------------------------
    
    estimated_stockout_date = fields.Date(
        string='Est. Stockout Date',
    )
    suggested_action_date = fields.Date(
        string='Action By Date',
        help='Recommended date to take action.',
    )
    days_until_action = fields.Integer(
        string='Days Until Action',
        compute='_compute_days_until_action',
    )
    is_overdue = fields.Boolean(
        string='Is Overdue',
        compute='_compute_days_until_action',
    )
    
    # -------------------------------------------------------------------------
    # FIELDS - Financial Impact
    # -------------------------------------------------------------------------
    
    potential_lost_sales = fields.Monetary(
        string='Potential Lost Sales',
        currency_field='currency_id',
        help='Estimated revenue loss if stockout occurs.',
    )
    estimated_cost = fields.Monetary(
        string='Estimated Cost',
        currency_field='currency_id',
        help='Estimated cost of recommended action.',
    )
    storage_savings = fields.Monetary(
        string='Storage Savings',
        currency_field='currency_id',
        help='Potential storage fee savings (for removals).',
    )
    
    # -------------------------------------------------------------------------
    # FIELDS - Reasoning
    # -------------------------------------------------------------------------
    
    reason = fields.Text(
        string='Reason',
        help='Human-readable explanation of the recommendation.',
    )
    algorithm_details = fields.Text(
        string='Algorithm Details',
        help='Technical details of the calculation.',
    )
    
    # -------------------------------------------------------------------------
    # FIELDS - Status & Workflow
    # -------------------------------------------------------------------------
    
    status = fields.Selection(
        selection=[
            ('pending', 'Pending Review'),
            ('accepted', 'Accepted'),
            ('dismissed', 'Dismissed'),
            ('completed', 'Completed'),
            ('expired', 'Expired'),
        ],
        string='Status',
        default='pending',
        required=True,
        index=True,
        tracking=True,
    )
    status_changed_date = fields.Datetime(
        string='Status Changed',
    )
    status_changed_by = fields.Many2one(
        'res.users',
        string='Changed By',
    )
    dismissed_reason = fields.Text(
        string='Dismiss Reason',
    )
    
    # -------------------------------------------------------------------------
    # FIELDS - Dates
    # -------------------------------------------------------------------------
    
    created_date = fields.Datetime(
        string='Created',
        default=fields.Datetime.now,
    )
    expire_date = fields.Date(
        string='Expires',
        help='Suggestion expires if not actioned.',
    )
    
    # -------------------------------------------------------------------------
    # COMPUTES
    # -------------------------------------------------------------------------
    
    @api.depends('product_id', 'suggestion_type', 'priority')
    def _compute_display_name(self):
        type_icons = {
            'restock': '📦',
            'removal': '📤',
            'price_adjust': '💰',
            'promotion': '🏷️',
        }
        for record in self:
            icon = type_icons.get(record.suggestion_type, '📋')
            product = record.product_sku or record.product_id.name[:20] if record.product_id else 'Unknown'
            record.display_name = f"{icon} {record.suggestion_type.title()}: {product}"
    
    @api.depends('priority')
    def _compute_priority_sort(self):
        """Numeric priority for sorting (lower = more urgent)."""
        priority_map = {
            'critical': 1,
            'high': 2,
            'medium': 3,
            'low': 4,
        }
        for record in self:
            record.priority_sort = priority_map.get(record.priority, 5)
    
    @api.depends('suggested_action_date')
    def _compute_days_until_action(self):
        today = fields.Date.today()
        for record in self:
            if record.suggested_action_date:
                delta = (record.suggested_action_date - today).days
                record.days_until_action = delta
                record.is_overdue = delta < 0
            else:
                record.days_until_action = 999
                record.is_overdue = False
    
    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Set expire date if not provided
            if 'expire_date' not in vals:
                vals['expire_date'] = fields.Date.today() + timedelta(days=14)
            
            # Calculate potential financial impact
            if vals.get('suggestion_type') == 'restock' and vals.get('forecasted_demand'):
                # Estimate potential lost sales (rough: demand * avg price)
                product = self.env['product.product'].browse(vals.get('product_id'))
                if product:
                    vals['potential_lost_sales'] = vals['forecasted_demand'] * (product.list_price or 0)
        
        records = super().create(vals_list)
        
        # Send notification for critical suggestions
        for record in records:
            if record.priority == 'critical':
                record._send_critical_alert()
        
        return records
    
    def write(self, vals):
        if 'status' in vals:
            vals['status_changed_date'] = fields.Datetime.now()
            vals['status_changed_by'] = self.env.uid
        return super().write(vals)
    
    # -------------------------------------------------------------------------
    # ACTIONS - Status Changes
    # -------------------------------------------------------------------------
    
    def action_accept(self):
        """Accept the suggestion and take action."""
        for record in self:
            if record.status != 'pending':
                continue
                
            if record.suggestion_type == 'restock':
                # Open wizard to create FBA shipment
                return record._action_create_shipment_wizard()
            elif record.suggestion_type == 'removal':
                # Open removal wizard
                return record._action_create_removal_wizard()
            else:
                record.write({'status': 'accepted'})
        
        return True
    
    def action_dismiss(self):
        """Dismiss the suggestion."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Dismiss Suggestion'),
            'res_model': 'amazon.restock.dismiss.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_suggestion_ids': self.ids,
            },
        }
    
    def action_complete(self):
        """Mark suggestion as completed."""
        self.write({'status': 'completed'})
    
    def action_reopen(self):
        """Reopen a dismissed/expired suggestion."""
        self.write({
            'status': 'pending',
            'expire_date': fields.Date.today() + timedelta(days=7),
        })
    
    # -------------------------------------------------------------------------
    # ACTIONS - Restock
    # -------------------------------------------------------------------------
    
    def action_create_fba_shipment(self):
        """
        Create FBA shipment from restock suggestion.
        """
        self.ensure_one()
        
        if self.suggestion_type != 'restock':
            raise UserError(_('Can only create shipment for restock suggestions.'))
        
        if self.fba_shipment_id:
            raise UserError(_('FBA shipment already exists for this suggestion.'))
        
        FBAShipment = self.env['amazon.fba.shipment']
        
        # Create shipment
        shipment = FBAShipment.create({
            'account_id': self.account_id.id,
            'marketplace_id': self.marketplace_id.id,
            'name': f"Restock: {self.product_sku}",
            'ship_from_name': self.account_id.company_id.name,
            'ship_from_address_1': self.account_id.company_id.street,
            'ship_from_city': self.account_id.company_id.city,
            'ship_from_postal_code': self.account_id.company_id.zip,
            'ship_from_country_code': self.account_id.company_id.country_id.code,
        })
        
        # Add item
        self.env['amazon.fba.shipment.item'].create({
            'shipment_id': shipment.id,
            'product_id': self.product_id.id,
            'amazon_sku': self.product_sku,
            'quantity_shipped': self.recommended_qty,
        })
        
        # Update suggestion
        self.write({
            'status': 'accepted',
            'fba_shipment_id': shipment.id,
        })
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('FBA Shipment'),
            'res_model': 'amazon.fba.shipment',
            'res_id': shipment.id,
            'view_mode': 'form',
        }
    
    def _action_create_shipment_wizard(self):
        """Open wizard to create FBA shipment."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create FBA Shipment'),
            'res_model': 'amazon.fba.shipment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_account_id': self.account_id.id,
                'default_marketplace_id': self.marketplace_id.id,
                'default_product_ids': [(6, 0, [self.product_id.id])],
                'default_suggested_qty': self.recommended_qty,
                'default_suggestion_id': self.id,
            },
        }
    
    def _action_create_removal_wizard(self):
        """Open wizard to create removal order."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Removal Order'),
            'res_model': 'amazon.removal.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_account_id': self.account_id.id,
                'default_marketplace_id': self.marketplace_id.id,
                'default_product_id': self.product_id.id,
                'default_quantity': self.recommended_qty,
                'default_suggestion_id': self.id,
            },
        }
    
    # -------------------------------------------------------------------------
    # ACTIONS - Views
    # -------------------------------------------------------------------------
    
    def action_view_forecast(self):
        """View the related forecast."""
        self.ensure_one()
        if not self.forecast_id:
            raise UserError(_('No forecast record linked.'))
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Forecast'),
            'res_model': 'amazon.inventory.forecast',
            'res_id': self.forecast_id.id,
            'view_mode': 'form',
        }
    
    def action_view_product(self):
        """View the product."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Product'),
            'res_model': 'product.product',
            'res_id': self.product_id.id,
            'view_mode': 'form',
        }
    
    def action_view_shipment(self):
        """View the created FBA shipment."""
        self.ensure_one()
        if not self.fba_shipment_id:
            raise UserError(_('No FBA shipment created for this suggestion.'))
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('FBA Shipment'),
            'res_model': 'amazon.fba.shipment',
            'res_id': self.fba_shipment_id.id,
            'view_mode': 'form',
        }
    
    # -------------------------------------------------------------------------
    # NOTIFICATIONS
    # -------------------------------------------------------------------------
    
    def _send_critical_alert(self):
        """Send email alert for critical suggestions."""
        self.ensure_one()
        
        template = self.env.ref(
            'amazon_connector.mail_template_restock_critical_alert',
            raise_if_not_found=False
        )
        
        if template:
            template.send_mail(self.id, force_send=True)
    
    # -------------------------------------------------------------------------
    # BULK ACTIONS
    # -------------------------------------------------------------------------
    
    def action_bulk_accept(self):
        """Accept multiple suggestions."""
        pending = self.filtered(lambda s: s.status == 'pending')
        pending.write({'status': 'accepted'})
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Suggestions Accepted'),
                'message': _('%d suggestions accepted.') % len(pending),
                'type': 'success',
            }
        }
    
    def action_bulk_dismiss(self):
        """Dismiss multiple suggestions."""
        pending = self.filtered(lambda s: s.status == 'pending')
        pending.write({
            'status': 'dismissed',
            'dismissed_reason': 'Bulk dismissed',
        })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Suggestions Dismissed'),
                'message': _('%d suggestions dismissed.') % len(pending),
                'type': 'warning',
            }
        }
    
    # -------------------------------------------------------------------------
    # CRON METHODS
    # -------------------------------------------------------------------------
    
    @api.model
    def _cron_generate_suggestions(self):
        """
        Generate new suggestions from forecasts.
        """
        _logger.info('Starting restock suggestion generation cron')
        
        Forecast = self.env['amazon.inventory.forecast']
        
        # Find forecasts needing restock
        forecasts = Forecast.search([
            ('active', '=', True),
            ('stockout_risk', 'in', ['critical', 'high', 'medium']),
            ('recommended_restock_qty', '>', 0),
        ])
        
        created = 0
        for forecast in forecasts:
            # Check for existing pending suggestion
            existing = self.search([
                ('forecast_id', '=', forecast.id),
                ('status', '=', 'pending'),
                ('suggestion_type', '=', 'restock'),
            ], limit=1)
            
            if existing:
                continue
            
            try:
                forecast._create_restock_suggestion()
                created += 1
            except Exception as e:
                _logger.warning('Could not create suggestion for forecast %s: %s', 
                               forecast.display_name, str(e))
        
        # Also check for overstock suggestions
        overstock_forecasts = Forecast.search([
            ('active', '=', True),
            ('is_overstock', '=', True),
            ('recommended_removal_qty', '>', 0),
        ])
        
        for forecast in overstock_forecasts:
            existing = self.search([
                ('forecast_id', '=', forecast.id),
                ('status', '=', 'pending'),
                ('suggestion_type', '=', 'removal'),
            ], limit=1)
            
            if existing:
                continue
            
            try:
                self._create_removal_suggestion(forecast)
                created += 1
            except Exception as e:
                _logger.warning('Could not create removal suggestion for forecast %s: %s',
                               forecast.display_name, str(e))
        
        _logger.info('Created %d restock suggestions', created)
    
    @api.model
    def _create_removal_suggestion(self, forecast):
        """Create a removal suggestion for overstock."""
        reason_parts = [
            f"📦 OVERSTOCK ALERT: {forecast.days_of_supply:.0f} days of supply",
            f"Current stock: {forecast.current_stock} units",
            f"Daily velocity: {forecast.weighted_velocity:.1f} units/day",
            f"Estimated monthly storage: {forecast.estimated_storage_cost:.2f}",
            f"Recommendation: Remove {forecast.recommended_removal_qty} units",
        ]
        
        return self.create({
            'forecast_id': forecast.id,
            'product_id': forecast.product_id.id,
            'marketplace_id': forecast.marketplace_id.id,
            'account_id': forecast.account_id.id,
            'suggestion_type': 'removal',
            'priority': 'medium',
            'current_stock': forecast.current_stock,
            'forecasted_demand': forecast.forecasted_demand_30d,
            'recommended_qty': forecast.recommended_removal_qty,
            'suggested_action_date': fields.Date.today() + timedelta(days=7),
            'storage_savings': forecast.estimated_storage_cost * 0.5,  # Estimated 50% savings
            'reason': '\n'.join(reason_parts),
        })
    
    @api.model
    def _cron_expire_old_suggestions(self):
        """Expire old pending suggestions."""
        today = fields.Date.today()
        
        expired = self.search([
            ('status', '=', 'pending'),
            ('expire_date', '<', today),
        ])
        
        expired.write({'status': 'expired'})
        
        _logger.info('Expired %d old suggestions', len(expired))
    
    @api.model
    def _cron_send_weekly_summary(self):
        """Send weekly summary of pending suggestions."""
        _logger.info('Sending weekly restock summary')
        
        # Group by account
        accounts = self.env['amazon.account'].search([('state', '=', 'active')])
        
        for account in accounts:
            pending = self.search([
                ('account_id', '=', account.id),
                ('status', '=', 'pending'),
            ])
            
            if not pending:
                continue
            
            template = self.env.ref(
                'amazon_connector.mail_template_restock_weekly_summary',
                raise_if_not_found=False
            )
            
            if template:
                # Use first suggestion as record for template
                template.with_context(
                    all_suggestions=pending,
                    account=account,
                ).send_mail(pending[0].id, force_send=True)


class AmazonRestockDismissWizard(models.TransientModel):
    """Wizard for dismissing restock suggestions with a reason."""
    _name = 'amazon.restock.dismiss.wizard'
    _description = 'Dismiss Restock Suggestion'

    suggestion_ids = fields.Many2many(
        'amazon.restock.suggestion',
        string='Suggestions',
    )
    reason = fields.Selection(
        selection=[
            ('not_needed', 'Not Needed'),
            ('already_ordered', 'Already Ordered'),
            ('discontinuing', 'Discontinuing Product'),
            ('seasonal', 'Seasonal Adjustment'),
            ('other', 'Other'),
        ],
        string='Reason',
        required=True,
    )
    notes = fields.Text(
        string='Notes',
    )

    def action_confirm(self):
        """Confirm dismissal."""
        reason_text = dict(self._fields['reason'].selection).get(self.reason)
        if self.notes:
            reason_text = f"{reason_text}: {self.notes}"
        
        self.suggestion_ids.write({
            'status': 'dismissed',
            'dismissed_reason': reason_text,
        })
        
        return {'type': 'ir.actions.act_window_close'}
