# -*- coding: utf-8 -*-
"""
Amazon SP-API Sellers API Client

Handles:
- Marketplace participations
"""

import logging
from typing import Any, Dict

from .sp_api_client import SPAPIClient

_logger = logging.getLogger(__name__)


class SPAPISellers:
    """
    Amazon Sellers API Client

    Provides access to:
    - Marketplace participations
    """

    API_VERSION = "v1"

    def __init__(self, client: SPAPIClient):
        """
        Initialize Sellers API client.

        Args:
            client: Base SP-API client instance
        """
        self.client = client

    def get_marketplace_participations(self) -> Dict[str, Any]:
        """
        Returns a list of marketplaces that the seller can participate in.

        Returns:
            Marketplace participations
        """
        return self.client.get(
            f'/sellers/{self.API_VERSION}/marketplaceParticipations',
            operation='getMarketplaceParticipations',
        )
