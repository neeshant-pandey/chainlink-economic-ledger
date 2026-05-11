"""BigQuery client wrapper for public-dataset extraction.

Thin wrapper over `google.cloud.bigquery.Client`. Public surface is the
contract; concrete query construction is delegated to the per-artifact
extractor modules in this package.

Why a wrapper at all (vs. using `bigquery.Client` directly):
  - Single place to enforce dry-run cost guards (we read `bigquery-public-data`
    which counts against our 1 TB/month free tier — a bad query can eat it)
  - Single place to standardize partition / cluster predicates so the cost
    estimate stays small
  - Single place to set `use_query_cache=True`, location='US', and the labels
    we attach for cost attribution

This module imports `google.cloud.bigquery` lazily so unit tests that don't
need live BQ can still import the module.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

# Default labels attached to every job for cost attribution.
_DEFAULT_LABELS = {
    "pipeline": "chainlink-economic-ledger",
    "owner": "data-engineering",
}


class BQCostError(RuntimeError):
    """Raised when a query's dry-run estimate exceeds `max_bytes_billed`.

    Carries `sql`, `estimate_bytes`, and `limit_bytes` attributes so the
    caller can log them or auto-narrow the predicate.
    """

    def __init__(self, sql: str, estimate_bytes: int, limit_bytes: int) -> None:
        super().__init__(
            f"query would scan {estimate_bytes:,} bytes "
            f"(> limit {limit_bytes:,}). Narrow the predicate.",
        )
        self.sql = sql
        self.estimate_bytes = estimate_bytes
        self.limit_bytes = limit_bytes


class BQClient:
    """Strict public surface used by the per-artifact extractors.

    Construction does NOT instantiate a `bigquery.Client` immediately — that
    happens lazily on first query so import is cheap and unit tests don't
    require live credentials.
    """

    def __init__(
        self,
        gcp_project: str,
        location: str = "US",
        max_bytes_billed: int | None = 50 * 1024**3,  # 50 GB default
        labels: dict[str, str] | None = None,
    ) -> None:
        """Construct a BQClient bound to a GCP project.

        Args:
            gcp_project: project that owns the *job* (not the dataset).
                Public datasets live in `bigquery-public-data` but jobs run /
                bill against the caller's project.
            location: required to be 'US' for `bigquery-public-data.crypto_*`.
            max_bytes_billed: hard ceiling per query. Rejecting queries that
                exceed this is the difference between a $0 portfolio project
                and a $300 BQ bill. Default 50 GB (~5% of free tier).
            labels: attached to every job for cost attribution.
        """
        self.gcp_project = gcp_project
        self.location = location
        self.max_bytes_billed = max_bytes_billed
        self.labels = {**_DEFAULT_LABELS, **(labels or {})}
        self._client: Any = None  # lazy

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from google.cloud import bigquery

        self._client = bigquery.Client(project=self.gcp_project, location=self.location)
        return self._client

    def _build_query_params(self, query_params: dict[str, Any] | None) -> list[Any]:
        """Translate a dict of named params into BigQuery ScalarQueryParameter
        / ArrayQueryParameter objects. Keeps SQL parameterized — never
        f-string addresses (by design / the parameterization rule).
        """
        from google.cloud import bigquery

        if not query_params:
            return []
        out: list[Any] = []
        for name, value in query_params.items():
            if isinstance(value, list):
                if not value:
                    out.append(bigquery.ArrayQueryParameter(name, "STRING", value))
                    continue
                sample = value[0]
                if isinstance(sample, int):
                    out.append(bigquery.ArrayQueryParameter(name, "INT64", value))
                else:
                    out.append(
                        bigquery.ArrayQueryParameter(name, "STRING", [str(x) for x in value])
                    )
            elif isinstance(value, int):
                out.append(bigquery.ScalarQueryParameter(name, "INT64", value))
            elif isinstance(value, str):
                out.append(bigquery.ScalarQueryParameter(name, "STRING", value))
            else:
                out.append(bigquery.ScalarQueryParameter(name, "STRING", str(value)))
        return out

    def estimate_bytes(self, sql: str, query_params: dict[str, Any] | None = None) -> int:
        """Run a dry-run job and return scanned-bytes estimate.

        Used by every extractor as a pre-flight check. If estimate >
        max_bytes_billed, raises `BQCostError` with the SQL + estimate.
        """
        from google.cloud import bigquery

        client = self._get_client()
        job_config = bigquery.QueryJobConfig(
            dry_run=True,
            use_query_cache=False,
            query_parameters=self._build_query_params(query_params),
            labels=self.labels,
        )
        job = client.query(sql, job_config=job_config)
        estimate = int(getattr(job, "total_bytes_processed", 0) or 0)
        if self.max_bytes_billed is not None and estimate > self.max_bytes_billed:
            raise BQCostError(sql, estimate, self.max_bytes_billed)
        return estimate

    def query_iter(
        self,
        sql: str,
        query_params: dict[str, Any] | None = None,
        page_size: int = 10000,
    ) -> Iterator[dict[str, Any]]:
        """Execute the query and stream rows as plain dicts.

        Returns dicts (not `bigquery.Row`) so downstream code stays library-
        agnostic. Pagination is via the BQ result iterator with `page_size`.

        Gotcha: BQ returns INT64 as Python int, but FLOAT64 as float — for
        uint256 amounts we use NUMERIC and the client returns decimal.Decimal.
        Cast to int upstream where you need raw uint256.
        """
        from google.cloud import bigquery

        client = self._get_client()
        job_config = bigquery.QueryJobConfig(
            use_query_cache=True,
            query_parameters=self._build_query_params(query_params),
            labels=self.labels,
            maximum_bytes_billed=self.max_bytes_billed,
        )
        job = client.query(sql, job_config=job_config)
        result_iter = job.result(page_size=page_size)
        for row in result_iter:
            yield dict(row.items())

    def query_dataframe(
        self,
        sql: str,
        query_params: dict[str, Any] | None = None,
    ) -> Any:  # pyarrow.Table to avoid hard import
        """Execute the query and return a `pyarrow.Table`.

        Used when the consumer is the parquet writer — pyarrow → parquet is
        zero-copy and avoids a pandas materialization.
        """
        from google.cloud import bigquery

        client = self._get_client()
        job_config = bigquery.QueryJobConfig(
            use_query_cache=True,
            query_parameters=self._build_query_params(query_params),
            labels=self.labels,
            maximum_bytes_billed=self.max_bytes_billed,
        )
        job = client.query(sql, job_config=job_config)
        return job.to_arrow()
