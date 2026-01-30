# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

import logging
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmazonSettlementImportWizard(models.TransientModel):
    """
    Wizard for importing Amazon settlement reports.
    Settlement reports contain all financial transactions including
    sales, refunds, fees, and other adjustments.
    """
    _name = 'amazon.settlement.import.wizard'
    _description = 'Import Amazon Settlement Reports'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    
    # Account Selection
    account_id = fields.Many2one(
        'amazon.account',
        string='Amazon Account',
        required=True,
        default=lambda self: self._default_account_id(),
    )
    
    # Date Range
    date_from = fields.Date(
        string='From Date',
        required=True,
        default=lambda self: fields.Date.today() - timedelta(days=30),
    )
    date_to = fields.Date(
        string='To Date',
        required=True,
        default=lambda self: fields.Date.today(),
    )
    
    # Import Options
    import_mode = fields.Selection([
        ('new', 'New Settlements Only'),
        ('all', 'All Settlements'),
        ('specific', 'Specific Settlement ID'),
    ], string='Import Mode', default='new', required=True,
       help='New: Only settlements not yet imported\n'
            'All: Re-import all settlements in date range\n'
            'Specific: Import a specific settlement by ID')
    
    settlement_id = fields.Char(
        string='Settlement ID',
        help='Amazon Settlement ID to import (required for Specific mode).',
    )
    
    # Reconciliation Options
    auto_reconcile = fields.Boolean(
        string='Auto-Reconcile',
        default=True,
        help='Automatically match settlement lines with invoices and orders.',
    )
    reconcile_payments = fields.Boolean(
        string='Create Bank Payments',
        default=False,
        help='Create payment entries for the settlement total.',
    )
    bank_journal_id = fields.Many2one(
        'account.journal',
        string='Bank Journal',
        domain="[('type', '=', 'bank')]",
        help='Journal for settlement payments.',
    )
    
    # Fee Processing
    create_fee_entries = fields.Boolean(
        string='Create Fee Entries',
        default=True,
        help='Create expense entries for Amazon fees.',
    )
    fee_account_id = fields.Many2one(
        'account.account',
        string='Fee Expense Account',
        help='Account for Amazon fees.',
    )
    fee_product_id = fields.Many2one(
        'product.product',
        string='Fee Product',
        help='Product to use for fee invoice lines.',
    )
    
    # State & Progress
    state = fields.Selection([
        ('draft', 'Configuration'),
        ('fetching', 'Fetching Reports'),
        ('preview', 'Preview'),
        ('importing', 'Importing'),
        ('done', 'Completed'),
        ('error', 'Error'),
    ], string='State', default='draft')
    
    progress_percent = fields.Float(string='Progress', default=0.0)
    progress_message = fields.Char(string='Status')
    
    # Preview
    preview_line_ids = fields.One2many(
        'amazon.settlement.import.wizard.line',
        'wizard_id',
        string='Settlements Found',
    )
    preview_count = fields.Integer(
        string='Settlements Found',
        compute='_compute_preview_stats',
    )
    preview_total_amount = fields.Monetary(
        string='Total Amount',
        compute='_compute_preview_stats',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    
    # Results
    imported_settlement_ids = fields.Many2many(
        'amazon.settlement',
        string='Imported Settlements',
    )
    result_count = fields.Integer(string='Settlements Imported', default=0)
    result_lines = fields.Integer(string='Lines Imported', default=0)
    result_reconciled = fields.Integer(string='Lines Reconciled', default=0)
    result_amount = fields.Monetary(
        string='Total Imported',
        currency_field='currency_id',
    )
    result_log = fields.Text(string='Import Log')
    
    # -------------------------------------------------------------------------
    # DEFAULT METHODS
    # -------------------------------------------------------------------------
    
    def _default_account_id(self):
        return self.env['amazon.account'].search([('active', '=', True)], limit=1)
    
    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    
    @api.depends('preview_line_ids', 'preview_line_ids.total_amount')
    def _compute_preview_stats(self):
        for wizard in self:
            wizard.preview_count = len(wizard.preview_line_ids)
            wizard.preview_total_amount = sum(wizard.preview_line_ids.mapped('total_amount'))
    
    # -------------------------------------------------------------------------
    # ONCHANGE METHODS
    # -------------------------------------------------------------------------
    
    @api.onchange('import_mode')
    def _onchange_import_mode(self):
        if self.import_mode != 'specific':
            self.settlement_id = False
    
    @api.onchange('reconcile_payments')
    def _onchange_reconcile_payments(self):
        if self.reconcile_payments and not self.bank_journal_id:
            self.bank_journal_id = self.env['account.journal'].search([
                ('type', '=', 'bank'),
                ('company_id', '=', self.env.company.id),
            ], limit=1)
    
    @api.onchange('create_fee_entries')
    def _onchange_create_fee_entries(self):
        if self.create_fee_entries:
            if not self.fee_account_id:
                # Try to find an expense account
                self.fee_account_id = self.env['account.account'].search([
                    ('account_type', '=', 'expense'),
                    ('company_id', '=', self.env.company.id),
                ], limit=1)
            if not self.fee_product_id:
                # Try to find or suggest a fee product
                self.fee_product_id = self.env['product.product'].search([
                    ('name', 'ilike', 'amazon fee'),
                ], limit=1)
    
    # -------------------------------------------------------------------------
    # CONSTRAINT METHODS
    # -------------------------------------------------------------------------
    
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from > wizard.date_to:
                raise UserError(_('From Date must be before To Date.'))
            if wizard.date_to > fields.Date.today():
                raise UserError(_('To Date cannot be in the future.'))
    
    # -------------------------------------------------------------------------
    # ACTION METHODS
    # -------------------------------------------------------------------------
    
    def action_fetch_settlements(self):
        """Fetch available settlement reports from Amazon."""
        self.ensure_one()
        
        if self.import_mode == 'specific' and not self.settlement_id:
            raise UserError(_('Please enter a Settlement ID.'))
        
        self.state = 'fetching'
        self.progress_message = _('Connecting to Amazon...')
        self.preview_line_ids.unlink()
        
        try:
            sp_api = self.account_id._get_sp_api_client()
            
            if self.import_mode == 'specific':
                settlements = [sp_api.get_settlement_report(self.settlement_id)]
            else:
                settlements = sp_api.get_settlement_reports(
                    start_date=fields.Datetime.to_datetime(self.date_from),
                    end_date=fields.Datetime.to_datetime(self.date_to),
                )
            
            for settlement in settlements:
                # Check if already imported
                existing = self.env['amazon.settlement'].search([
                    ('amazon_settlement_id', '=', settlement.get('settlement_id')),
                    ('account_id', '=', self.account_id.id),
                ], limit=1)
                
                if self.import_mode == 'new' and existing:
                    continue
                
                self.env['amazon.settlement.import.wizard.line'].create({
                    'wizard_id': self.id,
                    'selected': True,
                    'settlement_id': settlement.get('settlement_id'),
                    'start_date': settlement.get('settlement_start_date'),
                    'end_date': settlement.get('settlement_end_date'),
                    'total_amount': settlement.get('total_amount', 0.0),
                    'currency': settlement.get('currency', 'EUR'),
                    'deposit_date': settlement.get('deposit_date'),
                    'status': 'imported' if existing else 'new',
                    'existing_id': existing.id if existing else False,
                })
            
            self.state = 'preview'
            self.progress_message = _('Found %d settlement reports', len(self.preview_line_ids))
            
        except Exception as e:
            _logger.exception('Error fetching settlement reports')
            self.state = 'error'
            self.progress_message = _('Error: %s', str(e))
        
        return self._return_wizard()
    
    def action_import(self):
        """Import selected settlement reports."""
        self.ensure_one()
        
        selected = self.preview_line_ids.filtered(lambda l: l.selected)
        if not selected:
            raise UserError(_('Please select at least one settlement to import.'))
        
        self.state = 'importing'
        self.result_count = 0
        self.result_lines = 0
        self.result_reconciled = 0
        self.result_amount = 0.0
        log_lines = []
        imported_ids = []
        
        try:
            sp_api = self.account_id._get_sp_api_client()
            
            total = len(selected)
            for idx, line in enumerate(selected, 1):
                self.progress_percent = (idx / total) * 100
                self.progress_message = _('Importing settlement %s (%d/%d)...', 
                                         line.settlement_id, idx, total)
                
                try:
                    # Fetch full settlement data
                    settlement_data = sp_api.get_settlement_report_data(line.settlement_id)
                    
                    # Create or update settlement record
                    settlement = self._create_settlement(line, settlement_data)
                    imported_ids.append(settlement.id)
                    
                    self.result_count += 1
                    self.result_lines += len(settlement.line_ids)
                    self.result_amount += settlement.total_amount
                    
                    # Auto-reconcile if enabled
                    if self.auto_reconcile:
                        reconciled = self._reconcile_settlement(settlement)
                        self.result_reconciled += reconciled
                    
                    # Create fee entries if enabled
                    if self.create_fee_entries:
                        self._create_fee_entries(settlement)
                    
                    log_lines.append(f"✓ {line.settlement_id}: {line.total_amount} {line.currency}")
                    line.status = 'imported'
                    
                except Exception as e:
                    _logger.exception('Error importing settlement %s', line.settlement_id)
                    log_lines.append(f"✗ {line.settlement_id}: {e}")
                    line.status = 'error'
            
            self.imported_settlement_ids = [(6, 0, imported_ids)]
            self.state = 'done'
            self.progress_percent = 100.0
            self.progress_message = _(
                'Completed: %d settlements, %d lines, %d reconciled',
                self.result_count, self.result_lines, self.result_reconciled
            )
            
            # Create bank payment if enabled
            if self.reconcile_payments and imported_ids:
                self._create_bank_payment()
            
        except Exception as e:
            _logger.exception('Error during settlement import')
            self.state = 'error'
            self.progress_message = _('Error: %s', str(e))
        
        self.result_log = '\n'.join(log_lines)
        return self._return_wizard()
    
    def action_view_settlements(self):
        """View imported settlements."""
        self.ensure_one()
        
        if not self.imported_settlement_ids:
            raise UserError(_('No settlements to view.'))
        
        return {
            'name': _('Imported Settlements'),
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.settlement',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.imported_settlement_ids.ids)],
        }
    
    def action_back(self):
        """Go back to configuration."""
        self.state = 'draft'
        return self._return_wizard()
    
    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------
    
    def _create_settlement(self, line, data):
        """Create or update settlement record from API data."""
        Settlement = self.env['amazon.settlement']
        
        # Check for existing
        settlement = Settlement.search([
            ('amazon_settlement_id', '=', line.settlement_id),
            ('account_id', '=', self.account_id.id),
        ], limit=1)
        
        vals = {
            'account_id': self.account_id.id,
            'amazon_settlement_id': line.settlement_id,
            'settlement_start_date': line.start_date,
            'settlement_end_date': line.end_date,
            'deposit_date': line.deposit_date,
            'total_amount': line.total_amount,
            'currency_id': self.env['res.currency'].search([
                ('name', '=', line.currency)
            ], limit=1).id,
            'state': 'imported',
        }
        
        if settlement:
            settlement.write(vals)
            settlement.line_ids.unlink()  # Re-import lines
        else:
            settlement = Settlement.create(vals)
        
        # Create settlement lines
        for item in data.get('items', []):
            self._create_settlement_line(settlement, item)
        
        return settlement
    
    def _create_settlement_line(self, settlement, item):
        """Create settlement line from API item data."""
        Line = self.env['amazon.settlement.line']
        
        # Map item type
        item_type = item.get('item_type', 'Other')
        
        # Try to find related order/product
        order = None
        product = None
        
        if item.get('amazon_order_id'):
            order = self.env['amazon.order'].search([
                ('amazon_order_id', '=', item['amazon_order_id']),
            ], limit=1)
        
        if item.get('sku'):
            listing = self.env['amazon.product.listing'].search([
                ('seller_sku', '=', item['sku']),
            ], limit=1)
            if listing:
                product = listing.product_tmpl_id
        
        return Line.create({
            'settlement_id': settlement.id,
            'posted_date': item.get('posted_date'),
            'transaction_type': item.get('transaction_type', 'Other'),
            'amazon_order_id': item.get('amazon_order_id'),
            'seller_sku': item.get('sku'),
            'quantity': item.get('quantity', 0),
            'marketplace_name': item.get('marketplace_name'),
            'amount_type': item.get('amount_type'),
            'amount': item.get('amount', 0.0),
            'amount_description': item.get('amount_description'),
            'order_id': order.id if order else False,
            'product_id': product.id if product else False,
        })
    
    def _reconcile_settlement(self, settlement):
        """Auto-reconcile settlement lines with orders/invoices."""
        reconciled = 0
        
        for line in settlement.line_ids.filtered(lambda l: l.amazon_order_id and not l.reconciled):
            # Try to find and match order
            order = self.env['amazon.order'].search([
                ('amazon_order_id', '=', line.amazon_order_id),
            ], limit=1)
            
            if order and order.sale_order_id:
                line.write({
                    'order_id': order.id,
                    'sale_order_id': order.sale_order_id.id,
                    'reconciled': True,
                })
                reconciled += 1
        
        settlement._compute_reconciliation_status()
        return reconciled
    
    def _create_fee_entries(self, settlement):
        """Create expense journal entries for Amazon fees."""
        if not self.fee_account_id:
            return
        
        # Group fees by type
        fee_lines = settlement.line_ids.filtered(
            lambda l: l.transaction_type in ('Fee', 'FBA Fee', 'Commission')
        )
        
        if not fee_lines:
            return
        
        total_fees = sum(fee_lines.mapped('amount'))
        
        # Fees are typically negative amounts (costs)
        # Create vendor bill or journal entry
        # Implementation depends on accounting preferences
        _logger.info('Total fees for settlement %s: %s', 
                    settlement.amazon_settlement_id, total_fees)
    
    def _create_bank_payment(self):
        """Create bank payment for settlement total."""
        if not self.bank_journal_id:
            return
        
        # Create payment/bank statement line
        # Implementation depends on accounting workflow
        _logger.info('Creating bank payment for %s settlements', len(self.imported_settlement_ids))
    
    def _return_wizard(self):
        """Return action to keep wizard open."""
        return {
            'name': _('Import Settlement Reports'),
            'type': 'ir.actions.act_window',
            'res_model': 'amazon.settlement.import.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }


class AmazonSettlementImportWizardLine(models.TransientModel):
    """Settlement preview line."""
    _name = 'amazon.settlement.import.wizard.line'
    _description = 'Settlement Import Preview Line'
    _order = 'end_date desc'
    
    wizard_id = fields.Many2one(
        'amazon.settlement.import.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    selected = fields.Boolean(string='Import', default=True)
    
    settlement_id = fields.Char(string='Settlement ID', required=True)
    start_date = fields.Datetime(string='Start Date')
    end_date = fields.Datetime(string='End Date')
    total_amount = fields.Float(string='Total Amount')
    currency = fields.Char(string='Currency')
    deposit_date = fields.Date(string='Deposit Date')
    
    status = fields.Selection([
        ('new', 'New'),
        ('imported', 'Already Imported'),
        ('error', 'Error'),
    ], string='Status', default='new')
    
    existing_id = fields.Many2one(
        'amazon.settlement',
        string='Existing Settlement',
    )
