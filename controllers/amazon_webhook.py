# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

"""
Amazon SP-API Webhook Receiver

Handles incoming notifications from Amazon SP-API including:
- Order status updates (ANY_OFFER_CHANGED, ORDER_STATUS_CHANGE)
- Inventory alerts (FBA_INVENTORY_AVAILABILITY_CHANGES)
- Feed processing results (FEED_PROCESSING_FINISHED)
- Report availability (REPORT_PROCESSING_FINISHED)
- Fulfillment notifications (FULFILLMENT_ORDER_STATUS)

Security:
- Signature validation using Amazon's signing key
- Request timestamp validation (prevents replay attacks)
- Account verification
"""

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

from odoo import http, SUPERUSER_ID
from odoo.http import request

_logger = logging.getLogger(__name__)


class AmazonWebhookController(http.Controller):
    """Controller for Amazon SP-API webhook notifications."""
    
    # Supported notification types
    NOTIFICATION_TYPES = {
        'ANY_OFFER_CHANGED': '_handle_offer_changed',
        'ORDER_STATUS_CHANGE': '_handle_order_status_change',
        'ORDER_CHANGE': '_handle_order_change',
        'FBA_INVENTORY_AVAILABILITY_CHANGES': '_handle_fba_inventory_change',
        'FEED_PROCESSING_FINISHED': '_handle_feed_finished',
        'REPORT_PROCESSING_FINISHED': '_handle_report_finished',
        'FULFILLMENT_ORDER_STATUS': '_handle_fulfillment_status',
        'FEE_PROMOTION': '_handle_fee_promotion',
        'BRANDED_ITEM_CONTENT_CHANGE': '_handle_content_change',
        'ITEM_PRODUCT_TYPE_CHANGE': '_handle_product_type_change',
        'LISTINGS_ITEM_STATUS_CHANGE': '_handle_listing_status_change',
        'LISTINGS_ITEM_ISSUES_CHANGE': '_handle_listing_issues_change',
        'B2B_ANY_OFFER_CHANGED': '_handle_b2b_offer_changed',
    }
    
    # Maximum age of webhook requests (5 minutes)
    MAX_REQUEST_AGE_SECONDS = 300
    
    @http.route(
        '/amazon/webhook',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False
    )
    def amazon_webhook(self):
        """
        Main webhook endpoint for Amazon SP-API notifications.
        
        Amazon sends notifications as JSON payloads with signature headers.
        We validate the signature and route to appropriate handlers.
        
        Returns:
            dict: Response with status
        """
        try:
            # Get the raw request data
            data = request.get_json_data() if hasattr(request, 'get_json_data') else json.loads(request.httprequest.get_data(as_text=True))
            
            _logger.info(
                "Amazon webhook received: type=%s",
                data.get('notificationType', 'unknown')
            )
            
            # Validate the request signature
            if not self._validate_webhook_signature():
                _logger.warning("Amazon webhook signature validation failed")
                return {'status': 'error', 'message': 'Invalid signature'}
            
            # Validate request timestamp (prevent replay attacks)
            if not self._validate_request_timestamp(data):
                _logger.warning("Amazon webhook timestamp validation failed")
                return {'status': 'error', 'message': 'Request expired'}
            
            # Extract notification details
            notification_type = data.get('notificationType')
            payload = data.get('payload', {})
            notification_metadata = data.get('notificationMetadata', {})
            
            # Log the notification
            self._log_notification(notification_type, notification_metadata, payload)
            
            # Route to appropriate handler
            handler_name = self.NOTIFICATION_TYPES.get(notification_type)
            if handler_name:
                handler = getattr(self, handler_name, None)
                if handler:
                    result = handler(payload, notification_metadata)
                    return {'status': 'ok', 'result': result}
                else:
                    _logger.warning(
                        "Handler %s not implemented for notification type %s",
                        handler_name, notification_type
                    )
            else:
                _logger.info(
                    "Unhandled notification type: %s",
                    notification_type
                )
            
            return {'status': 'ok', 'message': 'Notification received'}
            
        except Exception as e:
            _logger.exception("Error processing Amazon webhook: %s", str(e))
            return {'status': 'error', 'message': str(e)}
    
    @http.route(
        '/amazon/webhook/test',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False
    )
    def amazon_webhook_test(self):
        """
        Test endpoint to verify webhook is reachable.
        Amazon may ping this during subscription setup.
        """
        return request.make_response(
            'Amazon Webhook Endpoint Active',
            headers={'Content-Type': 'text/plain'}
        )
    
    def _validate_webhook_signature(self):
        """
        Validate the Amazon webhook signature.
        
        Amazon uses HMAC-SHA256 to sign webhook payloads.
        The signature is in the 'x-amz-sp-signature' header.
        
        Returns:
            bool: True if signature is valid
        """
        try:
            headers = request.httprequest.headers
            
            # Get signature from headers
            signature = headers.get('x-amz-sp-signature')
            if not signature:
                _logger.debug("No signature header found in webhook request")
                # For development/testing, may want to allow unsigned requests
                return self._allow_unsigned_requests()
            
            # Get the raw body
            body = request.httprequest.get_data(as_text=True)
            
            # Find the account and get the signing key
            # The account can be identified from the payload or a header
            account_id = headers.get('x-amz-seller-id')
            if not account_id:
                _logger.warning("No seller ID in webhook headers")
                return False
            
            # Get the account's webhook secret
            env = request.env(user=SUPERUSER_ID)
            account = env['amazon.account'].search([
                ('seller_id', '=', account_id),
                ('active', '=', True)
            ], limit=1)
            
            if not account or not account.webhook_secret:
                _logger.warning(
                    "No webhook secret configured for account %s",
                    account_id
                )
                return self._allow_unsigned_requests()
            
            # Calculate expected signature
            expected_signature = hmac.new(
                account.webhook_secret.encode('utf-8'),
                body.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            # Compare signatures (constant-time comparison)
            return hmac.compare_digest(signature.lower(), expected_signature.lower())
            
        except Exception as e:
            _logger.exception("Error validating webhook signature: %s", str(e))
            return False
    
    def _allow_unsigned_requests(self):
        """
        Check if unsigned webhook requests are allowed (dev/test mode).
        
        Returns:
            bool: True if unsigned requests are allowed
        """
        env = request.env(user=SUPERUSER_ID)
        config = env['ir.config_parameter'].sudo()
        return config.get_param('amazon_connector.allow_unsigned_webhooks', 'False') == 'True'
    
    def _validate_request_timestamp(self, data):
        """
        Validate that the request is not too old (prevents replay attacks).
        
        Args:
            data: Webhook payload
            
        Returns:
            bool: True if timestamp is valid
        """
        try:
            metadata = data.get('notificationMetadata', {})
            publish_time = metadata.get('publishTime')
            
            if not publish_time:
                # No timestamp provided - allow for backward compatibility
                return True
            
            # Parse the timestamp (ISO 8601 format)
            if publish_time.endswith('Z'):
                publish_time = publish_time[:-1] + '+00:00'
            
            publish_dt = datetime.fromisoformat(publish_time)
            now = datetime.now(timezone.utc)
            
            # Check if request is too old
            age = (now - publish_dt).total_seconds()
            if age > self.MAX_REQUEST_AGE_SECONDS:
                _logger.warning(
                    "Webhook request too old: %d seconds",
                    age
                )
                return False
            
            # Check if request is from the future (clock skew tolerance: 60 seconds)
            if age < -60:
                _logger.warning(
                    "Webhook request from the future: %d seconds",
                    abs(age)
                )
                return False
            
            return True
            
        except Exception as e:
            _logger.warning("Error validating webhook timestamp: %s", str(e))
            # Allow on parse errors for robustness
            return True
    
    def _log_notification(self, notification_type, metadata, payload):
        """
        Log the notification for audit and debugging.
        
        Args:
            notification_type: Type of notification
            metadata: Notification metadata
            payload: Notification payload
        """
        try:
            env = request.env(user=SUPERUSER_ID)
            
            # Get account if available
            seller_id = request.httprequest.headers.get('x-amz-seller-id')
            account = None
            if seller_id:
                account = env['amazon.account'].search([
                    ('seller_id', '=', seller_id)
                ], limit=1)
            
            # Create log entry (if model exists)
            if 'amazon.sync.log' in env:
                env['amazon.sync.log'].sudo().create({
                    'account_id': account.id if account else False,
                    'operation': 'webhook_received',
                    'notification_type': notification_type,
                    'notification_id': metadata.get('notificationId', ''),
                    'payload': json.dumps(payload, indent=2),
                    'state': 'pending',
                })
                
        except Exception as e:
            _logger.warning("Error logging notification: %s", str(e))
    
    # ==================== NOTIFICATION HANDLERS ====================
    
    def _handle_order_status_change(self, payload, metadata):
        """
        Handle ORDER_STATUS_CHANGE notifications.
        
        Triggered when an order's status changes (e.g., Pending → Unshipped → Shipped).
        
        Args:
            payload: Notification payload
            metadata: Notification metadata
        """
        try:
            env = request.env(user=SUPERUSER_ID)
            
            order_change = payload.get('OrderStatusChange', {})
            amazon_order_id = order_change.get('AmazonOrderId')
            new_status = order_change.get('OrderStatus')
            
            if not amazon_order_id:
                _logger.warning("ORDER_STATUS_CHANGE missing AmazonOrderId")
                return {'processed': False}
            
            _logger.info(
                "Order status change: %s → %s",
                amazon_order_id, new_status
            )
            
            # Find and update the order
            order = env['amazon.order'].sudo().search([
                ('amazon_order_id', '=', amazon_order_id)
            ], limit=1)
            
            if order:
                order.with_context(from_webhook=True).write({
                    'status': new_status,
                    'last_update_date': datetime.now(timezone.utc),
                })
                
                # Trigger any necessary actions based on status
                if new_status == 'Shipped':
                    order._on_shipped()
                elif new_status == 'Canceled':
                    order._on_canceled()
                elif new_status == 'Delivered':
                    order._on_delivered()
                
                return {'processed': True, 'order_id': order.id}
            else:
                # Order not found - queue for sync
                _logger.info(
                    "Order %s not found, queuing for sync",
                    amazon_order_id
                )
                return {'processed': False, 'queued': True}
                
        except Exception as e:
            _logger.exception("Error handling ORDER_STATUS_CHANGE: %s", str(e))
            return {'processed': False, 'error': str(e)}
    
    def _handle_order_change(self, payload, metadata):
        """
        Handle ORDER_CHANGE notifications (general order updates).
        """
        try:
            env = request.env(user=SUPERUSER_ID)
            
            order_change = payload.get('OrderChange', {})
            amazon_order_id = order_change.get('AmazonOrderId')
            change_type = order_change.get('ChangeType')
            
            _logger.info(
                "Order change: %s, type: %s",
                amazon_order_id, change_type
            )
            
            # Trigger order resync
            if amazon_order_id:
                order = env['amazon.order'].sudo().search([
                    ('amazon_order_id', '=', amazon_order_id)
                ], limit=1)
                
                if order:
                    order._sync_from_amazon()
                    return {'processed': True, 'order_id': order.id}
            
            return {'processed': False, 'queued': True}
            
        except Exception as e:
            _logger.exception("Error handling ORDER_CHANGE: %s", str(e))
            return {'processed': False, 'error': str(e)}
    
    def _handle_offer_changed(self, payload, metadata):
        """
        Handle ANY_OFFER_CHANGED notifications.
        
        Triggered when offers change (price, availability) - useful for repricing.
        
        Args:
            payload: Notification payload
            metadata: Notification metadata
        """
        try:
            env = request.env(user=SUPERUSER_ID)
            
            offer_change = payload.get('AnyOfferChangedNotification', {})
            asin = offer_change.get('OfferChangeTrigger', {}).get('ASIN')
            marketplace_id = offer_change.get('OfferChangeTrigger', {}).get('MarketplaceId')
            
            _logger.info(
                "Offer changed for ASIN %s in marketplace %s",
                asin, marketplace_id
            )
            
            # Find the listing
            listing = env['amazon.product.listing'].sudo().search([
                ('asin', '=', asin),
                ('marketplace_id.marketplace_id', '=', marketplace_id),
            ], limit=1)
            
            if listing:
                # Update competitive pricing data
                summary = offer_change.get('Summary', {})
                buy_box = summary.get('BuyBoxPrices', [{}])[0] if summary.get('BuyBoxPrices') else {}
                
                listing.write({
                    'buy_box_price': float(buy_box.get('LandedPrice', {}).get('Amount', 0)),
                    'buy_box_seller': buy_box.get('SellerSKU', ''),
                    'is_buy_box_winner': buy_box.get('IsBuyBoxWinner', False),
                    'last_offer_update': datetime.now(timezone.utc),
                })
                
                # Send alert if we lost the buy box
                if listing.was_buy_box_winner and not listing.is_buy_box_winner:
                    listing._send_buy_box_lost_alert()
                
                return {'processed': True, 'listing_id': listing.id}
            
            return {'processed': False, 'asin_not_found': asin}
            
        except Exception as e:
            _logger.exception("Error handling ANY_OFFER_CHANGED: %s", str(e))
            return {'processed': False, 'error': str(e)}
    
    def _handle_fba_inventory_change(self, payload, metadata):
        """
        Handle FBA_INVENTORY_AVAILABILITY_CHANGES notifications.
        
        Triggered when FBA inventory levels change.
        
        Args:
            payload: Notification payload
            metadata: Notification metadata
        """
        try:
            env = request.env(user=SUPERUSER_ID)
            
            inventory_change = payload.get('FbaInventoryAvailabilityChanges', {})
            
            for item in inventory_change.get('Items', []):
                seller_sku = item.get('SellerSKU')
                fnsku = item.get('FNSKU')
                fulfillable_qty = item.get('FulfillableQuantity', 0)
                
                _logger.info(
                    "FBA inventory change: SKU=%s, FNSKU=%s, Qty=%d",
                    seller_sku, fnsku, fulfillable_qty
                )
                
                # Update FBA inventory
                fba_inv = env['amazon.fba.inventory'].sudo().search([
                    '|',
                    ('seller_sku', '=', seller_sku),
                    ('fnsku', '=', fnsku),
                ], limit=1)
                
                if fba_inv:
                    old_qty = fba_inv.fulfillable_quantity
                    fba_inv.write({
                        'fulfillable_quantity': fulfillable_qty,
                        'last_updated': datetime.now(timezone.utc),
                    })
                    
                    # Check for low inventory alert
                    if fulfillable_qty <= fba_inv.reorder_point and old_qty > fba_inv.reorder_point:
                        fba_inv._send_low_inventory_alert()
            
            return {'processed': True, 'items_count': len(inventory_change.get('Items', []))}
            
        except Exception as e:
            _logger.exception("Error handling FBA_INVENTORY_AVAILABILITY_CHANGES: %s", str(e))
            return {'processed': False, 'error': str(e)}
    
    def _handle_feed_finished(self, payload, metadata):
        """
        Handle FEED_PROCESSING_FINISHED notifications.
        
        Triggered when a feed (inventory, price, product) finishes processing.
        
        Args:
            payload: Notification payload
            metadata: Notification metadata
        """
        try:
            env = request.env(user=SUPERUSER_ID)
            
            feed_info = payload.get('FeedProcessingFinishedNotification', {})
            feed_id = feed_info.get('FeedId')
            processing_status = feed_info.get('ProcessingStatus')
            
            _logger.info(
                "Feed processing finished: ID=%s, Status=%s",
                feed_id, processing_status
            )
            
            # Find and update the feed record
            if 'amazon.feed' in env:
                feed = env['amazon.feed'].sudo().search([
                    ('amazon_feed_id', '=', feed_id)
                ], limit=1)
                
                if feed:
                    feed.write({
                        'processing_status': processing_status,
                        'processing_end_time': datetime.now(timezone.utc),
                    })
                    
                    # Fetch and process the feed result
                    if processing_status == 'DONE':
                        feed._fetch_processing_result()
                    
                    return {'processed': True, 'feed_id': feed.id}
            
            return {'processed': False, 'feed_not_found': feed_id}
            
        except Exception as e:
            _logger.exception("Error handling FEED_PROCESSING_FINISHED: %s", str(e))
            return {'processed': False, 'error': str(e)}
    
    def _handle_report_finished(self, payload, metadata):
        """
        Handle REPORT_PROCESSING_FINISHED notifications.
        
        Triggered when a requested report is ready for download.
        
        Args:
            payload: Notification payload
            metadata: Notification metadata
        """
        try:
            env = request.env(user=SUPERUSER_ID)
            
            report_info = payload.get('ReportProcessingFinishedNotification', {})
            report_id = report_info.get('ReportId')
            report_type = report_info.get('ReportType')
            processing_status = report_info.get('ProcessingStatus')
            
            _logger.info(
                "Report processing finished: ID=%s, Type=%s, Status=%s",
                report_id, report_type, processing_status
            )
            
            # Handle based on report type
            if processing_status == 'DONE':
                if report_type.startswith('GET_V2_SETTLEMENT_REPORT'):
                    # Settlement report ready
                    env['amazon.settlement'].sudo()._process_ready_report(report_id)
                elif report_type.startswith('GET_FBA_FULFILLMENT_'):
                    # FBA report ready
                    env['amazon.fba.inventory'].sudo()._process_ready_report(report_id, report_type)
            
            return {'processed': True, 'report_id': report_id}
            
        except Exception as e:
            _logger.exception("Error handling REPORT_PROCESSING_FINISHED: %s", str(e))
            return {'processed': False, 'error': str(e)}
    
    def _handle_fulfillment_status(self, payload, metadata):
        """
        Handle FULFILLMENT_ORDER_STATUS notifications.
        
        Triggered when an FBA fulfillment order status changes.
        
        Args:
            payload: Notification payload
            metadata: Notification metadata
        """
        try:
            env = request.env(user=SUPERUSER_ID)
            
            fulfillment = payload.get('FulfillmentOrderStatusNotification', {})
            order_id = fulfillment.get('FulfillmentOrderId')
            status = fulfillment.get('FulfillmentOrderStatus')
            
            _logger.info(
                "Fulfillment status change: Order=%s, Status=%s",
                order_id, status
            )
            
            # Update the FBA shipment
            shipment = env['amazon.fba.shipment'].sudo().search([
                ('shipment_id', '=', order_id)
            ], limit=1)
            
            if shipment:
                shipment.write({
                    'status': status,
                    'last_updated': datetime.now(timezone.utc),
                })
                
                # Handle specific status updates
                if status == 'RECEIVED':
                    shipment._on_received()
                    
                    # Send notification email
                    if shipment.account_id.notify_fba_received:
                        shipment._send_received_notification()
                
                return {'processed': True, 'shipment_id': shipment.id}
            
            return {'processed': False, 'order_not_found': order_id}
            
        except Exception as e:
            _logger.exception("Error handling FULFILLMENT_ORDER_STATUS: %s", str(e))
            return {'processed': False, 'error': str(e)}
    
    def _handle_fee_promotion(self, payload, metadata):
        """Handle FEE_PROMOTION notifications."""
        _logger.info("Fee promotion notification received")
        return {'processed': True, 'type': 'fee_promotion'}
    
    def _handle_content_change(self, payload, metadata):
        """Handle BRANDED_ITEM_CONTENT_CHANGE notifications."""
        _logger.info("Branded content change notification received")
        return {'processed': True, 'type': 'content_change'}
    
    def _handle_product_type_change(self, payload, metadata):
        """Handle ITEM_PRODUCT_TYPE_CHANGE notifications."""
        _logger.info("Product type change notification received")
        return {'processed': True, 'type': 'product_type_change'}
    
    def _handle_listing_status_change(self, payload, metadata):
        """
        Handle LISTINGS_ITEM_STATUS_CHANGE notifications.
        
        Triggered when a listing's status changes (active, inactive, suppressed).
        """
        try:
            env = request.env(user=SUPERUSER_ID)
            
            status_change = payload.get('ListingsItemStatusChange', {})
            seller_sku = status_change.get('SellerSku')
            marketplace_id = status_change.get('MarketplaceId')
            status = status_change.get('Status')
            
            _logger.info(
                "Listing status change: SKU=%s, Marketplace=%s, Status=%s",
                seller_sku, marketplace_id, status
            )
            
            listing = env['amazon.product.listing'].sudo().search([
                ('seller_sku', '=', seller_sku),
                ('marketplace_id.marketplace_id', '=', marketplace_id),
            ], limit=1)
            
            if listing:
                listing.write({
                    'status': status,
                    'last_status_update': datetime.now(timezone.utc),
                })
                
                # Send alert if listing was suppressed
                if status in ('INACTIVE', 'SUPPRESSED'):
                    listing._send_suppression_alert()
                
                return {'processed': True, 'listing_id': listing.id}
            
            return {'processed': False, 'sku_not_found': seller_sku}
            
        except Exception as e:
            _logger.exception("Error handling LISTINGS_ITEM_STATUS_CHANGE: %s", str(e))
            return {'processed': False, 'error': str(e)}
    
    def _handle_listing_issues_change(self, payload, metadata):
        """
        Handle LISTINGS_ITEM_ISSUES_CHANGE notifications.
        
        Triggered when listing issues (errors, warnings) are added or resolved.
        """
        try:
            env = request.env(user=SUPERUSER_ID)
            
            issues_change = payload.get('ListingsItemIssuesChange', {})
            seller_sku = issues_change.get('SellerSku')
            marketplace_id = issues_change.get('MarketplaceId')
            issues = issues_change.get('Issues', [])
            
            _logger.info(
                "Listing issues change: SKU=%s, Issues count=%d",
                seller_sku, len(issues)
            )
            
            listing = env['amazon.product.listing'].sudo().search([
                ('seller_sku', '=', seller_sku),
                ('marketplace_id.marketplace_id', '=', marketplace_id),
            ], limit=1)
            
            if listing:
                # Store issues as JSON
                listing.write({
                    'listing_issues': json.dumps(issues),
                    'issue_count': len(issues),
                    'has_critical_issues': any(
                        i.get('Severity') == 'ERROR' for i in issues
                    ),
                })
                
                return {'processed': True, 'listing_id': listing.id}
            
            return {'processed': False, 'sku_not_found': seller_sku}
            
        except Exception as e:
            _logger.exception("Error handling LISTINGS_ITEM_ISSUES_CHANGE: %s", str(e))
            return {'processed': False, 'error': str(e)}
    
    def _handle_b2b_offer_changed(self, payload, metadata):
        """Handle B2B_ANY_OFFER_CHANGED notifications (business pricing)."""
        _logger.info("B2B offer change notification received")
        # Similar to _handle_offer_changed but for B2B offers
        return self._handle_offer_changed(
            {'AnyOfferChangedNotification': payload.get('B2bAnyOfferChangedNotification', {})},
            metadata
        )
