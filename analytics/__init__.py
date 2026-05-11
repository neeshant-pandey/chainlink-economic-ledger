"""Incentive-modeling and tokenomics analysis layer.

Consumes reconciled mart data (`ledger_entries`, `staking_link_flows`,
`pa_fee_flows`) and produces analyst-grade economic answers: realized APY,
reward distribution efficiency, fee attribution by source chain.

This layer closes the chain `raw EVM → reconciled ledger → economic answer`
that the project scope calls for ("support incentive modeling",
"tokenomics analysis"). Without it, the pipeline reconstructs data but
doesn't deliver insight.
"""
