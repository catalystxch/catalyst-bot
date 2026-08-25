"""Shared test-only setup for authenticated API mutation contract tests."""

from contextlib import ExitStack, contextmanager
from unittest.mock import patch


def _api_mutation_patches(api_server):
    """Return fresh patches for one explicitly permitted API test scope."""

    return (
        patch.object(api_server, "_ensure_mutation_runtime", return_value=None),
        patch.object(
            api_server.mutation_gate,
            "enter_mutation",
            return_value="permit",
        ),
        patch.object(api_server.mutation_gate, "exit_mutation", return_value=True),
        patch.object(api_server, "start_mutation_thread", return_value=None),
        patch("blueprints.cat._get_dexie_pairs", return_value=[]),
        patch("market_data_collector._fetch_xch_usd_price", return_value=None),
        patch("wallet.get_wallets", return_value={"success": True, "wallets": []}),
    )


def permit_api_mutations(test_case, api_server) -> None:
    """Install an explicit successful Task 15 mutation permit for one test."""

    for mutation_patch in _api_mutation_patches(api_server):
        mutation_patch.start()
        test_case.addCleanup(mutation_patch.stop)


@contextmanager
def api_mutations_permitted(api_server):
    """Permit mutations for one pytest-style test function only."""

    with ExitStack() as stack:
        for mutation_patch in _api_mutation_patches(api_server):
            stack.enter_context(mutation_patch)
        yield
