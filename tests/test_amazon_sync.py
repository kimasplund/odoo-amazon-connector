# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests.common import TransactionCase
from unittest.mock import patch

class TestAmazonInventorySync(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Product = self.env['product.product']
        self.Listing = self.env['amazon.product.listing']
        self.Sync = self.env['amazon.inventory.sync']
        self.Account = self.env['amazon.account']
        self.Marketplace = self.env['amazon.marketplace']

        # Create Marketplace
        self.marketplace = self.Marketplace.create({
            'name': 'US',
            'amazon_marketplace_id': 'ATVPDKIKX0DER',
            'code': 'US',
            'currency_id': self.env.ref('base.USD').id,
        })

        # Create Account
        self.account = self.Account.create({
            'name': 'Test Account',
            'active': True,
        })
        self.account.marketplace_ids = [(4, self.marketplace.id)]

        # Create products
        self.product1 = self.Product.create({'name': 'P1', 'type': 'product'})
        self.product2 = self.Product.create({'name': 'P2', 'type': 'product'})

        # Update stock for P1
        self.env['stock.quant'].create({
            'product_id': self.product1.id,
            'location_id': self.env.ref('stock.stock_location_stock').id,
            'quantity': 10,
        })

        # Create Listings
        self.listing1 = self.Listing.create({
            'account_id': self.account.id,
            'marketplace_id': self.marketplace.id,
            'product_id': self.product1.id,
            'product_tmpl_id': self.product1.product_tmpl_id.id,
            'asin': 'ASIN000001',
            'sku': 'SKU001',
            'fulfillment_channel': 'FBM',
            'state': 'active',
        })
        self.listing2 = self.Listing.create({
            'account_id': self.account.id,
            'marketplace_id': self.marketplace.id,
            'product_id': self.product2.id,
            'product_tmpl_id': self.product2.product_tmpl_id.id,
            'asin': 'ASIN000002',
            'sku': 'SKU002',
            'fulfillment_channel': 'FBM',
            'state': 'active',
        })

    def test_get_sellable_quantities_batch(self):
        """Test that _get_sellable_quantities_batch works."""
        listings = self.listing1 + self.listing2

        # Call the method
        quantities = listings._get_sellable_quantities_batch()

        # Verify result structure
        self.assertIsInstance(quantities, dict)
        self.assertEqual(len(quantities), 2)

        # Verify values
        self.assertEqual(quantities[self.listing1.id], 10.0)
        self.assertEqual(quantities[self.listing2.id], 0.0)

    def test_get_sellable_quantity_single(self):
        """Test backward compatibility for single record call."""
        qty = self.listing1._get_sellable_quantity()
        self.assertIsInstance(qty, (float, int))
        self.assertEqual(qty, 10.0)

    def test_sync_fbm_export_batch(self):
        """Test that sync uses the batch method."""
        sync = self.Sync.create({
            'account_id': self.account.id,
            'sync_type': 'fbm_export',
            'marketplace_ids': [(4, self.marketplace.id)],
        })

        # Mock _get_sellable_quantities_batch to ensure it's called
        with patch.object(type(self.Listing), '_get_sellable_quantities_batch', wraps=self.Listing._get_sellable_quantities_batch) as mock_batch:
             # Prevent actual API call by mocking _log to swallow errors if any API call fails
             # or by ensuring listing has correct handling_time field if it's missing in mocks

             sync._sync_fbm_export()

             # Verify batch call
             self.assertTrue(mock_batch.called)
