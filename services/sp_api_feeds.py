# -*- coding: utf-8 -*-
"""
Amazon SP-API Feeds API Client

Handles:
- Feed document creation and upload
- Feed submission
- Feed processing status tracking
- Feed result retrieval
"""

import gzip
import hashlib
import io
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union, BinaryIO, TypedDict
from enum import Enum

import requests

from .sp_api_client import SPAPIClient, SPAPIError

_logger = logging.getLogger(__name__)


class FeedType(str, Enum):
    """Common Amazon feed types."""
    # Product feeds
    POST_PRODUCT_DATA = "POST_PRODUCT_DATA"
    POST_INVENTORY_AVAILABILITY_DATA = "POST_INVENTORY_AVAILABILITY_DATA"
    POST_PRODUCT_OVERRIDES_DATA = "POST_PRODUCT_OVERRIDES_DATA"
    POST_PRODUCT_PRICING_DATA = "POST_PRODUCT_PRICING_DATA"
    POST_PRODUCT_IMAGE_DATA = "POST_PRODUCT_IMAGE_DATA"
    POST_PRODUCT_RELATIONSHIP_DATA = "POST_PRODUCT_RELATIONSHIP_DATA"
    
    # Listings feeds (JSON-based)
    JSON_LISTINGS_FEED = "JSON_LISTINGS_FEED"
    
    # Order feeds
    POST_ORDER_ACKNOWLEDGEMENT_DATA = "POST_ORDER_ACKNOWLEDGEMENT_DATA"
    POST_ORDER_FULFILLMENT_DATA = "POST_ORDER_FULFILLMENT_DATA"
    POST_INVOICE_CONFIRMATION_DATA = "POST_INVOICE_CONFIRMATION_DATA"
    POST_PAYMENT_ADJUSTMENT_DATA = "POST_PAYMENT_ADJUSTMENT_DATA"
    
    # FBA feeds
    POST_FBA_INBOUND_CARTON_CONTENTS = "POST_FBA_INBOUND_CARTON_CONTENTS"
    POST_FLAT_FILE_FBA_CREATE_INBOUND_PLAN = "POST_FLAT_FILE_FBA_CREATE_INBOUND_PLAN"
    POST_FLAT_FILE_FBA_UPDATE_INBOUND_PLAN = "POST_FLAT_FILE_FBA_UPDATE_INBOUND_PLAN"
    
    # Flat file feeds
    POST_FLAT_FILE_LISTINGS_DATA = "POST_FLAT_FILE_LISTINGS_DATA"
    POST_FLAT_FILE_INVLOADER_DATA = "POST_FLAT_FILE_INVLOADER_DATA"
    POST_FLAT_FILE_PRICEANDQUANTITYONLY = "POST_FLAT_FILE_PRICEANDQUANTITYONLY"
    POST_FLAT_FILE_FULFILLMENT_DATA = "POST_FLAT_FILE_FULFILLMENT_DATA"
    
    # Easy Ship
    POST_EASYSHIP_DOCUMENTS = "POST_EASYSHIP_DOCUMENTS"


class FeedStatus(str, Enum):
    """Feed processing status."""
    CANCELLED = "CANCELLED"
    DONE = "DONE"
    FATAL = "FATAL"
    IN_PROGRESS = "IN_PROGRESS"
    IN_QUEUE = "IN_QUEUE"


class FeedContentType(str, Enum):
    """Feed content types."""
    XML = "text/xml"
    TSV = "text/tab-separated-values"
    JSON = "application/json"


# ============================================================================
# TypedDicts
# ============================================================================

class FeedDocument(TypedDict, total=False):
    feedDocumentId: str
    url: str
    encryptionDetails: Dict[str, Any]
    compressionAlgorithm: str


class Feed(TypedDict, total=False):
    feedId: str
    feedType: str
    marketplaceIds: List[str]
    createdTime: str
    processingStatus: str
    processingStartTime: str
    processingEndTime: str
    resultFeedDocumentId: str


class GetFeedsResponse(TypedDict, total=False):
    feeds: List[Feed]
    nextToken: str


class CreateFeedResponse(TypedDict):
    feedId: str


class CreateFeedDocumentResponse(TypedDict):
    feedDocumentId: str
    url: str


# ============================================================================
# SPAPIFeeds Class
# ============================================================================

class SPAPIFeeds:
    """
    Amazon Feeds API Client
    
    Provides access to:
    - Feed document creation
    - Feed submission
    - Feed status tracking
    - Feed result download
    """
    
    API_VERSION = "2021-06-30"
    
    # Feed type to content type mapping
    FEED_CONTENT_TYPES = {
        # XML feeds
        FeedType.POST_PRODUCT_DATA: FeedContentType.XML,
        FeedType.POST_INVENTORY_AVAILABILITY_DATA: FeedContentType.XML,
        FeedType.POST_PRODUCT_OVERRIDES_DATA: FeedContentType.XML,
        FeedType.POST_PRODUCT_PRICING_DATA: FeedContentType.XML,
        FeedType.POST_PRODUCT_IMAGE_DATA: FeedContentType.XML,
        FeedType.POST_PRODUCT_RELATIONSHIP_DATA: FeedContentType.XML,
        FeedType.POST_ORDER_ACKNOWLEDGEMENT_DATA: FeedContentType.XML,
        FeedType.POST_ORDER_FULFILLMENT_DATA: FeedContentType.XML,
        FeedType.POST_INVOICE_CONFIRMATION_DATA: FeedContentType.XML,
        FeedType.POST_PAYMENT_ADJUSTMENT_DATA: FeedContentType.XML,
        FeedType.POST_FBA_INBOUND_CARTON_CONTENTS: FeedContentType.XML,
        
        # JSON feeds
        FeedType.JSON_LISTINGS_FEED: FeedContentType.JSON,
        
        # Flat file (TSV) feeds
        FeedType.POST_FLAT_FILE_LISTINGS_DATA: FeedContentType.TSV,
        FeedType.POST_FLAT_FILE_INVLOADER_DATA: FeedContentType.TSV,
        FeedType.POST_FLAT_FILE_PRICEANDQUANTITYONLY: FeedContentType.TSV,
        FeedType.POST_FLAT_FILE_FULFILLMENT_DATA: FeedContentType.TSV,
        FeedType.POST_FLAT_FILE_FBA_CREATE_INBOUND_PLAN: FeedContentType.TSV,
        FeedType.POST_FLAT_FILE_FBA_UPDATE_INBOUND_PLAN: FeedContentType.TSV,
    }
    
    def __init__(self, client: SPAPIClient):
        """
        Initialize Feeds API client.
        
        Args:
            client: Base SP-API client instance
        """
        self.client = client
        self._upload_session = requests.Session()
    
    # =========================================================================
    # Feed Documents
    # =========================================================================
    
    def create_feed_document(
        self,
        content_type: Union[str, FeedContentType] = FeedContentType.JSON,
    ) -> Dict[str, Any]:
        """
        Create a feed document for uploading feed content.
        
        Args:
            content_type: MIME type of the feed content
            
        Returns:
            Feed document with upload URL and document ID
        """
        ct = content_type.value if isinstance(content_type, FeedContentType) else content_type
        
        data = {
            'contentType': ct,
        }
        
        return self.client.post(
            f'/feeds/{self.API_VERSION}/documents',
            operation='createFeedDocument',
            data=data,
            add_marketplace=False,
        )
    
    def get_feed_document(
        self,
        feed_document_id: str,
    ) -> Dict[str, Any]:
        """
        Get a feed document.
        
        Args:
            feed_document_id: Feed document ID
            
        Returns:
            Feed document with download URL
        """
        return self.client.get(
            f'/feeds/{self.API_VERSION}/documents/{feed_document_id}',
            operation='getFeedDocument',
            add_marketplace=False,
        )
    
    def upload_feed_document(
        self,
        feed_document: Dict[str, Any],
        content: Union[str, bytes, BinaryIO],
        compress: bool = True,
    ) -> bool:
        """
        Upload content to a feed document.
        
        Args:
            feed_document: Feed document from create_feed_document
            content: Feed content (string, bytes, or file-like object)
            compress: Whether to gzip compress the content
            
        Returns:
            True if upload successful
            
        Raises:
            SPAPIError: If upload fails
        """
        url = feed_document['url']
        
        # Convert content to bytes
        content_bytes: bytes
        if isinstance(content, str):
            content_bytes = content.encode('utf-8')
        elif hasattr(content, 'read'):
            content_bytes = content.read()
            if isinstance(content_bytes, str):
                content_bytes = content_bytes.encode('utf-8')
        else:
            content_bytes = content
        
        # Compress if requested
        upload_content: bytes
        content_encoding: Optional[str] = None

        if compress:
            buffer = io.BytesIO()
            with gzip.GzipFile(fileobj=buffer, mode='wb') as gz:
                gz.write(content_bytes)
            upload_content = buffer.getvalue()
            content_encoding = 'gzip'
        else:
            upload_content = content_bytes
            content_encoding = None
        
        # Build headers
        headers = {
            'Content-Type': feed_document.get('contentType', 'application/json'),
        }
        if content_encoding:
            headers['Content-Encoding'] = content_encoding
        
        _logger.debug(
            "Uploading feed document (%d bytes, compressed=%s)",
            len(upload_content), compress
        )
        
        try:
            response = self._upload_session.put(
                url,
                data=upload_content,
                headers=headers,
                timeout=300,  # 5 minute timeout for large uploads
            )
            
            if response.status_code in (200, 201):
                _logger.info(
                    "Feed document uploaded successfully (%d bytes)",
                    len(upload_content)
                )
                return True
            else:
                raise SPAPIError(
                    f"Feed document upload failed: {response.status_code} {response.text}",
                    status_code=response.status_code,
                )
                
        except requests.RequestException as e:
            _logger.error("Feed document upload failed: %s", str(e))
            raise SPAPIError(f"Feed document upload failed: {str(e)}")
    
    def download_feed_document(
        self,
        feed_document_id: str,
        decompress: bool = True,
    ) -> bytes:
        """
        Download content from a feed document.
        
        Args:
            feed_document_id: Feed document ID
            decompress: Whether to auto-decompress gzipped content
            
        Returns:
            Feed document content as bytes
        """
        # Get document info
        doc = self.get_feed_document(feed_document_id)
        url = doc['url']
        compression = doc.get('compressionAlgorithm')
        
        _logger.debug("Downloading feed document %s", feed_document_id)
        
        try:
            response = self._upload_session.get(url, timeout=300)
            
            if response.status_code != 200:
                raise SPAPIError(
                    f"Feed document download failed: {response.status_code}",
                    status_code=response.status_code,
                )
            
            content = response.content
            
            # Decompress if needed
            if decompress and compression == 'GZIP':
                content = gzip.decompress(content)
            
            _logger.info(
                "Feed document downloaded (%d bytes)",
                len(content)
            )
            
            return content
            
        except requests.RequestException as e:
            _logger.error("Feed document download failed: %s", str(e))
            raise SPAPIError(f"Feed document download failed: {str(e)}")
    
    # =========================================================================
    # Feed Submission
    # =========================================================================
    
    def create_feed(
        self,
        feed_type: Union[str, FeedType],
        input_feed_document_id: str,
        marketplace_ids: Optional[List[str]] = None,
        feed_options: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a feed submission.
        
        Args:
            feed_type: Type of feed
            input_feed_document_id: Feed document ID with uploaded content
            marketplace_ids: Marketplaces to submit to
            feed_options: Feed-specific options
            
        Returns:
            Feed submission result with feed ID
        """
        ft = feed_type.value if isinstance(feed_type, FeedType) else feed_type
        
        data: Dict[str, Any] = {
            'feedType': ft,
            'inputFeedDocumentId': input_feed_document_id,
            'marketplaceIds': marketplace_ids or [self.client.marketplace_id],
        }
        
        if feed_options:
            data['feedOptions'] = feed_options
        
        return self.client.post(
            f'/feeds/{self.API_VERSION}/feeds',
            operation='createFeed',
            data=data,
            add_marketplace=False,
        )
    
    def get_feed(
        self,
        feed_id: str,
    ) -> Dict[str, Any]:
        """
        Get a feed submission status.
        
        Args:
            feed_id: Feed ID
            
        Returns:
            Feed submission details and status
        """
        return self.client.get(
            f'/feeds/{self.API_VERSION}/feeds/{feed_id}',
            operation='getFeed',
            add_marketplace=False,
        )
    
    def get_feeds(
        self,
        feed_types: Optional[List[Union[str, FeedType]]] = None,
        marketplace_ids: Optional[List[str]] = None,
        page_size: int = 10,
        processing_statuses: Optional[List[Union[str, FeedStatus]]] = None,
        created_since: Union[datetime, str, None] = None,
        created_until: Union[datetime, str, None] = None,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get a list of feeds.
        
        Args:
            feed_types: Filter by feed types
            marketplace_ids: Filter by marketplaces
            page_size: Number of results per page
            processing_statuses: Filter by processing status
            created_since: Filter by creation date
            created_until: Filter by creation date
            next_token: Pagination token
            
        Returns:
            List of feeds
        """
        def format_datetime(dt: Union[datetime, str, None]) -> Optional[str]:
            if dt is None:
                return None
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            return dt
        
        params: Dict[str, Any] = {
            'pageSize': page_size,
        }
        
        if feed_types:
            types = [ft.value if isinstance(ft, FeedType) else ft for ft in feed_types]
            params['feedTypes'] = ','.join(types)
        if marketplace_ids:
            params['marketplaceIds'] = ','.join(marketplace_ids)
        elif self.client.marketplace_id:
            params['marketplaceIds'] = self.client.marketplace_id
        if processing_statuses:
            statuses = [s.value if isinstance(s, FeedStatus) else s for s in processing_statuses]
            params['processingStatuses'] = ','.join(statuses)
        if created_since:
            params['createdSince'] = format_datetime(created_since) or ""
        if created_until:
            params['createdUntil'] = format_datetime(created_until) or ""
        if next_token:
            params['nextToken'] = next_token
        
        return self.client.get(
            f'/feeds/{self.API_VERSION}/feeds',
            operation='getFeeds',
            params=params,
            add_marketplace=False,
        )
    
    def cancel_feed(
        self,
        feed_id: str,
    ) -> Dict[str, Any]:
        """
        Cancel a feed submission.
        
        Args:
            feed_id: Feed ID to cancel
            
        Returns:
            Cancellation result
        """
        return self.client.delete(
            f'/feeds/{self.API_VERSION}/feeds/{feed_id}',
            operation='cancelFeed',
            add_marketplace=False,
        )
    
    # =========================================================================
    # High-Level Feed Operations
    # =========================================================================
    
    def submit_feed(
        self,
        feed_type: Union[str, FeedType],
        content: Union[str, bytes, Dict[str, Any], List[Any]],
        marketplace_ids: Optional[List[str]] = None,
        feed_options: Optional[Dict[str, str]] = None,
        wait_for_completion: bool = False,
        poll_interval: int = 30,
        max_wait: int = 3600,
    ) -> Dict[str, Any]:
        """
        High-level method to submit a feed in one call.
        
        Args:
            feed_type: Type of feed
            content: Feed content (string, bytes, dict, or list)
            marketplace_ids: Marketplaces to submit to
            feed_options: Feed-specific options
            wait_for_completion: Whether to wait for feed to complete
            poll_interval: Seconds between status checks
            max_wait: Maximum seconds to wait
            
        Returns:
            Feed submission result (or final status if wait_for_completion)
        """
        ft = feed_type.value if isinstance(feed_type, FeedType) else feed_type
        
        # Determine content type
        content_type = self.FEED_CONTENT_TYPES.get(
            FeedType(ft) if isinstance(ft, str) else ft,  # type: ignore
            FeedContentType.JSON
        )
        
        # Serialize content if needed
        content_str: Union[str, bytes]
        if isinstance(content, (dict, list)):
            content_str = json.dumps(content)
        elif isinstance(content, bytes):
            content_str = content
        else:
            content_str = content
        
        # Step 1: Create feed document
        _logger.info("Creating feed document for %s", ft)
        doc = self.create_feed_document(content_type)
        feed_document_id = doc['feedDocumentId']
        
        # Step 2: Upload content
        _logger.info("Uploading feed content to document %s", feed_document_id)
        self.upload_feed_document(doc, content_str)
        
        # Step 3: Create feed
        _logger.info("Submitting feed %s", ft)
        feed = self.create_feed(
            feed_type=ft,
            input_feed_document_id=feed_document_id,
            marketplace_ids=marketplace_ids,
            feed_options=feed_options,
        )
        
        feed_id = feed['feedId']
        _logger.info("Feed submitted: %s", feed_id)
        
        # Step 4: Optionally wait for completion
        if wait_for_completion:
            return self.wait_for_feed(
                feed_id,
                poll_interval=poll_interval,
                max_wait=max_wait,
            )
        
        return feed
    
    def wait_for_feed(
        self,
        feed_id: str,
        poll_interval: int = 30,
        max_wait: int = 3600,
    ) -> Dict[str, Any]:
        """
        Wait for a feed to complete processing.
        
        Args:
            feed_id: Feed ID
            poll_interval: Seconds between status checks
            max_wait: Maximum seconds to wait
            
        Returns:
            Final feed status
            
        Raises:
            SPAPIError: If feed fails or times out
        """
        start_time = time.time()
        terminal_statuses = [FeedStatus.DONE, FeedStatus.CANCELLED, FeedStatus.FATAL]
        
        _logger.info("Waiting for feed %s to complete", feed_id)
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait:
                raise SPAPIError(
                    f"Feed {feed_id} timed out after {max_wait} seconds"
                )
            
            feed = self.get_feed(feed_id)
            status = feed.get('processingStatus')
            
            _logger.debug(
                "Feed %s status: %s (%.0fs elapsed)",
                feed_id, status, elapsed
            )
            
            if status in [s.value for s in terminal_statuses]:
                _logger.info(
                    "Feed %s completed with status: %s (%.0fs)",
                    feed_id, status, elapsed
                )
                return feed
            
            time.sleep(poll_interval)
    
    def get_feed_result(
        self,
        feed_id: str,
        decode: bool = True,
    ) -> Union[bytes, str, Dict[str, Any], List[Any]]:
        """
        Get the result/report for a completed feed.
        
        Args:
            feed_id: Feed ID
            decode: Whether to decode the result
            
        Returns:
            Feed result content
        """
        # Get feed to get result document ID
        feed = self.get_feed(feed_id)
        
        status = feed.get('processingStatus')
        if status not in [FeedStatus.DONE.value, FeedStatus.FATAL.value]:
            raise SPAPIError(
                f"Feed {feed_id} is not complete (status: {status})"
            )
        
        result_document_id = feed.get('resultFeedDocumentId')
        if not result_document_id:
            _logger.warning("Feed %s has no result document", feed_id)
            return {}
        
        # Download result
        content = self.download_feed_document(result_document_id)
        
        if not decode:
            return content
        
        # Try to decode
        try:
            text = content.decode('utf-8')
            
            # Try to parse as JSON
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
                
        except UnicodeDecodeError:
            return content
    
    # =========================================================================
    # Feed Content Builders
    # =========================================================================
    
    def build_json_listings_feed(
        self,
        messages: List[Dict[str, Any]],
        header: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build a JSON listings feed.
        
        Args:
            messages: List of listing messages
            header: Optional header info
            
        Returns:
            JSON feed structure
        """
        feed = {
            'header': header or {
                'sellerId': '',  # Will be filled by Amazon
                'version': '2.0',
            },
            'messages': messages,
        }
        
        return feed
    
    def build_listing_message(
        self,
        message_id: int,
        sku: str,
        operation_type: str,
        product_type: str,
        attributes: Dict[str, Any],
        requirements: str = "LISTING",
    ) -> Dict[str, Any]:
        """
        Build a single listing message for JSON listings feed.
        
        Args:
            message_id: Unique message ID (1, 2, 3, ...)
            sku: Seller SKU
            operation_type: Operation (UPDATE, DELETE, PARTIAL_UPDATE)
            product_type: Amazon product type
            attributes: Product attributes
            requirements: Listing requirements
            
        Returns:
            Listing message dictionary
        """
        return {
            'messageId': message_id,
            'sku': sku,
            'operationType': operation_type,
            'productType': product_type,
            'requirements': requirements,
            'attributes': attributes,
        }
    
    def build_price_and_quantity_message(
        self,
        sku: str,
        price: Optional[float] = None,
        quantity: Optional[int] = None,
        currency_code: str = "EUR",
    ) -> Dict[str, Any]:
        """
        Build a price and quantity update message.
        
        Args:
            sku: Seller SKU
            price: New price (optional)
            quantity: New quantity (optional)
            currency_code: Currency code
            
        Returns:
            Price/quantity message
        """
        message: Dict[str, Any] = {
            'sku': sku,
            'operationType': 'PARTIAL_UPDATE',
        }
        
        attributes: Dict[str, Any] = {}
        
        if price is not None:
            attributes['purchasable_offer'] = [{
                'marketplace_id': self.client.marketplace_id,
                'currency': currency_code,
                'our_price': [{
                    'schedule': [{
                        'value_with_tax': price
                    }]
                }]
            }]
        
        if quantity is not None:
            attributes['fulfillment_availability'] = [{
                'fulfillment_channel_code': 'DEFAULT',
                'quantity': quantity,
                'marketplace_id': self.client.marketplace_id,
            }]
        
        message['attributes'] = attributes
        
        return message
    
    def build_inventory_feed_xml(
        self,
        items: List[Dict[str, Any]],
        merchant_id: str = "",
    ) -> str:
        """
        Build XML inventory feed.
        
        Args:
            items: List of items with sku and quantity
            merchant_id: Seller merchant ID
            
        Returns:
            XML feed string
        """
        messages = []
        for i, item in enumerate(items, 1):
            messages.append(f"""
    <Message>
        <MessageID>{i}</MessageID>
        <OperationType>Update</OperationType>
        <Inventory>
            <SKU>{item['sku']}</SKU>
            <Quantity>{item['quantity']}</Quantity>
        </Inventory>
    </Message>""")
        
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<AmazonEnvelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="amzn-envelope.xsd">
    <Header>
        <DocumentVersion>1.01</DocumentVersion>
        <MerchantIdentifier>{merchant_id}</MerchantIdentifier>
    </Header>
    <MessageType>Inventory</MessageType>
{''.join(messages)}
</AmazonEnvelope>"""
        
        return xml
    
    def build_price_feed_xml(
        self,
        items: List[Dict[str, Any]],
        merchant_id: str = "",
        currency_code: str = "EUR",
    ) -> str:
        """
        Build XML price feed.
        
        Args:
            items: List of items with sku and price
            merchant_id: Seller merchant ID
            currency_code: Currency code
            
        Returns:
            XML feed string
        """
        messages = []
        for i, item in enumerate(items, 1):
            price_element = f"""
            <StandardPrice currency="{currency_code}">{item['price']:.2f}</StandardPrice>"""
            
            if 'sale_price' in item:
                sale_start = item.get('sale_start', datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'))
                sale_end = item.get('sale_end', (datetime.now(timezone.utc) + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S'))
                price_element += f"""
            <Sale>
                <StartDate>{sale_start}</StartDate>
                <EndDate>{sale_end}</EndDate>
                <SalePrice currency="{currency_code}">{item['sale_price']:.2f}</SalePrice>
            </Sale>"""
            
            messages.append(f"""
    <Message>
        <MessageID>{i}</MessageID>
        <OperationType>Update</OperationType>
        <Price>
            <SKU>{item['sku']}</SKU>{price_element}
        </Price>
    </Message>""")
        
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<AmazonEnvelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="amzn-envelope.xsd">
    <Header>
        <DocumentVersion>1.01</DocumentVersion>
        <MerchantIdentifier>{merchant_id}</MerchantIdentifier>
    </Header>
    <MessageType>Price</MessageType>
{''.join(messages)}
</AmazonEnvelope>"""
        
        return xml
    
    def build_fulfillment_feed_xml(
        self,
        shipments: List[Dict[str, Any]],
        merchant_id: str = "",
    ) -> str:
        """
        Build XML order fulfillment feed.
        
        Args:
            shipments: List of shipment info with order_id, carrier, tracking, etc.
            merchant_id: Seller merchant ID
            
        Returns:
            XML feed string
        """
        messages = []
        for i, shipment in enumerate(shipments, 1):
            items_xml = ""
            if 'items' in shipment:
                for item in shipment['items']:
                    items_xml += f"""
                <Item>
                    <AmazonOrderItemCode>{item['order_item_id']}</AmazonOrderItemCode>
                    <Quantity>{item['quantity']}</Quantity>
                </Item>"""
            
            messages.append(f"""
    <Message>
        <MessageID>{i}</MessageID>
        <OperationType>Update</OperationType>
        <OrderFulfillment>
            <AmazonOrderID>{shipment['order_id']}</AmazonOrderID>
            <FulfillmentDate>{shipment.get('fulfillment_date', datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))}</FulfillmentDate>
            <FulfillmentData>
                <CarrierCode>{shipment.get('carrier_code', 'Other')}</CarrierCode>
                <ShippingMethod>{shipment.get('shipping_method', 'Standard')}</ShippingMethod>
                <ShipperTrackingNumber>{shipment['tracking_number']}</ShipperTrackingNumber>
            </FulfillmentData>{items_xml}
        </OrderFulfillment>
    </Message>""")
        
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<AmazonEnvelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="amzn-envelope.xsd">
    <Header>
        <DocumentVersion>1.01</DocumentVersion>
        <MerchantIdentifier>{merchant_id}</MerchantIdentifier>
    </Header>
    <MessageType>OrderFulfillment</MessageType>
{''.join(messages)}
</AmazonEnvelope>"""
        
        return xml
    
    def build_payment_adjustment_feed_xml(
        self,
        adjustments: List[Dict[str, Any]],
        merchant_id: str = "",
    ) -> str:
        """
        Build XML payment adjustment (refund) feed.

        Args:
            adjustments: List of adjustment info with order_id, order_item_id, reason, components
            merchant_id: Seller merchant ID

        Returns:
            XML feed string
        """
        messages = []
        for i, adj in enumerate(adjustments, 1):
            components_xml = ""
            for comp in adj.get('components', []):
                components_xml += f"""
                    <Component>
                        <Type>{comp['type']}</Type>
                        <Amount currency="{comp['currency']}">{comp['amount']:.2f}</Amount>
                    </Component>"""

            messages.append(f"""
    <Message>
        <MessageID>{i}</MessageID>
        <OrderAdjustment>
            <AmazonOrderID>{adj['order_id']}</AmazonOrderID>
            <AdjustedItem>
                <AmazonOrderItemCode>{adj['order_item_id']}</AmazonOrderItemCode>
                <MerchantAdjustmentItemID>{adj.get('adjustment_id', '')}</MerchantAdjustmentItemID>
                <AdjustmentReason>{adj.get('reason', 'NoLongerNeeded')}</AdjustmentReason>
                <ItemPriceAdjustments>{components_xml}
                </ItemPriceAdjustments>
            </AdjustedItem>
        </OrderAdjustment>
    </Message>""")

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<AmazonEnvelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="amzn-envelope.xsd">
    <Header>
        <DocumentVersion>1.01</DocumentVersion>
        <MerchantIdentifier>{merchant_id}</MerchantIdentifier>
    </Header>
    <MessageType>OrderAdjustment</MessageType>
{''.join(messages)}
</AmazonEnvelope>"""

        return xml

    # =========================================================================
    # Convenience Methods
    # =========================================================================
    
    def submit_inventory_update(
        self,
        items: List[Dict[str, Any]],
        wait_for_completion: bool = True,
    ) -> Dict[str, Any]:
        """
        Submit an inventory update feed.
        
        Args:
            items: List of items with sku and quantity
            wait_for_completion: Whether to wait for completion
            
        Returns:
            Feed result
        """
        xml_content = self.build_inventory_feed_xml(items)
        
        return self.submit_feed(
            feed_type=FeedType.POST_INVENTORY_AVAILABILITY_DATA,
            content=xml_content,
            wait_for_completion=wait_for_completion,
        )
    
    def submit_price_update(
        self,
        items: List[Dict[str, Any]],
        currency_code: str = "EUR",
        wait_for_completion: bool = True,
    ) -> Dict[str, Any]:
        """
        Submit a price update feed.
        
        Args:
            items: List of items with sku and price
            currency_code: Currency code
            wait_for_completion: Whether to wait for completion
            
        Returns:
            Feed result
        """
        xml_content = self.build_price_feed_xml(items, currency_code=currency_code)
        
        return self.submit_feed(
            feed_type=FeedType.POST_PRODUCT_PRICING_DATA,
            content=xml_content,
            wait_for_completion=wait_for_completion,
        )
    
    def submit_fulfillment_update(
        self,
        shipments: List[Dict[str, Any]],
        wait_for_completion: bool = True,
    ) -> Dict[str, Any]:
        """
        Submit an order fulfillment feed.
        
        Args:
            shipments: List of shipment info
            wait_for_completion: Whether to wait for completion
            
        Returns:
            Feed result
        """
        xml_content = self.build_fulfillment_feed_xml(shipments)
        
        return self.submit_feed(
            feed_type=FeedType.POST_ORDER_FULFILLMENT_DATA,
            content=xml_content,
            wait_for_completion=wait_for_completion,
        )
    
    def submit_payment_adjustment(
        self,
        adjustments: List[Dict[str, Any]],
        merchant_id: str = "",
        wait_for_completion: bool = True,
    ) -> Dict[str, Any]:
        """
        Submit a payment adjustment (refund) feed.

        Args:
            adjustments: List of adjustment info
            merchant_id: Seller merchant ID
            wait_for_completion: Whether to wait for completion

        Returns:
            Feed result
        """
        xml_content = self.build_payment_adjustment_feed_xml(adjustments, merchant_id=merchant_id)

        return self.submit_feed(
            feed_type=FeedType.POST_PAYMENT_ADJUSTMENT_DATA,
            content=xml_content,
            wait_for_completion=wait_for_completion,
        )

    def submit_json_listings_feed(
        self,
        messages: List[Dict[str, Any]],
        wait_for_completion: bool = True,
    ) -> Dict[str, Any]:
        """
        Submit a JSON listings feed.
        
        Args:
            messages: Listing messages
            wait_for_completion: Whether to wait for completion
            
        Returns:
            Feed result
        """
        feed_content = self.build_json_listings_feed(messages)
        
        return self.submit_feed(
            feed_type=FeedType.JSON_LISTINGS_FEED,
            content=feed_content,
            wait_for_completion=wait_for_completion,
        )
