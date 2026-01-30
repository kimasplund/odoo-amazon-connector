# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AmazonSettlement(models.Model):
    """
    Amazon Settlement Report Model.
    
    Settlement reports provide financial data from Amazon including:
    - Order payments
    - Refunds
    - FBA fees
    - Advertising costs
    - Other financial transactions
    
    These are used for reconciliation with bank statements and
    to track actual revenue after Amazon fees.
    """
    _name = 'amazon.settlement'
    _description = 'Amazon Settlement Report'
    _order = 'deposit_date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # ==========================================
    # FIELDS
    # ==========================================
    
    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
        readonly=True,
    )
    settlement_id = fields.Char(
        string='Settlement ID',
        required=True,
        index=True,
        tracking=True,
        help='Unique Amazon Settlement Report ID',
    )
    account_id = fields.Many2one(
        'amazon.account',
        string='Amazon Account',
        required=True,
        ondelete='cascade',
        tracking=True,
        index=True,
    )
    marketplace_id = fields.Many2one(
        'amazon.marketplace',
        string='Marketplace',
        required=True,
        ondelete='restrict',
        tracking=True,
    )
    
    # Date range
    settlement_start_date = fields.Datetime(
        string='Start Date',
        required=True,
        help='Settlement period start date',
    )
    settlement_end_date = fields.Datetime(
        string='End Date',
        required=True,
        help='Settlement period end date',
    )
    deposit_date = fields.Date(
        string='Deposit Date',
        tracking=True,
        help='Date when funds were deposited to bank account',
    )
    
    # Financial
    total_amount = fields.Monetary(
        string='Total Amount',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
        help='Net settlement amount (deposit amount)',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    
    # Computed amount breakdowns
    gross_sales_amount = fields.Monetary(
        string='Gross Sales',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
        help='Total product sales before fees and refunds',
    )
    refund_amount = fields.Monetary(
        string='Refunds',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
        help='Total refunds issued',
    )
    total_fees = fields.Monetary(
        string='Total Fees',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
        help='Total Amazon fees (FBA, referral, etc.)',
    )
    promotion_amount = fields.Monetary(
        string='Promotions',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
        help='Promotional discounts',
    )
    other_amount = fields.Monetary(
        string='Other',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
        help='Other transactions (adjustments, reimbursements, etc.)',
    )
    
    # Status
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('reconciled', 'Reconciled'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, required=True)
    
    # Line items
    line_ids = fields.One2many(
        'amazon.settlement.line',
        'settlement_id',
        string='Settlement Lines',
    )
    line_count = fields.Integer(
        string='Line Count',
        compute='_compute_line_count',
    )
    
    # Accounting
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
        domain="[('type', '=', 'bank')]",
        help='Bank journal for reconciliation',
    )
    move_ids = fields.One2many(
        'account.move',
        'amazon_settlement_id',
        string='Journal Entries',
    )
    move_count = fields.Integer(
        string='Entry Count',
        compute='_compute_move_count',
    )
    is_reconciled = fields.Boolean(
        string='Reconciled',
        compute='_compute_is_reconciled',
        store=True,
        help='True if all related journal entries are reconciled',
    )
    
    # Metadata
    import_date = fields.Datetime(
        string='Imported On',
        default=fields.Datetime.now,
        readonly=True,
    )
    report_data = fields.Text(
        string='Raw Report Data',
        help='Original settlement report data (JSON)',
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    
    active = fields.Boolean(default=True)
    
    # ==========================================
    # CONSTRAINTS
    # ==========================================
    
    _sql_constraints = [
        ('settlement_id_account_uniq', 
         'UNIQUE(settlement_id, account_id)',
         'Settlement ID must be unique per Amazon account!'),
    ]
    
    @api.constrains('settlement_start_date', 'settlement_end_date')
    def _check_dates(self):
        for record in self:
            if record.settlement_start_date and record.settlement_end_date:
                if record.settlement_start_date > record.settlement_end_date:
                    raise ValidationError(_(
                        'Settlement start date must be before end date.'
                    ))
    
    # ==========================================
    # COMPUTE METHODS
    # ==========================================
    
    @api.depends('settlement_id', 'marketplace_id', 'deposit_date')
    def _compute_name(self):
        for record in self:
            parts = []
            if record.marketplace_id:
                parts.append(record.marketplace_id.code or record.marketplace_id.country_code)
            if record.settlement_id:
                parts.append(record.settlement_id[:12])
            if record.deposit_date:
                parts.append(record.deposit_date.strftime('%Y-%m-%d'))
            record.name = ' / '.join(parts) if parts else _('New Settlement')
    
    @api.depends('line_ids', 'line_ids.amount', 'line_ids.transaction_type', 'line_ids.amount_type')
    def _compute_totals(self):
        for record in self:
            lines = record.line_ids
            
            # Gross sales: Principal on orders
            gross_sales = sum(lines.filtered(
                lambda l: l.transaction_type == 'Order' and 
                         l.amount_type in ('ItemPrice', 'Principal')
            ).mapped('amount'))
            
            # Refunds
            refunds = abs(sum(lines.filtered(
                lambda l: l.transaction_type == 'Refund'
            ).mapped('amount')))
            
            # Fees (usually negative)
            fees = abs(sum(lines.filtered(
                lambda l: l.amount_type in (
                    'FBAPerUnitFulfillmentFee', 'Commission', 
                    'RefundCommission', 'ShippingChargeback',
                    'FBAWeightBasedFee', 'FBAPickAndPackFee',
                    'Fee', 'ItemFees'
                ) or l.transaction_type == 'ServiceFee'
            ).mapped('amount')))
            
            # Promotions (usually negative)
            promotions = abs(sum(lines.filtered(
                lambda l: l.amount_type in ('Promotion', 'PromotionalRebates')
            ).mapped('amount')))
            
            # Other (adjustments, reimbursements, etc.)
            other_types = ('Adjustment', 'Other', 'REVERSAL_REIMBURSEMENT', 
                          'COMPENSATED_CLAWBACK', 'Reimbursement')
            other = sum(lines.filtered(
                lambda l: l.transaction_type in other_types or 
                         l.amount_type in other_types
            ).mapped('amount'))
            
            # Total (sum of all lines)
            total = sum(lines.mapped('amount'))
            
            record.gross_sales_amount = gross_sales
            record.refund_amount = refunds
            record.total_fees = fees
            record.promotion_amount = promotions
            record.other_amount = other
            record.total_amount = total
    
    def _compute_line_count(self):
        for record in self:
            record.line_count = len(record.line_ids)
    
    def _compute_move_count(self):
        for record in self:
            record.move_count = len(record.move_ids)
    
    @api.depends('move_ids', 'move_ids.state', 'move_ids.line_ids.reconciled')
    def _compute_is_reconciled(self):
        for record in self:
            if not record.move_ids:
                record.is_reconciled = False
            else:
                # Check if all bank-type lines are reconciled
                bank_lines = record.move_ids.mapped('line_ids').filtered(
                    lambda l: l.account_id.account_type == 'asset_cash'
                )
                record.is_reconciled = (
                    bank_lines and 
                    all(line.reconciled for line in bank_lines)
                )
    
    # ==========================================
    # BUSINESS METHODS
    # ==========================================
    
    def action_confirm(self):
        """Confirm the settlement and move to pending state."""
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Only draft settlements can be confirmed.'))
            record.state = 'pending'
        return True
    
    def action_process(self):
        """Process the settlement and create journal entries."""
        for record in self:
            if record.state not in ('draft', 'pending'):
                raise UserError(_('Only draft or pending settlements can be processed.'))
            
            # Create journal entries
            record._create_journal_entries()
            record.state = 'processed'
        return True
    
    def action_reconcile(self):
        """Mark settlement as reconciled."""
        for record in self:
            if record.state != 'processed':
                raise UserError(_('Only processed settlements can be reconciled.'))
            record.state = 'reconciled'
        return True
    
    def action_cancel(self):
        """Cancel the settlement."""
        for record in self:
            if record.state == 'reconciled':
                raise UserError(_('Cannot cancel a reconciled settlement.'))
            # Cancel/delete related moves
            moves = record.move_ids.filtered(lambda m: m.state != 'posted')
            moves.unlink()
            posted_moves = record.move_ids.filtered(lambda m: m.state == 'posted')
            if posted_moves:
                posted_moves.button_draft()
                posted_moves.button_cancel()
            record.state = 'cancelled'
        return True
    
    def action_draft(self):
        """Reset to draft state."""
        for record in self:
            if record.state not in ('cancelled', 'pending'):
                raise UserError(_('Only cancelled or pending settlements can be reset to draft.'))
            record.state = 'draft'
        return True
    
    def action_view_lines(self):
        """Open settlement lines view."""
        self.ensure_one()
        return {
            'name': _('Settlement Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.settlement.line',
            'view_mode': 'tree,form',
            'domain': [('settlement_id', '=', self.id)],
            'context': {'default_settlement_id': self.id},
        }
    
    def action_view_moves(self):
        """Open journal entries view."""
        self.ensure_one()
        return {
            'name': _('Journal Entries'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('amazon_settlement_id', '=', self.id)],
        }
    
    # ==========================================
    # SETTLEMENT IMPORT
    # ==========================================
    
    @api.model
    def import_settlement(self, account, settlement_data):
        """
        Import settlement report from Amazon SP-API.
        
        Args:
            account: amazon.account record
            settlement_data: dict with settlement report data from SP-API
            
        Returns:
            amazon.settlement record(s) created
        """
        settlements = self.env['amazon.settlement']
        
        # Settlement data structure from SP-API:
        # {
        #     'settlementId': 'xxxx',
        #     'settlementStartDate': '2024-01-01T00:00:00Z',
        #     'settlementEndDate': '2024-01-14T23:59:59Z',
        #     'depositDate': '2024-01-16',
        #     'totalAmount': {'currencyCode': 'EUR', 'amount': '1234.56'},
        #     'settlementReportRows': [...]
        # }
        
        settlement_id = settlement_data.get('settlementId')
        if not settlement_id:
            raise UserError(_('Settlement ID is required.'))
        
        # Check if already imported
        existing = self.search([
            ('settlement_id', '=', settlement_id),
            ('account_id', '=', account.id),
        ], limit=1)
        
        if existing:
            _logger.info('Settlement %s already imported, skipping.', settlement_id)
            return existing
        
        # Parse dates
        start_date = self._parse_amazon_date(settlement_data.get('settlementStartDate'))
        end_date = self._parse_amazon_date(settlement_data.get('settlementEndDate'))
        deposit_date = self._parse_amazon_date(
            settlement_data.get('depositDate'), 
            as_date=True
        )
        
        # Get currency
        total_amount_data = settlement_data.get('totalAmount', {})
        currency_code = total_amount_data.get('currencyCode', 'EUR')
        currency = self.env['res.currency'].search([
            ('name', '=', currency_code)
        ], limit=1)
        
        if not currency:
            raise UserError(_('Currency %s not found.') % currency_code)
        
        # Determine marketplace
        marketplace = self._determine_marketplace(settlement_data, account)
        
        # Create settlement record
        import json
        settlement = self.create({
            'settlement_id': settlement_id,
            'account_id': account.id,
            'marketplace_id': marketplace.id,
            'settlement_start_date': start_date,
            'settlement_end_date': end_date,
            'deposit_date': deposit_date,
            'currency_id': currency.id,
            'report_data': json.dumps(settlement_data),
            'state': 'draft',
        })
        
        # Import line items
        rows = settlement_data.get('settlementReportRows', [])
        self.env['amazon.settlement.line'].import_lines(settlement, rows)
        
        _logger.info(
            'Imported settlement %s with %d lines.',
            settlement_id, len(rows)
        )
        
        settlements |= settlement
        return settlements
    
    @api.model
    def import_settlements_from_api(self, account, date_from=None, date_to=None):
        """
        Fetch and import settlement reports from Amazon SP-API.
        
        Args:
            account: amazon.account record
            date_from: Start date (defaults to 90 days ago)
            date_to: End date (defaults to today)
        """
        if not date_from:
            date_from = datetime.now() - timedelta(days=90)
        if not date_to:
            date_to = datetime.now()
        
        # Get SP-API service
        sp_api = account._get_sp_api_client()
        
        # Request settlement reports
        try:
            settlements_data = sp_api.get_settlement_reports(
                date_from=date_from,
                date_to=date_to
            )
        except Exception as e:
            _logger.exception('Failed to fetch settlement reports: %s', e)
            raise UserError(_('Failed to fetch settlement reports: %s') % str(e))
        
        imported = self.env['amazon.settlement']
        for settlement_data in settlements_data:
            try:
                settlement = self.import_settlement(account, settlement_data)
                imported |= settlement
            except Exception as e:
                _logger.exception(
                    'Failed to import settlement %s: %s',
                    settlement_data.get('settlementId'), e
                )
        
        return imported
    
    # ==========================================
    # ORDER RECONCILIATION
    # ==========================================
    
    def reconcile_with_orders(self):
        """
        Reconcile settlement lines with Amazon orders.
        
        Links settlement line items to their corresponding order lines
        to provide accurate per-order profitability analysis.
        """
        self.ensure_one()
        
        AmazonOrder = self.env['amazon.order']
        reconciled_count = 0
        unmatched_lines = []
        
        # Optimization: Batch search for orders to avoid N+1 queries
        lines_to_process = self.line_ids.filtered(lambda l: not l.amazon_order_id and l.order_id_text)

        # Collect unique order IDs to search
        order_ids_text = set(lines_to_process.mapped('order_id_text'))

        order_map = {}
        if order_ids_text:
            orders = AmazonOrder.search([
                ('amazon_order_id', 'in', list(order_ids_text)),
                ('account_id', '=', self.account_id.id),
            ])
            order_map = {o.amazon_order_id: o for o in orders}

        for line in lines_to_process:
            order = order_map.get(line.order_id_text)
            
            if order:
                line.amazon_order_id = order.id
                reconciled_count += 1
            else:
                unmatched_lines.append(line.order_id_text)
        
        # Log reconciliation results
        _logger.info(
            'Settlement %s: Reconciled %d lines, %d unmatched.',
            self.settlement_id, reconciled_count, len(unmatched_lines)
        )
        
        # Post message to chatter
        self.message_post(
            body=_(
                'Order reconciliation completed:<br/>'
                '- Matched: %(matched)d lines<br/>'
                '- Unmatched: %(unmatched)d order IDs',
                matched=reconciled_count,
                unmatched=len(unmatched_lines)
            )
        )
        
        return {
            'reconciled': reconciled_count,
            'unmatched': unmatched_lines,
        }
    
    # ==========================================
    # JOURNAL ENTRY CREATION
    # ==========================================
    
    def _create_journal_entries(self):
        """
        Create journal entries for the settlement.
        
        Creates entries for:
        - Sales revenue
        - Amazon fees expense
        - Refunds
        - Bank deposit (receivable from Amazon)
        """
        self.ensure_one()
        
        if not self.journal_id:
            # Find default bank journal
            self.journal_id = self.env['account.journal'].search([
                ('type', '=', 'bank'),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
        
        if not self.journal_id:
            raise UserError(_('Please select a bank journal for the settlement.'))
        
        # Get accounts (using default accounts or from account settings)
        accounts = self._get_settlement_accounts()
        
        # Prepare move lines
        move_lines = []
        
        # Revenue line (credit)
        if self.gross_sales_amount:
            move_lines.append({
                'name': _('Amazon Sales - %s') % self.name,
                'account_id': accounts['revenue'].id,
                'credit': self.gross_sales_amount,
                'debit': 0,
            })
        
        # Fees line (debit - expense)
        if self.total_fees:
            move_lines.append({
                'name': _('Amazon Fees - %s') % self.name,
                'account_id': accounts['fees'].id,
                'debit': self.total_fees,
                'credit': 0,
            })
        
        # Refunds line (debit - reduces revenue)
        if self.refund_amount:
            move_lines.append({
                'name': _('Amazon Refunds - %s') % self.name,
                'account_id': accounts['refunds'].id,
                'debit': self.refund_amount,
                'credit': 0,
            })
        
        # Promotions (debit - expense)
        if self.promotion_amount:
            move_lines.append({
                'name': _('Amazon Promotions - %s') % self.name,
                'account_id': accounts['promotions'].id,
                'debit': self.promotion_amount,
                'credit': 0,
            })
        
        # Other adjustments
        if self.other_amount:
            if self.other_amount > 0:
                move_lines.append({
                    'name': _('Amazon Adjustments - %s') % self.name,
                    'account_id': accounts['other'].id,
                    'credit': self.other_amount,
                    'debit': 0,
                })
            else:
                move_lines.append({
                    'name': _('Amazon Adjustments - %s') % self.name,
                    'account_id': accounts['other'].id,
                    'debit': abs(self.other_amount),
                    'credit': 0,
                })
        
        # Bank/Receivable line (the net deposit)
        if self.total_amount:
            if self.total_amount > 0:
                move_lines.append({
                    'name': _('Amazon Deposit - %s') % self.name,
                    'account_id': accounts['bank'].id,
                    'debit': self.total_amount,
                    'credit': 0,
                })
            else:
                move_lines.append({
                    'name': _('Amazon Payment - %s') % self.name,
                    'account_id': accounts['bank'].id,
                    'debit': 0,
                    'credit': abs(self.total_amount),
                })
        
        if not move_lines:
            _logger.info('No journal entry needed for settlement %s (zero amounts)', self.name)
            return self.env['account.move']
        
        # Create the journal entry
        move = self.env['account.move'].create({
            'journal_id': self.journal_id.id,
            'date': self.deposit_date or fields.Date.today(),
            'ref': _('Amazon Settlement: %s') % self.settlement_id,
            'amazon_settlement_id': self.id,
            'move_type': 'entry',
            'line_ids': [(0, 0, line) for line in move_lines],
        })
        
        _logger.info('Created journal entry %s for settlement %s', move.name, self.name)
        
        return move
    
    def _get_settlement_accounts(self):
        """
        Get accounting accounts for settlement entries.
        
        Returns dict with accounts:
        - revenue: Sales revenue account
        - fees: Amazon fees expense account
        - refunds: Refunds/returns account
        - promotions: Promotional expense account
        - other: Other adjustments account
        - bank: Bank/cash account
        """
        # Get from account configuration or use defaults
        company = self.company_id
        
        # Default account codes (adjust based on your chart of accounts)
        def get_account(account_type, default_code=None):
            # Try to get from settings first
            # Then fall back to searching by type/code
            account = None
            
            if default_code:
                account = self.env['account.account'].search([
                    ('code', '=like', default_code + '%'),
                    ('company_id', '=', company.id),
                ], limit=1)
            
            if not account:
                account = self.env['account.account'].search([
                    ('account_type', '=', account_type),
                    ('company_id', '=', company.id),
                ], limit=1)
            
            return account
        
        accounts = {
            'revenue': get_account('income', '4'),  # Revenue/Income
            'fees': get_account('expense', '6'),    # Expenses
            'refunds': get_account('income', '4'),  # Contra-revenue
            'promotions': get_account('expense', '6'),
            'other': get_account('income_other', '7'),
            'bank': self.journal_id.default_account_id or get_account('asset_cash'),
        }
        
        # Validate all accounts found
        for name, account in accounts.items():
            if not account:
                raise UserError(_(
                    'Could not find %(account_type)s account for settlement. '
                    'Please configure your chart of accounts.',
                    account_type=name
                ))
        
        return accounts
    
    # ==========================================
    # HELPER METHODS
    # ==========================================
    
    @api.model
    def _parse_amazon_date(self, date_str, as_date=False):
        """Parse Amazon date string to datetime or date object."""
        if not date_str:
            return None
        
        # Handle various Amazon date formats
        formats = [
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%dT%H:%M:%S.%fZ',
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%d',
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.replace('+00:00', 'Z'), fmt)
                return dt.date() if as_date else dt
            except ValueError:
                continue
        
        _logger.warning('Could not parse date: %s', date_str)
        return None
    
    @api.model
    def _determine_marketplace(self, settlement_data, account):
        """Determine marketplace from settlement data."""
        # Try to get from settlement data
        marketplace_id = settlement_data.get('marketplaceId')
        
        if marketplace_id:
            marketplace = self.env['amazon.marketplace'].search([
                ('marketplace_id', '=', marketplace_id),
            ], limit=1)
            if marketplace:
                return marketplace
        
        # Fall back to account's primary marketplace
        if account.marketplace_ids:
            return account.marketplace_ids[0]
        
        # Last resort: search by currency
        currency_code = settlement_data.get('totalAmount', {}).get('currencyCode')
        if currency_code:
            marketplace = self.env['amazon.marketplace'].search([
                ('currency_id.name', '=', currency_code),
            ], limit=1)
            if marketplace:
                return marketplace
        
        raise UserError(_('Could not determine marketplace for settlement.'))
    
    # ==========================================
    # CRON METHODS
    # ==========================================
    
    @api.model
    def cron_import_settlements(self):
        """
        Scheduled action to import settlement reports.
        
        Runs periodically to fetch new settlement reports
        from all active Amazon accounts.
        """
        accounts = self.env['amazon.account'].search([
            ('active', '=', True),
            ('state', '=', 'connected'),
        ])
        
        for account in accounts:
            try:
                self.import_settlements_from_api(account)
            except Exception as e:
                _logger.exception(
                    'Failed to import settlements for account %s: %s',
                    account.name, e
                )
    
    @api.model
    def cron_reconcile_settlements(self):
        """
        Scheduled action to reconcile settlement lines with orders.
        """
        settlements = self.search([
            ('state', 'in', ['draft', 'pending']),
        ])
        
        for settlement in settlements:
            try:
                settlement.reconcile_with_orders()
            except Exception as e:
                _logger.exception(
                    'Failed to reconcile settlement %s: %s',
                    settlement.name, e
                )
