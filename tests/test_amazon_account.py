from odoo.tests.common import TransactionCase
from unittest.mock import patch
from datetime import datetime, timedelta

class TestAmazonAccount(TransactionCase):

    def setUp(self):
        super().setUp()
        self.AmazonAccount = self.env['amazon.account']

        # Create a test account
        self.account = self.AmazonAccount.create({
            'name': 'Test Account',
            'seller_id': 'TEST_SELLER_ID',
            'lwa_client_id': 'TEST_CLIENT_ID',
            'lwa_client_secret': 'TEST_CLIENT_SECRET',
            'refresh_token': 'TEST_REFRESH_TOKEN',
            'environment': 'sandbox',
            'marketplace_ids': [],
        })

    def test_refresh_access_token(self):
        """Test that _refresh_access_token calls SPAPIAuthenticator correctly."""

        # We target the class in the services module
        # Assuming the module name is 'amazon_connector' based on manifest assets
        target = 'odoo.addons.amazon_connector.services.sp_api_auth.SPAPIAuthenticator'

        with patch(target) as MockAuth:
            # Setup mock instance
            mock_auth_instance = MockAuth.return_value
            mock_lwa_client = mock_auth_instance.lwa_client

            # Setup return values
            expected_token = 'NEW_ACCESS_TOKEN'
            expected_expiry = datetime.now() + timedelta(hours=1)

            mock_lwa_client.get_access_token.return_value = expected_token
            mock_lwa_client._token_expiry = expected_expiry

            # Call the method
            token = self.account._refresh_access_token()

            # Verify result
            self.assertEqual(token, expected_token)

            # Verify record update
            self.assertEqual(self.account.access_token, expected_token)
            self.assertEqual(self.account.access_token_expiry, expected_expiry)

            # Verify SPAPIAuthenticator was initialized with correct args
            MockAuth.assert_called_with(
                client_id='TEST_CLIENT_ID',
                client_secret='TEST_CLIENT_SECRET',
                refresh_token='TEST_REFRESH_TOKEN',
                sandbox=True
            )

            # Verify methods called
            mock_lwa_client.get_access_token.assert_called_once()
            mock_auth_instance.close.assert_called_once()
