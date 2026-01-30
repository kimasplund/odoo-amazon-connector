# -*- coding: utf-8 -*-
"""
Amazon SP-API Authentication Handler

Implements OAuth 2.0 / Login with Amazon (LWA) authentication with:
- Access token management
- Automatic token refresh
- Token caching and expiration handling
"""

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlencode

import requests

_logger = logging.getLogger(__name__)


class SPAPIAuthError(Exception):
    """Base exception for SP-API authentication errors."""
    
    def __init__(self, message: str, error_code: str = None, response: dict = None):
        super().__init__(message)
        self.error_code = error_code
        self.response = response or {}


class LWATokenExpiredError(SPAPIAuthError):
    """Raised when the LWA token has expired and cannot be refreshed."""
    pass


class LWAClient:
    """
    Login with Amazon (LWA) OAuth 2.0 Client
    
    Handles OAuth 2.0 token management for Amazon SP-API including:
    - Access token retrieval using refresh token
    - Automatic token caching
    - Token expiration handling
    """
    
    LWA_ENDPOINT = "https://api.amazon.com/auth/o2/token"
    TOKEN_BUFFER_SECONDS = 60  # Refresh token 60 seconds before expiry
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        sandbox: bool = False
    ):
        """
        Initialize LWA Client.
        
        Args:
            client_id: LWA App Client ID
            client_secret: LWA App Client Secret
            refresh_token: LWA Refresh Token from Seller Central authorization
            sandbox: Use sandbox mode (affects token scope)
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.sandbox = sandbox
        
        # Token cache
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        
        # Session for connection pooling
        self._session = requests.Session()
        
    def get_access_token(self) -> str:
        """
        Get a valid access token, refreshing if necessary.
        
        Returns:
            Valid access token string
            
        Raises:
            SPAPIAuthError: If token retrieval fails
        """
        if self._is_token_valid():
            return self._access_token
            
        return self._refresh_access_token()
    
    def _is_token_valid(self) -> bool:
        """Check if the current cached token is still valid."""
        if not self._access_token or not self._token_expiry:
            return False
            
        # Add buffer to ensure token doesn't expire during request
        expiry_with_buffer = self._token_expiry - timedelta(seconds=self.TOKEN_BUFFER_SECONDS)
        return datetime.now(timezone.utc) < expiry_with_buffer
    
    def _refresh_access_token(self) -> str:
        """
        Refresh the access token using the refresh token.
        
        Returns:
            New access token
            
        Raises:
            SPAPIAuthError: If token refresh fails
        """
        _logger.debug("Refreshing LWA access token")
        
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        
        try:
            response = self._session.post(
                self.LWA_ENDPOINT,
                data=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self._access_token = token_data["access_token"]
                expires_in = token_data.get("expires_in", 3600)
                self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                
                _logger.debug(
                    "LWA token refreshed successfully, expires in %d seconds",
                    expires_in
                )
                return self._access_token
            else:
                error_data = response.json() if response.content else {}
                error_code = error_data.get("error", "unknown_error")
                error_desc = error_data.get("error_description", response.text)
                
                _logger.error(
                    "LWA token refresh failed: %s - %s",
                    error_code, error_desc
                )
                
                if error_code == "invalid_grant":
                    raise LWATokenExpiredError(
                        f"Refresh token is invalid or expired: {error_desc}",
                        error_code=error_code,
                        response=error_data
                    )
                    
                raise SPAPIAuthError(
                    f"Failed to refresh LWA token: {error_desc}",
                    error_code=error_code,
                    response=error_data
                )
                
        except requests.RequestException as e:
            _logger.error("LWA token refresh request failed: %s", str(e))
            raise SPAPIAuthError(f"Network error during token refresh: {str(e)}")
    
    def invalidate_token(self):
        """Invalidate the cached token, forcing a refresh on next request."""
        self._access_token = None
        self._token_expiry = None
        _logger.debug("LWA token cache invalidated")
    
    def close(self):
        """Close the underlying session."""
        self._session.close()


class AWSSigV4Auth:
    """
    AWS Signature Version 4 Request Signing
    
    Implements AWS Signature V4 for SP-API request authentication.
    SP-API uses a restricted variant of SigV4 that doesn't require
    actual AWS credentials - it uses the LWA access token instead.
    """
    
    ALGORITHM = "AWS4-HMAC-SHA256"
    SERVICE = "execute-api"
    
    def __init__(
        self,
        access_key: str = None,
        secret_key: str = None,
        region: str = "eu-west-1",
        service: str = "execute-api"
    ):
        """
        Initialize AWS SigV4 Auth.
        
        For SP-API, access_key and secret_key can be None as the
        signing is done differently (role assumption via STS).
        
        Args:
            access_key: AWS Access Key ID (or None for SP-API)
            secret_key: AWS Secret Access Key (or None for SP-API)
            region: AWS region (eu-west-1 for EU, us-east-1 for NA, etc.)
            service: AWS service name (execute-api for API Gateway)
        """
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.service = service
    
    def _sign(self, key: bytes, msg: str) -> bytes:
        """Create HMAC-SHA256 signature."""
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()
    
    def _get_signature_key(
        self,
        key: str,
        date_stamp: str,
        region_name: str,
        service_name: str
    ) -> bytes:
        """Derive the signing key."""
        k_date = self._sign(('AWS4' + key).encode('utf-8'), date_stamp)
        k_region = self._sign(k_date, region_name)
        k_service = self._sign(k_region, service_name)
        k_signing = self._sign(k_service, 'aws4_request')
        return k_signing
    
    def sign_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        payload: str = "",
        params: Dict[str, str] = None
    ) -> Dict[str, str]:
        """
        Sign a request using AWS Signature V4.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full request URL
            headers: Request headers (will be modified with auth headers)
            payload: Request body (empty string for GET)
            params: Query parameters
            
        Returns:
            Updated headers dict with Authorization header
        """
        if not self.access_key or not self.secret_key:
            _logger.debug("No AWS credentials provided, skipping SigV4 signing")
            return headers
            
        # Parse URL
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        host = parsed.netloc
        canonical_uri = parsed.path or '/'
        
        # Create timestamp
        t = datetime.now(timezone.utc)
        amz_date = t.strftime('%Y%m%dT%H%M%SZ')
        date_stamp = t.strftime('%Y%m%d')
        
        # Add required headers
        headers['host'] = host
        headers['x-amz-date'] = amz_date
        
        # Create canonical query string
        if params:
            canonical_querystring = urlencode(sorted(params.items()))
        else:
            canonical_querystring = ''
        
        # Create canonical headers
        signed_headers_list = sorted(headers.keys())
        canonical_headers = ''
        for key in signed_headers_list:
            canonical_headers += f"{key.lower()}:{headers[key].strip()}\n"
        signed_headers = ';'.join([k.lower() for k in signed_headers_list])
        
        # Create payload hash
        payload_hash = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        
        # Create canonical request
        canonical_request = '\n'.join([
            method.upper(),
            canonical_uri,
            canonical_querystring,
            canonical_headers,
            signed_headers,
            payload_hash
        ])
        
        # Create string to sign
        credential_scope = f"{date_stamp}/{self.region}/{self.service}/aws4_request"
        string_to_sign = '\n'.join([
            self.ALGORITHM,
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
        ])
        
        # Calculate signature
        signing_key = self._get_signature_key(
            self.secret_key, date_stamp, self.region, self.service
        )
        signature = hmac.new(
            signing_key, string_to_sign.encode('utf-8'), hashlib.sha256
        ).hexdigest()
        
        # Create authorization header
        authorization_header = (
            f"{self.ALGORITHM} "
            f"Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )
        
        headers['Authorization'] = authorization_header
        
        return headers


class SPAPIAuthenticator:
    """
    Complete SP-API Authentication Handler
    
    Combines LWA OAuth and AWS SigV4 signing for full SP-API authentication.
    """
    
    # Regional endpoints
    ENDPOINTS = {
        'na': {
            'region': 'us-east-1',
            'endpoint': 'https://sellingpartnerapi-na.amazon.com',
            'sandbox': 'https://sandbox.sellingpartnerapi-na.amazon.com'
        },
        'eu': {
            'region': 'eu-west-1',
            'endpoint': 'https://sellingpartnerapi-eu.amazon.com',
            'sandbox': 'https://sandbox.sellingpartnerapi-eu.amazon.com'
        },
        'fe': {
            'region': 'us-west-2',
            'endpoint': 'https://sellingpartnerapi-fe.amazon.com',
            'sandbox': 'https://sandbox.sellingpartnerapi-fe.amazon.com'
        }
    }
    
    # Marketplace to region mapping
    MARKETPLACE_REGIONS = {
        # North America
        'A2EUQ1WTGCTBG2': 'na',  # CA
        'ATVPDKIKX0DER': 'na',   # US
        'A1AM78C64UM0Y8': 'na',  # MX
        'A2Q3Y263D00KWC': 'na',  # BR
        
        # Europe
        'A1RKKUPIHCS9HS': 'eu',  # ES
        'A1F83G8C2ARO7P': 'eu',  # UK
        'A13V1IB3VIYZZH': 'eu',  # FR
        'A1PA6795UKMFR9': 'eu',  # DE
        'APJ6JRA9NG5V4': 'eu',   # IT
        'A1805IZSGTT6HS': 'eu',  # NL
        'A2NODRKZP88ZB9': 'eu',  # SE
        'A1C3SOZRARQ6R3': 'eu',  # PL
        'AMEN7PMS3EDWL': 'eu',   # BE
        'A33AVAJ2PDY3EV': 'eu',  # TR
        'A17E79C6D8DWNP': 'eu',  # SA
        'A2VIGQ35RCS4UG': 'eu',  # AE
        
        # Far East
        'A1VC38T7YXB528': 'fe',  # JP
        'A39IBJ37TRP1C6': 'fe',  # AU
        'A19VAU5U5O7RUS': 'fe',  # SG
        
        # India uses EU endpoint per Amazon documentation
        'A21TJRUUN4KGV': 'eu',   # IN
    }
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        aws_access_key: str = None,
        aws_secret_key: str = None,
        region: str = 'eu',
        marketplace_id: str = None,
        sandbox: bool = False
    ):
        """
        Initialize SP-API Authenticator.
        
        Args:
            client_id: LWA App Client ID
            client_secret: LWA App Client Secret
            refresh_token: LWA Refresh Token
            aws_access_key: AWS Access Key (optional for SP-API)
            aws_secret_key: AWS Secret Key (optional for SP-API)
            region: Region code (na, eu, fe) or auto-detect from marketplace_id
            marketplace_id: Amazon Marketplace ID (for auto-detecting region)
            sandbox: Use sandbox environment
        """
        # Determine region
        if marketplace_id and marketplace_id in self.MARKETPLACE_REGIONS:
            region = self.MARKETPLACE_REGIONS[marketplace_id]
        
        self.region = region
        self.sandbox = sandbox
        
        # Get endpoint config
        endpoint_config = self.ENDPOINTS.get(region, self.ENDPOINTS['eu'])
        self.aws_region = endpoint_config['region']
        self.endpoint = endpoint_config['sandbox'] if sandbox else endpoint_config['endpoint']
        
        # Initialize LWA client
        self.lwa_client = LWAClient(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            sandbox=sandbox
        )
        
        # Initialize SigV4 auth (optional, SP-API may not require it)
        self.sigv4_auth = AWSSigV4Auth(
            access_key=aws_access_key,
            secret_key=aws_secret_key,
            region=self.aws_region
        ) if aws_access_key and aws_secret_key else None
        
        _logger.info(
            "SP-API Authenticator initialized for region %s (%s mode)",
            region, "sandbox" if sandbox else "production"
        )
    
    def get_auth_headers(self) -> Dict[str, str]:
        """
        Get authentication headers for SP-API request.
        
        Returns:
            Dict with required auth headers
        """
        access_token = self.lwa_client.get_access_token()
        
        return {
            'x-amz-access-token': access_token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
    
    def sign_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        payload: str = "",
        params: Dict[str, str] = None
    ) -> Dict[str, str]:
        """
        Sign a request with AWS SigV4 if credentials are available.
        
        Args:
            method: HTTP method
            url: Full URL
            headers: Request headers
            payload: Request body
            params: Query parameters
            
        Returns:
            Signed headers
        """
        if self.sigv4_auth:
            return self.sigv4_auth.sign_request(method, url, headers, payload, params)
        return headers
    
    def get_endpoint(self) -> str:
        """Get the base API endpoint URL."""
        return self.endpoint
    
    def invalidate_token(self):
        """Invalidate the cached access token."""
        self.lwa_client.invalidate_token()
    
    def close(self):
        """Clean up resources."""
        self.lwa_client.close()
