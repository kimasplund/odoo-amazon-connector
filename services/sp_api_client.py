# -*- coding: utf-8 -*-
"""
Amazon SP-API Base Client

Core client with:
- OAuth 2.0 / LWA authentication integration
- Automatic token refresh
- Rate limiting with exponential backoff
- Request signing (AWS Signature v4)
- Error handling with specific Amazon error codes
- Sandbox/Production mode switching
- Proper logging
"""

import json
import logging
import random
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlencode, urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .sp_api_auth import SPAPIAuthenticator, SPAPIAuthError, LWATokenExpiredError

_logger = logging.getLogger(__name__)


# ============================================================================
# Exception Classes
# ============================================================================

class SPAPIError(Exception):
    """Base exception for SP-API errors."""
    
    def __init__(
        self,
        message: str,
        error_code: str = None,
        status_code: int = None,
        response: dict = None,
        request_id: str = None
    ):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code
        self.response = response or {}
        self.request_id = request_id
    
    def __str__(self):
        parts = [super().__str__()]
        if self.error_code:
            parts.append(f"[{self.error_code}]")
        if self.status_code:
            parts.append(f"(HTTP {self.status_code})")
        if self.request_id:
            parts.append(f"RequestId: {self.request_id}")
        return " ".join(parts)


class SPAPIRateLimitError(SPAPIError):
    """Raised when rate limit is exceeded (HTTP 429)."""
    
    def __init__(self, message: str, retry_after: int = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class SPAPIQuotaExceededError(SPAPIError):
    """Raised when quota is exceeded."""
    pass


class SPAPIAccessDeniedError(SPAPIError):
    """Raised when access is denied (HTTP 403)."""
    pass


class SPAPIInvalidInputError(SPAPIError):
    """Raised when request input is invalid (HTTP 400)."""
    pass


class SPAPIResourceNotFoundError(SPAPIError):
    """Raised when a resource is not found (HTTP 404)."""
    pass


class SPAPIServerError(SPAPIError):
    """Raised for server errors (HTTP 5xx)."""
    pass


class SPAPIThrottledError(SPAPIError):
    """Raised when the API is throttling requests."""
    pass


# Amazon-specific error codes
AMAZON_ERROR_CODES = {
    'InvalidInput': SPAPIInvalidInputError,
    'InvalidParameterValue': SPAPIInvalidInputError,
    'MissingParameter': SPAPIInvalidInputError,
    'AccessDenied': SPAPIAccessDeniedError,
    'Unauthorized': SPAPIAccessDeniedError,
    'ResourceNotFound': SPAPIResourceNotFoundError,
    'QuotaExceeded': SPAPIQuotaExceededError,
    'Throttled': SPAPIThrottledError,
    'InternalFailure': SPAPIServerError,
    'ServiceUnavailable': SPAPIServerError,
}


# ============================================================================
# Rate Limiter
# ============================================================================

class RateLimiter:
    """
    Token bucket rate limiter with per-operation tracking.
    
    Implements Amazon's rate limiting model with:
    - Per-operation rate limits
    - Burst capacity
    - Token replenishment
    """
    
    # Default rate limits per operation (requests per second)
    # These are conservative defaults; actual limits vary by API
    DEFAULT_LIMITS = {
        'default': {'rate': 1.0, 'burst': 5},
        'getOrders': {'rate': 0.0167, 'burst': 20},  # 1 per minute, burst 20
        'getOrder': {'rate': 0.5, 'burst': 30},
        'getOrderItems': {'rate': 0.5, 'burst': 30},
        'getListingsItem': {'rate': 5.0, 'burst': 10},
        'putListingsItem': {'rate': 5.0, 'burst': 10},
        'getInventorySummaries': {'rate': 2.0, 'burst': 2},
        'createFeedDocument': {'rate': 0.0083, 'burst': 15},  # 30 per hour
        'createFeed': {'rate': 0.0083, 'burst': 15},
        'getFeed': {'rate': 2.0, 'burst': 15},
        'getFeeds': {'rate': 0.0222, 'burst': 10},
        'createReport': {'rate': 0.0167, 'burst': 15},
        'getReport': {'rate': 2.0, 'burst': 15},
        'getReports': {'rate': 0.0222, 'burst': 10},
        'getReportDocument': {'rate': 0.0167, 'burst': 15},
        'getProductPricing': {'rate': 0.5, 'burst': 1},
        'getCompetitivePricing': {'rate': 0.5, 'burst': 1},
        'getItemOffers': {'rate': 0.5, 'burst': 1},
    }
    
    def __init__(self, limits: Dict[str, Dict[str, float]] = None):
        """
        Initialize rate limiter.
        
        Args:
            limits: Optional custom rate limits per operation
        """
        self.limits = {**self.DEFAULT_LIMITS, **(limits or {})}
        self.tokens = defaultdict(lambda: {'tokens': 5, 'last_update': time.time()})
        self._lock = None  # Will be set if threading is needed
    
    def _get_limit(self, operation: str) -> Dict[str, float]:
        """Get rate limit config for an operation."""
        return self.limits.get(operation, self.limits['default'])
    
    def _replenish_tokens(self, operation: str) -> float:
        """Replenish tokens based on time elapsed."""
        bucket = self.tokens[operation]
        limit = self._get_limit(operation)
        
        now = time.time()
        elapsed = now - bucket['last_update']
        bucket['last_update'] = now
        
        # Add tokens based on rate
        new_tokens = bucket['tokens'] + (elapsed * limit['rate'])
        bucket['tokens'] = min(new_tokens, limit['burst'])
        
        return bucket['tokens']
    
    def acquire(self, operation: str = 'default') -> float:
        """
        Acquire a rate limit token.
        
        Args:
            operation: The API operation name
            
        Returns:
            Wait time in seconds (0 if no wait needed)
        """
        tokens = self._replenish_tokens(operation)
        
        if tokens >= 1:
            self.tokens[operation]['tokens'] -= 1
            return 0.0
        
        # Calculate wait time
        limit = self._get_limit(operation)
        wait_time = (1 - tokens) / limit['rate']
        
        return wait_time
    
    def wait(self, operation: str = 'default') -> None:
        """
        Wait for rate limit if necessary.
        
        Args:
            operation: The API operation name
        """
        wait_time = self.acquire(operation)
        if wait_time > 0:
            _logger.debug(
                "Rate limiter: waiting %.2f seconds for operation %s",
                wait_time, operation
            )
            time.sleep(wait_time)
            # After waiting, consume the token
            self.tokens[operation]['tokens'] -= 1
    
    def update_from_headers(self, operation: str, headers: Dict[str, str]) -> None:
        """
        Update rate limits based on response headers.
        
        Amazon provides rate limit info in headers:
        - x-amzn-RateLimit-Limit
        
        Args:
            operation: The API operation name
            headers: Response headers
        """
        rate_limit = headers.get('x-amzn-RateLimit-Limit')
        if rate_limit:
            try:
                rate = float(rate_limit)
                if operation not in self.limits:
                    self.limits[operation] = {'rate': rate, 'burst': int(rate * 10)}
                else:
                    self.limits[operation]['rate'] = rate
                _logger.debug(
                    "Updated rate limit for %s: %.4f/s",
                    operation, rate
                )
            except ValueError:
                pass


# ============================================================================
# Retry Handler
# ============================================================================

class RetryHandler:
    """
    Exponential backoff retry handler with jitter.
    """
    
    def __init__(
        self,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_status_codes: Tuple[int, ...] = (429, 500, 502, 503, 504)
    ):
        """
        Initialize retry handler.
        
        Args:
            max_retries: Maximum number of retries
            base_delay: Initial delay in seconds
            max_delay: Maximum delay in seconds
            exponential_base: Base for exponential backoff
            jitter: Add random jitter to delays
            retryable_status_codes: HTTP status codes to retry
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_status_codes = retryable_status_codes
    
    def should_retry(self, status_code: int, retry_count: int) -> bool:
        """
        Determine if a request should be retried.
        
        Args:
            status_code: HTTP status code
            retry_count: Current retry count
            
        Returns:
            True if should retry
        """
        if retry_count >= self.max_retries:
            return False
        return status_code in self.retryable_status_codes
    
    def get_delay(self, retry_count: int, retry_after: int = None) -> float:
        """
        Calculate delay before next retry.
        
        Args:
            retry_count: Current retry count
            retry_after: Optional Retry-After header value
            
        Returns:
            Delay in seconds
        """
        if retry_after:
            return min(retry_after, self.max_delay)
        
        # Exponential backoff
        delay = self.base_delay * (self.exponential_base ** retry_count)
        delay = min(delay, self.max_delay)
        
        # Add jitter
        if self.jitter:
            delay = delay * (0.5 + random.random())
        
        return delay
    
    def wait(self, retry_count: int, retry_after: int = None) -> None:
        """
        Wait before retrying.
        
        Args:
            retry_count: Current retry count
            retry_after: Optional Retry-After header value
        """
        delay = self.get_delay(retry_count, retry_after)
        _logger.debug("Retry %d: waiting %.2f seconds", retry_count + 1, delay)
        time.sleep(delay)


# ============================================================================
# Base SP-API Client
# ============================================================================

class SPAPIClient:
    """
    Base SP-API Client
    
    Provides core functionality for all SP-API operations including:
    - Authentication with automatic token refresh
    - Rate limiting
    - Exponential backoff retry logic
    - Error handling
    - Request/Response logging
    """
    
    USER_AGENT = "OdooAmazonConnector/1.0 (Language=Python; Platform=Odoo18)"
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        aws_access_key: str = None,
        aws_secret_key: str = None,
        region: str = 'eu',
        marketplace_id: str = None,
        sandbox: bool = False,
        rate_limits: Dict[str, Dict[str, float]] = None,
        max_retries: int = 5,
        timeout: int = 30,
    ):
        """
        Initialize SP-API Client.
        
        Args:
            client_id: LWA App Client ID
            client_secret: LWA App Client Secret
            refresh_token: LWA Refresh Token
            aws_access_key: AWS Access Key (optional)
            aws_secret_key: AWS Secret Key (optional)
            region: Region code (na, eu, fe)
            marketplace_id: Amazon Marketplace ID
            sandbox: Use sandbox environment
            rate_limits: Custom rate limits per operation
            max_retries: Maximum retry attempts
            timeout: Request timeout in seconds
        """
        self.marketplace_id = marketplace_id
        self.sandbox = sandbox
        self.timeout = timeout
        
        # Initialize authenticator
        self.auth = SPAPIAuthenticator(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            aws_access_key=aws_access_key,
            aws_secret_key=aws_secret_key,
            region=region,
            marketplace_id=marketplace_id,
            sandbox=sandbox
        )
        
        # Initialize rate limiter and retry handler
        self.rate_limiter = RateLimiter(rate_limits)
        self.retry_handler = RetryHandler(max_retries=max_retries)
        
        # Initialize session with connection pooling
        self._session = self._create_session()
        
        _logger.info(
            "SP-API Client initialized for marketplace %s (%s mode)",
            marketplace_id or "default",
            "sandbox" if sandbox else "production"
        )
    
    def _create_session(self) -> requests.Session:
        """Create a requests session with retry configuration."""
        session = requests.Session()
        
        # Configure retry strategy for connection errors
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[],  # We handle status codes ourselves
            allowed_methods=["HEAD", "GET", "PUT", "POST", "DELETE", "PATCH"]
        )
        
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=10
        )
        
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        return session
    
    def _build_url(self, path: str) -> str:
        """Build full URL from path."""
        base = self.auth.get_endpoint()
        return urljoin(base + '/', path.lstrip('/'))
    
    def _parse_error_response(
        self,
        response: requests.Response
    ) -> Tuple[str, str, dict]:
        """
        Parse error response from Amazon.
        
        Returns:
            Tuple of (error_code, error_message, full_response)
        """
        try:
            data = response.json()
            
            # Handle various error response formats
            if 'errors' in data:
                errors = data['errors']
                if errors:
                    first_error = errors[0]
                    return (
                        first_error.get('code', 'UnknownError'),
                        first_error.get('message', 'Unknown error'),
                        data
                    )
            
            if 'error' in data:
                return (
                    data.get('error', 'UnknownError'),
                    data.get('error_description', data.get('message', 'Unknown error')),
                    data
                )
            
            return ('UnknownError', str(data), data)
            
        except (json.JSONDecodeError, KeyError):
            return ('ParseError', response.text[:500], {})
    
    def _raise_for_error(
        self,
        response: requests.Response,
        request_id: str = None
    ) -> None:
        """
        Raise appropriate exception based on response.
        
        Args:
            response: Response object
            request_id: Amazon request ID
        """
        error_code, error_message, error_data = self._parse_error_response(response)
        status_code = response.status_code
        
        # Build error kwargs
        error_kwargs = {
            'error_code': error_code,
            'status_code': status_code,
            'response': error_data,
            'request_id': request_id,
        }
        
        # Rate limiting
        if status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 1))
            raise SPAPIRateLimitError(
                f"Rate limit exceeded: {error_message}",
                retry_after=retry_after,
                **error_kwargs
            )
        
        # Access denied
        if status_code == 403:
            raise SPAPIAccessDeniedError(
                f"Access denied: {error_message}",
                **error_kwargs
            )
        
        # Bad request
        if status_code == 400:
            # Check for specific error codes
            exception_class = AMAZON_ERROR_CODES.get(error_code, SPAPIInvalidInputError)
            raise exception_class(error_message, **error_kwargs)
        
        # Not found
        if status_code == 404:
            raise SPAPIResourceNotFoundError(
                f"Resource not found: {error_message}",
                **error_kwargs
            )
        
        # Server errors
        if 500 <= status_code < 600:
            raise SPAPIServerError(
                f"Server error: {error_message}",
                **error_kwargs
            )
        
        # Check for specific Amazon error codes
        exception_class = AMAZON_ERROR_CODES.get(error_code, SPAPIError)
        raise exception_class(error_message, **error_kwargs)
    
    def request(
        self,
        method: str,
        path: str,
        operation: str = None,
        params: Dict[str, Any] = None,
        data: Dict[str, Any] = None,
        headers: Dict[str, str] = None,
        add_marketplace: bool = True,
        raw_response: bool = False,
    ) -> Union[Dict[str, Any], requests.Response]:
        """
        Make an authenticated request to SP-API.
        
        Args:
            method: HTTP method
            path: API path (e.g., '/orders/v0/orders')
            operation: Operation name for rate limiting
            params: Query parameters
            data: Request body (will be JSON-encoded)
            headers: Additional headers
            add_marketplace: Add marketplace_id to params if not present
            raw_response: Return raw Response object
            
        Returns:
            Parsed JSON response or raw Response object
            
        Raises:
            SPAPIError: On API errors
        """
        operation = operation or path.split('/')[-1]
        url = self._build_url(path)
        
        # Prepare params
        params = dict(params or {})
        if add_marketplace and self.marketplace_id and 'marketplaceIds' not in params:
            params['marketplaceIds'] = self.marketplace_id
        
        # Prepare headers
        req_headers = {
            'User-Agent': self.USER_AGENT,
        }
        req_headers.update(self.auth.get_auth_headers())
        if headers:
            req_headers.update(headers)
        
        # Prepare body
        body = json.dumps(data) if data else ""
        if data:
            req_headers['Content-Type'] = 'application/json'
        
        # Rate limit
        self.rate_limiter.wait(operation)
        
        # Execute with retry
        retry_count = 0
        last_error = None
        
        while True:
            try:
                _logger.debug(
                    "SP-API Request: %s %s (params=%s)",
                    method.upper(), url, params
                )
                
                response = self._session.request(
                    method=method,
                    url=url,
                    params=params if params else None,
                    data=body if body else None,
                    headers=req_headers,
                    timeout=self.timeout,
                )
                
                # Get request ID for logging
                request_id = response.headers.get('x-amz-RequestId', 'N/A')
                
                _logger.debug(
                    "SP-API Response: HTTP %d (RequestId: %s)",
                    response.status_code, request_id
                )
                
                # Update rate limits from headers
                self.rate_limiter.update_from_headers(operation, response.headers)
                
                # Check for success
                if response.status_code in (200, 201, 202, 204):
                    if raw_response:
                        return response
                    if response.status_code == 204 or not response.content:
                        return {}
                    return response.json()
                
                # Check if retryable
                if self.retry_handler.should_retry(response.status_code, retry_count):
                    retry_after = None
                    if response.status_code == 429:
                        retry_after = int(response.headers.get('Retry-After', 1))
                    
                    _logger.warning(
                        "SP-API request failed (HTTP %d), retrying... (attempt %d/%d, RequestId: %s)",
                        response.status_code,
                        retry_count + 1,
                        self.retry_handler.max_retries,
                        request_id
                    )
                    
                    self.retry_handler.wait(retry_count, retry_after)
                    retry_count += 1
                    continue
                
                # Not retryable, raise error
                self._raise_for_error(response, request_id)
                
            except requests.RequestException as e:
                _logger.error("SP-API network error: %s", str(e))
                
                if retry_count < self.retry_handler.max_retries:
                    _logger.warning(
                        "Retrying after network error (attempt %d/%d)",
                        retry_count + 1,
                        self.retry_handler.max_retries
                    )
                    self.retry_handler.wait(retry_count)
                    retry_count += 1
                    continue
                
                raise SPAPIError(f"Network error: {str(e)}")
            
            except SPAPIAuthError:
                # Auth errors shouldn't be retried normally, but we can try
                # invalidating the token once
                if retry_count == 0:
                    _logger.warning("Auth error, invalidating token and retrying")
                    self.auth.invalidate_token()
                    req_headers.update(self.auth.get_auth_headers())
                    retry_count += 1
                    continue
                raise
    
    def get(
        self,
        path: str,
        operation: str = None,
        params: Dict[str, Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Make GET request."""
        return self.request('GET', path, operation, params=params, **kwargs)
    
    def post(
        self,
        path: str,
        operation: str = None,
        data: Dict[str, Any] = None,
        params: Dict[str, Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Make POST request."""
        return self.request('POST', path, operation, params=params, data=data, **kwargs)
    
    def put(
        self,
        path: str,
        operation: str = None,
        data: Dict[str, Any] = None,
        params: Dict[str, Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Make PUT request."""
        return self.request('PUT', path, operation, params=params, data=data, **kwargs)
    
    def patch(
        self,
        path: str,
        operation: str = None,
        data: Dict[str, Any] = None,
        params: Dict[str, Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Make PATCH request."""
        return self.request('PATCH', path, operation, params=params, data=data, **kwargs)
    
    def delete(
        self,
        path: str,
        operation: str = None,
        params: Dict[str, Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Make DELETE request."""
        return self.request('DELETE', path, operation, params=params, **kwargs)
    
    def paginate(
        self,
        method: str,
        path: str,
        operation: str = None,
        params: Dict[str, Any] = None,
        data: Dict[str, Any] = None,
        result_key: str = None,
        next_token_key: str = 'nextToken',
        max_pages: int = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Paginate through API results.
        
        Args:
            method: HTTP method
            path: API path
            operation: Operation name for rate limiting
            params: Query parameters
            data: Request body
            result_key: Key in response containing results
            next_token_key: Key for pagination token
            max_pages: Maximum pages to fetch (None for all)
            
        Returns:
            List of all results
        """
        params = dict(params or {})
        all_results = []
        page_count = 0
        
        while True:
            response = self.request(
                method, path, operation, params=params, data=data, **kwargs
            )
            
            # Extract results
            if result_key and result_key in response:
                results = response[result_key]
                if isinstance(results, list):
                    all_results.extend(results)
                else:
                    all_results.append(results)
            else:
                all_results.append(response)
            
            page_count += 1
            
            # Check for next page
            next_token = response.get(next_token_key)
            if not next_token:
                # Also check in nested 'payload'
                payload = response.get('payload', {})
                next_token = payload.get(next_token_key)
            
            if not next_token:
                break
            
            if max_pages and page_count >= max_pages:
                _logger.info("Reached max pages limit (%d)", max_pages)
                break
            
            params[next_token_key] = next_token
            _logger.debug("Fetching page %d (nextToken: %s...)", page_count + 1, next_token[:20])
        
        _logger.info("Pagination complete: %d pages, %d results", page_count, len(all_results))
        return all_results
    
    def close(self):
        """Clean up resources."""
        self._session.close()
        self.auth.close()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


# ============================================================================
# Odoo Integration Helper
# ============================================================================

class OdooSPAPIClient(SPAPIClient):
    """
    SP-API Client with Odoo-specific integrations.
    
    Extends the base client with:
    - Odoo model integration
    - Credential loading from Odoo records
    - Error logging to Odoo
    """
    
    @classmethod
    def from_credential_record(cls, credential, sandbox: bool = None):
        """
        Create client from Odoo amazon.credential record.
        
        Args:
            credential: amazon.credential record
            sandbox: Override sandbox setting (None to use credential setting)
            
        Returns:
            OdooSPAPIClient instance
        """
        if sandbox is None:
            sandbox = credential.sandbox_mode
        
        return cls(
            client_id=credential.client_id,
            client_secret=credential.client_secret,
            refresh_token=credential.refresh_token,
            aws_access_key=credential.aws_access_key or None,
            aws_secret_key=credential.aws_secret_key or None,
            region=credential.region or 'eu',
            marketplace_id=credential.marketplace_id.marketplace_id if credential.marketplace_id else None,
            sandbox=sandbox,
        )
    
    def log_api_call(
        self,
        env,
        operation: str,
        success: bool,
        request_data: dict = None,
        response_data: dict = None,
        error_message: str = None
    ):
        """
        Log API call to Odoo for debugging/audit.
        
        Args:
            env: Odoo environment
            operation: API operation name
            success: Whether call succeeded
            request_data: Request data (sanitized)
            response_data: Response data
            error_message: Error message if failed
        """
        try:
            if 'amazon.api.log' in env:
                env['amazon.api.log'].sudo().create({
                    'operation': operation,
                    'success': success,
                    'request_data': json.dumps(request_data or {}, default=str)[:10000],
                    'response_data': json.dumps(response_data or {}, default=str)[:10000],
                    'error_message': error_message,
                    'timestamp': datetime.now(timezone.utc),
                })
        except Exception as e:
            _logger.warning("Failed to log API call: %s", str(e))
