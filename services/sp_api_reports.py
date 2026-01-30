# -*- coding: utf-8 -*-
"""
Amazon SP-API Reports API Client

Handles:
- Report generation request
- Report status tracking
- Report document download
- Settlement reports
- Inventory reports
- Order reports
- Performance reports
"""

import csv
import gzip
import io
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union
from enum import Enum

import requests

from .sp_api_client import SPAPIClient, SPAPIError

_logger = logging.getLogger(__name__)


class ReportType(str, Enum):
    """Common Amazon report types."""
    
    # Inventory Reports
    GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA = "GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA"
    GET_FBA_MYI_ALL_INVENTORY_DATA = "GET_FBA_MYI_ALL_INVENTORY_DATA"
    GET_MERCHANT_LISTINGS_ALL_DATA = "GET_MERCHANT_LISTINGS_ALL_DATA"
    GET_MERCHANT_LISTINGS_DATA = "GET_MERCHANT_LISTINGS_DATA"
    GET_MERCHANT_LISTINGS_INACTIVE_DATA = "GET_MERCHANT_LISTINGS_INACTIVE_DATA"
    GET_MERCHANT_LISTINGS_DATA_BACK_COMPAT = "GET_MERCHANT_LISTINGS_DATA_BACK_COMPAT"
    GET_MERCHANT_LISTINGS_DATA_LITE = "GET_MERCHANT_LISTINGS_DATA_LITE"
    GET_MERCHANT_LISTINGS_DATA_LITER = "GET_MERCHANT_LISTINGS_DATA_LITER"
    GET_FLAT_FILE_OPEN_LISTINGS_DATA = "GET_FLAT_FILE_OPEN_LISTINGS_DATA"
    GET_FLAT_FILE_GEO_OPPORTUNITIES = "GET_FLAT_FILE_GEO_OPPORTUNITIES"
    GET_REFERRAL_FEE_PREVIEW_REPORT = "GET_REFERRAL_FEE_PREVIEW_REPORT"
    
    # Order Reports
    GET_FLAT_FILE_ORDERS_DATA = "GET_FLAT_FILE_ORDERS_DATA"
    GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE = "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE"
    GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE = "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE"
    GET_FLAT_FILE_ARCHIVED_ORDERS_DATA_BY_ORDER_DATE = "GET_FLAT_FILE_ARCHIVED_ORDERS_DATA_BY_ORDER_DATE"
    GET_XML_ALL_ORDERS_DATA_BY_LAST_UPDATE = "GET_XML_ALL_ORDERS_DATA_BY_LAST_UPDATE"
    GET_XML_ALL_ORDERS_DATA_BY_ORDER_DATE = "GET_XML_ALL_ORDERS_DATA_BY_ORDER_DATE"
    GET_FLAT_FILE_PENDING_ORDERS_DATA = "GET_FLAT_FILE_PENDING_ORDERS_DATA"
    GET_PENDING_ORDERS_DATA = "GET_PENDING_ORDERS_DATA"
    GET_CONVERGED_FLAT_FILE_PENDING_ORDERS_DATA = "GET_CONVERGED_FLAT_FILE_PENDING_ORDERS_DATA"
    
    # Order Tracking Reports
    GET_FLAT_FILE_ACTIONABLE_ORDER_DATA = "GET_FLAT_FILE_ACTIONABLE_ORDER_DATA"
    GET_ORDER_REPORT_DATA_INVOICING = "GET_ORDER_REPORT_DATA_INVOICING"
    GET_ORDER_REPORT_DATA_TAX = "GET_ORDER_REPORT_DATA_TAX"
    GET_ORDER_REPORT_DATA_SHIPPING = "GET_ORDER_REPORT_DATA_SHIPPING"
    GET_FLAT_FILE_ORDER_REPORT_DATA_INVOICING = "GET_FLAT_FILE_ORDER_REPORT_DATA_INVOICING"
    GET_FLAT_FILE_ORDER_REPORT_DATA_SHIPPING = "GET_FLAT_FILE_ORDER_REPORT_DATA_SHIPPING"
    GET_FLAT_FILE_ORDER_REPORT_DATA_TAX = "GET_FLAT_FILE_ORDER_REPORT_DATA_TAX"
    
    # Returns Reports
    GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA = "GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA"
    GET_FLAT_FILE_RETURNS_DATA_BY_RETURN_DATE = "GET_FLAT_FILE_RETURNS_DATA_BY_RETURN_DATE"
    GET_FLAT_FILE_MFN_SKU_RETURN_ATTRIBUTES_REPORT = "GET_FLAT_FILE_MFN_SKU_RETURN_ATTRIBUTES_REPORT"
    GET_XML_RETURNS_DATA_BY_RETURN_DATE = "GET_XML_RETURNS_DATA_BY_RETURN_DATE"
    
    # FBA Reports
    GET_FBA_ESTIMATED_FBA_FEES_TXT_DATA = "GET_FBA_ESTIMATED_FBA_FEES_TXT_DATA"
    GET_FBA_REIMBURSEMENTS_DATA = "GET_FBA_REIMBURSEMENTS_DATA"
    GET_FBA_FULFILLMENT_INBOUND_NONCOMPLIANCE_DATA = "GET_FBA_FULFILLMENT_INBOUND_NONCOMPLIANCE_DATA"
    GET_FBA_FULFILLMENT_CURRENT_INVENTORY_DATA = "GET_FBA_FULFILLMENT_CURRENT_INVENTORY_DATA"
    GET_FBA_FULFILLMENT_MONTHLY_INVENTORY_DATA = "GET_FBA_FULFILLMENT_MONTHLY_INVENTORY_DATA"
    GET_FBA_INVENTORY_PLANNING_DATA = "GET_FBA_INVENTORY_PLANNING_DATA"
    GET_FBA_STORAGE_FEE_CHARGES_DATA = "GET_FBA_STORAGE_FEE_CHARGES_DATA"
    GET_FBA_FULFILLMENT_LONGTERM_STORAGE_FEE_CHARGES_DATA = "GET_FBA_FULFILLMENT_LONGTERM_STORAGE_FEE_CHARGES_DATA"
    GET_FBA_FULFILLMENT_REMOVAL_ORDER_DETAIL_DATA = "GET_FBA_FULFILLMENT_REMOVAL_ORDER_DETAIL_DATA"
    GET_FBA_FULFILLMENT_REMOVAL_SHIPMENT_DETAIL_DATA = "GET_FBA_FULFILLMENT_REMOVAL_SHIPMENT_DETAIL_DATA"
    GET_FBA_SNS_FORECAST_DATA = "GET_FBA_SNS_FORECAST_DATA"
    GET_FBA_SNS_PERFORMANCE_DATA = "GET_FBA_SNS_PERFORMANCE_DATA"
    GET_FBA_INVENTORY_AGED_DATA = "GET_FBA_INVENTORY_AGED_DATA"
    # Duplicate removed: GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA
    GET_EXCESS_INVENTORY_DATA = "GET_EXCESS_INVENTORY_DATA"
    GET_STRANDED_INVENTORY_UI_DATA = "GET_STRANDED_INVENTORY_UI_DATA"
    GET_STRANDED_INVENTORY_LOADER_DATA = "GET_STRANDED_INVENTORY_LOADER_DATA"
    
    # Settlement Reports
    GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE = "GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE"
    GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE_V2 = "GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE_V2"
    GET_V2_SETTLEMENT_REPORT_DATA_XML = "GET_V2_SETTLEMENT_REPORT_DATA_XML"
    
    # Sales & Traffic Reports
    GET_SALES_AND_TRAFFIC_REPORT = "GET_SALES_AND_TRAFFIC_REPORT"
    GET_FLAT_FILE_SALES_AND_TRAFFIC_REPORT = "GET_FLAT_FILE_SALES_AND_TRAFFIC_REPORT"
    
    # Browse Tree Reports
    GET_XML_BROWSE_TREE_DATA = "GET_XML_BROWSE_TREE_DATA"
    
    # Tax Reports
    GET_FLAT_FILE_SALES_TAX_DATA = "GET_FLAT_FILE_SALES_TAX_DATA"
    SC_VAT_TAX_REPORT = "SC_VAT_TAX_REPORT"
    GET_VAT_TRANSACTION_DATA = "GET_VAT_TRANSACTION_DATA"
    GET_GST_MTR_B2B_CUSTOM = "GET_GST_MTR_B2B_CUSTOM"
    GET_GST_MTR_B2C_CUSTOM = "GET_GST_MTR_B2C_CUSTOM"
    
    # Brand Analytics Reports
    GET_BRAND_ANALYTICS_MARKET_BASKET_REPORT = "GET_BRAND_ANALYTICS_MARKET_BASKET_REPORT"
    GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT = "GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT"
    GET_BRAND_ANALYTICS_REPEAT_PURCHASE_REPORT = "GET_BRAND_ANALYTICS_REPEAT_PURCHASE_REPORT"
    GET_BRAND_ANALYTICS_ALTERNATE_PURCHASE_REPORT = "GET_BRAND_ANALYTICS_ALTERNATE_PURCHASE_REPORT"
    GET_BRAND_ANALYTICS_ITEM_COMPARISON_REPORT = "GET_BRAND_ANALYTICS_ITEM_COMPARISON_REPORT"
    
    # Performance Reports
    GET_V1_SELLER_PERFORMANCE_REPORT = "GET_V1_SELLER_PERFORMANCE_REPORT"
    GET_PROMOTION_PERFORMANCE_REPORT = "GET_PROMOTION_PERFORMANCE_REPORT"
    GET_COUPON_PERFORMANCE_REPORT = "GET_COUPON_PERFORMANCE_REPORT"


class ReportStatus(str, Enum):
    """Report processing status."""
    CANCELLED = "CANCELLED"
    DONE = "DONE"
    FATAL = "FATAL"
    IN_PROGRESS = "IN_PROGRESS"
    IN_QUEUE = "IN_QUEUE"


class ReportScheduleFrequency(str, Enum):
    """Report schedule frequency."""
    PT5M = "PT5M"    # Every 5 minutes
    PT15M = "PT15M"  # Every 15 minutes
    PT30M = "PT30M"  # Every 30 minutes
    PT1H = "PT1H"    # Hourly
    PT2H = "PT2H"    # Every 2 hours
    PT4H = "PT4H"    # Every 4 hours
    PT8H = "PT8H"    # Every 8 hours
    PT12H = "PT12H"  # Every 12 hours
    P1D = "P1D"      # Daily
    P2D = "P2D"      # Every 2 days
    P3D = "P3D"      # Every 3 days
    PT84H = "PT84H"  # Every 84 hours
    P7D = "P7D"      # Weekly
    P14D = "P14D"    # Every 2 weeks
    P15D = "P15D"    # Every 15 days
    P18D = "P18D"    # Every 18 days
    P30D = "P30D"    # Monthly


class SPAPIReports:
    """
    Amazon Reports API Client
    
    Provides access to:
    - Report request creation
    - Report status tracking
    - Report document download
    - Report scheduling
    """
    
    API_VERSION = "2021-06-30"
    
    # Reports containing PII that require RDT
    PII_REPORT_TYPES = {
        ReportType.GET_FLAT_FILE_ORDERS_DATA,
        ReportType.GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE,
        ReportType.GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE,
        ReportType.GET_FLAT_FILE_ARCHIVED_ORDERS_DATA_BY_ORDER_DATE,
        ReportType.GET_XML_ALL_ORDERS_DATA_BY_LAST_UPDATE,
        ReportType.GET_XML_ALL_ORDERS_DATA_BY_ORDER_DATE,
        ReportType.GET_FLAT_FILE_PENDING_ORDERS_DATA,
        ReportType.GET_PENDING_ORDERS_DATA,
        ReportType.GET_CONVERGED_FLAT_FILE_PENDING_ORDERS_DATA,
        ReportType.GET_FLAT_FILE_RETURNS_DATA_BY_RETURN_DATE,
        ReportType.GET_XML_RETURNS_DATA_BY_RETURN_DATE,
        ReportType.GET_VAT_TRANSACTION_DATA,
        ReportType.SC_VAT_TAX_REPORT,
        ReportType.GET_FLAT_FILE_SALES_TAX_DATA,
        ReportType.GET_ORDER_REPORT_DATA_SHIPPING,
        ReportType.GET_FLAT_FILE_ORDER_REPORT_DATA_SHIPPING,
    }

    def __init__(self, client: SPAPIClient):
        """
        Initialize Reports API client.
        
        Args:
            client: Base SP-API client instance
        """
        self.client = client
        self._download_session = requests.Session()
    
    # =========================================================================
    # Report Requests
    # =========================================================================
    
    def create_report(
        self,
        report_type: Union[str, ReportType],
        marketplace_ids: List[str] = None,
        data_start_time: Union[datetime, str] = None,
        data_end_time: Union[datetime, str] = None,
        report_options: Dict[str, str] = None,
    ) -> Dict[str, Any]:
        """
        Create a report request.
        
        Args:
            report_type: Type of report
            marketplace_ids: Marketplaces to include
            data_start_time: Start of data range
            data_end_time: End of data range
            report_options: Report-specific options
            
        Returns:
            Report request result with report ID
        """
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            return dt
        
        rt = report_type.value if isinstance(report_type, ReportType) else report_type
        
        data = {
            'reportType': rt,
            'marketplaceIds': marketplace_ids or [self.client.marketplace_id],
        }
        
        if data_start_time:
            data['dataStartTime'] = format_datetime(data_start_time)
        if data_end_time:
            data['dataEndTime'] = format_datetime(data_end_time)
        if report_options:
            data['reportOptions'] = report_options
        
        return self.client.post(
            f'/reports/{self.API_VERSION}/reports',
            operation='createReport',
            data=data,
            add_marketplace=False,
        )
    
    def get_report(
        self,
        report_id: str,
    ) -> Dict[str, Any]:
        """
        Get a report request status.
        
        Args:
            report_id: Report ID
            
        Returns:
            Report request details and status
        """
        return self.client.get(
            f'/reports/{self.API_VERSION}/reports/{report_id}',
            operation='getReport',
            add_marketplace=False,
        )
    
    def get_reports(
        self,
        report_types: List[Union[str, ReportType]] = None,
        processing_statuses: List[Union[str, ReportStatus]] = None,
        marketplace_ids: List[str] = None,
        page_size: int = 10,
        created_since: Union[datetime, str] = None,
        created_until: Union[datetime, str] = None,
        next_token: str = None,
    ) -> Dict[str, Any]:
        """
        Get a list of reports.
        
        Args:
            report_types: Filter by report types
            processing_statuses: Filter by processing status
            marketplace_ids: Filter by marketplaces
            page_size: Number of results per page
            created_since: Filter by creation date
            created_until: Filter by creation date
            next_token: Pagination token
            
        Returns:
            List of reports
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
            'pageSize': page_size,
        }
        
        if report_types:
            types = [rt.value if isinstance(rt, ReportType) else rt for rt in report_types]
            params['reportTypes'] = ','.join(types)
        if processing_statuses:
            statuses = [s.value if isinstance(s, ReportStatus) else s for s in processing_statuses]
            params['processingStatuses'] = ','.join(statuses)
        if marketplace_ids:
            params['marketplaceIds'] = ','.join(marketplace_ids)
        elif self.client.marketplace_id:
            params['marketplaceIds'] = self.client.marketplace_id
        if created_since:
            params['createdSince'] = format_datetime(created_since)
        if created_until:
            params['createdUntil'] = format_datetime(created_until)
        if next_token:
            params['nextToken'] = next_token
        
        return self.client.get(
            f'/reports/{self.API_VERSION}/reports',
            operation='getReports',
            params=params,
            add_marketplace=False,
        )
    
    def cancel_report(
        self,
        report_id: str,
    ) -> Dict[str, Any]:
        """
        Cancel a report request.
        
        Args:
            report_id: Report ID to cancel
            
        Returns:
            Cancellation result
        """
        return self.client.delete(
            f'/reports/{self.API_VERSION}/reports/{report_id}',
            operation='cancelReport',
            add_marketplace=False,
        )
    
    # =========================================================================
    # Report Documents
    # =========================================================================
    
    def get_report_document(
        self,
        report_document_id: str,
        report_type: str = None,
    ) -> Dict[str, Any]:
        """
        Get a report document.
        
        Args:
            report_document_id: Report document ID
            report_type: Report type (used to determine if RDT is needed)
            
        Returns:
            Report document with download URL
        """
        restricted_resources = None
        if report_type in self.PII_REPORT_TYPES:
            restricted_resources = [{
                'method': 'GET',
                'path': f'/reports/{self.API_VERSION}/documents/{report_document_id}',
                'dataElements': []  # No data elements required for report documents
            }]

        return self.client.get(
            f'/reports/{self.API_VERSION}/documents/{report_document_id}',
            operation='getReportDocument',
            add_marketplace=False,
            restricted_resources=restricted_resources,
        )
    
    def download_report_document(
        self,
        report_document_id: str,
        decompress: bool = True,
        report_type: str = None,
    ) -> bytes:
        """
        Download content from a report document.
        
        Args:
            report_document_id: Report document ID
            decompress: Whether to auto-decompress gzipped content
            report_type: Report type (used to determine if RDT is needed)
            
        Returns:
            Report document content as bytes
        """
        # Get document info
        doc = self.get_report_document(report_document_id, report_type=report_type)
        url = doc['url']
        compression = doc.get('compressionAlgorithm')
        
        _logger.debug("Downloading report document %s", report_document_id)
        
        try:
            response = self._download_session.get(url, timeout=300)
            
            if response.status_code != 200:
                raise SPAPIError(
                    f"Report document download failed: {response.status_code}",
                    status_code=response.status_code,
                )
            
            content = response.content
            
            # Decompress if needed
            if decompress and compression == 'GZIP':
                content = gzip.decompress(content)
            
            _logger.info(
                "Report document downloaded (%d bytes)",
                len(content)
            )
            
            return content
            
        except requests.RequestException as e:
            _logger.error("Report document download failed: %s", str(e))
            raise SPAPIError(f"Report document download failed: {str(e)}")
    
    # =========================================================================
    # Report Schedules
    # =========================================================================
    
    def create_report_schedule(
        self,
        report_type: Union[str, ReportType],
        period: Union[str, ReportScheduleFrequency],
        marketplace_ids: List[str] = None,
        report_options: Dict[str, str] = None,
        next_report_creation_time: Union[datetime, str] = None,
    ) -> Dict[str, Any]:
        """
        Create a report schedule.
        
        Args:
            report_type: Type of report
            period: Schedule frequency
            marketplace_ids: Marketplaces to include
            report_options: Report-specific options
            next_report_creation_time: When to create next report
            
        Returns:
            Schedule creation result
        """
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            return dt
        
        rt = report_type.value if isinstance(report_type, ReportType) else report_type
        p = period.value if isinstance(period, ReportScheduleFrequency) else period
        
        data = {
            'reportType': rt,
            'period': p,
            'marketplaceIds': marketplace_ids or [self.client.marketplace_id],
        }
        
        if report_options:
            data['reportOptions'] = report_options
        if next_report_creation_time:
            data['nextReportCreationTime'] = format_datetime(next_report_creation_time)
        
        return self.client.post(
            f'/reports/{self.API_VERSION}/schedules',
            operation='createReportSchedule',
            data=data,
            add_marketplace=False,
        )
    
    def get_report_schedule(
        self,
        report_schedule_id: str,
    ) -> Dict[str, Any]:
        """
        Get a report schedule.
        
        Args:
            report_schedule_id: Schedule ID
            
        Returns:
            Schedule details
        """
        return self.client.get(
            f'/reports/{self.API_VERSION}/schedules/{report_schedule_id}',
            operation='getReportSchedule',
            add_marketplace=False,
        )
    
    def get_report_schedules(
        self,
        report_types: List[Union[str, ReportType]] = None,
    ) -> Dict[str, Any]:
        """
        Get all report schedules.
        
        Args:
            report_types: Filter by report types
            
        Returns:
            List of schedules
        """
        params = {}
        
        if report_types:
            types = [rt.value if isinstance(rt, ReportType) else rt for rt in report_types]
            params['reportTypes'] = ','.join(types)
        
        return self.client.get(
            f'/reports/{self.API_VERSION}/schedules',
            operation='getReportSchedules',
            params=params if params else None,
            add_marketplace=False,
        )
    
    def cancel_report_schedule(
        self,
        report_schedule_id: str,
    ) -> Dict[str, Any]:
        """
        Cancel a report schedule.
        
        Args:
            report_schedule_id: Schedule ID to cancel
            
        Returns:
            Cancellation result
        """
        return self.client.delete(
            f'/reports/{self.API_VERSION}/schedules/{report_schedule_id}',
            operation='cancelReportSchedule',
            add_marketplace=False,
        )
    
    # =========================================================================
    # High-Level Report Operations
    # =========================================================================
    
    def request_report(
        self,
        report_type: Union[str, ReportType],
        marketplace_ids: List[str] = None,
        data_start_time: Union[datetime, str] = None,
        data_end_time: Union[datetime, str] = None,
        report_options: Dict[str, str] = None,
        wait_for_completion: bool = False,
        poll_interval: int = 30,
        max_wait: int = 3600,
    ) -> Dict[str, Any]:
        """
        High-level method to request a report.
        
        Args:
            report_type: Type of report
            marketplace_ids: Marketplaces to include
            data_start_time: Start of data range
            data_end_time: End of data range
            report_options: Report-specific options
            wait_for_completion: Whether to wait for report to complete
            poll_interval: Seconds between status checks
            max_wait: Maximum seconds to wait
            
        Returns:
            Report request result (or final status if wait_for_completion)
        """
        rt = report_type.value if isinstance(report_type, ReportType) else report_type
        
        _logger.info("Requesting report: %s", rt)
        
        report = self.create_report(
            report_type=rt,
            marketplace_ids=marketplace_ids,
            data_start_time=data_start_time,
            data_end_time=data_end_time,
            report_options=report_options,
        )
        
        report_id = report['reportId']
        _logger.info("Report requested: %s", report_id)
        
        if wait_for_completion:
            return self.wait_for_report(
                report_id,
                poll_interval=poll_interval,
                max_wait=max_wait,
            )
        
        return report
    
    def wait_for_report(
        self,
        report_id: str,
        poll_interval: int = 30,
        max_wait: int = 3600,
    ) -> Dict[str, Any]:
        """
        Wait for a report to complete processing.
        
        Args:
            report_id: Report ID
            poll_interval: Seconds between status checks
            max_wait: Maximum seconds to wait
            
        Returns:
            Final report status
            
        Raises:
            SPAPIError: If report fails or times out
        """
        start_time = time.time()
        terminal_statuses = [ReportStatus.DONE, ReportStatus.CANCELLED, ReportStatus.FATAL]
        
        _logger.info("Waiting for report %s to complete", report_id)
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait:
                raise SPAPIError(
                    f"Report {report_id} timed out after {max_wait} seconds"
                )
            
            report = self.get_report(report_id)
            status = report.get('processingStatus')
            
            _logger.debug(
                "Report %s status: %s (%.0fs elapsed)",
                report_id, status, elapsed
            )
            
            if status in [s.value for s in terminal_statuses]:
                _logger.info(
                    "Report %s completed with status: %s (%.0fs)",
                    report_id, status, elapsed
                )
                return report
            
            time.sleep(poll_interval)
    
    def get_report_data(
        self,
        report_id: str,
        parse: bool = True,
        encoding: str = 'utf-8',
    ) -> Union[bytes, str, List[Dict[str, Any]]]:
        """
        Get the data for a completed report.
        
        Args:
            report_id: Report ID
            parse: Whether to parse the report data
            encoding: Character encoding
            
        Returns:
            Report data (bytes, string, or parsed list of dicts)
        """
        # Get report to get document ID
        report = self.get_report(report_id)
        
        status = report.get('processingStatus')
        if status != ReportStatus.DONE.value:
            raise SPAPIError(
                f"Report {report_id} is not complete (status: {status})"
            )
        
        report_document_id = report.get('reportDocumentId')
        if not report_document_id:
            raise SPAPIError(f"Report {report_id} has no document")
        
        # Download document
        content = self.download_report_document(
            report_document_id,
            report_type=report.get('reportType')
        )
        
        if not parse:
            return content
        
        # Decode and parse
        text = content.decode(encoding)
        
        # Most Amazon reports are tab-separated
        if '\t' in text[:1000]:
            return self._parse_tsv(text)
        
        # Some are JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # Return as string
        return text
    
    def _parse_tsv(self, text: str) -> List[Dict[str, Any]]:
        """
        Parse tab-separated values into list of dicts.
        
        Args:
            text: TSV content
            
        Returns:
            List of dicts with header keys
        """
        reader = csv.DictReader(io.StringIO(text), delimiter='\t')
        return list(reader)
    
    # =========================================================================
    # Convenience Methods for Common Reports
    # =========================================================================
    
    def get_fba_inventory_report(
        self,
        wait_for_completion: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get FBA inventory report.
        
        Args:
            wait_for_completion: Whether to wait for completion
            
        Returns:
            Parsed inventory data
        """
        report = self.request_report(
            report_type=ReportType.GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA,
            wait_for_completion=wait_for_completion,
        )
        
        if wait_for_completion:
            return self.get_report_data(report['reportId'])
        return report
    
    def get_all_listings_report(
        self,
        wait_for_completion: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get all listings report.
        
        Args:
            wait_for_completion: Whether to wait for completion
            
        Returns:
            Parsed listings data
        """
        report = self.request_report(
            report_type=ReportType.GET_MERCHANT_LISTINGS_ALL_DATA,
            wait_for_completion=wait_for_completion,
        )
        
        if wait_for_completion:
            return self.get_report_data(report['reportId'])
        return report
    
    def get_orders_report(
        self,
        start_date: Union[datetime, str] = None,
        end_date: Union[datetime, str] = None,
        wait_for_completion: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get orders report.
        
        Args:
            start_date: Start of date range
            end_date: End of date range
            wait_for_completion: Whether to wait for completion
            
        Returns:
            Parsed orders data
        """
        if start_date is None:
            start_date = datetime.now(timezone.utc) - timedelta(days=30)
        
        report = self.request_report(
            report_type=ReportType.GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE,
            data_start_time=start_date,
            data_end_time=end_date,
            wait_for_completion=wait_for_completion,
        )
        
        if wait_for_completion:
            return self.get_report_data(report['reportId'])
        return report
    
    def get_settlement_reports(
        self,
        settlement_id: str = None,
        created_since: Union[datetime, str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get list of settlement reports.
        
        Args:
            settlement_id: Specific settlement ID
            created_since: Filter by creation date
            
        Returns:
            List of settlement reports
        """
        if created_since is None:
            created_since = datetime.now(timezone.utc) - timedelta(days=90)
        
        response = self.get_reports(
            report_types=[ReportType.GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE_V2],
            created_since=created_since,
            page_size=100,
        )
        
        return response.get('reports', [])
    
    def get_settlement_report_data(
        self,
        report_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Get data from a settlement report.
        
        Args:
            report_id: Settlement report ID
            
        Returns:
            Parsed settlement data
        """
        return self.get_report_data(report_id)
    
    def get_returns_report(
        self,
        start_date: Union[datetime, str] = None,
        end_date: Union[datetime, str] = None,
        wait_for_completion: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get returns report.
        
        Args:
            start_date: Start of date range
            end_date: End of date range
            wait_for_completion: Whether to wait for completion
            
        Returns:
            Parsed returns data
        """
        if start_date is None:
            start_date = datetime.now(timezone.utc) - timedelta(days=30)
        
        report = self.request_report(
            report_type=ReportType.GET_FLAT_FILE_RETURNS_DATA_BY_RETURN_DATE,
            data_start_time=start_date,
            data_end_time=end_date,
            wait_for_completion=wait_for_completion,
        )
        
        if wait_for_completion:
            return self.get_report_data(report['reportId'])
        return report
    
    def get_fba_fees_report(
        self,
        wait_for_completion: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get FBA fees estimate report.
        
        Args:
            wait_for_completion: Whether to wait for completion
            
        Returns:
            Parsed fees data
        """
        report = self.request_report(
            report_type=ReportType.GET_FBA_ESTIMATED_FBA_FEES_TXT_DATA,
            wait_for_completion=wait_for_completion,
        )
        
        if wait_for_completion:
            return self.get_report_data(report['reportId'])
        return report
    
    def get_stranded_inventory_report(
        self,
        wait_for_completion: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get stranded inventory report.
        
        Args:
            wait_for_completion: Whether to wait for completion
            
        Returns:
            Parsed stranded inventory data
        """
        report = self.request_report(
            report_type=ReportType.GET_STRANDED_INVENTORY_UI_DATA,
            wait_for_completion=wait_for_completion,
        )
        
        if wait_for_completion:
            return self.get_report_data(report['reportId'])
        return report
    
    def get_reimbursements_report(
        self,
        start_date: Union[datetime, str] = None,
        end_date: Union[datetime, str] = None,
        wait_for_completion: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get FBA reimbursements report.
        
        Args:
            start_date: Start of date range
            end_date: End of date range
            wait_for_completion: Whether to wait for completion
            
        Returns:
            Parsed reimbursements data
        """
        if start_date is None:
            start_date = datetime.now(timezone.utc) - timedelta(days=90)
        
        report = self.request_report(
            report_type=ReportType.GET_FBA_REIMBURSEMENTS_DATA,
            data_start_time=start_date,
            data_end_time=end_date,
            wait_for_completion=wait_for_completion,
        )
        
        if wait_for_completion:
            return self.get_report_data(report['reportId'])
        return report
    
    def get_storage_fee_report(
        self,
        wait_for_completion: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get FBA storage fee report.
        
        Args:
            wait_for_completion: Whether to wait for completion
            
        Returns:
            Parsed storage fee data
        """
        report = self.request_report(
            report_type=ReportType.GET_FBA_STORAGE_FEE_CHARGES_DATA,
            wait_for_completion=wait_for_completion,
        )
        
        if wait_for_completion:
            return self.get_report_data(report['reportId'])
        return report
