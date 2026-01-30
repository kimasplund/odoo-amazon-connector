# -*- coding: utf-8 -*-
"""
Amazon SP-API Orders API Client

Handles:
- Order retrieval and search
- Order items
- Order metrics
- Shipping and tracking
- Order acknowledgements
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union
from enum import Enum

from .sp_api_client import SPAPIClient, SPAPIError

_logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    """Amazon order status values."""
    PENDING = "Pending"
    UNSHIPPED = "Unshipped"
    PARTIALLY_SHIPPED = "PartiallyShipped"
    SHIPPED = "Shipped"
    CANCELED = "Canceled"
    UNFULFILLABLE = "Unfulfillable"
    INVOICE_UNCONFIRMED = "InvoiceUnconfirmed"
    PENDING_AVAILABILITY = "PendingAvailability"


class FulfillmentChannel(str, Enum):
    """Fulfillment channels."""
    MFN = "MFN"  # Merchant Fulfilled Network (FBM)
    AFN = "AFN"  # Amazon Fulfilled Network (FBA)


class EasyShipShipmentStatus(str, Enum):
    """Easy Ship shipment status."""
    PENDING_SCHEDULE = "PendingSchedule"
    PENDING_PICK_UP = "PendingPickUp"
    PENDING_DROP_OFF = "PendingDropOff"
    LABEL_CANCELED = "LabelCanceled"
    PICKED_UP = "PickedUp"
    DROPPED_OFF = "DroppedOff"
    AT_ORIGIN_FC = "AtOriginFC"
    AT_DESTINATION_FC = "AtDestinationFC"
    DELIVERED = "Delivered"
    REJECTED_BY_BUYER = "RejectedByBuyer"
    UNDELIVERABLE = "Undeliverable"
    RETURNING_TO_SELLER = "ReturningToSeller"
    RETURNED_TO_SELLER = "ReturnedToSeller"
    LOST = "Lost"
    OUT_FOR_DELIVERY = "OutForDelivery"
    DAMAGED = "Damaged"


class PaymentMethod(str, Enum):
    """Payment methods."""
    COD = "COD"
    CVS = "CVS"
    OTHER = "Other"


class SPAPIOrders:
    """
    Amazon Orders API Client
    
    Provides access to:
    - Orders retrieval (getOrders, getOrder)
    - Order items (getOrderItems)
    - Order buyer info
    - Order address
    - Order metrics
    - Shipping confirmations
    """
    
    API_VERSION = "v0"
    
    def __init__(self, client: SPAPIClient):
        """
        Initialize Orders API client.
        
        Args:
            client: Base SP-API client instance
        """
        self.client = client
    
    # =========================================================================
    # Orders Retrieval
    # =========================================================================
    
    def get_orders(
        self,
        created_after: Union[datetime, str] = None,
        created_before: Union[datetime, str] = None,
        last_updated_after: Union[datetime, str] = None,
        last_updated_before: Union[datetime, str] = None,
        order_statuses: List[Union[str, OrderStatus]] = None,
        marketplace_ids: List[str] = None,
        fulfillment_channels: List[Union[str, FulfillmentChannel]] = None,
        payment_methods: List[Union[str, PaymentMethod]] = None,
        buyer_email: str = None,
        seller_order_id: str = None,
        max_results_per_page: int = 100,
        easy_ship_shipment_statuses: List[Union[str, EasyShipShipmentStatus]] = None,
        electronic_invoice_statuses: List[str] = None,
        next_token: str = None,
        amazon_order_ids: List[str] = None,
        actual_fulfillment_supply_source_id: str = None,
        is_ispu: bool = None,
        store_chain_store_id: str = None,
        earliest_delivery_date_before: Union[datetime, str] = None,
        earliest_delivery_date_after: Union[datetime, str] = None,
        latest_delivery_date_before: Union[datetime, str] = None,
        latest_delivery_date_after: Union[datetime, str] = None,
    ) -> Dict[str, Any]:
        """
        Get orders matching criteria.
        
        At least one of these must be specified:
        - created_after
        - last_updated_after
        - amazon_order_ids
        
        Args:
            created_after: Orders created after this date
            created_before: Orders created before this date
            last_updated_after: Orders updated after this date
            last_updated_before: Orders updated before this date
            order_statuses: Filter by order status
            marketplace_ids: Filter by marketplace IDs
            fulfillment_channels: Filter by fulfillment channel (MFN, AFN)
            payment_methods: Filter by payment method
            buyer_email: Filter by buyer email
            seller_order_id: Filter by seller order ID
            max_results_per_page: Max results per page (1-100)
            easy_ship_shipment_statuses: Filter by Easy Ship status
            electronic_invoice_statuses: Filter by e-invoice status
            next_token: Pagination token
            amazon_order_ids: Specific order IDs to retrieve (max 50)
            actual_fulfillment_supply_source_id: Supply source filter
            is_ispu: Filter by In-Store Pickup
            store_chain_store_id: Store chain filter
            earliest_delivery_date_before: Delivery date filter
            earliest_delivery_date_after: Delivery date filter
            latest_delivery_date_before: Delivery date filter
            latest_delivery_date_after: Delivery date filter
            
        Returns:
            Orders response with pagination
        """
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            return dt
        
        params = {
            'MaxResultsPerPage': min(max_results_per_page, 100),
        }
        
        # Date filters
        if created_after:
            params['CreatedAfter'] = format_datetime(created_after)
        if created_before:
            params['CreatedBefore'] = format_datetime(created_before)
        if last_updated_after:
            params['LastUpdatedAfter'] = format_datetime(last_updated_after)
        if last_updated_before:
            params['LastUpdatedBefore'] = format_datetime(last_updated_before)
        
        # Delivery date filters
        if earliest_delivery_date_before:
            params['EarliestDeliveryDateBefore'] = format_datetime(earliest_delivery_date_before)
        if earliest_delivery_date_after:
            params['EarliestDeliveryDateAfter'] = format_datetime(earliest_delivery_date_after)
        if latest_delivery_date_before:
            params['LatestDeliveryDateBefore'] = format_datetime(latest_delivery_date_before)
        if latest_delivery_date_after:
            params['LatestDeliveryDateAfter'] = format_datetime(latest_delivery_date_after)
        
        # Status filters
        if order_statuses:
            statuses = [s.value if isinstance(s, OrderStatus) else s for s in order_statuses]
            params['OrderStatuses'] = ','.join(statuses)
        
        # Marketplace filter
        if marketplace_ids:
            params['MarketplaceIds'] = ','.join(marketplace_ids)
        elif self.client.marketplace_id:
            params['MarketplaceIds'] = self.client.marketplace_id
        
        # Fulfillment channel filter
        if fulfillment_channels:
            channels = [c.value if isinstance(c, FulfillmentChannel) else c for c in fulfillment_channels]
            params['FulfillmentChannels'] = ','.join(channels)
        
        # Payment method filter
        if payment_methods:
            methods = [m.value if isinstance(m, PaymentMethod) else m for m in payment_methods]
            params['PaymentMethods'] = ','.join(methods)
        
        # Other filters
        if buyer_email:
            params['BuyerEmail'] = buyer_email
        if seller_order_id:
            params['SellerOrderId'] = seller_order_id
        if amazon_order_ids:
            params['AmazonOrderIds'] = ','.join(amazon_order_ids[:50])
        if actual_fulfillment_supply_source_id:
            params['ActualFulfillmentSupplySourceId'] = actual_fulfillment_supply_source_id
        if is_ispu is not None:
            params['IsISPU'] = str(is_ispu).lower()
        if store_chain_store_id:
            params['StoreChainStoreId'] = store_chain_store_id
        
        # Easy Ship status filter
        if easy_ship_shipment_statuses:
            statuses = [s.value if isinstance(s, EasyShipShipmentStatus) else s for s in easy_ship_shipment_statuses]
            params['EasyShipShipmentStatuses'] = ','.join(statuses)
        
        # E-invoice status filter
        if electronic_invoice_statuses:
            params['ElectronicInvoiceStatuses'] = ','.join(electronic_invoice_statuses)
        
        # Pagination
        if next_token:
            params['NextToken'] = next_token
        
        # Request RDT for PII access
        restricted_resources = [{
            'method': 'GET',
            'path': f'/orders/{self.API_VERSION}/orders',
            'dataElements': ['buyerInfo', 'shippingAddress']
        }]

        return self.client.get(
            f'/orders/{self.API_VERSION}/orders',
            operation='getOrders',
            params=params,
            add_marketplace=False,
            restricted_resources=restricted_resources,
        )
    
    def get_order(self, order_id: str) -> Dict[str, Any]:
        """
        Get a single order by Amazon Order ID.
        
        Args:
            order_id: Amazon Order ID
            
        Returns:
            Order details
        """
        restricted_resources = [{
            'method': 'GET',
            'path': f'/orders/{self.API_VERSION}/orders/{order_id}',
            'dataElements': ['buyerInfo', 'shippingAddress']
        }]

        return self.client.get(
            f'/orders/{self.API_VERSION}/orders/{order_id}',
            operation='getOrder',
            restricted_resources=restricted_resources,
        )
    
    def get_order_buyer_info(self, order_id: str) -> Dict[str, Any]:
        """
        Get buyer information for an order.
        
        Note: Requires PII (Personally Identifiable Information) access.
        
        Args:
            order_id: Amazon Order ID
            
        Returns:
            Buyer information
        """
        restricted_resources = [{
            'method': 'GET',
            'path': f'/orders/{self.API_VERSION}/orders/{order_id}/buyerInfo',
            'dataElements': ['buyerInfo']
        }]

        return self.client.get(
            f'/orders/{self.API_VERSION}/orders/{order_id}/buyerInfo',
            operation='getOrderBuyerInfo',
            restricted_resources=restricted_resources,
        )
    
    def get_order_address(self, order_id: str) -> Dict[str, Any]:
        """
        Get shipping address for an order.
        
        Note: Requires PII access.
        
        Args:
            order_id: Amazon Order ID
            
        Returns:
            Shipping address
        """
        restricted_resources = [{
            'method': 'GET',
            'path': f'/orders/{self.API_VERSION}/orders/{order_id}/address',
            'dataElements': ['shippingAddress']
        }]

        return self.client.get(
            f'/orders/{self.API_VERSION}/orders/{order_id}/address',
            operation='getOrderAddress',
            restricted_resources=restricted_resources,
        )
    
    def get_orders_all(
        self,
        created_after: Union[datetime, str] = None,
        last_updated_after: Union[datetime, str] = None,
        max_pages: int = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Get all orders matching criteria with automatic pagination.
        
        Args:
            created_after: Orders created after this date
            last_updated_after: Orders updated after this date
            max_pages: Maximum pages to fetch
            **kwargs: Additional arguments for get_orders
            
        Returns:
            List of all matching orders
        """
        all_orders = []
        next_token = None
        page_count = 0
        
        # Default to last 7 days if no date specified
        if not created_after and not last_updated_after and not kwargs.get('amazon_order_ids'):
            created_after = datetime.now(timezone.utc) - timedelta(days=7)
        
        while True:
            response = self.get_orders(
                created_after=created_after,
                last_updated_after=last_updated_after,
                next_token=next_token,
                **kwargs
            )
            
            payload = response.get('payload', response)
            orders = payload.get('Orders', [])
            all_orders.extend(orders)
            
            page_count += 1
            
            # Get next token
            next_token = payload.get('NextToken')
            
            if not next_token:
                break
            
            if max_pages and page_count >= max_pages:
                _logger.info("Reached max pages limit (%d)", max_pages)
                break
        
        _logger.info("Retrieved %d orders across %d pages", len(all_orders), page_count)
        return all_orders
    
    # =========================================================================
    # Order Items
    # =========================================================================
    
    def get_order_items(
        self,
        order_id: str,
        next_token: str = None,
    ) -> Dict[str, Any]:
        """
        Get items for an order.
        
        Args:
            order_id: Amazon Order ID
            next_token: Pagination token
            
        Returns:
            Order items
        """
        params = {}
        if next_token:
            params['NextToken'] = next_token
        
        restricted_resources = [{
            'method': 'GET',
            'path': f'/orders/{self.API_VERSION}/orders/{order_id}/orderItems',
            'dataElements': ['buyerInfo']
        }]

        return self.client.get(
            f'/orders/{self.API_VERSION}/orders/{order_id}/orderItems',
            operation='getOrderItems',
            params=params if params else None,
            restricted_resources=restricted_resources,
        )
    
    def get_order_items_buyer_info(
        self,
        order_id: str,
        next_token: str = None,
    ) -> Dict[str, Any]:
        """
        Get buyer info for order items.
        
        Note: Requires PII access.
        
        Args:
            order_id: Amazon Order ID
            next_token: Pagination token
            
        Returns:
            Order items with buyer info
        """
        params = {}
        if next_token:
            params['NextToken'] = next_token

        restricted_resources = [{
            'method': 'GET',
            'path': f'/orders/{self.API_VERSION}/orders/{order_id}/orderItems/buyerInfo',
            'dataElements': ['buyerInfo']
        }]
        
        return self.client.get(
            f'/orders/{self.API_VERSION}/orders/{order_id}/orderItems/buyerInfo',
            operation='getOrderItemsBuyerInfo',
            params=params if params else None,
            restricted_resources=restricted_resources,
        )
    
    def get_order_items_all(
        self,
        order_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Get all items for an order with automatic pagination.
        
        Args:
            order_id: Amazon Order ID
            
        Returns:
            List of all order items
        """
        all_items = []
        next_token = None
        
        while True:
            response = self.get_order_items(order_id, next_token)
            
            payload = response.get('payload', response)
            items = payload.get('OrderItems', [])
            all_items.extend(items)
            
            next_token = payload.get('NextToken')
            
            if not next_token:
                break
        
        return all_items
    
    # =========================================================================
    # Order Regulated Info
    # =========================================================================
    
    def get_order_regulated_info(self, order_id: str) -> Dict[str, Any]:
        """
        Get regulated information for an order.
        
        Args:
            order_id: Amazon Order ID
            
        Returns:
            Regulated order information
        """
        return self.client.get(
            f'/orders/{self.API_VERSION}/orders/{order_id}/regulatedInfo',
            operation='getOrderRegulatedInfo',
        )
    
    def update_verification_status(
        self,
        order_id: str,
        regulated_order_verification_status: str,
        external_reviewer_id: str = None,
        rejection_reason_id: str = None,
    ) -> Dict[str, Any]:
        """
        Update verification status for a regulated order.
        
        Args:
            order_id: Amazon Order ID
            regulated_order_verification_status: New verification status
            external_reviewer_id: External reviewer ID
            rejection_reason_id: Rejection reason if rejecting
            
        Returns:
            Update result
        """
        data = {
            'regulatedOrderVerificationStatus': {
                'status': regulated_order_verification_status,
            }
        }
        
        if external_reviewer_id:
            data['regulatedOrderVerificationStatus']['externalReviewerId'] = external_reviewer_id
        if rejection_reason_id:
            data['regulatedOrderVerificationStatus']['rejectionReasonId'] = rejection_reason_id
        
        return self.client.patch(
            f'/orders/{self.API_VERSION}/orders/{order_id}/regulatedInfo',
            operation='updateVerificationStatus',
            data=data,
        )
    
    # =========================================================================
    # Shipment Confirmation
    # =========================================================================
    
    def confirm_shipment(
        self,
        order_id: str,
        package_detail: Dict[str, Any],
        marketplace_id: str = None,
        cod_collection_method: str = None,
    ) -> Dict[str, Any]:
        """
        Confirm shipment of an order.
        
        Args:
            order_id: Amazon Order ID
            package_detail: Package details including tracking info
            marketplace_id: Marketplace ID
            cod_collection_method: COD collection method if applicable
            
        Returns:
            Confirmation result
        """
        data = {
            'marketplaceId': marketplace_id or self.client.marketplace_id,
            'packageDetail': package_detail,
        }
        
        if cod_collection_method:
            data['codCollectionMethod'] = cod_collection_method
        
        return self.client.post(
            f'/orders/{self.API_VERSION}/orders/{order_id}/shipmentConfirmation',
            operation='confirmShipment',
            data=data,
            add_marketplace=False,
        )
    
    # =========================================================================
    # Order Metrics
    # =========================================================================
    
    def get_order_metrics(
        self,
        marketplace_ids: List[str] = None,
        interval: str = None,
        interval_start: Union[datetime, str] = None,
        interval_end: Union[datetime, str] = None,
        granularity: str = "Total",
        granularity_time_zone: str = None,
        buyer_type: str = "All",
        fulfillment_network: str = None,
        first_day_of_week: str = "Monday",
        asin: str = None,
        sku: str = None,
    ) -> Dict[str, Any]:
        """
        Get order metrics for analytics.
        
        Args:
            marketplace_ids: Marketplace IDs to include
            interval: Time interval (ISO 8601 duration or date range)
            interval_start: Start of interval
            interval_end: End of interval
            granularity: Aggregation granularity (Total, Day, Week, Month)
            granularity_time_zone: Time zone for granularity
            buyer_type: Filter by buyer type (All, B2B, B2C)
            fulfillment_network: Filter by fulfillment (MFN, AFN)
            first_day_of_week: First day of week for Week granularity
            asin: Filter by ASIN
            sku: Filter by SKU
            
        Returns:
            Order metrics
        """
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            return dt
        
        # Build interval parameter
        if interval:
            interval_param = interval
        elif interval_start and interval_end:
            start = format_datetime(interval_start)
            end = format_datetime(interval_end)
            interval_param = f"{start}--{end}"
        else:
            # Default to last 30 days
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=30)
            interval_param = f"{format_datetime(start)}--{format_datetime(end)}"
        
        params = {
            'interval': interval_param,
            'granularity': granularity,
            'buyerType': buyer_type,
            'firstDayOfWeek': first_day_of_week,
        }
        
        if marketplace_ids:
            params['marketplaceIds'] = ','.join(marketplace_ids)
        elif self.client.marketplace_id:
            params['marketplaceIds'] = self.client.marketplace_id
        
        if granularity_time_zone:
            params['granularityTimeZone'] = granularity_time_zone
        if fulfillment_network:
            params['fulfillmentNetwork'] = fulfillment_network
        if asin:
            params['asin'] = asin
        if sku:
            params['sku'] = sku
        
        return self.client.get(
            f'/sales/{self.API_VERSION}/orderMetrics',
            operation='getOrderMetrics',
            params=params,
            add_marketplace=False,
        )
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def build_package_detail(
        self,
        tracking_number: str,
        carrier_code: str = None,
        carrier_name: str = None,
        ship_from_supply_source_id: str = None,
        order_items: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build package detail for shipment confirmation.
        
        Args:
            tracking_number: Shipment tracking number
            carrier_code: Standard carrier code
            carrier_name: Carrier name (if carrier_code not available)
            ship_from_supply_source_id: Supply source ID
            order_items: List of order items with quantities
            
        Returns:
            Package detail dictionary
        """
        package = {
            'trackingNumber': tracking_number,
        }
        
        if carrier_code:
            package['carrierCode'] = carrier_code
        elif carrier_name:
            package['carrierName'] = carrier_name
        
        if ship_from_supply_source_id:
            package['shipFromSupplySourceId'] = ship_from_supply_source_id
        
        if order_items:
            package['orderItems'] = order_items
        
        return package
    
    def get_recent_orders(
        self,
        days: int = 7,
        order_statuses: List[Union[str, OrderStatus]] = None,
        fulfillment_channels: List[Union[str, FulfillmentChannel]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Convenience method to get recent orders.
        
        Args:
            days: Number of days to look back
            order_statuses: Filter by status
            fulfillment_channels: Filter by fulfillment channel
            
        Returns:
            List of recent orders
        """
        created_after = datetime.now(timezone.utc) - timedelta(days=days)
        
        return self.get_orders_all(
            created_after=created_after,
            order_statuses=order_statuses,
            fulfillment_channels=fulfillment_channels,
        )
    
    def get_unshipped_orders(
        self,
        days: int = 30,
        fulfillment_channels: List[Union[str, FulfillmentChannel]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all unshipped orders.
        
        Args:
            days: Number of days to look back
            fulfillment_channels: Filter by fulfillment channel (default: MFN only)
            
        Returns:
            List of unshipped orders
        """
        if fulfillment_channels is None:
            fulfillment_channels = [FulfillmentChannel.MFN]
        
        return self.get_recent_orders(
            days=days,
            order_statuses=[OrderStatus.UNSHIPPED, OrderStatus.PARTIALLY_SHIPPED],
            fulfillment_channels=fulfillment_channels,
        )
    
    def get_order_with_items(self, order_id: str) -> Dict[str, Any]:
        """
        Get order with all items in a single call.
        
        Args:
            order_id: Amazon Order ID
            
        Returns:
            Order with items
        """
        order = self.get_order(order_id)
        items = self.get_order_items_all(order_id)
        
        # Merge items into order
        if 'payload' in order:
            order['payload']['OrderItems'] = items
        else:
            order['OrderItems'] = items
        
        return order
    
    # =========================================================================
    # Common Carrier Codes
    # =========================================================================
    
    # Standard carrier codes for use with confirm_shipment
    CARRIER_CODES = {
        # Global
        'DHL': 'DHL',
        'UPS': 'UPS',
        'FEDEX': 'FedEx',
        'USPS': 'USPS',
        'TNT': 'TNT',
        
        # Europe
        'DPD': 'DPD',
        'GLS': 'GLS',
        'HERMES': 'HERMES_DE',
        'DEUTSCHE_POST': 'DEUTSCHE_POST',
        'DHL_DE': 'DHL_DE',
        'DHL_UK': 'DHL_UK',
        'ROYAL_MAIL': 'ROYAL_MAIL',
        'PARCELFORCE': 'PARCELFORCE',
        'CHRONOPOST': 'CHRONOPOST',
        'COLISSIMO': 'COLISSIMO',
        'LA_POSTE': 'LA_POSTE',
        'POSTE_ITALIANE': 'POSTE_ITALIANE',
        'SDA': 'SDA',
        'BRT': 'BRT',
        'CORREOS': 'CORREOS',
        'SEUR': 'SEUR',
        'POSTNL': 'POSTNL',
        'POSTNORD': 'POSTNORD',
        'POCZTA_POLSKA': 'POCZTA_POLSKA',
        'INPOST': 'INPOST',
        
        # Amazon
        'AMAZON_LOGISTICS': 'AMZN_US',
        'AMAZON_LOGISTICS_EU': 'AMZN_EU',
        
        # Other
        'OTHER': 'OTHER',
    }
    
    @classmethod
    def get_carrier_code(cls, carrier_name: str) -> Optional[str]:
        """
        Get standard carrier code from carrier name.
        
        Args:
            carrier_name: Carrier name (case-insensitive)
            
        Returns:
            Carrier code or None if not found
        """
        normalized = carrier_name.upper().replace(' ', '_').replace('-', '_')
        return cls.CARRIER_CODES.get(normalized)
