# -*- coding: utf-8 -*-
"""
Amazon SP-API Tokens API Client

Handles:
- Restricted Data Token (RDT) generation
"""

import logging
from typing import Any, Dict, List, Optional

from .sp_api_client import SPAPIClient

_logger = logging.getLogger(__name__)


class SPAPITokens:
    """
    Amazon Tokens API Client

    Provides access to:
    - RDT generation for restricted operations
    """

    API_VERSION = "2021-03-01"

    def __init__(self, client: SPAPIClient):
        """
        Initialize Tokens API client.

        Args:
            client: Base SP-API client instance
        """
        self.client = client

    def create_restricted_data_token(
        self,
        restricted_resources: List[Dict[str, Any]],
        target_application: str = None,
    ) -> Dict[str, Any]:
        """
        Create a Restricted Data Token (RDT).

        Args:
            restricted_resources: List of resources to access
                [
                    {
                        "method": "GET",
                        "path": "/orders/v0/orders/{orderId}/address",
                        "dataElements": ["shippingAddress", "buyerInfo"]
                    }
                ]
            target_application: Target application ID (optional)

        Returns:
            RDT response containing restrictedDataToken and expiresIn
        """
        data = {
            'restrictedResources': restricted_resources,
        }

        if target_application:
            data['targetApplication'] = target_application

        # RDT request itself uses LWA token, so we use the standard client request
        # but we must ensure we don't try to use RDT for this request!
        return self.client.post(
            f'/tokens/{self.API_VERSION}/restrictedDataToken',
            operation='createRestrictedDataToken',
            data=data,
            add_marketplace=False,
        )
