import unittest
from unittest.mock import patch

import api_server
from blueprints import market


class MarketDatabaseBoundaryTests(unittest.TestCase):
    def test_retired_sage_single_offer_route_has_no_wallet_or_database_effect(self):
        with (
            api_server.app.test_request_context(
                "/api/debug/sage-single-offer-test",
                method="POST",
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            ),
            patch("wallet.create_offer") as create_offer,
            patch("wallet.cancel_offer") as cancel_offer,
            patch(
                "database.get_smallest_free_tier_spare",
                create=True,
            ) as spare,
        ):
            response = market.api_debug_sage_single_offer_test()

        if isinstance(response, tuple):
            response, status = response
            self.assertEqual(status, 404)
        self.assertEqual(response.get_json()["error"], "debug_routes_disabled")
        create_offer.assert_not_called()
        cancel_offer.assert_not_called()
        spare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
