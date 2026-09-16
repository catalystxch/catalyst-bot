"""Immutable server execution bindings for approved prep economic outputs.

No wallet/provider/database access, signing or dispatch permission lives here.
Configuration types are preserved; prepared sizes already include headroom.
"""

from dataclasses import asdict
from decimal import Decimal, InvalidOperation

from coin_prep_economics import build_exact_prep_economics
from sage_offer_wire import decode_wallet_puzzle_hash


def _configuration_keys():
    from coin_prep_fee_runtime import _CONTEXT_KEYS

    return {*_CONTEXT_KEYS, "network"}


def _decimal_text(value):
    if not value.is_finite():
        raise ValueError("FEE_EXECUTION_CONTEXT_INVALID")
    if not value:
        return "0"
    sign, digits, exponent = value.as_tuple()
    # Bound the fixed-point expansion BEFORE formatting a compact exponent.
    length = (len(digits) + exponent if exponent >= 0
              else max(len(digits) + 1, 2 - exponent)) + sign
    if length > 128:
        raise ValueError("FEE_EXECUTION_CONTEXT_INVALID")
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def encode_execution_configuration(configuration):
    """Canonical lossless typed configuration, never float-to-money coercion."""
    if type(configuration) is not dict or set(configuration) != _configuration_keys():
        raise ValueError("FEE_EXECUTION_CONTEXT_INVALID")
    encoded = {}
    for key, value in configuration.items():
        if value is None:
            kind = "none"
        elif type(value) is bool:
            kind = "bool"
        elif type(value) is int and -(2**63 - 1) <= value <= 2**63 - 1:
            kind = "int"
        elif type(value) is str and len(value) <= 4096:
            kind = "str"
        elif type(value) is Decimal:
            kind, value = "decimal", _decimal_text(value)
        else:
            raise ValueError("FEE_EXECUTION_CONTEXT_INVALID")
        encoded[key] = {"kind": kind, "value": value}
    return encoded


def _decode_configuration(encoded):
    if type(encoded) is not dict or set(encoded) != _configuration_keys():
        raise ValueError("FEE_EXECUTION_CONTEXT_INVALID")
    configuration = {}
    for key, field in encoded.items():
        if type(field) is not dict or set(field) != {"kind", "value"}:
            raise ValueError("FEE_EXECUTION_CONTEXT_INVALID")
        kind, value = field["kind"], field["value"]
        if kind == "decimal" and type(value) is str and len(value) <= 128:
            try:
                value = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError("FEE_EXECUTION_CONTEXT_INVALID") from exc
        elif not ((kind == "none" and value is None)
                  or (kind == "bool" and type(value) is bool)
                  or (kind == "int" and type(value) is int)
                  or (kind == "str" and type(value) is str)):
            raise ValueError("FEE_EXECUTION_CONTEXT_INVALID")
        configuration[key] = value
    if encode_execution_configuration(configuration) != encoded:
        raise ValueError("FEE_EXECUTION_CONTEXT_INVALID")
    return configuration


def validate_execution_context(binding, identity, economic_plan):
    """Reconstruct exact prepared targets and refuse resizing CLI overrides."""
    if (type(binding) is not dict or set(binding) != {
            "version", "configuration", "receive_address", "worker_args"}
            or type(binding["version"]) is not int or binding["version"] != 1):
        raise ValueError("FEE_EXECUTION_CONTEXT_INVALID")
    configuration = _decode_configuration(binding["configuration"])
    expected = {
        "network": identity["network"], "WALLET_TYPE": identity["wallet_type"],
        "CAT_WALLET_ID": identity["wallet_id"], "WALLET_ID_XCH": identity["xch_wallet_id"],
        "CAT_ASSET_ID": identity["asset_id"], "CAT_TICKER_ID": identity["ticker"],
        "SAGE_FINGERPRINT": str(identity["wallet_fingerprint"]),
    }
    if any(configuration[key] != value for key, value in expected.items()):
        raise ValueError("FEE_EXECUTION_CONTEXT_INVALID")
    address = binding["receive_address"]
    try:
        decode_wallet_puzzle_hash(address)
        prefix = "xch1" if identity["network"] == "mainnet" else "txch1"
        if not address.startswith(prefix):
            raise ValueError("wrong network address")
        recipe = build_exact_prep_economics(
            configuration=configuration, worker_args=binding["worker_args"],
            campaign_revision=economic_plan["campaign_revision"] or 0,
            target_seconds=economic_plan["target_seconds"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("FEE_EXECUTION_CONTEXT_INVALID") from exc
    generated = sorted((asdict(t) for t in recipe["targets"]), key=lambda t: (t["asset"], t["ordinal"]))
    if (generated != economic_plan["outputs"]
            or recipe["economic_plan"]["reserve_floors_mojos"] != economic_plan["reserve_floors_mojos"]
            or recipe["economic_plan"]["liquidity_mode"] != economic_plan["liquidity_mode"]):
        raise ValueError("FEE_EXECUTION_CONTEXT_INVALID")
    # Keep approved multiplier/headroom metadata, but NEVER apply it a second time.
    return {**recipe, "economic_plan": economic_plan}


def freeze_execution_context(context):
    """Persist trusted collector settings, not executable bundles or coin IDs."""
    binding = {
        "version": 1,
        "configuration": encode_execution_configuration(context["configuration"]),
        "receive_address": context["receive_address"],
        "worker_args": dict(context["recipe"]["worker_args"]),
    }
    plan = context["recipe"]["economic_plan"]
    canonical_plan = {**plan, "outputs": sorted(plan["outputs"], key=lambda t: (t["asset"], t["ordinal"]))}
    validate_execution_context(binding, context["identity"], canonical_plan)
    return binding
