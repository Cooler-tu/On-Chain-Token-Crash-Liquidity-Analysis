import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.data.artifacts import (
    ArtifactDependencyError,
    normalize_artifact_format,
    query_tables,
    read_table,
    validate_artifact_environment,
    write_table,
)
from src.analysis.metrics import (
    calculate_price_timeline_from_swaps,
    calculate_volume_metrics,
)
from src.analysis.holdings import _write_holdings_artifacts
from src.indexer.dune_index import index_events_from_dune
from src.models import VerifiedPool


HAS_PYARROW = importlib.util.find_spec("pyarrow") is not None
HAS_DUCKDB = importlib.util.find_spec("duckdb") is not None

TARGET = "0x44b28991B167582F18BA0259e0173176ca125505"
WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
POOL = "0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775"


def _swap_row():
    return {
        "block_number": 25_000_001,
        "block_timestamp": 1_778_000_000,
        "transaction_hash": "0xABCDEF",
        "log_index": 7,
        "protocol": "Uniswap",
        "version": "v4",
        "pool_address": "0xAABBCC",
        "event_type": "SWAP",
        "actor": "0xA1B2",
        "recipient": "0xC3D4",
        "token0_address": "0xEEFF",
        "token1_address": "0x1122",
        "amount_usd": 123.45,
        "token0_amount": str(2**255 + 123),
        "token1_amount": "9000000000000000000",
        "liquidity_delta": "0",
        "source_event": "dex.trades",
        "verified": True,
        "nft_token_id": None,
    }


def _transfer_row():
    return {
        "block_number": 25_000_003,
        "block_timestamp": 1_778_000_100,
        "transaction_hash": "0xA1B2C3",
        "log_index": 9,
        "protocol": "",
        "version": "",
        "pool_address": "",
        "event_type": "TOKEN_TRANSFER",
        "actor": "0xAABB",
        "recipient": "0xCCDD",
        "token0_amount": str(2**255 + 456),
        "token1_amount": "0",
        "liquidity_delta": "0",
        "source_event": "Transfer",
        "verified": True,
        "nft_token_id": None,
    }


def _liquidity_row():
    return {
        **_transfer_row(),
        "event_type": "LIQUIDITY_REMOVE",
        "protocol": "uniswap",
        "version": "v4",
        "pool_address": "0xEEFF",
        "liquidity_delta": "-12345678901234567890",
        "source_event": "ModifyLiquidity",
        "tick_lower": -120,
        "tick_upper": 120,
        "salt": str(2**200),
        "event_count": 4,
        "aggregation_scope": "pool_block",
    }


def _holding_row():
    return {
        "address": "0xAABB",
        "address_type": "EOA",
        "is_contract": False,
        "is_pool": False,
        "pool_label": "",
        "resolved_owner": "",
        "resolution_method": "eoa",
        "balance_raw": str(2**255 + 789),
        "balance_decimal": 42.5,
        "balance_start_raw": "100",
        "balance_start_decimal": 1.0,
        "balance_end_raw": str(2**255 + 789),
        "net_change_raw": "25",
        "net_change_decimal": 0.25,
        "peak_balance_raw": str(2**255 + 789),
        "peak_balance_decimal": 42.5,
        "moved_in_raw": "",
        "moved_out_raw": "",
        "balance_source": "dune_historical",
        "trajectory_source": "window_ledger",
        "tx_count": 7,
        "first_seen_block": 25_000_000,
        "last_seen_block": 25_000_100,
        "query_timestamp": 1_778_000_200,
    }


class ArtifactFormatTest(unittest.TestCase):
    def test_format_validation(self):
        self.assertEqual(normalize_artifact_format(" BOTH "), "both")
        with self.assertRaisesRegex(ValueError, "json, parquet, both"):
            normalize_artifact_format("csv")

    def test_json_write_and_column_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = write_table("swaps", [_swap_row()], tmp, "json")
            self.assertEqual(meta["rows"], 1)
            self.assertIn("json", meta["paths"])
            self.assertFalse((Path(tmp) / "swaps.json.tmp").exists())
            rows = read_table(
                "swaps", tmp, prefer="json", columns=["block_number", "token0_amount"]
            )
            self.assertEqual(rows[0]["block_number"], 25_000_001)
            self.assertEqual(rows[0]["token0_amount"], str(2**255 + 123))

    @unittest.skipIf(HAS_PYARROW, "only verifies the dependency error without PyArrow")
    def test_requested_parquet_has_clear_dependency_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ArtifactDependencyError, "PyArrow"):
                write_table("swaps", [_swap_row()], tmp, "both")
            self.assertFalse((Path(tmp) / "swaps.json").exists())
            with self.assertRaisesRegex(ArtifactDependencyError, "PyArrow"):
                validate_artifact_environment("both")


@unittest.skipUnless(HAS_PYARROW, "PyArrow is required for Parquet integration")
class ParquetArtifactTest(unittest.TestCase):
    def test_dual_write_schema_and_logical_values(self):
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmp:
            row = _swap_row()
            meta = write_table("swaps", [row], tmp, "both")
            parquet_path = Path(meta["paths"]["parquet"])
            self.assertTrue((Path(tmp) / "swaps.json").exists())
            self.assertTrue(parquet_path.exists())

            table = pq.read_table(parquet_path)
            self.assertEqual(table.num_rows, 1)
            timestamp_type = table.schema.field("block_timestamp").type
            self.assertTrue(str(timestamp_type).startswith("timestamp["))
            self.assertEqual(timestamp_type.tz, "UTC")
            self.assertEqual(
                table.schema.metadata[b"raw_amount_encoding"], b"base10-string"
            )

            stored = table.to_pylist()[0]
            self.assertEqual(stored["pool_address"], "0xaabbcc")
            self.assertEqual(stored["transaction_hash"], "0xabcdef")
            self.assertEqual(stored["token0_amount"], row["token0_amount"])
            self.assertEqual(stored["amount_usd"], row["amount_usd"])

            json_rows = json.loads((Path(tmp) / "swaps.json").read_text())
            self.assertEqual(len(json_rows), table.num_rows)
            self.assertEqual(json_rows[0]["token0_amount"], stored["token0_amount"])

    def test_empty_swaps_table_keeps_schema(self):
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmp:
            meta = write_table("swaps", [], tmp, "parquet")
            table = pq.read_table(meta["paths"]["parquet"])
            self.assertEqual(table.num_rows, 0)
            self.assertIn("block_number", table.column_names)

    def test_transfer_and_liquidity_schemas_preserve_raw_values(self):
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmp:
            transfer_meta = write_table(
                "transfers", [_transfer_row()], tmp, "both"
            )
            liquidity_meta = write_table(
                "liquidity_events", [_liquidity_row()], tmp, "both"
            )
            transfer = pq.read_table(
                transfer_meta["paths"]["parquet"]
            ).to_pylist()[0]
            liquidity = pq.read_table(
                liquidity_meta["paths"]["parquet"]
            ).to_pylist()[0]

            self.assertEqual(transfer["actor"], "0xaabb")
            self.assertIsNone(transfer["pool_address"])
            self.assertEqual(
                transfer["token0_amount"], _transfer_row()["token0_amount"]
            )
            self.assertEqual(liquidity["event_count"], 4)
            self.assertEqual(liquidity["tick_lower"], -120)
            self.assertEqual(
                liquidity["liquidity_delta"], "-12345678901234567890"
            )

    def test_holdings_parquet_preserves_nested_json_summary(self):
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            row = _holding_row()
            result = {
                "from_block": 25_000_000,
                "to_block": 25_000_100,
                "holdings_count": 1,
                "holdings": [row],
                "pool_identification": [],
            }
            _write_holdings_artifacts(out, result, [row], "both")

            document = json.loads((out / "holdings.json").read_text())
            self.assertEqual(document["from_block"], 25_000_000)
            self.assertEqual(document["holdings"][0]["address"], "0xAABB")
            self.assertEqual(document["artifact_format"], "both")
            self.assertIn(
                "parquet", document["artifacts"]["holdings"]["paths"]
            )
            json_rows = read_table("holdings", out, prefer="json")
            self.assertEqual(len(json_rows), 1)
            self.assertEqual(json_rows[0]["address"], "0xAABB")

            table = pq.read_table(out / "tables" / "holdings.parquet")
            stored = table.to_pylist()[0]
            self.assertEqual(stored["address"], "0xaabb")
            self.assertEqual(stored["balance_raw"], row["balance_raw"])
            self.assertIsNone(stored["moved_in_raw"])

            legacy = read_table(
                "holdings", out, prefer="parquet", legacy_rows=True
            )
            self.assertEqual(legacy[0]["query_timestamp"], 1_778_000_200)

    def test_existing_price_and_volume_metrics_match_parquet_rows(self):
        pool = VerifiedPool(
            chain_id=1,
            protocol="uniswap",
            version="v3",
            architecture="direct_pool",
            factory_address="0x0000000000000000000000000000000000000000",
            pool_address=POOL,
            custody_address=POOL,
            token0=TARGET,
            token1=WETH,
            verified=True,
        )
        rows = [
            {
                **_swap_row(),
                "pool_address": POOL,
                "token0_address": TARGET,
                "token1_address": WETH,
                "token0_amount": "2000000000000000000",
                "token1_amount": "1000000000000000000",
                "amount_usd": 5000.0,
            },
            {
                **_swap_row(),
                "block_number": 25_000_002,
                "log_index": 8,
                "pool_address": POOL,
                "token0_address": TARGET,
                "token1_address": WETH,
                "token0_amount": "3000000000000000000",
                "token1_amount": "1000000000000000000",
                "amount_usd": 9000.0,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            write_table("swaps", rows, tmp, "both")
            parquet_rows = read_table(
                "swaps", tmp, prefer="parquet", legacy_rows=True
            )
            self.assertIsInstance(parquet_rows[0]["block_timestamp"], int)
            json_volume = calculate_volume_metrics(
                rows, [pool], TARGET, 18, bucket_seconds=3600
            )
            parquet_volume = calculate_volume_metrics(
                parquet_rows, [pool], TARGET, 18, bucket_seconds=3600
            )
            self.assertEqual(parquet_volume, json_volume)

            json_price = calculate_price_timeline_from_swaps(
                rows, [pool], TARGET, 18, bucket_seconds=3600
            )
            parquet_price = calculate_price_timeline_from_swaps(
                parquet_rows, [pool], TARGET, 18, bucket_seconds=3600
            )
            self.assertEqual(parquet_price, json_price)

    def test_dune_index_dual_writes_swaps_and_records_metadata(self):
        row = {
            "block_number": 100,
            "block_time": "2026-08-13 00:00:00 UTC",
            "transaction_hash": "0xabc",
            "log_index": 1,
            "protocol": "uniswap",
            "version": "v3",
            "pool_address": "0x0000000000000000000000000000000000000011",
            "actor": "0x0000000000000000000000000000000000000022",
            "token_bought": "0x0000000000000000000000000000000000000033",
            "token_sold": "0x0000000000000000000000000000000000000044",
            "token_bought_amount_raw": "3",
            "token_sold_amount_raw": "4",
            "amount_usd": 5.0,
        }

        def fake_query(name, **_kwargs):
            self.assertEqual(name, "swaps")
            return [row]

        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.indexer.dune_index.query", side_effect=fake_query
        ):
            result = index_events_from_dune(
                [],
                "0x0000000000000000000000000000000000000001",
                100,
                100,
                output_dir=tmp,
                index_token_transfer=False,
                artifact_format="both",
            )
            self.assertEqual(len(result["swaps"]), 1)
            self.assertTrue((Path(tmp) / "swaps.json").exists())
            self.assertTrue((Path(tmp) / "tables" / "swaps.parquet").exists())
            self.assertTrue((Path(tmp) / "tables" / "transfers.parquet").exists())
            self.assertTrue(
                (Path(tmp) / "tables" / "liquidity_events.parquet").exists()
            )
            source = json.loads((Path(tmp) / "index_source.json").read_text())
            self.assertEqual(source["artifact_format"], "both")
            self.assertEqual(source["artifacts"]["swaps"]["rows"], 1)
            self.assertEqual(source["artifacts"]["transfers"]["rows"], 0)
            self.assertEqual(source["artifacts"]["liquidity_events"]["rows"], 0)


@unittest.skipUnless(
    HAS_PYARROW and HAS_DUCKDB,
    "PyArrow and DuckDB are required for local SQL integration",
)
class DuckDbArtifactTest(unittest.TestCase):
    def test_query_tables_registers_parquet_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_table("swaps", [_swap_row()], tmp, "parquet")
            rows = query_tables(
                "SELECT pool_address, SUM(amount_usd) AS volume_usd "
                "FROM swaps GROUP BY pool_address",
                tmp,
                table_names=["swaps"],
            )
            self.assertEqual(rows[0]["pool_address"], "0xaabbcc")
            self.assertAlmostEqual(rows[0]["volume_usd"], 123.45)
