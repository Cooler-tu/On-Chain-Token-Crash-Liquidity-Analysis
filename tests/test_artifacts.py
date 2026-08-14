import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.data.artifacts import (
    ArtifactDependencyError,
    flatten_volume_timeline,
    inflate_volume_timeline,
    normalize_artifact_format,
    query_tables,
    read_table,
    validate_artifact_environment,
    write_table,
)
from src.analysis.metrics import (
    _write_volume_timeline_artifacts,
    calculate_all_metrics,
    calculate_price_timeline_from_swaps,
    calculate_volume_metrics,
)
from src.analysis.holdings import _write_holdings_artifacts
from src.analysis.positions import analyze_positions, _write_position_artifacts
from src.analysis.dashboard import _load_dashboard_inputs
from scripts.lp_correlation import _load_analysis_inputs
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


def _position_row():
    return {
        "pool_address": "0xAABBCC",
        "owner": "0xDDEEFF",
        "lp_token_address": None,
        "nft_token_id": 2**200,
        "liquidity": str(2**255 + 321),
        "share_pct": 12.345678,
        "beneficial_owner": "0x112233",
        "resolution_method": "v4_dune_active_liquidity_share_at_to_block",
        "confidence": 0.95,
        "tick_lower": -887220,
        "tick_upper": 887220,
        "token0_amount": str(2**180),
        "token1_amount": None,
    }


def _tvl_timeline_row():
    return {
        "block_number": 25_000_001,
        "block_timestamp": 1_778_000_000,
        "bucket": "hour",
        "chart_span": "week",
        "pool_address": "0xAABBCC",
        "protocol": "uniswap",
        "version": "v4",
        "event_type": "SNAPSHOT",
        "source_event": "balance_x_price",
        "balance_raw": str(2**255 + 987),
        "liquidity": None,
        "reserve0": None,
        "reserve1": None,
        "token0_amount": None,
        "token1_amount": None,
        "tvl_in_token": str(2**255 + 987),
        "tvl_usd": 98765.4321,
        "price": 0.123456789,
        "price_usd": 0.123457,
        "quote_symbol": "USD",
    }


def _volume_timeline_document():
    return {
        "total_volume_in_token": 15.0,
        "volume_by_pool": {
            "0xAABB": {
                "protocol": "uniswap",
                "version": "v3",
                "quote_symbol": "WETH",
            },
            "0xCCDD": {
                "protocol": "curve",
                "version": "v1",
                "quote_symbol": "USDC",
            },
        },
        "volume_timeline": [
            {
                "bucket_ts": 1_778_000_000,
                "total_volume_in_token": 15.0,
                "pools": {
                    "0xAABB": {"volume_in_token": 10.0, "volume_usd": 25.0},
                    "0xCCDD": {"volume_in_token": 5.0, "volume_usd": None},
                },
            }
        ],
        "bucket_seconds": 3600,
        "chart_span": "week",
        "bucket": "hour",
        "source": "local_swaps",
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

    def test_positions_dual_write_preserves_protocol_fields_and_summary(self):
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            row = _position_row()
            summary = {
                "total_positions": 1,
                "total_unique_holders": 1,
                "snapshot_block": 25_000_100,
                "top_5_holders": [],
            }
            _write_position_artifacts(out, [row], summary, "both")

            json_rows = json.loads((out / "positions.json").read_text())
            self.assertEqual(json_rows, [row])
            document = json.loads((out / "position_summary.json").read_text())
            self.assertEqual(document["artifact_format"], "both")
            self.assertEqual(document["artifacts"]["positions"]["rows"], 1)

            table = pq.read_table(out / "tables" / "positions.parquet")
            stored = table.to_pylist()[0]
            self.assertEqual(table.schema.metadata[b"artifact_name"], b"positions")
            self.assertEqual(stored["pool_address"], "0xaabbcc")
            self.assertEqual(stored["owner"], "0xddeeff")
            self.assertEqual(stored["nft_token_id"], str(2**200))
            self.assertEqual(stored["liquidity"], row["liquidity"])
            self.assertEqual(stored["tick_lower"], -887220)
            self.assertIsNone(stored["token1_amount"])

    def test_empty_positions_table_keeps_cross_protocol_schema(self):
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmp:
            meta = write_table("positions", [], tmp, "parquet")
            table = pq.read_table(meta["paths"]["parquet"])
            self.assertEqual(table.num_rows, 0)
            self.assertEqual(
                table.column_names,
                [
                    "pool_address", "owner", "lp_token_address", "nft_token_id",
                    "liquidity", "share_pct", "beneficial_owner",
                    "resolution_method", "confidence", "tick_lower", "tick_upper",
                    "token0_amount", "token1_amount",
                ],
            )

    def test_empty_allowlist_analyze_flow_writes_positions_parquet(self):
        with tempfile.TemporaryDirectory() as tmp:
            positions, summary = analyze_positions(
                None,
                [],
                [],
                TARGET,
                25_000_000,
                25_000_100,
                output_dir=tmp,
                owner_allowlist=[],
                artifact_format="both",
            )
            self.assertEqual(positions, [])
            self.assertEqual(summary["total_positions"], 0)
            self.assertTrue((Path(tmp) / "positions.json").exists())
            self.assertTrue(
                (Path(tmp) / "tables" / "positions.parquet").exists()
            )

    def test_tvl_timeline_preserves_raw_values_and_typed_timestamp(self):
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmp:
            row = _tvl_timeline_row()
            meta = write_table("tvl_timeline", [row], tmp, "both")
            json_rows = json.loads((Path(tmp) / "tvl_timeline.json").read_text())
            self.assertEqual(json_rows, [row])

            table = pq.read_table(meta["paths"]["parquet"])
            stored = table.to_pylist()[0]
            self.assertEqual(table.schema.metadata[b"artifact_name"], b"tvl_timeline")
            self.assertEqual(stored["pool_address"], "0xaabbcc")
            self.assertEqual(stored["balance_raw"], row["balance_raw"])
            self.assertEqual(stored["tvl_in_token"], row["tvl_in_token"])
            self.assertIsNone(stored["reserve0"])
            self.assertEqual(table.schema.field("block_timestamp").type.tz, "UTC")

    def test_volume_timeline_flattens_nested_json_for_parquet_and_fallback(self):
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            document = _volume_timeline_document()
            expected_rows = flatten_volume_timeline(document)
            artifact = _write_volume_timeline_artifacts(out, document, "both")

            saved = json.loads((out / "volume_timeline.json").read_text())
            self.assertEqual(saved["volume_timeline"][0]["pools"]["0xAABB"], {
                "volume_in_token": 10.0,
                "volume_usd": 25.0,
            })
            self.assertEqual(saved["artifacts"]["volume_timeline"]["rows"], 2)

            table = pq.read_table(artifact["paths"]["parquet"])
            self.assertEqual(table.num_rows, 2)
            rows = table.to_pylist()
            self.assertEqual({row["pool_address"] for row in rows}, {
                "0xaabb", "0xccdd",
            })
            curve = next(row for row in rows if row["pool_address"] == "0xccdd")
            self.assertIsNone(curve["volume_usd"])
            self.assertEqual(table.schema.field("bucket_timestamp").type.tz, "UTC")

            json_rows = read_table("volume_timeline", out, prefer="json")
            self.assertEqual(json_rows, expected_rows)
            legacy_rows = read_table(
                "volume_timeline", out, prefer="parquet", legacy_rows=True
            )
            self.assertEqual(legacy_rows[0]["bucket_timestamp"], 1_778_000_000)

            inflated = inflate_volume_timeline(legacy_rows, saved)
            self.assertEqual(
                inflated["volume_timeline"][0]["pools"]["0xaabb"],
                {"volume_in_token": 10.0, "volume_usd": 25.0},
            )

    def test_empty_timeline_tables_keep_schemas(self):
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmp:
            tvl_meta = write_table("tvl_timeline", [], tmp, "parquet")
            volume_meta = write_table("volume_timeline", [], tmp, "parquet")
            tvl = pq.read_table(tvl_meta["paths"]["parquet"])
            volume = pq.read_table(volume_meta["paths"]["parquet"])
            self.assertEqual(tvl.num_rows, 0)
            self.assertIn("tvl_in_token", tvl.column_names)
            self.assertEqual(volume.num_rows, 0)
            self.assertIn("bucket_timestamp", volume.column_names)

    def test_metrics_flow_dual_writes_empty_timeline_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics = calculate_all_metrics(
                [],
                [],
                [],
                [],
                TARGET,
                18,
                output_dir=tmp,
                artifact_format="both",
            )
            self.assertEqual(metrics["artifact_format"], "both")
            self.assertEqual(metrics["artifacts"]["tvl_timeline"]["rows"], 0)
            self.assertEqual(metrics["artifacts"]["volume_timeline"]["rows"], 0)
            self.assertTrue(
                (Path(tmp) / "tables" / "tvl_timeline.parquet").exists()
            )
            self.assertTrue(
                (Path(tmp) / "tables" / "volume_timeline.parquet").exists()
            )

    def test_metrics_both_keeps_runtime_timelines_but_trims_metrics_json(self):
        tvl_row = _tvl_timeline_row()
        volume = _volume_timeline_document()
        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.analysis.metrics.build_tvl_timeline", return_value=[tvl_row]
        ), patch(
            "src.analysis.metrics.calculate_volume_metrics", return_value=volume
        ):
            metrics = calculate_all_metrics(
                [],
                [],
                [],
                [],
                TARGET,
                18,
                output_dir=tmp,
                artifact_format="both",
            )
            self.assertEqual(metrics["tvl_timeline"], [tvl_row])
            self.assertEqual(len(metrics["volume"]["volume_timeline"]), 1)

            saved = json.loads((Path(tmp) / "metrics.json").read_text())
            self.assertEqual(saved["tvl_timeline"], [])
            self.assertEqual(saved["volume"]["volume_timeline"], [])
            self.assertEqual(saved["artifacts"]["tvl_timeline"]["rows"], 1)
            self.assertEqual(saved["artifacts"]["volume_timeline"]["rows"], 2)

    def test_dashboard_inputs_prefer_parquet_and_rebuild_volume_buckets(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "holdings.json").write_text(json.dumps({
                "holdings": [{"address": "0xSTALE"}],
                "holdings_count": 1,
            }))
            (out / "positions.json").write_text(json.dumps([
                {**_position_row(), "owner": "0xSTALE"}
            ]))
            (out / "swaps.json").write_text("[]")
            (out / "liquidity_events.json").write_text("[]")
            (out / "transfers.json").write_text("[]")
            (out / "metrics.json").write_text(json.dumps({
                "tvl_timeline": [],
                "volume": {
                    **_volume_timeline_document(),
                    "volume_timeline": [],
                },
            }))
            (out / "volume_timeline.json").write_text(json.dumps({
                **_volume_timeline_document(),
                "volume_timeline": [],
            }))

            write_table("holdings", [_holding_row()], out, "parquet")
            write_table("positions", [_position_row()], out, "parquet")
            write_table("swaps", [_swap_row()], out, "parquet")
            write_table("tvl_timeline", [_tvl_timeline_row()], out, "parquet")
            write_table(
                "volume_timeline",
                flatten_volume_timeline(_volume_timeline_document()),
                out,
                "parquet",
            )

            inputs = _load_dashboard_inputs(out)
            self.assertEqual(inputs["holdings"]["holdings"][0]["address"], "0xaabb")
            self.assertEqual(inputs["positions"][0]["owner"], "0xddeeff")
            self.assertEqual(len(inputs["events_all"]), 1)
            self.assertEqual(
                inputs["metrics"]["tvl_timeline"][0]["price"],
                _tvl_timeline_row()["price"],
            )
            volume_timeline = inputs["metrics"]["volume"]["volume_timeline"]
            self.assertEqual(len(volume_timeline), 1)
            self.assertEqual(
                volume_timeline[0]["pools"]["0xaabb"]["volume_in_token"],
                10.0,
            )

            correlation_metrics, liquidity_rows, transfer_rows = (
                _load_analysis_inputs(out)
            )
            self.assertEqual(
                correlation_metrics["tvl_timeline"][0]["tvl_in_token"],
                _tvl_timeline_row()["tvl_in_token"],
            )
            self.assertEqual(
                correlation_metrics["volume"]["volume_timeline"][0]
                ["pools"]["0xaabb"]["volume_in_token"],
                10.0,
            )
            self.assertEqual(liquidity_rows, [])
            self.assertEqual(transfer_rows, [])

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

    def test_query_flat_volume_timeline_by_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = flatten_volume_timeline(_volume_timeline_document())
            write_table("volume_timeline", rows, tmp, "parquet")
            result = query_tables(
                "SELECT pool_address, SUM(volume_in_token) AS volume "
                "FROM volume_timeline GROUP BY pool_address ORDER BY pool_address",
                tmp,
                table_names=["volume_timeline"],
            )
            self.assertEqual(result, [
                {"pool_address": "0xaabb", "volume": 10.0},
                {"pool_address": "0xccdd", "volume": 5.0},
            ])
