# -*- coding: utf-8 -*-
"""
Amazon SP-API FBA (Fulfillment by Amazon) API Client

Handles:
- FBA Inventory (Fulfillment Inventory API)
- Inbound Fulfillment (FBA Inbound API)
- Outbound Fulfillment (Multi-Channel Fulfillment)
- FBA Small and Light
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union
from enum import Enum

from .sp_api_client import SPAPIClient, SPAPIError

_logger = logging.getLogger(__name__)


class InventoryGranularity(str, Enum):
    """Inventory granularity levels."""
    MARKETPLACE = "Marketplace"


class InventoryCondition(str, Enum):
    """Inventory condition filters."""
    SELLABLE = "Sellable"
    UNSELLABLE = "Unsellable"


class ShipmentStatus(str, Enum):
    """FBA Inbound shipment status."""
    WORKING = "WORKING"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    RECEIVING = "RECEIVING"
    CANCELLED = "CANCELLED"
    DELETED = "DELETED"
    CLOSED = "CLOSED"
    ERROR = "ERROR"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CHECKED_IN = "CHECKED_IN"


class PrepInstruction(str, Enum):
    """FBA Prep instructions."""
    POLYBAGGING = "Polybagging"
    BUBBLE_WRAPPING = "BubbleWrapping"
    TAPING = "Taping"
    BLACK_SHRINK_WRAPPING = "BlackShrinkWrapping"
    LABELING = "Labeling"
    HANG_GARMENT = "HangGarment"
    SET_CREATION = "SetCreation"
    BOXING = "Boxing"
    REMOVAL = "Removal"
    NO_PREP = "NoPrep"


class LabelOwner(str, Enum):
    """Label owner for FBA shipments."""
    AMAZON = "AMAZON"
    SELLER = "SELLER"


class IntendedBoxContentsSource(str, Enum):
    """Source of box contents information."""
    NONE = "NONE"
    FEED = "FEED"
    TWO_D_BARCODE = "2D_BARCODE"


class FulfillmentAction(str, Enum):
    """Outbound fulfillment action."""
    SHIP = "Ship"
    HOLD = "Hold"


class FulfillmentPolicy(str, Enum):
    """Outbound fulfillment policy."""
    FILL_OR_KILL = "FillOrKill"
    FILL_ALL = "FillAll"
    FILL_ALL_AVAILABLE = "FillAllAvailable"


class ShippingSpeedCategory(str, Enum):
    """Shipping speed categories."""
    STANDARD = "Standard"
    EXPEDITED = "Expedited"
    PRIORITY = "Priority"
    SCHEDULED_DELIVERY = "ScheduledDelivery"


class SPAPIFba:
    """
    Amazon FBA API Client
    
    Provides access to:
    - FBA Inventory API (inventory levels, summaries)
    - FBA Inbound API (shipment creation, tracking)
    - FBA Outbound API (Multi-Channel Fulfillment)
    - FBA Small and Light API
    """
    
    INVENTORY_API_VERSION = "v1"
    INBOUND_API_VERSION = "v0"
    OUTBOUND_API_VERSION = "2020-07-01"
    SMALL_LIGHT_API_VERSION = "v1"
    
    def __init__(self, client: SPAPIClient):
        """
        Initialize FBA API client.
        
        Args:
            client: Base SP-API client instance
        """
        self.client = client
    
    # =========================================================================
    # FBA Inventory API
    # =========================================================================
    
    def get_inventory_summaries(
        self,
        granularity_type: Union[str, InventoryGranularity] = InventoryGranularity.MARKETPLACE,
        granularity_id: str = None,
        start_date_time: Union[datetime, str] = None,
        seller_skus: List[str] = None,
        seller_sku: str = None,
        next_token: str = None,
        marketplace_ids: List[str] = None,
        details: bool = True,
    ) -> Dict[str, Any]:
        """
        Get FBA inventory summaries.
        
        Args:
            granularity_type: Type of aggregation (Marketplace)
            granularity_id: ID for aggregation (marketplace ID)
            start_date_time: Filter by last updated date
            seller_skus: Filter by seller SKUs (max 50)
            seller_sku: Filter by single seller SKU
            next_token: Pagination token
            marketplace_ids: Filter by marketplace IDs
            details: Include detailed inventory info
            
        Returns:
            Inventory summaries
        """
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            return dt
        
        granularity = granularity_type.value if isinstance(granularity_type, InventoryGranularity) else granularity_type
        
        params = {
            'granularityType': granularity,
            'granularityId': granularity_id or self.client.marketplace_id,
            'details': str(details).lower(),
        }
        
        if marketplace_ids:
            params['marketplaceIds'] = ','.join(marketplace_ids)
        elif self.client.marketplace_id:
            params['marketplaceIds'] = self.client.marketplace_id
        
        if start_date_time:
            params['startDateTime'] = format_datetime(start_date_time)
        if seller_skus:
            params['sellerSkus'] = ','.join(seller_skus[:50])
        if seller_sku:
            params['sellerSku'] = seller_sku
        if next_token:
            params['nextToken'] = next_token
        
        return self.client.get(
            f'/fba/inventory/{self.INVENTORY_API_VERSION}/summaries',
            operation='getInventorySummaries',
            params=params,
            add_marketplace=False,
        )
    
    def get_inventory_summaries_all(
        self,
        max_pages: int = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Get all FBA inventory summaries with pagination.
        
        Args:
            max_pages: Maximum pages to fetch
            **kwargs: Arguments for get_inventory_summaries
            
        Returns:
            List of all inventory summaries
        """
        all_summaries = []
        next_token = None
        page_count = 0
        
        while True:
            response = self.get_inventory_summaries(
                next_token=next_token,
                **kwargs
            )
            
            payload = response.get('payload', response)
            summaries = payload.get('inventorySummaries', [])
            all_summaries.extend(summaries)
            
            page_count += 1
            
            pagination = payload.get('pagination', {})
            next_token = pagination.get('nextToken')
            
            if not next_token:
                break
            
            if max_pages and page_count >= max_pages:
                _logger.info("Reached max pages limit (%d)", max_pages)
                break
        
        _logger.info("Retrieved %d inventory summaries", len(all_summaries))
        return all_summaries
    
    # =========================================================================
    # FBA Inbound API
    # =========================================================================
    
    def get_inbound_guidance(
        self,
        seller_sku_list: List[str] = None,
        asin_list: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Get inbound guidance for items.
        
        Args:
            seller_sku_list: List of seller SKUs
            asin_list: List of ASINs
            
        Returns:
            Inbound guidance information
        """
        params = {}
        
        if seller_sku_list:
            params['SellerSKUList'] = ','.join(seller_sku_list)
        if asin_list:
            params['ASINList'] = ','.join(asin_list)
        
        return self.client.get(
            f'/fba/inbound/{self.INBOUND_API_VERSION}/itemsGuidance',
            operation='getInboundGuidance',
            params=params,
        )
    
    def create_inbound_shipment_plan(
        self,
        ship_from_address: Dict[str, Any],
        inbound_shipment_plan_request_items: List[Dict[str, Any]],
        label_prep_preference: str = "SELLER_LABEL",
    ) -> Dict[str, Any]:
        """
        Create an inbound shipment plan.
        
        Args:
            ship_from_address: Ship from address
            inbound_shipment_plan_request_items: Items for the shipment
            label_prep_preference: Label prep preference (SELLER_LABEL, AMAZON_LABEL)
            
        Returns:
            Shipment plan details
        """
        data = {
            'ShipFromAddress': ship_from_address,
            'InboundShipmentPlanRequestItems': inbound_shipment_plan_request_items,
            'LabelPrepPreference': label_prep_preference,
        }
        
        return self.client.post(
            f'/fba/inbound/{self.INBOUND_API_VERSION}/plans',
            operation='createInboundShipmentPlan',
            data=data,
        )
    
    def create_inbound_shipment(
        self,
        shipment_id: str,
        inbound_shipment_header: Dict[str, Any],
        inbound_shipment_items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Create an inbound shipment from a shipment plan.
        
        Args:
            shipment_id: Shipment ID from the plan
            inbound_shipment_header: Shipment header info
            inbound_shipment_items: Items for the shipment
            
        Returns:
            Created shipment details
        """
        data = {
            'InboundShipmentHeader': inbound_shipment_header,
            'InboundShipmentItems': inbound_shipment_items,
        }
        
        return self.client.post(
            f'/fba/inbound/{self.INBOUND_API_VERSION}/shipments/{shipment_id}',
            operation='createInboundShipment',
            data=data,
        )
    
    def update_inbound_shipment(
        self,
        shipment_id: str,
        inbound_shipment_header: Dict[str, Any],
        inbound_shipment_items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Update an existing inbound shipment.
        
        Args:
            shipment_id: Shipment ID
            inbound_shipment_header: Updated header info
            inbound_shipment_items: Updated items
            
        Returns:
            Updated shipment details
        """
        data = {
            'InboundShipmentHeader': inbound_shipment_header,
            'InboundShipmentItems': inbound_shipment_items,
        }
        
        return self.client.put(
            f'/fba/inbound/{self.INBOUND_API_VERSION}/shipments/{shipment_id}',
            operation='updateInboundShipment',
            data=data,
        )
    
    def get_shipments(
        self,
        shipment_status_list: List[Union[str, ShipmentStatus]] = None,
        shipment_id_list: List[str] = None,
        last_updated_after: Union[datetime, str] = None,
        last_updated_before: Union[datetime, str] = None,
        query_type: str = "SHIPMENT",
        next_token: str = None,
    ) -> Dict[str, Any]:
        """
        Get inbound shipments.
        
        Args:
            shipment_status_list: Filter by status
            shipment_id_list: Filter by shipment IDs
            last_updated_after: Filter by last updated date
            last_updated_before: Filter by last updated date
            query_type: Query type (SHIPMENT, DATE_RANGE, NEXT_TOKEN)
            next_token: Pagination token
            
        Returns:
            Shipments list
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
            'QueryType': query_type,
        }
        
        if shipment_status_list:
            statuses = [s.value if isinstance(s, ShipmentStatus) else s for s in shipment_status_list]
            params['ShipmentStatusList'] = ','.join(statuses)
        if shipment_id_list:
            params['ShipmentIdList'] = ','.join(shipment_id_list)
        if last_updated_after:
            params['LastUpdatedAfter'] = format_datetime(last_updated_after)
        if last_updated_before:
            params['LastUpdatedBefore'] = format_datetime(last_updated_before)
        if next_token:
            params['NextToken'] = next_token
        
        return self.client.get(
            f'/fba/inbound/{self.INBOUND_API_VERSION}/shipments',
            operation='getShipments',
            params=params,
        )
    
    def get_shipment_items(
        self,
        shipment_id: str = None,
        last_updated_after: Union[datetime, str] = None,
        last_updated_before: Union[datetime, str] = None,
        query_type: str = "SHIPMENT",
        next_token: str = None,
    ) -> Dict[str, Any]:
        """
        Get items in an inbound shipment.
        
        Args:
            shipment_id: Shipment ID
            last_updated_after: Filter by last updated date
            last_updated_before: Filter by last updated date
            query_type: Query type
            next_token: Pagination token
            
        Returns:
            Shipment items
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
            'QueryType': query_type,
        }
        
        if shipment_id:
            params['ShipmentId'] = shipment_id
        if last_updated_after:
            params['LastUpdatedAfter'] = format_datetime(last_updated_after)
        if last_updated_before:
            params['LastUpdatedBefore'] = format_datetime(last_updated_before)
        if next_token:
            params['NextToken'] = next_token
        
        return self.client.get(
            f'/fba/inbound/{self.INBOUND_API_VERSION}/shipmentItems',
            operation='getShipmentItems',
            params=params,
        )
    
    def get_prep_instructions(
        self,
        ship_to_country_code: str,
        seller_sku_list: List[str] = None,
        asin_list: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Get prep instructions for items.
        
        Args:
            ship_to_country_code: Destination country code
            seller_sku_list: List of seller SKUs
            asin_list: List of ASINs
            
        Returns:
            Prep instructions
        """
        params = {
            'ShipToCountryCode': ship_to_country_code,
        }
        
        if seller_sku_list:
            params['SellerSKUList'] = ','.join(seller_sku_list)
        if asin_list:
            params['ASINList'] = ','.join(asin_list)
        
        return self.client.get(
            f'/fba/inbound/{self.INBOUND_API_VERSION}/prepInstructions',
            operation='getPrepInstructions',
            params=params,
        )
    
    def get_labels(
        self,
        shipment_id: str,
        page_type: str,
        label_type: str,
        number_of_packages: int = None,
        package_labels_to_print: List[str] = None,
        number_of_pallets: int = None,
        page_size: int = None,
        page_start_index: int = None,
    ) -> Dict[str, Any]:
        """
        Get labels for an inbound shipment.
        
        Args:
            shipment_id: Shipment ID
            page_type: Page type for labels
            label_type: Label type (BARCODE_2D, UNIQUE, PALLET)
            number_of_packages: Number of packages (for UNIQUE labels)
            package_labels_to_print: Specific packages to print
            number_of_pallets: Number of pallets
            page_size: Page size for pagination
            page_start_index: Start index for pagination
            
        Returns:
            Labels data (PDF or PNG)
        """
        params = {
            'PageType': page_type,
            'LabelType': label_type,
        }
        
        if number_of_packages:
            params['NumberOfPackages'] = number_of_packages
        if package_labels_to_print:
            params['PackageLabelsToPrint'] = ','.join(package_labels_to_print)
        if number_of_pallets:
            params['NumberOfPallets'] = number_of_pallets
        if page_size:
            params['PageSize'] = page_size
        if page_start_index:
            params['PageStartIndex'] = page_start_index
        
        return self.client.get(
            f'/fba/inbound/{self.INBOUND_API_VERSION}/shipments/{shipment_id}/labels',
            operation='getLabels',
            params=params,
        )
    
    def estimate_transport(
        self,
        shipment_id: str,
    ) -> Dict[str, Any]:
        """
        Get transport cost estimate.
        
        Args:
            shipment_id: Shipment ID
            
        Returns:
            Transport estimate
        """
        return self.client.post(
            f'/fba/inbound/{self.INBOUND_API_VERSION}/shipments/{shipment_id}/transport/estimate',
            operation='estimateTransport',
        )
    
    def get_transport_details(
        self,
        shipment_id: str,
    ) -> Dict[str, Any]:
        """
        Get transport details for a shipment.
        
        Args:
            shipment_id: Shipment ID
            
        Returns:
            Transport details
        """
        return self.client.get(
            f'/fba/inbound/{self.INBOUND_API_VERSION}/shipments/{shipment_id}/transport',
            operation='getTransportDetails',
        )
    
    def confirm_transport(
        self,
        shipment_id: str,
    ) -> Dict[str, Any]:
        """
        Confirm transport for a shipment.
        
        Args:
            shipment_id: Shipment ID
            
        Returns:
            Confirmation result
        """
        return self.client.post(
            f'/fba/inbound/{self.INBOUND_API_VERSION}/shipments/{shipment_id}/transport/confirm',
            operation='confirmTransport',
        )
    
    def void_transport(
        self,
        shipment_id: str,
    ) -> Dict[str, Any]:
        """
        Void transport for a shipment.
        
        Args:
            shipment_id: Shipment ID
            
        Returns:
            Void result
        """
        return self.client.post(
            f'/fba/inbound/{self.INBOUND_API_VERSION}/shipments/{shipment_id}/transport/void',
            operation='voidTransport',
        )
    
    # =========================================================================
    # FBA Outbound (Multi-Channel Fulfillment) API
    # =========================================================================
    
    def get_fulfillment_preview(
        self,
        address: Dict[str, Any],
        items: List[Dict[str, Any]],
        shipping_speed_categories: List[Union[str, ShippingSpeedCategory]] = None,
        include_cod_fulfillment_preview: bool = False,
        include_delivery_windows: bool = False,
        feature_constraints: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Get fulfillment preview for multi-channel order.
        
        Args:
            address: Destination address
            items: Items to fulfill
            shipping_speed_categories: Shipping speeds to preview
            include_cod_fulfillment_preview: Include COD options
            include_delivery_windows: Include delivery windows
            feature_constraints: Feature constraints
            
        Returns:
            Fulfillment previews
        """
        data = {
            'address': address,
            'items': items,
        }
        
        if shipping_speed_categories:
            speeds = [s.value if isinstance(s, ShippingSpeedCategory) else s for s in shipping_speed_categories]
            data['shippingSpeedCategories'] = speeds
        if include_cod_fulfillment_preview:
            data['includeCODFulfillmentPreview'] = include_cod_fulfillment_preview
        if include_delivery_windows:
            data['includeDeliveryWindows'] = include_delivery_windows
        if feature_constraints:
            data['featureConstraints'] = feature_constraints
        
        return self.client.post(
            f'/fba/outbound/{self.OUTBOUND_API_VERSION}/fulfillmentOrders/preview',
            operation='getFulfillmentPreview',
            data=data,
        )
    
    def create_fulfillment_order(
        self,
        seller_fulfillment_order_id: str,
        displayable_order_id: str,
        displayable_order_date: Union[datetime, str],
        displayable_order_comment: str,
        shipping_speed_category: Union[str, ShippingSpeedCategory],
        destination_address: Dict[str, Any],
        items: List[Dict[str, Any]],
        fulfillment_action: Union[str, FulfillmentAction] = FulfillmentAction.SHIP,
        fulfillment_policy: Union[str, FulfillmentPolicy] = FulfillmentPolicy.FILL_OR_KILL,
        notification_emails: List[str] = None,
        cod_settings: Dict[str, Any] = None,
        delivery_window: Dict[str, Any] = None,
        feature_constraints: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a multi-channel fulfillment order.
        
        Args:
            seller_fulfillment_order_id: Your order ID
            displayable_order_id: Display order ID for customer
            displayable_order_date: Order date shown to customer
            displayable_order_comment: Comment shown to customer
            shipping_speed_category: Shipping speed
            destination_address: Ship to address
            items: Items to fulfill
            fulfillment_action: Action (Ship or Hold)
            fulfillment_policy: Fulfillment policy
            notification_emails: Email addresses for notifications
            cod_settings: COD settings if applicable
            delivery_window: Scheduled delivery window
            feature_constraints: Feature constraints
            
        Returns:
            Created fulfillment order
        """
        def format_datetime(dt):
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            return dt
        
        speed = shipping_speed_category.value if isinstance(shipping_speed_category, ShippingSpeedCategory) else shipping_speed_category
        action = fulfillment_action.value if isinstance(fulfillment_action, FulfillmentAction) else fulfillment_action
        policy = fulfillment_policy.value if isinstance(fulfillment_policy, FulfillmentPolicy) else fulfillment_policy
        
        data = {
            'sellerFulfillmentOrderId': seller_fulfillment_order_id,
            'displayableOrderId': displayable_order_id,
            'displayableOrderDate': format_datetime(displayable_order_date),
            'displayableOrderComment': displayable_order_comment,
            'shippingSpeedCategory': speed,
            'destinationAddress': destination_address,
            'items': items,
            'fulfillmentAction': action,
            'fulfillmentPolicy': policy,
        }
        
        if notification_emails:
            data['notificationEmails'] = notification_emails
        if cod_settings:
            data['codSettings'] = cod_settings
        if delivery_window:
            data['deliveryWindow'] = delivery_window
        if feature_constraints:
            data['featureConstraints'] = feature_constraints
        
        return self.client.post(
            f'/fba/outbound/{self.OUTBOUND_API_VERSION}/fulfillmentOrders',
            operation='createFulfillmentOrder',
            data=data,
        )
    
    def get_fulfillment_order(
        self,
        seller_fulfillment_order_id: str,
    ) -> Dict[str, Any]:
        """
        Get a fulfillment order.
        
        Args:
            seller_fulfillment_order_id: Your order ID
            
        Returns:
            Fulfillment order details
        """
        return self.client.get(
            f'/fba/outbound/{self.OUTBOUND_API_VERSION}/fulfillmentOrders/{seller_fulfillment_order_id}',
            operation='getFulfillmentOrder',
        )
    
    def list_all_fulfillment_orders(
        self,
        query_start_date: Union[datetime, str] = None,
        next_token: str = None,
    ) -> Dict[str, Any]:
        """
        List all fulfillment orders.
        
        Args:
            query_start_date: Start date for query
            next_token: Pagination token
            
        Returns:
            List of fulfillment orders
        """
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            return dt
        
        params = {}
        
        if query_start_date:
            params['queryStartDate'] = format_datetime(query_start_date)
        if next_token:
            params['nextToken'] = next_token
        
        return self.client.get(
            f'/fba/outbound/{self.OUTBOUND_API_VERSION}/fulfillmentOrders',
            operation='listAllFulfillmentOrders',
            params=params if params else None,
        )
    
    def update_fulfillment_order(
        self,
        seller_fulfillment_order_id: str,
        displayable_order_id: str = None,
        displayable_order_date: Union[datetime, str] = None,
        displayable_order_comment: str = None,
        shipping_speed_category: Union[str, ShippingSpeedCategory] = None,
        destination_address: Dict[str, Any] = None,
        fulfillment_action: Union[str, FulfillmentAction] = None,
        fulfillment_policy: Union[str, FulfillmentPolicy] = None,
        notification_emails: List[str] = None,
        items: List[Dict[str, Any]] = None,
        feature_constraints: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Update a fulfillment order.
        
        Args:
            seller_fulfillment_order_id: Your order ID
            displayable_order_id: Updated display order ID
            displayable_order_date: Updated order date
            displayable_order_comment: Updated comment
            shipping_speed_category: Updated shipping speed
            destination_address: Updated address
            fulfillment_action: Updated action
            fulfillment_policy: Updated policy
            notification_emails: Updated notification emails
            items: Updated items
            feature_constraints: Updated feature constraints
            
        Returns:
            Update result
        """
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            return dt
        
        data = {}
        
        if displayable_order_id:
            data['displayableOrderId'] = displayable_order_id
        if displayable_order_date:
            data['displayableOrderDate'] = format_datetime(displayable_order_date)
        if displayable_order_comment:
            data['displayableOrderComment'] = displayable_order_comment
        if shipping_speed_category:
            speed = shipping_speed_category.value if isinstance(shipping_speed_category, ShippingSpeedCategory) else shipping_speed_category
            data['shippingSpeedCategory'] = speed
        if destination_address:
            data['destinationAddress'] = destination_address
        if fulfillment_action:
            action = fulfillment_action.value if isinstance(fulfillment_action, FulfillmentAction) else fulfillment_action
            data['fulfillmentAction'] = action
        if fulfillment_policy:
            policy = fulfillment_policy.value if isinstance(fulfillment_policy, FulfillmentPolicy) else fulfillment_policy
            data['fulfillmentPolicy'] = policy
        if notification_emails:
            data['notificationEmails'] = notification_emails
        if items:
            data['items'] = items
        if feature_constraints:
            data['featureConstraints'] = feature_constraints
        
        return self.client.put(
            f'/fba/outbound/{self.OUTBOUND_API_VERSION}/fulfillmentOrders/{seller_fulfillment_order_id}',
            operation='updateFulfillmentOrder',
            data=data,
        )
    
    def cancel_fulfillment_order(
        self,
        seller_fulfillment_order_id: str,
    ) -> Dict[str, Any]:
        """
        Cancel a fulfillment order.
        
        Args:
            seller_fulfillment_order_id: Your order ID
            
        Returns:
            Cancellation result
        """
        return self.client.put(
            f'/fba/outbound/{self.OUTBOUND_API_VERSION}/fulfillmentOrders/{seller_fulfillment_order_id}/cancel',
            operation='cancelFulfillmentOrder',
        )
    
    def get_package_tracking_details(
        self,
        package_number: int,
    ) -> Dict[str, Any]:
        """
        Get tracking details for a package.
        
        Args:
            package_number: Package number
            
        Returns:
            Tracking details
        """
        params = {
            'packageNumber': package_number,
        }
        
        return self.client.get(
            f'/fba/outbound/{self.OUTBOUND_API_VERSION}/tracking',
            operation='getPackageTrackingDetails',
            params=params,
        )
    
    def list_return_reason_codes(
        self,
        seller_sku: str,
        language: str = "en_US",
        seller_fulfillment_order_id: str = None,
    ) -> Dict[str, Any]:
        """
        Get return reason codes.
        
        Args:
            seller_sku: Seller SKU
            language: Language code
            seller_fulfillment_order_id: Optional order ID
            
        Returns:
            Return reason codes
        """
        import urllib.parse
        
        params = {
            'sellerSku': seller_sku,
            'language': language,
        }
        
        if seller_fulfillment_order_id:
            params['sellerFulfillmentOrderId'] = seller_fulfillment_order_id
        
        return self.client.get(
            f'/fba/outbound/{self.OUTBOUND_API_VERSION}/returnReasonCodes',
            operation='listReturnReasonCodes',
            params=params,
        )
    
    def create_fulfillment_return(
        self,
        seller_fulfillment_order_id: str,
        items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Create a fulfillment return.
        
        Args:
            seller_fulfillment_order_id: Your order ID
            items: Items to return
            
        Returns:
            Return creation result
        """
        data = {
            'items': items,
        }
        
        return self.client.put(
            f'/fba/outbound/{self.OUTBOUND_API_VERSION}/fulfillmentOrders/{seller_fulfillment_order_id}/return',
            operation='createFulfillmentReturn',
            data=data,
        )
    
    def get_features(self) -> Dict[str, Any]:
        """
        Get features available for the seller's account.
        
        Returns:
            Available features
        """
        return self.client.get(
            f'/fba/outbound/{self.OUTBOUND_API_VERSION}/features',
            operation='getFeatures',
        )
    
    def get_feature_inventory(
        self,
        feature_name: str,
        next_token: str = None,
    ) -> Dict[str, Any]:
        """
        Get inventory that is eligible for a feature.
        
        Args:
            feature_name: Feature name
            next_token: Pagination token
            
        Returns:
            Feature-eligible inventory
        """
        params = {}
        if next_token:
            params['nextToken'] = next_token
        
        return self.client.get(
            f'/fba/outbound/{self.OUTBOUND_API_VERSION}/features/inventory/{feature_name}',
            operation='getFeatureInventory',
            params=params if params else None,
        )
    
    def get_feature_sku(
        self,
        feature_name: str,
        seller_sku: str,
    ) -> Dict[str, Any]:
        """
        Check if a SKU is eligible for a feature.
        
        Args:
            feature_name: Feature name
            seller_sku: Seller SKU
            
        Returns:
            Feature eligibility for SKU
        """
        import urllib.parse
        encoded_sku = urllib.parse.quote(seller_sku, safe='')
        
        return self.client.get(
            f'/fba/outbound/{self.OUTBOUND_API_VERSION}/features/inventory/{feature_name}/{encoded_sku}',
            operation='getFeatureSKU',
        )
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def build_address(
        self,
        name: str,
        address_line_1: str,
        city: str,
        country_code: str,
        postal_code: str = None,
        address_line_2: str = None,
        address_line_3: str = None,
        state_or_province_code: str = None,
        district_or_county: str = None,
        phone: str = None,
    ) -> Dict[str, Any]:
        """
        Build an address dictionary.
        
        Args:
            name: Name
            address_line_1: Address line 1
            city: City
            country_code: Country code
            postal_code: Postal/ZIP code
            address_line_2: Address line 2
            address_line_3: Address line 3
            state_or_province_code: State/Province code
            district_or_county: District/County
            phone: Phone number
            
        Returns:
            Address dictionary
        """
        address = {
            'name': name,
            'addressLine1': address_line_1,
            'city': city,
            'countryCode': country_code,
        }
        
        if postal_code:
            address['postalCode'] = postal_code
        if address_line_2:
            address['addressLine2'] = address_line_2
        if address_line_3:
            address['addressLine3'] = address_line_3
        if state_or_province_code:
            address['stateOrProvinceCode'] = state_or_province_code
        if district_or_county:
            address['districtOrCounty'] = district_or_county
        if phone:
            address['phone'] = phone
        
        return address
    
    def build_inbound_shipment_item(
        self,
        seller_sku: str,
        quantity_shipped: int,
        quantity_in_case: int = None,
        prep_details_list: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build an inbound shipment item.
        
        Args:
            seller_sku: Seller SKU
            quantity_shipped: Quantity being shipped
            quantity_in_case: Quantity per case
            prep_details_list: Prep instructions
            
        Returns:
            Shipment item dictionary
        """
        item = {
            'SellerSKU': seller_sku,
            'QuantityShipped': quantity_shipped,
        }
        
        if quantity_in_case:
            item['QuantityInCase'] = quantity_in_case
        if prep_details_list:
            item['PrepDetailsList'] = prep_details_list
        
        return item
    
    def build_fulfillment_order_item(
        self,
        seller_sku: str,
        seller_fulfillment_order_item_id: str,
        quantity: int,
        gift_message: str = None,
        displayable_comment: str = None,
        fulfillment_network_sku: str = None,
        per_unit_declared_value: Dict[str, Any] = None,
        per_unit_price: Dict[str, Any] = None,
        per_unit_tax: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Build a fulfillment order item for MCF.
        
        Args:
            seller_sku: Seller SKU
            seller_fulfillment_order_item_id: Your item ID
            quantity: Quantity to fulfill
            gift_message: Gift message
            displayable_comment: Comment shown to customer
            fulfillment_network_sku: FBA SKU
            per_unit_declared_value: Declared value per unit
            per_unit_price: Price per unit
            per_unit_tax: Tax per unit
            
        Returns:
            Fulfillment order item dictionary
        """
        item = {
            'sellerSku': seller_sku,
            'sellerFulfillmentOrderItemId': seller_fulfillment_order_item_id,
            'quantity': quantity,
        }
        
        if gift_message:
            item['giftMessage'] = gift_message
        if displayable_comment:
            item['displayableComment'] = displayable_comment
        if fulfillment_network_sku:
            item['fulfillmentNetworkSku'] = fulfillment_network_sku
        if per_unit_declared_value:
            item['perUnitDeclaredValue'] = per_unit_declared_value
        if per_unit_price:
            item['perUnitPrice'] = per_unit_price
        if per_unit_tax:
            item['perUnitTax'] = per_unit_tax
        
        return item
    
    def get_low_inventory_items(
        self,
        threshold: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get inventory items below a threshold.
        
        Args:
            threshold: Quantity threshold
            
        Returns:
            List of low inventory items
        """
        all_inventory = self.get_inventory_summaries_all()
        
        low_items = [
            item for item in all_inventory
            if item.get('inventoryDetails', {}).get('fulfillableQuantity', 0) < threshold
        ]
        
        return low_items
