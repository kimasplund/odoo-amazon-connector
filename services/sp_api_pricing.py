# -*- coding: utf-8 -*-
"""
Amazon SP-API Pricing Service

Provides pricing-related API operations:
- Get competitive pricing
- Get item offers (listing offers)
- Get Buy Box eligible offers
- Submit price updates via Feeds API

Note: Amazon's Product Pricing API has strict rate limits:
- getCompetitivePricing: 10 requests/second, burst 20
- getListingOffers: 5 requests/second, burst 10
- getPricing: 10 requests/second, burst 20
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .sp_api_client import SPAPIClient, OdooSPAPIClient, SPAPIError

_logger = logging.getLogger(__name__)


class SPAPIPricingService:
    """
    SP-API Pricing Service.
    
    Handles all pricing-related operations through Amazon's Product Pricing API.
    """
    
    # API Base Path
    PRICING_API_PATH = '/products/pricing/v0'
    
    def __init__(self, client: SPAPIClient):
        """
        Initialize pricing service.
        
        Args:
            client: Configured SPAPIClient instance
        """
        self.client = client
        self.marketplace_id = client.marketplace_id
    
    # =========================================================================
    # COMPETITIVE PRICING
    # =========================================================================
    
    def get_competitive_pricing_for_asin(
        self,
        asin: str,
        customer_type: str = 'Consumer'
    ) -> Dict[str, Any]:
        """
        Get competitive pricing for a single ASIN.
        
        Args:
            asin: Amazon Standard Identification Number
            customer_type: 'Consumer' or 'Business'
            
        Returns:
            Dict with competitive pricing data
        """
        path = f'{self.PRICING_API_PATH}/competitivePrice'
        
        response = self.client.get(
            path,
            operation='getCompetitivePricing',
            params={
                'MarketplaceId': self.marketplace_id,
                'Asins': asin,
                'ItemType': 'Asin',
                'CustomerType': customer_type,
            },
            add_marketplace=False,
        )
        
        return self._parse_competitive_pricing(response)
    
    def get_competitive_pricing_for_asins(
        self,
        asins: List[str],
        customer_type: str = 'Consumer'
    ) -> List[Dict[str, Any]]:
        """
        Get competitive pricing for multiple ASINs (max 20).
        
        Args:
            asins: List of ASINs (max 20)
            customer_type: 'Consumer' or 'Business'
            
        Returns:
            List of competitive pricing data dicts
        """
        if len(asins) > 20:
            _logger.warning('Too many ASINs (%d), truncating to 20', len(asins))
            asins = asins[:20]
        
        path = f'{self.PRICING_API_PATH}/competitivePrice'
        
        response = self.client.get(
            path,
            operation='getCompetitivePricing',
            params={
                'MarketplaceId': self.marketplace_id,
                'Asins': ','.join(asins),
                'ItemType': 'Asin',
                'CustomerType': customer_type,
            },
            add_marketplace=False,
        )
        
        results = []
        payload = response.get('payload', [])
        
        for item in payload:
            results.append(self._parse_competitive_pricing_item(item))
        
        return results
    
    def get_competitive_pricing_for_sku(
        self,
        sku: str,
        customer_type: str = 'Consumer'
    ) -> Dict[str, Any]:
        """
        Get competitive pricing for a single SKU.
        
        Args:
            sku: Seller SKU
            customer_type: 'Consumer' or 'Business'
            
        Returns:
            Dict with competitive pricing data
        """
        path = f'{self.PRICING_API_PATH}/competitivePrice'
        
        response = self.client.get(
            path,
            operation='getCompetitivePricing',
            params={
                'MarketplaceId': self.marketplace_id,
                'Skus': sku,
                'ItemType': 'Sku',
                'CustomerType': customer_type,
            },
            add_marketplace=False,
        )
        
        return self._parse_competitive_pricing(response)
    
    def _parse_competitive_pricing(self, response: Dict) -> Dict[str, Any]:
        """Parse competitive pricing response for single item."""
        payload = response.get('payload', [])
        if payload:
            return self._parse_competitive_pricing_item(payload[0])
        return {}
    
    def _parse_competitive_pricing_item(self, item: Dict) -> Dict[str, Any]:
        """Parse a single competitive pricing item."""
        product = item.get('Product', {})
        identifiers = product.get('Identifiers', {})
        
        result = {
            'asin': identifiers.get('MarketplaceASIN', {}).get('ASIN'),
            'sku': identifiers.get('SKUIdentifier', {}).get('SellerSKU'),
            'marketplace_id': identifiers.get('MarketplaceASIN', {}).get('MarketplaceId'),
            'competitive_prices': [],
            'number_of_offer_listings': [],
            'trade_in_value': None,
            'sales_rankings': [],
        }
        
        # Competitive prices
        competitive_pricing = product.get('CompetitivePricing', {})
        
        for cp in competitive_pricing.get('CompetitivePrices', []):
            price_data = {
                'competitive_price_id': cp.get('CompetitivePriceId'),
                'belongs_to_requester': cp.get('belongsToRequester', False),
                'condition': cp.get('condition'),
                'subcondition': cp.get('subcondition'),
                'listing_price': None,
                'shipping': None,
                'landed_price': None,
            }
            
            price = cp.get('Price', {})
            
            listing_price = price.get('ListingPrice', {})
            if listing_price:
                price_data['listing_price'] = {
                    'amount': float(listing_price.get('Amount', 0)),
                    'currency': listing_price.get('CurrencyCode'),
                }
            
            shipping = price.get('Shipping', {})
            if shipping:
                price_data['shipping'] = {
                    'amount': float(shipping.get('Amount', 0)),
                    'currency': shipping.get('CurrencyCode'),
                }
            
            landed = price.get('LandedPrice', {})
            if landed:
                price_data['landed_price'] = {
                    'amount': float(landed.get('Amount', 0)),
                    'currency': landed.get('CurrencyCode'),
                }
            
            result['competitive_prices'].append(price_data)
        
        # Offer listing counts
        for count in competitive_pricing.get('NumberOfOfferListings', []):
            result['number_of_offer_listings'].append({
                'condition': count.get('condition'),
                'count': int(count.get('Count', 0)),
            })
        
        # Sales rankings
        for ranking in product.get('SalesRankings', {}).get('SalesRankList', []):
            result['sales_rankings'].append({
                'category_id': ranking.get('ProductCategoryId'),
                'rank': int(ranking.get('Rank', 0)),
            })
        
        return result
    
    # =========================================================================
    # ITEM OFFERS (LISTING OFFERS)
    # =========================================================================
    
    def get_item_offers(
        self,
        asin: str,
        item_condition: str = 'New',
        customer_type: str = 'Consumer'
    ) -> Dict[str, Any]:
        """
        Get all offers for an ASIN (including competitors).
        
        This is the key method for competitive analysis - it returns
        all sellers offering this product.
        
        Args:
            asin: Amazon Standard Identification Number
            item_condition: 'New', 'Used', 'Collectible', 'Refurbished', 'Club'
            customer_type: 'Consumer' or 'Business'
            
        Returns:
            Dict with all offers data
        """
        path = f'{self.PRICING_API_PATH}/items/{asin}/offers'
        
        response = self.client.get(
            path,
            operation='getItemOffers',
            params={
                'MarketplaceId': self.marketplace_id,
                'ItemCondition': item_condition,
                'CustomerType': customer_type,
            },
            add_marketplace=False,
        )
        
        return self._parse_item_offers(response)
    
    def get_listing_offers(
        self,
        sku: str,
        item_condition: str = 'New',
        customer_type: str = 'Consumer'
    ) -> Dict[str, Any]:
        """
        Get all offers for a SKU (your listing).
        
        Args:
            sku: Seller SKU
            item_condition: 'New', 'Used', 'Collectible', 'Refurbished', 'Club'
            customer_type: 'Consumer' or 'Business'
            
        Returns:
            Dict with all offers data
        """
        path = f'{self.PRICING_API_PATH}/listings/{sku}/offers'
        
        response = self.client.get(
            path,
            operation='getListingOffers',
            params={
                'MarketplaceId': self.marketplace_id,
                'ItemCondition': item_condition,
                'CustomerType': customer_type,
            },
            add_marketplace=False,
        )
        
        return self._parse_item_offers(response)
    
    def _parse_item_offers(self, response: Dict) -> Dict[str, Any]:
        """Parse item/listing offers response."""
        payload = response.get('payload', {})
        
        result = {
            'asin': payload.get('ASIN'),
            'marketplace_id': payload.get('MarketplaceId'),
            'item_condition': payload.get('ItemCondition'),
            'status': payload.get('status'),
            'summary': None,
            'offers': [],
        }
        
        # Summary with Buy Box info
        summary = payload.get('Summary', {})
        if summary:
            result['summary'] = {
                'total_offer_count': summary.get('TotalOfferCount', 0),
                'number_of_offers': [],
                'buy_box_prices': [],
                'lowest_prices': [],
                'buy_box_eligible_offers': [],
                'offers_available_time': summary.get('OffersAvailableTime'),
            }
            
            # Offers by condition
            for noo in summary.get('NumberOfOffers', []):
                result['summary']['number_of_offers'].append({
                    'condition': noo.get('condition'),
                    'fulfillment_channel': noo.get('fulfillmentChannel'),
                    'count': int(noo.get('OfferCount', 0)),
                })
            
            # Buy Box prices
            for bbp in summary.get('BuyBoxPrices', []):
                bb_data = {
                    'condition': bbp.get('condition'),
                    'listing_price': None,
                    'shipping': None,
                    'landed_price': None,
                    'quantity_tier': bbp.get('quantityTier'),
                    'discount_type': bbp.get('quantityDiscountType'),
                    'seller_id': bbp.get('sellerId'),
                }
                
                if bbp.get('ListingPrice'):
                    bb_data['listing_price'] = {
                        'amount': float(bbp['ListingPrice'].get('Amount', 0)),
                        'currency': bbp['ListingPrice'].get('CurrencyCode'),
                    }
                
                if bbp.get('Shipping'):
                    bb_data['shipping'] = {
                        'amount': float(bbp['Shipping'].get('Amount', 0)),
                        'currency': bbp['Shipping'].get('CurrencyCode'),
                    }
                
                if bbp.get('LandedPrice'):
                    bb_data['landed_price'] = {
                        'amount': float(bbp['LandedPrice'].get('Amount', 0)),
                        'currency': bbp['LandedPrice'].get('CurrencyCode'),
                    }
                
                result['summary']['buy_box_prices'].append(bb_data)
            
            # Lowest prices
            for lp in summary.get('LowestPrices', []):
                lp_data = {
                    'condition': lp.get('condition'),
                    'fulfillment_channel': lp.get('fulfillmentChannel'),
                    'listing_price': None,
                    'shipping': None,
                    'landed_price': None,
                }
                
                if lp.get('ListingPrice'):
                    lp_data['listing_price'] = {
                        'amount': float(lp['ListingPrice'].get('Amount', 0)),
                        'currency': lp['ListingPrice'].get('CurrencyCode'),
                    }
                
                if lp.get('Shipping'):
                    lp_data['shipping'] = {
                        'amount': float(lp['Shipping'].get('Amount', 0)),
                        'currency': lp['Shipping'].get('CurrencyCode'),
                    }
                
                if lp.get('LandedPrice'):
                    lp_data['landed_price'] = {
                        'amount': float(lp['LandedPrice'].get('Amount', 0)),
                        'currency': lp['LandedPrice'].get('CurrencyCode'),
                    }
                
                result['summary']['lowest_prices'].append(lp_data)
            
            # Buy Box eligible offers count
            for bbeo in summary.get('BuyBoxEligibleOffers', []):
                result['summary']['buy_box_eligible_offers'].append({
                    'condition': bbeo.get('condition'),
                    'fulfillment_channel': bbeo.get('fulfillmentChannel'),
                    'count': int(bbeo.get('OfferCount', 0)),
                })
        
        # Individual offers
        for offer in payload.get('Offers', []):
            offer_data = {
                'seller_id': offer.get('SellerId'),
                'subcondition': offer.get('SubCondition'),
                'seller_feedback_rating': None,
                'shipping_time': None,
                'listing_price': None,
                'shipping': None,
                'is_fba': offer.get('IsFulfilledByAmazon', False),
                'is_featured_merchant': offer.get('IsFeaturedMerchant', False),
                'is_buy_box_winner': offer.get('IsBuyBoxWinner', False),
                'prime_information': None,
                'ships_from': None,
            }
            
            # Feedback
            feedback = offer.get('SellerFeedbackRating', {})
            if feedback:
                offer_data['seller_feedback_rating'] = {
                    'rating': float(feedback.get('SellerPositiveFeedbackRating', 0)),
                    'count': int(feedback.get('FeedbackCount', 0)),
                }
            
            # Shipping time
            shipping_time = offer.get('ShippingTime', {})
            if shipping_time:
                offer_data['shipping_time'] = {
                    'min_hours': shipping_time.get('minimumHours'),
                    'max_hours': shipping_time.get('maximumHours'),
                    'availability_type': shipping_time.get('availabilityType'),
                    'available_date': shipping_time.get('availableDate'),
                }
            
            # Listing price
            listing_price = offer.get('ListingPrice', {})
            if listing_price:
                offer_data['listing_price'] = {
                    'amount': float(listing_price.get('Amount', 0)),
                    'currency': listing_price.get('CurrencyCode'),
                }
            
            # Shipping
            shipping = offer.get('Shipping', {})
            if shipping:
                offer_data['shipping'] = {
                    'amount': float(shipping.get('Amount', 0)),
                    'currency': shipping.get('CurrencyCode'),
                }
            
            # Prime info
            prime = offer.get('PrimeInformation', {})
            if prime:
                offer_data['prime_information'] = {
                    'is_prime': prime.get('IsPrime', False),
                    'is_national_prime': prime.get('IsNationalPrime', False),
                }
            
            # Ships from
            ships_from = offer.get('ShipsFrom', {})
            if ships_from:
                offer_data['ships_from'] = {
                    'country': ships_from.get('Country'),
                    'state': ships_from.get('State'),
                }
            
            result['offers'].append(offer_data)
        
        return result
    
    # =========================================================================
    # BATCHED PRICE FETCHING
    # =========================================================================
    
    def get_pricing_for_asins(
        self,
        asins: List[str],
        item_type: str = 'Asin',
        item_condition: str = 'New'
    ) -> List[Dict[str, Any]]:
        """
        Get pricing for multiple ASINs (max 20 per request).
        
        Args:
            asins: List of ASINs
            item_type: 'Asin' or 'Sku'
            item_condition: 'New', 'Used', etc.
            
        Returns:
            List of pricing data dicts
        """
        path = f'{self.PRICING_API_PATH}/price'
        
        # Process in batches of 20
        all_results = []
        
        for i in range(0, len(asins), 20):
            batch = asins[i:i+20]
            
            response = self.client.get(
                path,
                operation='getPricing',
                params={
                    'MarketplaceId': self.marketplace_id,
                    'Asins': ','.join(batch),
                    'ItemType': item_type,
                    'ItemCondition': item_condition,
                },
                add_marketplace=False,
            )
            
            for item in response.get('payload', []):
                all_results.append(self._parse_pricing_item(item))
            
            # Small delay between batches
            if i + 20 < len(asins):
                time.sleep(0.2)
        
        return all_results
    
    def _parse_pricing_item(self, item: Dict) -> Dict[str, Any]:
        """Parse a pricing response item."""
        product = item.get('Product', {})
        identifiers = product.get('Identifiers', {})
        
        result = {
            'asin': identifiers.get('MarketplaceASIN', {}).get('ASIN'),
            'sku': identifiers.get('SKUIdentifier', {}).get('SellerSKU'),
            'offers': [],
            'status': item.get('status'),
        }
        
        for offer in product.get('Offers', []):
            offer_data = {
                'offer_type': offer.get('offerType'),
                'buying_price': None,
                'regular_price': None,
                'business_price': None,
                'quantity_discount_prices': [],
                'fulfillment_channel': offer.get('FulfillmentChannel'),
                'item_condition': offer.get('ItemCondition'),
                'item_subcondition': offer.get('ItemSubCondition'),
                'seller_sku': offer.get('SellerSKU'),
            }
            
            buying_price = offer.get('BuyingPrice', {})
            if buying_price:
                offer_data['buying_price'] = {
                    'listing_price': self._parse_money(buying_price.get('ListingPrice')),
                    'shipping': self._parse_money(buying_price.get('Shipping')),
                    'landed_price': self._parse_money(buying_price.get('LandedPrice')),
                }
            
            regular_price = offer.get('RegularPrice', {})
            if regular_price:
                offer_data['regular_price'] = self._parse_money(regular_price)
            
            result['offers'].append(offer_data)
        
        return result
    
    def _parse_money(self, money: Dict) -> Optional[Dict]:
        """Parse money field."""
        if not money:
            return None
        return {
            'amount': float(money.get('Amount', 0)),
            'currency': money.get('CurrencyCode'),
        }
    
    # =========================================================================
    # BUY BOX SPECIFIC
    # =========================================================================
    
    def get_buy_box_status(self, asin: str) -> Dict[str, Any]:
        """
        Get Buy Box status for an ASIN.
        
        Returns who currently has the Buy Box and at what price.
        
        Args:
            asin: Amazon Standard Identification Number
            
        Returns:
            Dict with Buy Box information
        """
        offers_data = self.get_item_offers(asin, item_condition='New')
        
        result = {
            'asin': asin,
            'has_buy_box': False,
            'buy_box_price': None,
            'buy_box_seller': None,
            'buy_box_is_fba': None,
            'total_offers': offers_data.get('summary', {}).get('total_offer_count', 0),
            'lowest_price': None,
            'our_offer': None,
        }
        
        # Get Buy Box from summary
        summary = offers_data.get('summary', {})
        buy_box_prices = summary.get('buy_box_prices', [])
        
        if buy_box_prices:
            bb = buy_box_prices[0]  # Primary Buy Box
            result['has_buy_box'] = True
            result['buy_box_price'] = bb.get('landed_price', {}).get('amount')
            result['buy_box_seller'] = bb.get('seller_id')
        
        # Get lowest price
        lowest_prices = summary.get('lowest_prices', [])
        for lp in lowest_prices:
            if lp.get('condition') == 'New':
                result['lowest_price'] = lp.get('landed_price', {}).get('amount')
                break
        
        # Find Buy Box winner in offers
        for offer in offers_data.get('offers', []):
            if offer.get('is_buy_box_winner'):
                result['buy_box_is_fba'] = offer.get('is_fba')
                break
        
        return result
    
    # =========================================================================
    # ODOO INTEGRATION
    # =========================================================================
    
    def sync_competitor_prices(self, env, listing):
        """
        Sync competitor prices to Odoo.
        
        Args:
            env: Odoo environment
            listing: amazon.product.listing record
            
        Returns:
            List of created amazon.competitor.price records
        """
        CompetitorPrice = env['amazon.competitor.price']
        
        try:
            offers_data = self.get_item_offers(listing.asin, item_condition='New')
        except SPAPIError as e:
            _logger.error('Failed to fetch offers for %s: %s', listing.asin, str(e))
            return []
        
        created_records = []
        seller_id = listing.account_id.seller_id if hasattr(listing.account_id, 'seller_id') else None
        
        # Determine rank
        prices = []
        for offer in offers_data.get('offers', []):
            if offer.get('listing_price'):
                total = (
                    offer['listing_price'].get('amount', 0) +
                    (offer.get('shipping', {}) or {}).get('amount', 0)
                )
                prices.append((total, offer))
        
        prices.sort(key=lambda x: x[0])
        
        for rank, (total_price, offer) in enumerate(prices, 1):
            listing_price = offer.get('listing_price', {}).get('amount', 0)
            shipping_price = (offer.get('shipping', {}) or {}).get('amount', 0)
            offer_seller_id = offer.get('seller_id')
            
            # Map condition
            condition_map = {
                'New': 'new',
                'UsedLikeNew': 'used_like_new',
                'UsedVeryGood': 'used_very_good',
                'UsedGood': 'used_good',
                'UsedAcceptable': 'used_acceptable',
                'Refurbished': 'refurbished',
            }
            condition = condition_map.get(offer.get('subcondition'), 'new')
            
            # Map availability
            availability = 'in_stock'
            shipping_time = offer.get('shipping_time', {})
            if shipping_time:
                avail_type = shipping_time.get('availability_type')
                if avail_type == 'NOW':
                    availability = 'in_stock'
                elif avail_type == 'FUTURE':
                    availability = 'backorder'
            
            record = CompetitorPrice.create({
                'product_listing_id': listing.id,
                'competitor_seller': offer_seller_id,
                'competitor_seller_id': offer_seller_id,
                'competitor_price': listing_price,
                'competitor_shipping': shipping_price,
                'condition': condition,
                'is_fba': offer.get('is_fba', False),
                'is_buy_box_winner': offer.get('is_buy_box_winner', False),
                'is_prime': (offer.get('prime_information', {}) or {}).get('is_prime', False),
                'availability': availability,
                'price_rank': rank,
                'is_our_offer': offer_seller_id == seller_id if seller_id else False,
            })
            
            created_records.append(record)
        
        _logger.info(
            'Synced %d competitor prices for %s',
            len(created_records), listing.sku
        )
        
        return created_records


class SPAPIPricingFeedService:
    """
    SP-API Price Update via Feeds.
    
    Handles price updates through the Feeds API.
    Amazon doesn't have a direct price update endpoint - 
    prices must be updated via feed submission.
    """
    
    def __init__(self, client: SPAPIClient, feeds_service=None):
        """
        Initialize pricing feed service.
        
        Args:
            client: Configured SPAPIClient instance
            feeds_service: Optional SPAPIFeedService instance
        """
        self.client = client
        self.marketplace_id = client.marketplace_id
        self._feeds_service = feeds_service
    
    @property
    def feeds_service(self):
        """Lazy-load feeds service."""
        if self._feeds_service is None:
            from .sp_api_feeds import SPAPIFeedService
            self._feeds_service = SPAPIFeedService(self.client)
        return self._feeds_service
    
    def submit_price_update(
        self,
        sku: str,
        price: float,
        currency: str = 'EUR',
        min_price: float = None,
        max_price: float = None,
        sale_price: float = None,
        sale_start: datetime = None,
        sale_end: datetime = None,
    ) -> Dict[str, Any]:
        """
        Submit a price update for a single SKU.
        
        Args:
            sku: Seller SKU
            price: New standard price
            currency: Currency code
            min_price: Optional minimum advertised price
            max_price: Optional maximum price
            sale_price: Optional sale price
            sale_start: Sale start datetime
            sale_end: Sale end datetime
            
        Returns:
            Feed submission result
        """
        feed_content = self._build_price_feed([{
            'sku': sku,
            'price': price,
            'currency': currency,
            'min_price': min_price,
            'max_price': max_price,
            'sale_price': sale_price,
            'sale_start': sale_start,
            'sale_end': sale_end,
        }])
        
        return self.feeds_service.submit_feed(
            feed_content=feed_content,
            feed_type='POST_PRODUCT_PRICING_DATA',
            content_type='text/xml',
        )
    
    def submit_bulk_price_update(
        self,
        price_updates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Submit price updates for multiple SKUs.
        
        Args:
            price_updates: List of dicts with sku, price, currency, etc.
            
        Returns:
            Feed submission result
        """
        feed_content = self._build_price_feed(price_updates)
        
        return self.feeds_service.submit_feed(
            feed_content=feed_content,
            feed_type='POST_PRODUCT_PRICING_DATA',
            content_type='text/xml',
        )
    
    def _build_price_feed(self, price_updates: List[Dict]) -> str:
        """
        Build XML feed content for price updates.
        
        Amazon requires a specific XML format for price feeds.
        """
        messages = []
        
        for idx, update in enumerate(price_updates, 1):
            sku = update['sku']
            price = update['price']
            currency = update.get('currency', 'EUR')
            
            message = f'''
        <Message>
            <MessageID>{idx}</MessageID>
            <Price>
                <SKU>{sku}</SKU>
                <StandardPrice currency="{currency}">{price:.2f}</StandardPrice>'''
            
            # Optional sale price
            if update.get('sale_price'):
                sale_start = update.get('sale_start')
                sale_end = update.get('sale_end')
                
                message += f'''
                <Sale>
                    <SalePrice currency="{currency}">{update['sale_price']:.2f}</SalePrice>'''
                
                if sale_start:
                    message += f'''
                    <StartDate>{sale_start.strftime('%Y-%m-%dT%H:%M:%S')}</StartDate>'''
                
                if sale_end:
                    message += f'''
                    <EndDate>{sale_end.strftime('%Y-%m-%dT%H:%M:%S')}</EndDate>'''
                
                message += '''
                </Sale>'''
            
            # Optional min/max prices (for Business pricing)
            if update.get('min_price'):
                message += f'''
                <MAP currency="{currency}">{update['min_price']:.2f}</MAP>'''
            
            message += '''
            </Price>
        </Message>'''
            
            messages.append(message)
        
        feed_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<AmazonEnvelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
                xsi:noNamespaceSchemaLocation="amzn-envelope.xsd">
    <Header>
        <DocumentVersion>1.01</DocumentVersion>
        <MerchantIdentifier>__MERCHANT_ID__</MerchantIdentifier>
    </Header>
    <MessageType>Price</MessageType>
    {''.join(messages)}
</AmazonEnvelope>'''
        
        return feed_xml


# ============================================================================
# ODOO SERVICE FACTORY
# ============================================================================

def get_pricing_service(credential) -> SPAPIPricingService:
    """
    Create pricing service from Odoo credential record.
    
    Args:
        credential: amazon.credential record
        
    Returns:
        SPAPIPricingService instance
    """
    client = OdooSPAPIClient.from_credential_record(credential)
    return SPAPIPricingService(client)


def get_pricing_feed_service(credential) -> SPAPIPricingFeedService:
    """
    Create pricing feed service from Odoo credential record.
    
    Args:
        credential: amazon.credential record
        
    Returns:
        SPAPIPricingFeedService instance
    """
    client = OdooSPAPIClient.from_credential_record(credential)
    return SPAPIPricingFeedService(client)
