# -*- coding: utf-8 -*-
"""
Amazon SP-API Products/Listings/Catalog API Client

Handles:
- Product catalog operations
- Listings management (Listings Items API)
- Product search and lookup
- Pricing information
- Competitive pricing
- Product fees
"""

import logging
from typing import Any, Dict, List, Optional, Union, TypedDict
from enum import Enum

from .sp_api_client import SPAPIClient, SPAPIError

_logger = logging.getLogger(__name__)


class IncludedData(str, Enum):
    """Included data options for catalog items."""
    ATTRIBUTES = "attributes"
    DIMENSIONS = "dimensions"
    IDENTIFIERS = "identifiers"
    IMAGES = "images"
    PRODUCT_TYPES = "productTypes"
    RELATIONSHIPS = "relationships"
    SALES_RANKS = "salesRanks"
    SUMMARIES = "summaries"
    VENDOR_DETAILS = "vendorDetails"


class ItemCondition(str, Enum):
    """Product condition."""
    NEW = "New"
    USED_LIKE_NEW = "UsedLikeNew"
    USED_VERY_GOOD = "UsedVeryGood"
    USED_GOOD = "UsedGood"
    USED_ACCEPTABLE = "UsedAcceptable"
    COLLECTIBLE_LIKE_NEW = "CollectibleLikeNew"
    COLLECTIBLE_VERY_GOOD = "CollectibleVeryGood"
    COLLECTIBLE_GOOD = "CollectibleGood"
    COLLECTIBLE_ACCEPTABLE = "CollectibleAcceptable"
    REFURBISHED = "Refurbished"
    CLUB = "Club"


class IssueLocale(str, Enum):
    """Locale for listing issues."""
    DE_DE = "de_DE"
    EN_US = "en_US"
    EN_GB = "en_GB"
    ES_ES = "es_ES"
    FR_FR = "fr_FR"
    IT_IT = "it_IT"
    NL_NL = "nl_NL"
    PL_PL = "pl_PL"
    PT_BR = "pt_BR"
    SV_SE = "sv_SE"
    JA_JP = "ja_JP"
    ZH_CN = "zh_CN"


# ============================================================================
# TypedDicts
# ============================================================================

class CatalogItem(TypedDict, total=False):
    asin: str
    attributes: Dict[str, Any]
    identifiers: List[Dict[str, Any]]
    images: List[Dict[str, Any]]
    productTypes: List[Dict[str, Any]]
    relationships: List[Dict[str, Any]]
    salesRanks: List[Dict[str, Any]]
    summaries: List[Dict[str, Any]]
    vendorDetails: List[Dict[str, Any]]


class FeesEstimateRequest(TypedDict, total=False):
    MarketplaceId: str
    IsAmazonFulfilled: bool
    PriceToEstimateFees: Dict[str, Dict[str, Any]]
    Identifier: str
    OptionalFulfillmentProgram: str


# ============================================================================
# SPAPIProducts Class
# ============================================================================

class SPAPIProducts:
    """
    Amazon Products/Catalog/Listings API Client
    
    Provides access to:
    - Catalog Items API (product search, ASIN lookup)
    - Listings Items API (create/update/delete listings)
    - Product Pricing API (prices, competitive pricing)
    - Product Fees API (fee estimates)
    """
    
    # API versions
    CATALOG_API_VERSION = "2022-04-01"
    LISTINGS_API_VERSION = "2021-08-01"
    PRICING_API_VERSION = "2022-05-01"
    FEES_API_VERSION = "v0"
    
    def __init__(self, client: SPAPIClient):
        """
        Initialize Products API client.
        
        Args:
            client: Base SP-API client instance
        """
        self.client = client
    
    # =========================================================================
    # Catalog Items API
    # =========================================================================
    
    def search_catalog_items(
        self,
        keywords: Optional[List[str]] = None,
        brand_names: Optional[List[str]] = None,
        classification_ids: Optional[List[str]] = None,
        identifiers: Optional[List[str]] = None,
        identifiers_type: Optional[str] = None,
        included_data: Optional[List[Union[str, IncludedData]]] = None,
        locale: Optional[str] = None,
        seller_id: Optional[str] = None,
        page_size: int = 20,
        page_token: Optional[str] = None,
        keywords_locale: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Search the Amazon catalog for items.
        
        Args:
            keywords: Search keywords
            brand_names: Filter by brand names
            classification_ids: Filter by classification/category IDs
            identifiers: Product identifiers (ASIN, EAN, UPC, etc.)
            identifiers_type: Type of identifiers (ASIN, EAN, GTIN, UPC, SKU)
            included_data: Data to include in response
            locale: Locale for product data
            seller_id: Seller ID for getting seller-specific data
            page_size: Number of results per page (max 20)
            page_token: Pagination token
            keywords_locale: Locale of the keywords
            
        Returns:
            Catalog search results
        """
        params: Dict[str, Any] = {
            'pageSize': min(page_size, 20),
        }
        
        if keywords:
            params['keywords'] = ','.join(keywords) if isinstance(keywords, list) else keywords
        if brand_names:
            params['brandNames'] = ','.join(brand_names)
        if classification_ids:
            params['classificationIds'] = ','.join(classification_ids)
        if identifiers:
            params['identifiers'] = ','.join(identifiers)
        if identifiers_type:
            params['identifiersType'] = identifiers_type
        if included_data:
            data_list = [d.value if isinstance(d, IncludedData) else d for d in included_data]
            params['includedData'] = ','.join(data_list)
        if locale:
            params['locale'] = locale
        if seller_id:
            params['sellerId'] = seller_id
        if page_token:
            params['pageToken'] = page_token
        if keywords_locale:
            params['keywordsLocale'] = keywords_locale
        
        return self.client.get(
            f'/catalog/{self.CATALOG_API_VERSION}/items',
            operation='searchCatalogItems',
            params=params,
        )
    
    def get_catalog_item(
        self,
        asin: str,
        included_data: Optional[List[Union[str, IncludedData]]] = None,
        locale: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get catalog item details by ASIN.
        
        Args:
            asin: Amazon Standard Identification Number
            included_data: Data to include in response
            locale: Locale for product data
            
        Returns:
            Catalog item details
        """
        params: Dict[str, Any] = {}
        
        if included_data:
            data_list = [d.value if isinstance(d, IncludedData) else d for d in included_data]
            params['includedData'] = ','.join(data_list)
        if locale:
            params['locale'] = locale
        
        return self.client.get(
            f'/catalog/{self.CATALOG_API_VERSION}/items/{asin}',
            operation='getCatalogItem',
            params=params,
        )
    
    def search_catalog_items_all(
        self,
        keywords: Optional[List[str]] = None,
        max_pages: Optional[int] = None,
        **kwargs: Any
    ) -> List[CatalogItem]:
        """
        Search catalog items with automatic pagination.
        
        Args:
            keywords: Search keywords
            max_pages: Maximum pages to fetch
            **kwargs: Additional arguments for search_catalog_items
            
        Returns:
            List of all catalog items found
        """
        all_items: List[CatalogItem] = []
        page_token: Optional[str] = None
        page_count = 0
        
        while True:
            response = self.search_catalog_items(
                keywords=keywords,
                page_token=page_token,
                **kwargs
            )
            
            items = response.get('items', [])
            all_items.extend(items)
            
            page_count += 1
            
            # Get next page token
            pagination = response.get('pagination', {})
            page_token = pagination.get('nextToken')
            
            if not page_token:
                break
            
            if max_pages and page_count >= max_pages:
                _logger.info("Reached max pages limit (%d)", max_pages)
                break
        
        return all_items
    
    # =========================================================================
    # Listings Items API
    # =========================================================================
    
    def get_listings_item(
        self,
        seller_id: str,
        sku: str,
        included_data: Optional[List[str]] = None,
        issue_locale: Union[str, IssueLocale, None] = None,
    ) -> Dict[str, Any]:
        """
        Get a listing item by SKU.
        
        Args:
            seller_id: Amazon Seller ID
            sku: Seller SKU
            included_data: Data to include (summaries, attributes, issues, etc.)
            issue_locale: Locale for issues
            
        Returns:
            Listing item details
        """
        params: Dict[str, Any] = {}
        
        if included_data:
            params['includedData'] = ','.join(included_data)
        if issue_locale:
            locale = issue_locale.value if isinstance(issue_locale, IssueLocale) else issue_locale
            params['issueLocale'] = locale
        
        # SKU must be URL-encoded
        import urllib.parse
        encoded_sku = urllib.parse.quote(sku, safe='')
        
        return self.client.get(
            f'/listings/{self.LISTINGS_API_VERSION}/items/{seller_id}/{encoded_sku}',
            operation='getListingsItem',
            params=params,
        )
    
    def put_listings_item(
        self,
        seller_id: str,
        sku: str,
        product_type: str,
        attributes: Dict[str, Any],
        requirements: str = "LISTING",
        issue_locale: Union[str, IssueLocale, None] = None,
    ) -> Dict[str, Any]:
        """
        Create or update a listing item.
        
        Args:
            seller_id: Amazon Seller ID
            sku: Seller SKU
            product_type: Amazon product type
            attributes: Product attributes
            requirements: Listing requirements (LISTING, LISTING_PRODUCT_ONLY, LISTING_OFFER_ONLY)
            issue_locale: Locale for issues
            
        Returns:
            Listing submission result
        """
        params: Dict[str, Any] = {}
        if issue_locale:
            locale = issue_locale.value if isinstance(issue_locale, IssueLocale) else issue_locale
            params['issueLocale'] = locale
        
        import urllib.parse
        encoded_sku = urllib.parse.quote(sku, safe='')
        
        data = {
            'productType': product_type,
            'requirements': requirements,
            'attributes': attributes,
        }
        
        return self.client.put(
            f'/listings/{self.LISTINGS_API_VERSION}/items/{seller_id}/{encoded_sku}',
            operation='putListingsItem',
            params=params,
            data=data,
        )
    
    def patch_listings_item(
        self,
        seller_id: str,
        sku: str,
        product_type: str,
        patches: List[Dict[str, Any]],
        issue_locale: Union[str, IssueLocale, None] = None,
    ) -> Dict[str, Any]:
        """
        Partially update a listing item.
        
        Args:
            seller_id: Amazon Seller ID
            sku: Seller SKU
            product_type: Amazon product type
            patches: List of JSON Patch operations
            issue_locale: Locale for issues
            
        Returns:
            Patch result
        """
        params: Dict[str, Any] = {}
        if issue_locale:
            locale = issue_locale.value if isinstance(issue_locale, IssueLocale) else issue_locale
            params['issueLocale'] = locale
        
        import urllib.parse
        encoded_sku = urllib.parse.quote(sku, safe='')
        
        data = {
            'productType': product_type,
            'patches': patches,
        }
        
        return self.client.patch(
            f'/listings/{self.LISTINGS_API_VERSION}/items/{seller_id}/{encoded_sku}',
            operation='patchListingsItem',
            params=params,
            data=data,
        )
    
    def delete_listings_item(
        self,
        seller_id: str,
        sku: str,
        issue_locale: Union[str, IssueLocale, None] = None,
    ) -> Dict[str, Any]:
        """
        Delete a listing item.
        
        Args:
            seller_id: Amazon Seller ID
            sku: Seller SKU
            issue_locale: Locale for issues
            
        Returns:
            Deletion result
        """
        params: Dict[str, Any] = {}
        if issue_locale:
            locale = issue_locale.value if isinstance(issue_locale, IssueLocale) else issue_locale
            params['issueLocale'] = locale
        
        import urllib.parse
        encoded_sku = urllib.parse.quote(sku, safe='')
        
        return self.client.delete(
            f'/listings/{self.LISTINGS_API_VERSION}/items/{seller_id}/{encoded_sku}',
            operation='deleteListingsItem',
            params=params,
        )
    
    # =========================================================================
    # Product Pricing API
    # =========================================================================
    
    def get_pricing(
        self,
        item_type: str = "Asin",
        asins: Optional[List[str]] = None,
        skus: Optional[List[str]] = None,
        item_condition: Union[str, ItemCondition, None] = None,
        offer_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get pricing information for products.
        
        Args:
            item_type: Item type (Asin or Sku)
            asins: List of ASINs (if item_type is Asin)
            skus: List of SKUs (if item_type is Sku)
            item_condition: Product condition filter
            offer_type: Offer type (B2C, B2B)
            
        Returns:
            Pricing information
        """
        params: Dict[str, Any] = {
            'ItemType': item_type,
            'MarketplaceId': self.client.marketplace_id,
        }
        
        if item_type == "Asin" and asins:
            params['Asins'] = ','.join(asins[:20])  # Max 20 ASINs
        elif item_type == "Sku" and skus:
            params['Skus'] = ','.join(skus[:20])  # Max 20 SKUs
        
        if item_condition:
            condition = item_condition.value if isinstance(item_condition, ItemCondition) else item_condition
            params['ItemCondition'] = condition
        if offer_type:
            params['OfferType'] = offer_type
        
        return self.client.get(
            '/products/pricing/v0/price',
            operation='getPricing',
            params=params,
            add_marketplace=False,
        )
    
    def get_competitive_pricing(
        self,
        item_type: str = "Asin",
        asins: Optional[List[str]] = None,
        skus: Optional[List[str]] = None,
        customer_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get competitive pricing for products.
        
        Args:
            item_type: Item type (Asin or Sku)
            asins: List of ASINs
            skus: List of SKUs
            customer_type: Customer type (Consumer, Business)
            
        Returns:
            Competitive pricing information
        """
        params: Dict[str, Any] = {
            'ItemType': item_type,
            'MarketplaceId': self.client.marketplace_id,
        }
        
        if item_type == "Asin" and asins:
            params['Asins'] = ','.join(asins[:20])
        elif item_type == "Sku" and skus:
            params['Skus'] = ','.join(skus[:20])
        
        if customer_type:
            params['CustomerType'] = customer_type
        
        return self.client.get(
            '/products/pricing/v0/competitivePrice',
            operation='getCompetitivePricing',
            params=params,
            add_marketplace=False,
        )
    
    def get_item_offers(
        self,
        asin: str,
        item_condition: Union[str, ItemCondition] = ItemCondition.NEW,
        customer_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get offers for a specific ASIN.
        
        Args:
            asin: Amazon ASIN
            item_condition: Product condition
            customer_type: Customer type (Consumer, Business)
            
        Returns:
            Item offers with Buy Box information
        """
        condition = item_condition.value if isinstance(item_condition, ItemCondition) else item_condition
        
        params: Dict[str, Any] = {
            'ItemCondition': condition,
        }
        
        if customer_type:
            params['CustomerType'] = customer_type
        
        return self.client.get(
            f'/products/pricing/v0/items/{asin}/offers',
            operation='getItemOffers',
            params=params,
        )
    
    def get_listing_offers(
        self,
        seller_sku: str,
        item_condition: Union[str, ItemCondition] = ItemCondition.NEW,
        customer_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get offers for a specific SKU.
        
        Args:
            seller_sku: Seller SKU
            item_condition: Product condition
            customer_type: Customer type (Consumer, Business)
            
        Returns:
            Listing offers
        """
        import urllib.parse
        encoded_sku = urllib.parse.quote(seller_sku, safe='')
        
        condition = item_condition.value if isinstance(item_condition, ItemCondition) else item_condition
        
        params: Dict[str, Any] = {
            'ItemCondition': condition,
        }
        
        if customer_type:
            params['CustomerType'] = customer_type
        
        return self.client.get(
            f'/products/pricing/v0/listings/{encoded_sku}/offers',
            operation='getListingOffers',
            params=params,
        )
    
    # =========================================================================
    # Batched Pricing Operations (2022-05-01)
    # =========================================================================
    
    def get_item_offers_batch(
        self,
        requests: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Get item offers for multiple ASINs in a single batch request.
        
        Args:
            requests: List of request objects with uri, method, body
            
        Returns:
            Batch response with offers
        """
        data = {
            'requests': requests
        }
        
        return self.client.post(
            f'/batches/products/pricing/{self.PRICING_API_VERSION}/itemOffers',
            operation='getItemOffersBatch',
            data=data,
            add_marketplace=False,
        )
    
    def get_listing_offers_batch(
        self,
        requests: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Get listing offers for multiple SKUs in a single batch request.
        
        Args:
            requests: List of request objects
            
        Returns:
            Batch response with offers
        """
        data = {
            'requests': requests
        }
        
        return self.client.post(
            f'/batches/products/pricing/{self.PRICING_API_VERSION}/listingOffers',
            operation='getListingOffersBatch',
            data=data,
            add_marketplace=False,
        )
    
    # =========================================================================
    # Product Fees API
    # =========================================================================
    
    def get_my_fees_estimate_for_sku(
        self,
        seller_sku: str,
        price: float,
        currency_code: str = "EUR",
        shipping: float = 0,
        is_fba: bool = True,
        identifier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get fee estimate for a SKU.
        
        Args:
            seller_sku: Seller SKU
            price: Listing price
            currency_code: Currency code (EUR, USD, etc.)
            shipping: Shipping price
            is_fba: Whether using FBA
            identifier: Request identifier
            
        Returns:
            Fee estimate details
        """
        import urllib.parse
        encoded_sku = urllib.parse.quote(seller_sku, safe='')
        
        data: Dict[str, Any] = {
            'FeesEstimateRequest': {
                'MarketplaceId': self.client.marketplace_id,
                'IsAmazonFulfilled': is_fba,
                'PriceToEstimateFees': {
                    'ListingPrice': {
                        'CurrencyCode': currency_code,
                        'Amount': price,
                    },
                    'Shipping': {
                        'CurrencyCode': currency_code,
                        'Amount': shipping,
                    },
                },
                'Identifier': identifier or seller_sku,
            }
        }
        
        return self.client.post(
            f'/products/fees/{self.FEES_API_VERSION}/listings/{encoded_sku}/feesEstimate',
            operation='getMyFeesEstimateForSKU',
            data=data,
            add_marketplace=False,
        )
    
    def get_my_fees_estimate_for_asin(
        self,
        asin: str,
        price: float,
        currency_code: str = "EUR",
        shipping: float = 0,
        is_fba: bool = True,
        identifier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get fee estimate for an ASIN.
        
        Args:
            asin: Amazon ASIN
            price: Listing price
            currency_code: Currency code
            shipping: Shipping price
            is_fba: Whether using FBA
            identifier: Request identifier
            
        Returns:
            Fee estimate details
        """
        data: Dict[str, Any] = {
            'FeesEstimateRequest': {
                'MarketplaceId': self.client.marketplace_id,
                'IsAmazonFulfilled': is_fba,
                'PriceToEstimateFees': {
                    'ListingPrice': {
                        'CurrencyCode': currency_code,
                        'Amount': price,
                    },
                    'Shipping': {
                        'CurrencyCode': currency_code,
                        'Amount': shipping,
                    },
                },
                'Identifier': identifier or asin,
            }
        }
        
        return self.client.post(
            f'/products/fees/{self.FEES_API_VERSION}/items/{asin}/feesEstimate',
            operation='getMyFeesEstimateForASIN',
            data=data,
            add_marketplace=False,
        )
    
    def get_my_fees_estimates(
        self,
        fee_requests: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Get fee estimates for multiple items in a batch.
        
        Args:
            fee_requests: List of fee estimate requests
            
        Returns:
            Batch fee estimates
        """
        return self.client.post(
            f'/products/fees/{self.FEES_API_VERSION}/feesEstimate',
            operation='getMyFeesEstimates',
            data=fee_requests,  # type: ignore
            add_marketplace=False,
        )
    
    # =========================================================================
    # Product Type Definitions API
    # =========================================================================
    
    def search_definitions_product_types(
        self,
        keywords: Optional[List[str]] = None,
        item_name: Optional[str] = None,
        locale: str = "en_US",
        search_locale: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Search for product type definitions.
        
        Args:
            keywords: Search keywords
            item_name: Item name to match
            locale: Locale for results
            search_locale: Locale for search
            
        Returns:
            Matching product types
        """
        params: Dict[str, Any] = {
            'locale': locale,
        }
        
        if keywords:
            params['keywords'] = ','.join(keywords) if isinstance(keywords, list) else keywords
        if item_name:
            params['itemName'] = item_name
        if search_locale:
            params['searchLocale'] = search_locale
        
        return self.client.get(
            '/definitions/2020-09-01/productTypes',
            operation='searchDefinitionsProductTypes',
            params=params,
        )
    
    def get_definitions_product_type(
        self,
        product_type: str,
        requirements: str = "LISTING",
        requirements_enforced: str = "ENFORCED",
        locale: str = "en_US",
        seller_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get product type definition with JSON schema.
        
        Args:
            product_type: Product type name
            requirements: Requirements level (LISTING, LISTING_PRODUCT_ONLY, LISTING_OFFER_ONLY)
            requirements_enforced: Enforcement level (ENFORCED, NOT_ENFORCED)
            locale: Locale for results
            seller_id: Seller ID for seller-specific requirements
            
        Returns:
            Product type definition with JSON schema
        """
        params = {
            'requirements': requirements,
            'requirementsEnforced': requirements_enforced,
            'locale': locale,
        }
        
        if seller_id:
            params['sellerId'] = seller_id
        
        return self.client.get(
            f'/definitions/2020-09-01/productTypes/{product_type}',
            operation='getDefinitionsProductType',
            params=params,
        )
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def build_listing_attributes(
        self,
        title: str,
        description: Optional[str] = None,
        bullet_points: Optional[List[str]] = None,
        brand: Optional[str] = None,
        manufacturer: Optional[str] = None,
        price: Optional[float] = None,
        currency_code: str = "EUR",
        quantity: Optional[int] = None,
        condition: str = "new_new",
        fulfillment_channel: str = "DEFAULT",
        main_image_url: Optional[str] = None,
        other_image_urls: Optional[List[str]] = None,
        item_package_quantity: Optional[int] = None,
        number_of_items: Optional[int] = None,
        **extra_attributes: Any
    ) -> Dict[str, Any]:
        """
        Build listing attributes dictionary for create/update operations.
        
        This helper constructs the attributes in Amazon's expected format.
        All values should be wrapped in marketplace-keyed arrays.
        
        Args:
            title: Product title
            description: Product description
            bullet_points: List of bullet points
            brand: Brand name
            manufacturer: Manufacturer name
            price: Listing price
            currency_code: Currency code
            quantity: Available quantity
            condition: Product condition
            fulfillment_channel: Fulfillment channel
            main_image_url: Main product image URL
            other_image_urls: Additional image URLs
            item_package_quantity: Items per package
            number_of_items: Number of items
            **extra_attributes: Additional attributes
            
        Returns:
            Attributes dictionary
        """
        marketplace_id = self.client.marketplace_id
        
        def wrap_value(value: Any) -> List[Dict[str, Any]]:
            """Wrap value in marketplace array format."""
            return [{"value": value, "marketplace_id": marketplace_id}]
        
        def wrap_price(amount: float, currency: str) -> List[Dict[str, Any]]:
            """Wrap price value."""
            return [{
                "value": amount,
                "currency": currency,
                "marketplace_id": marketplace_id
            }]
        
        attributes: Dict[str, Any] = {}
        
        # Required attributes
        if title:
            attributes['item_name'] = wrap_value(title)
        
        # Optional attributes
        if description:
            attributes['product_description'] = wrap_value(description)
        
        if bullet_points:
            attributes['bullet_point'] = [
                {"value": bp, "marketplace_id": marketplace_id}
                for bp in bullet_points[:5]  # Max 5 bullet points
            ]
        
        if brand:
            attributes['brand'] = wrap_value(brand)
        
        if manufacturer:
            attributes['manufacturer'] = wrap_value(manufacturer)
        
        if price is not None:
            attributes['purchasable_offer'] = [{
                "marketplace_id": marketplace_id,
                "currency": currency_code,
                "our_price": [{
                    "schedule": [{
                        "value_with_tax": price
                    }]
                }]
            }]
        
        if quantity is not None:
            attributes['fulfillment_availability'] = [{
                "fulfillment_channel_code": fulfillment_channel,
                "quantity": quantity,
                "marketplace_id": marketplace_id
            }]
        
        if condition:
            attributes['condition_type'] = wrap_value(condition)
        
        if main_image_url:
            attributes['main_product_image_locator'] = [{
                "media_location": main_image_url,
                "marketplace_id": marketplace_id
            }]
        
        if other_image_urls:
            attributes['other_product_image_locator_1'] = []
            for i, url in enumerate(other_image_urls[:8], 1):  # Max 8 additional images
                if i == 1:
                    attributes['other_product_image_locator_1'].append({
                        "media_location": url,
                        "marketplace_id": marketplace_id
                    })
                else:
                    attributes[f'other_product_image_locator_{i}'] = [{
                        "media_location": url,
                        "marketplace_id": marketplace_id
                    }]
        
        if item_package_quantity:
            attributes['item_package_quantity'] = wrap_value(item_package_quantity)
        
        if number_of_items:
            attributes['number_of_items'] = wrap_value(number_of_items)
        
        # Add any extra attributes
        for key, value in extra_attributes.items():
            if value is not None:
                if isinstance(value, list):
                    attributes[key] = value
                else:
                    attributes[key] = wrap_value(value)
        
        return attributes
    
    def build_listing_patch(
        self,
        operation: str,
        path: str,
        value: Any = None,
    ) -> Dict[str, Any]:
        """
        Build a JSON Patch operation for listing updates.
        
        Args:
            operation: Patch operation (add, replace, delete)
            path: JSON path to the attribute
            value: New value (for add/replace)
            
        Returns:
            Patch operation dictionary
        """
        patch = {
            "op": operation,
            "path": path,
        }
        
        if operation in ("add", "replace") and value is not None:
            patch["value"] = value
        
        return patch
