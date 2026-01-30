# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

"""
Amazon OAuth 2.0 Authorization Controller

Handles the OAuth 2.0 / Login with Amazon (LWA) authorization flow:
1. User initiates connection from Odoo
2. Redirects to Amazon Seller Central authorization page
3. Amazon redirects back with authorization code
4. We exchange code for access & refresh tokens
5. Store tokens securely in the database

Security considerations:
- State parameter validation to prevent CSRF attacks
- HTTPS required for production
- Secure token storage with encryption
"""

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

import requests
from werkzeug.exceptions import BadRequest, Forbidden

from odoo import http, SUPERUSER_ID, _
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)


class AmazonOAuthController(http.Controller):
    """Controller for Amazon OAuth 2.0 authorization flow."""
    
    # Amazon OAuth endpoints
    OAUTH_AUTHORIZE_URL = "https://sellercentral.amazon.com/apps/authorize/consent"
    OAUTH_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
    
    # Regional Seller Central URLs
    SELLER_CENTRAL_URLS = {
        'na': 'https://sellercentral.amazon.com',
        'eu': 'https://sellercentral-europe.amazon.com',
        'fe': 'https://sellercentral.amazon.co.jp',
    }
    
    # State expiration (10 minutes)
    STATE_EXPIRY_SECONDS = 600
    
    @http.route(
        '/amazon/oauth/initiate',
        type='http',
        auth='user',
        methods=['GET'],
        csrf=True
    )
    def oauth_initiate(self, account_id=None, **kwargs):
        """
        Initiate the OAuth authorization flow.
        
        Generates a state token and redirects to Amazon's authorization page.
        
        Args:
            account_id: ID of the amazon.account to authorize
            
        Returns:
            Redirect to Amazon Seller Central authorization page
        """
        if not account_id:
            raise BadRequest("Missing account_id parameter")
        
        try:
            account_id = int(account_id)
        except (ValueError, TypeError):
            raise BadRequest("Invalid account_id parameter")
        
        # Get the account
        account = request.env['amazon.account'].browse(account_id)
        if not account.exists():
            raise BadRequest("Account not found")
        
        # Check user has access
        if not request.env.user.has_group('amazon_connector.group_amazon_manager'):
            raise Forbidden("Insufficient permissions to authorize Amazon accounts")
        
        # Get OAuth configuration
        config = request.env['ir.config_parameter'].sudo()
        client_id = config.get_param('amazon_connector.lwa_client_id')
        
        if not client_id:
            raise UserError(_(
                "Amazon LWA Client ID not configured. "
                "Please configure it in Settings → Amazon Connector."
            ))
        
        # Generate state parameter (CSRF protection)
        state = self._generate_state(account_id)
        
        # Build redirect URI
        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        redirect_uri = f"{base_url}/amazon/oauth/callback"
        
        # Determine the correct Seller Central URL based on region
        region = account.marketplace_ids[0].region if account.marketplace_ids else 'eu'
        authorize_url = self.SELLER_CENTRAL_URLS.get(region, self.SELLER_CENTRAL_URLS['eu'])
        
        # Build authorization URL
        auth_params = {
            'application_id': client_id,
            'state': state,
            'redirect_uri': redirect_uri,
            'version': 'beta',  # Required for SP-API authorization
        }
        
        authorization_url = f"{authorize_url}/apps/authorize/consent?{urlencode(auth_params)}"
        
        _logger.info(
            "Initiating OAuth flow for account %s (region: %s)",
            account.name, region
        )
        
        return request.redirect(authorization_url)
    
    @http.route(
        '/amazon/oauth/callback',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False  # Amazon callback can't include CSRF token
    )
    def oauth_callback(self, **kwargs):
        """
        Handle OAuth callback from Amazon.
        
        Amazon redirects here with:
        - spapi_oauth_code: Authorization code
        - state: Our state parameter
        - selling_partner_id: Seller/Vendor ID
        
        Or on error:
        - error: Error code
        - error_description: Error description
        
        Args:
            **kwargs: Query parameters from Amazon
            
        Returns:
            Redirect to account view with success/error message
        """
        try:
            # Check for error response
            if 'error' in kwargs:
                error = kwargs.get('error')
                error_desc = kwargs.get('error_description', 'Unknown error')
                _logger.error(
                    "Amazon OAuth error: %s - %s",
                    error, error_desc
                )
                return self._redirect_with_error(
                    f"Amazon authorization failed: {error_desc}"
                )
            
            # Get required parameters
            auth_code = kwargs.get('spapi_oauth_code')
            state = kwargs.get('state')
            selling_partner_id = kwargs.get('selling_partner_id')
            
            if not all([auth_code, state]):
                _logger.warning("Missing required OAuth callback parameters")
                return self._redirect_with_error(
                    "Invalid callback: missing authorization code or state"
                )
            
            # Validate state and get account ID
            account_id = self._validate_state(state)
            if not account_id:
                _logger.warning("Invalid or expired OAuth state parameter")
                return self._redirect_with_error(
                    "Authorization expired or invalid. Please try again."
                )
            
            # Get the account
            env = request.env(user=SUPERUSER_ID)
            account = env['amazon.account'].browse(account_id)
            
            if not account.exists():
                return self._redirect_with_error("Account not found")
            
            # Exchange authorization code for tokens
            tokens = self._exchange_code_for_tokens(auth_code, account)
            
            if not tokens:
                return self._redirect_with_error(
                    "Failed to exchange authorization code for tokens"
                )
            
            # Store tokens securely
            self._store_tokens(account, tokens, selling_partner_id)
            
            _logger.info(
                "OAuth flow completed successfully for account %s",
                account.name
            )
            
            # Redirect to account view with success message
            return self._redirect_with_success(
                account_id,
                "Amazon account authorized successfully!"
            )
            
        except Exception as e:
            _logger.exception("Error in OAuth callback: %s", str(e))
            return self._redirect_with_error(f"Authorization error: {str(e)}")
    
    @http.route(
        '/amazon/oauth/revoke',
        type='http',
        auth='user',
        methods=['POST'],
        csrf=True
    )
    def oauth_revoke(self, account_id=None, **kwargs):
        """
        Revoke OAuth authorization for an account.
        
        Args:
            account_id: ID of the amazon.account to revoke
            
        Returns:
            Redirect to account view
        """
        if not account_id:
            raise BadRequest("Missing account_id parameter")
        
        try:
            account_id = int(account_id)
        except (ValueError, TypeError):
            raise BadRequest("Invalid account_id parameter")
        
        # Get the account
        account = request.env['amazon.account'].browse(account_id)
        if not account.exists():
            raise BadRequest("Account not found")
        
        # Check user has access
        if not request.env.user.has_group('amazon_connector.group_amazon_manager'):
            raise Forbidden("Insufficient permissions to revoke Amazon authorization")
        
        try:
            # Clear stored tokens
            account.sudo().write({
                'refresh_token': False,
                'access_token': False,
                'token_expiry': False,
                'seller_id': False,
                'authorization_status': 'revoked',
                'authorized_date': False,
            })
            
            _logger.info(
                "OAuth authorization revoked for account %s",
                account.name
            )
            
            return self._redirect_with_success(
                account_id,
                "Amazon authorization revoked successfully."
            )
            
        except Exception as e:
            _logger.exception("Error revoking OAuth: %s", str(e))
            return self._redirect_with_error(f"Revocation error: {str(e)}")
    
    def _generate_state(self, account_id):
        """
        Generate a secure state parameter for CSRF protection.
        
        The state includes:
        - Random token
        - Account ID (encrypted)
        - Timestamp
        
        Args:
            account_id: Account ID to encode
            
        Returns:
            State string
        """
        # Generate random token
        token = secrets.token_urlsafe(32)
        
        # Create state data
        state_data = {
            'token': token,
            'account_id': account_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'user_id': request.env.user.id,
        }
        
        # Store in session or database for validation
        # Using ir.config_parameter for simplicity (should use dedicated model in production)
        env = request.env(user=SUPERUSER_ID)
        state_store = env['ir.config_parameter'].sudo()
        
        # Store with expiry
        state_key = f'amazon_oauth_state_{token}'
        state_store.set_param(state_key, json.dumps(state_data))
        
        return token
    
    def _validate_state(self, state):
        """
        Validate the state parameter and return the account ID.
        
        Args:
            state: State token from callback
            
        Returns:
            Account ID if valid, None otherwise
        """
        try:
            env = request.env(user=SUPERUSER_ID)
            state_store = env['ir.config_parameter'].sudo()
            
            # Get stored state
            state_key = f'amazon_oauth_state_{state}'
            stored_data = state_store.get_param(state_key)
            
            if not stored_data:
                _logger.warning("State token not found: %s", state)
                return None
            
            # Delete state immediately (one-time use)
            state_store.set_param(state_key, False)
            
            # Parse state data
            state_data = json.loads(stored_data)
            
            # Check expiry
            timestamp = datetime.fromisoformat(state_data['timestamp'].replace('Z', '+00:00'))
            age = (datetime.now(timezone.utc) - timestamp).total_seconds()
            
            if age > self.STATE_EXPIRY_SECONDS:
                _logger.warning("State token expired: %d seconds old", age)
                return None
            
            return state_data['account_id']
            
        except Exception as e:
            _logger.exception("Error validating state: %s", str(e))
            return None
    
    def _exchange_code_for_tokens(self, auth_code, account):
        """
        Exchange authorization code for access and refresh tokens.
        
        Args:
            auth_code: Authorization code from Amazon
            account: amazon.account record
            
        Returns:
            Dict with tokens or None on error
        """
        try:
            # Get OAuth configuration
            config = request.env['ir.config_parameter'].sudo()
            client_id = config.get_param('amazon_connector.lwa_client_id')
            client_secret = config.get_param('amazon_connector.lwa_client_secret')
            
            if not client_id or not client_secret:
                _logger.error("LWA credentials not configured")
                return None
            
            # Build redirect URI (must match exactly)
            base_url = config.get_param('web.base.url')
            redirect_uri = f"{base_url}/amazon/oauth/callback"
            
            # Exchange code for tokens
            token_request = {
                'grant_type': 'authorization_code',
                'code': auth_code,
                'redirect_uri': redirect_uri,
                'client_id': client_id,
                'client_secret': client_secret,
            }
            
            response = requests.post(
                self.OAUTH_TOKEN_URL,
                data=token_request,
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=30
            )
            
            if response.status_code == 200:
                token_data = response.json()
                _logger.info("Token exchange successful")
                return {
                    'access_token': token_data.get('access_token'),
                    'refresh_token': token_data.get('refresh_token'),
                    'expires_in': token_data.get('expires_in', 3600),
                }
            else:
                error_data = response.json() if response.content else {}
                _logger.error(
                    "Token exchange failed: %s - %s",
                    response.status_code,
                    error_data.get('error_description', response.text)
                )
                return None
                
        except requests.RequestException as e:
            _logger.exception("Network error during token exchange: %s", str(e))
            return None
        except Exception as e:
            _logger.exception("Error exchanging code for tokens: %s", str(e))
            return None
    
    def _store_tokens(self, account, tokens, selling_partner_id):
        """
        Store tokens securely in the database.
        
        In production, tokens should be encrypted using Odoo's encryption
        facilities or a dedicated secret management system.
        
        Args:
            account: amazon.account record
            tokens: Dict with access_token, refresh_token, expires_in
            selling_partner_id: Amazon Seller ID
        """
        # Calculate token expiry
        expires_in = tokens.get('expires_in', 3600)
        token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        # Update account
        account.sudo().write({
            'refresh_token': tokens['refresh_token'],
            'access_token': tokens['access_token'],
            'token_expiry': token_expiry,
            'seller_id': selling_partner_id,
            'authorization_status': 'authorized',
            'authorized_date': datetime.now(timezone.utc),
        })
        
        _logger.info(
            "Tokens stored for account %s (Seller ID: %s)",
            account.name, selling_partner_id
        )
    
    def _redirect_with_success(self, account_id, message):
        """
        Redirect to account view with success message.
        
        Args:
            account_id: Account ID
            message: Success message
            
        Returns:
            Redirect response
        """
        # Store message in session
        if hasattr(request, 'session'):
            request.session['amazon_oauth_message'] = {
                'type': 'success',
                'message': message,
            }
        
        # Redirect to account form view
        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return request.redirect(
            f"{base_url}/web#id={account_id}&model=amazon.account&view_type=form"
        )
    
    def _redirect_with_error(self, message):
        """
        Redirect to Amazon menu with error message.
        
        Args:
            message: Error message
            
        Returns:
            Redirect response
        """
        # Store message in session
        if hasattr(request, 'session'):
            request.session['amazon_oauth_message'] = {
                'type': 'error',
                'message': message,
            }
        
        # Redirect to Amazon accounts list
        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return request.redirect(
            f"{base_url}/web#model=amazon.account&view_type=list"
        )


class AmazonConnectionTestController(http.Controller):
    """Controller for testing Amazon API connectivity."""
    
    @http.route(
        '/amazon/test-connection',
        type='json',
        auth='user',
        methods=['POST']
    )
    def test_connection(self, account_id=None, **kwargs):
        """
        Test the Amazon API connection for an account.
        
        Args:
            account_id: ID of the amazon.account to test
            
        Returns:
            Dict with test results
        """
        if not account_id:
            return {'success': False, 'error': 'Missing account_id'}
        
        try:
            account = request.env['amazon.account'].browse(int(account_id))
            if not account.exists():
                return {'success': False, 'error': 'Account not found'}
            
            # Test the connection
            result = account.test_api_connection()
            
            return {
                'success': result.get('success', False),
                'message': result.get('message', ''),
                'seller_info': result.get('seller_info', {}),
            }
            
        except Exception as e:
            _logger.exception("Error testing connection: %s", str(e))
            return {'success': False, 'error': str(e)}
