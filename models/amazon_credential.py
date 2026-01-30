# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AmazonCredential(models.Model):
    """Amazon API Credentials.
    
    Stores sensitive SP-API credentials separately for enhanced security.
    Access restricted to amazon_admin group only.
    """
    _name = 'amazon.credential'
    _description = 'Amazon API Credential'
    _order = 'name'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    name = fields.Char(
        string='Credential Name',
        required=True,
        help='Internal name for this credential set',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    account_id = fields.Many2one(
        comodel_name='amazon.account',
        string='Amazon Account',
        required=True,
        ondelete='cascade',
        help='Amazon account these credentials belong to',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='account_id.company_id',
        store=True,
    )

    # LWA Credentials (Login with Amazon)
    lwa_client_id = fields.Char(
        string='LWA Client ID',
        groups='amazon_connector.group_amazon_admin',
        help='Login with Amazon App Client ID',
    )
    lwa_client_secret = fields.Char(
        string='LWA Client Secret',
        groups='amazon_connector.group_amazon_admin',
        help='Login with Amazon App Client Secret',
    )
    refresh_token = fields.Char(
        string='Refresh Token',
        groups='amazon_connector.group_amazon_admin',
        help='OAuth refresh token for SP-API authentication',
    )

    # AWS Credentials
    aws_access_key = fields.Char(
        string='AWS Access Key',
        groups='amazon_connector.group_amazon_admin',
        help='AWS IAM access key for request signing',
    )
    aws_secret_key = fields.Char(
        string='AWS Secret Key',
        groups='amazon_connector.group_amazon_admin',
        help='AWS IAM secret key for request signing',
    )
    aws_role_arn = fields.Char(
        string='AWS Role ARN',
        groups='amazon_connector.group_amazon_admin',
        help='AWS IAM Role ARN for assuming role',
    )

    # Metadata
    last_used = fields.Datetime(
        string='Last Used',
        readonly=True,
        help='Last time these credentials were used',
    )
    is_valid = fields.Boolean(
        string='Valid',
        default=True,
        help='Whether these credentials are valid',
    )

    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------
    _sql_constraints = [
        (
            'account_unique',
            'UNIQUE(account_id)',
            'Only one credential set per Amazon account is allowed!',
        ),
    ]

    @api.constrains('lwa_client_id', 'lwa_client_secret', 'refresh_token')
    def _check_lwa_credentials(self):
        """Validate that all LWA credentials are provided together."""
        for record in self:
            lwa_fields = [record.lwa_client_id, record.lwa_client_secret, record.refresh_token]
            if any(lwa_fields) and not all(lwa_fields):
                raise ValidationError(
                    _('All LWA credentials (Client ID, Client Secret, Refresh Token) '
                      'must be provided together.')
                )

    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------
    def action_test_credentials(self):
        """Test if the credentials are valid by making a simple API call."""
        self.ensure_one()
        # Implementation would test the credentials via SP-API
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Credential Test'),
                'message': _('Credential testing not yet implemented.'),
                'type': 'warning',
                'sticky': False,
            },
        }

    def mark_as_used(self):
        """Update the last_used timestamp."""
        self.write({'last_used': fields.Datetime.now()})
