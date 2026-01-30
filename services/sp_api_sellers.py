# -*- coding: utf-8 -*-
"""
Amazon SP-API Sellers API Client

Handles:
- Marketplace participations
"""

import logging
from typing import Any, Dict, List, Optional, TypedDict, cast

from .sp_api_client import SPAPIClient

_logger = logging.getLogger(__name__)


class Marketplace(TypedDict):
    id: str
    name: str
    countryCode: str
    defaultCurrencyCode: str
    defaultLanguageCode: str
    domainName: str


class Participation(TypedDict):
    isParticipating: bool
    hasSuspendedListings: bool


class MarketplaceParticipation(TypedDict):
    marketplace: Marketplace
    participation: Participation


class GetMarketplaceParticipationsPayload(TypedDict):
    payload: List[MarketplaceParticipation]


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

    def get_marketplace_participations(self) -> GetMarketplaceParticipationsPayload:
        """
        Returns a list of marketplaces that the seller can participate in.

        Returns:
            Marketplace participations
        """
        return cast(GetMarketplaceParticipationsPayload, self.client.get(
            f'/sellers/{self.API_VERSION}/marketplaceParticipations',
            operation='getMarketplaceParticipations',
        ))
