import json

import pytest

from bilinc.core import MemoryType, StatePlane
from bilinc.core.event_ledger import EventOperation
from bilinc.eval.receipts import EvalReceiptError, create_eval_receipt
from bilinc.storage.sqlite import SQLiteBackend


async def _backend(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "receipts.db"))
    await backend.init()
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    await plane.commit("receipt:event-source", "receipt evidence", memory_type=MemoryType.SEMANTIC)
    return backend


@pytest.mark.asyncio
async def test_eval_receipt_requires_existing_event_ids_and_is_public_safe(tmp_path):
    backend = await _backend(tmp_path)
    events = await backend.list_memory_events()
    assert events

    with pytest.raises(EvalReceiptError):
        await create_eval_receipt(
            backend=backend,
            dataset_name="toy",
            dataset_hash="hash-toy",
            event_ids=["missing-event"],
            metrics={"recall@5": 1.0},
            run_config={"api_key": "sk-not-allowed-123456789012345"},
            result_artifact={"rows": [{"answer": "ok", "token": "secret-token"}]},
        )

    receipt = await create_eval_receipt(
        backend=backend,
        dataset_name="toy",
        dataset_hash="hash-toy",
        event_ids=[events[0].id],
        metrics={"recall@5": 1.0, "latency_ms": 12},
        metric_definitions={"recall@5": "hit in top five"},
        run_config={"profile": "balanced", "api_key": "sk-not-allowed-123456789012345"},
        result_artifact={"rows": [{"answer": "ok", "token": "secret-token"}]},
        notes="local temp-db test",
    )

    assert receipt.public_safe is True
    assert receipt.event_range_start == events[0].id
    assert receipt.event_range_end == events[0].id
    assert receipt.checkpoint_root == events[0].event_hash
    assert receipt.run_config_hash
    assert receipt.result_artifact_hash
    assert receipt.metrics["recall@5"] == 1.0
    payload = receipt.to_dict()
    dumped = json.dumps(payload, sort_keys=True)
    assert "***" not in dumped
    assert "secret-token" not in dumped
    assert "answer" not in dumped
    assert receipt.redactions["run_config_redacted"] is True
    assert receipt.redactions["result_artifact_redacted"] is True

    repeat = await create_eval_receipt(
        backend=backend,
        dataset_name="toy",
        dataset_hash="hash-toy",
        event_ids=[events[0].id],
        metrics={"latency_ms": 12, "recall@5": 1.0},
        metric_definitions={"recall@5": "hit in top five"},
        run_config={"api_key": "sk-not...2345", "profile": "balanced"},
        result_artifact={"rows": [{"token": "secret-token", "answer": "ok"}]},
        notes="local temp-db test",
    )
    assert repeat.receipt_id == receipt.receipt_id

    receipt_events = await backend.list_memory_events(operation=EventOperation.EVAL_RECEIPT.value)
    assert len(receipt_events) == 1
    assert receipt_events[0].subject == receipt.receipt_id
    assert receipt_events[0].payload_json["dataset_name"] == "toy"
    assert "result_artifact" not in receipt.redactions
    assert receipt.redactions["result_artifact_redacted"] is True
