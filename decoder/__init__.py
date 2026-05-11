"""ABI-driven decoding of raw EVM artifacts into typed Python objects.

Decoder is authoritative — dbt does not re-decode anything. All raw decoding
uses `eth_abi` (NOT `web3.py` contract methods) so the layer is library-light
and the on-the-wire bytes layout is observable.
"""
