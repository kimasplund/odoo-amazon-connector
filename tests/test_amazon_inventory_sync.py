# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch
from odoo.tests.common import TransactionCase
from odoo import fields

class TestAmazonInventorySync(TransactionCase):

    def setUp(self):
        super().setUp()
        self.AmazonAccount = self.env['amazon.account']
        self.AmazonMarketplace = self.env['amazon.marketplace']
        self.AmazonListing = self.env['amazon.product.listing']
        self.ProductTemplate = self.env['product.template']

        # Create marketplace
        self.marketplace = self.AmazonMarketplace.create({
            'name': 'Amazon US',
            'marketplace_id': 'ATVPDKIKX0DER',
            'region': 'na',
            'currency_id': self.env.ref('base.USD').id,
        })

        # Create account
        self.account = self.AmazonAccount.create({
            'name': 'Test Account',
            'seller_id': 'TESTSELLERID',
            'lwa_client_id': 'test_client_id',
            'lwa_client_secret': 'test_client_secret',
            'refresh_token': 'test_refresh_token',
            'aws_access_key': 'test_access_key',
            'aws_secret_key': 'test_secret_key',
            'marketplace_ids': [(6, 0, [self.marketplace.id])],
            'default_marketplace_id': self.marketplace.id,
            'environment': 'sandbox',
        })

        # Create product
        self.product_tmpl = self.ProductTemplate.create({
            'name': 'Test Product',
            'type': 'product',
        })

        # Create listing
        self.listing = self.AmazonListing.create({
            'account_id': self.account.id,
            'marketplace_id': self.marketplace.id,
            'product_tmpl_id': self.product_tmpl.id,
            'sku': 'TEST-SKU-001',
            'asin': 'B000000001',
            'fulfillment_channel': 'FBA',
        })

    def test_sync_inventory(self):
        """Test inventory synchronization logic."""

        # Mock API response
        mock_inventory_summaries = [
            {
                'asin': 'B000000001',
                'fnSku': 'FNSKU001',
                'sellerSku': 'TEST-SKU-001',
                'condition': 'NewItem',
                'inventoryDetails': {
                    'fulfillableQuantity': 100,
                    'inboundWorkingQuantity': 5,
                    'inboundShippedQuantity': 10,
                    'inboundReceivingQuantity': 2,
                    'reservedQuantity': {
                        'totalReservedQuantity': 3,
                        'pendingCustomerOrderQuantity': 1,
                        'pendingTransshipmentQuantity': 1,
                        'fcProcessingQuantity': 1
                    },
                    'researchingQuantity': {
                        'totalResearchingQuantity': 0,
                        'researchingQuantityBreakdown': []
                    },
                    'unfulfillableQuantity': {
                        'totalUnfulfillableQuantity': 4,
                        'customerDamagedQuantity': 1,
                        'warehouseDamagedQuantity': 1,
                        'distributorDamagedQuantity': 1,
                        'carrierDamagedQuantity': 1,
                        'defectiveQuantity': 0,
                        'expiredQuantity': 0
                    }
                },
                'lastUpdatedTime': '2023-01-01T12:00:00Z',
                'productName': 'Test Product',
                'totalQuantity': 124
            }
        ]

        # We need to verify where the class is imported from.
        # Assuming the structure is standard and the code I'm editing is in models/amazon_account.py
        # The imports inside that file are local ..services.sp_api_client
        # But patching target must be importable.

        # Since I'm editing models/amazon_account.py to add the import inside the method,
        # I should patch the class where it is defined, or where it is imported if I import it at module level.
        # But I plan to import inside the method.
        # So I should patch `odoo.addons.amazon_connector.services.sp_api_client.OdooSPAPIClient`
        # and `odoo.addons.amazon_connector.services.sp_api_fba.SPAPIFba`.

        with patch('odoo.addons.amazon_connector.services.sp_api_client.OdooSPAPIClient') as MockClient, \
             patch('odoo.addons.amazon_connector.services.sp_api_fba.SPAPIFba') as MockFba:

            # Setup mock instances
            mock_client_instance = MockClient.return_value
            mock_fba_instance = MockFba.return_value

            # Setup return value for get_inventory_summaries_all
            mock_fba_instance.get_inventory_summaries_all.return_value = mock_inventory_summaries

            # Run sync
            self.account._sync_inventory()

            # Verify API was called correctly
            # We expect it to be initialized with account credentials
            MockClient.assert_called()

            # We expect FBA client to be initialized with the API client
            MockFba.assert_called_with(mock_client_instance)

            # Verify inventory updates on listing
            self.listing.refresh() # Reload from DB
            self.assertEqual(self.listing.quantity_available, 100)
            self.assertEqual(self.listing.quantity_inbound, 17) # 5 + 10 + 2
            self.assertEqual(self.listing.quantity_reserved, 3)
            self.assertEqual(self.listing.quantity_unfulfillable, 4)
            self.assertTrue(self.listing.last_inventory_sync)
