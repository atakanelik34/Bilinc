# Bilinc — Phase 5 Detail Plan: Production v1.0

> **Created:** 2026-04-07
> **Phase:** 5 — Benchmarks, Observability, Security, Docs, v1.0 Release
> **Expected Version:** v1.0.0
> **Target Tests:** 30+ (plan: 40+)
> **Duration:** ~8-10 saat (marathon sessions bölünebilir)
> **Pre-requisites:** Phase 1 ✅, Phase 2 ✅, Phase 3 ✅, Phase 4 ✅

---

## 🔍 CURRENT STATE — NE VAR, NE YOK

### ✅ Mevcut (Phase 1-4):
| Component | File | Durum |
|-----------|------|-------|
| 5 Memory Types | `core/models.py` | ✅ Working |
| SQLite Backend | `storage/sqlite.py` | ✅ Working |
| Working Memory (8 slots) | `core/working_memory.py` | ✅ Working |
| Consolidation (7 phases) | `adaptive/consolidation.py` | ✅ Working |
| System 1/2 Arbiter | `core/dual_process.py` | ✅ Working |
| Confidence Estimator | `core/confidence.py` | ✅ Working |
| Forgetting Engine | `core/forgetting.py` | ✅ Working |
| Z3 SMT Verifier | `core/verifier.py` | ✅ Working |
| Merkle Audit | `core/audit.py` | ✅ Working |
| StatePlane | `core/stateplane.py` | ✅ Working |
| AGM Engine + DP Postulates | `adaptive/agm_engine.py` | ✅ Working |
| Knowledge Graph | `core/knowledge_graph.py` | ✅ Working |
| Multi-Agent Belief Sync | `core/belief_sync.py` | ✅ Working |
| MCP Server v2 (12 tools) | `mcp_server/server_v2.py` | ✅ Working |
| Rate Limiter | `mcp_server/rate_limiter.py` | ✅ Working |

**Current test count: 77 passing** (7 files)

### ❌ Eksik (Phase 5):
| Component | Status | Priority |
|-----------|--------|----------|
| Benchmark suite | Yok | HIGH |
| Observability | Yok | MEDIUM |
| Security hardening | Yok | HIGH |
| Production docs | Yok | MEDIUM |
| CHANGELOG.md | Yok | LOW |
| CONTRIBUTING.md | Yok | LOW |
| Git tag + PyPI upload | Yok | LOW |
| Pre-existing test fixes | 9 fail | HIGH (quick fix) |

### ⚠️ Pre-existing Failures (quick fix candidates):
Eski testler async StatePlane API'sine bağımlı, ama sync kullanıyoruz. Ya test'ler update ya da StatePlane'de sync wrapper eksik.

---

## 📋 STEP-BY-STEP PLAN

### Adım 5.0: Test Suite Temizliği + Pre-existing Fixes (1 saat)

**Problem:** `test_core.py` (6 fail) + `test_integration.py` (3 fail) — async/sync mismatch.

**Strateji:**
1. `StatePlane.commit()`, `.recall()`, `.forget()` zaten async — bunları sync wrapper'larla sar
2. Veya testleri `@pytest.mark.asyncio` yap (ama bu bağımlılık ekler)
3. **Karar:** StatePlane'de sync wrapper ekle (`commit_sync()`, `recall_sync()` vb), test'leri bunlara çevir.

| Action | File | Değişiklik |
|--------|------|------------|
| FIX | `core/stateplane.py` | `commit_sync()`, `recall_sync()`, `forget_sync()` ekle |
| FIX | `tests/test_core.py` | async → sync çağrılara çevir |
| FIX | `tests/test_integration.py` |同上 |
| FIX | `adapters/cross_tool.py` | `recall(intent=)` → sync recall |

**Expected:** 77 → **86/86 passing**

---

### Adım 5.1: Formal Benchmark Suite (2 saat)

**Dosya:** `benchmarks/`

#### 5.1.1: Memory Retrieval Benchmark
```python
# benchmarks/test_retrieval.py
# Dataset: 1000 synthetic memories
# Metrics: latency (p50, p95, p99), recall accuracy, precision
```
- `test_retrieval_latency_100_entries()` — p50, p95, p99
- `test_retrieval_latency_1000_entries()` — p50, p95, p99
- `test_retrieval_accuracy()` — correct/total
- `test_retrieval_per_memory_type()` — per-type latency

**4 benchmarks**

#### 5.1.2: Verification Benchmark
```python
# benchmarks/test_verification.py
# Dataset: 500 valid + 200 invalid
```
- `test_verification_accuracy()` — true positive rate
- `test_verification_false_positive_rate()`
- `test_verification_false_negative_rate()`
- `test_verification_scalability_1000()` — 1000 entries verification time

**4 benchmarks**

#### 5.1.3: Consolidation Benchmark
```python
# benchmarks/test_consolidation.py
```
- `test_consolidation_memory_reduction()` — before/after
- `test_consolidation_time()` — elapsed for 200 entries
- `test_consolidation_accuracy()` — important entries preserved
- `test_forget_curve_accuracy()` — Ebbinghaus model fit

**4 benchmarks**

#### 5.1.4: AGM Stress Test
```python
# benchmarks/test_agm_stress.py
```
- `test_agm_1000_operations()` — 1000 consecutive revise ops
- `test_agm_conflict_resolution_time()` — avg resolve time
- `test_agm_explanation_trail_growth()` — audit log size

**3 benchmarks**

**Total Benchmarks:** 15 (not unit tests, runnable scripts)
**Expected Version:** v0.9.0beta

---

### Adım 5.2: Security Hardening (1.5 saat)

**Dosyalar:** `src/bilinc/security/`

#### 5.2.1: Input Validation
```python
# security/input_validator.py
class InputValidator:
    def validate_key(key: str) -> str:
        """Key: alphanumeric, hyphens, underscores, max 256 chars."""
    
    def validate_value(value: Any, max_size: int = 1024 * 1024) -> Any:
        """Value: JSON serializable, max 1MB."""
    
    def sanitize_for_kg(text: str) -> str:
        """Remove XSS/injection from KG node names."""
```

#### 5.2.2: Resource Limits
```python
# security/resource_limits.py
class ResourceLimits:
    MAX_ENTRIES_PER_TYPE = {"episodic": 10000, "semantic": 5000, ...}
    MAX_ENTRENCHMENT_SIZE = 50000
    MAX_KG_NODES = 100000
    MAX_KG_EDGES = 500000
    
    @classmethod
    def check_entry(cls, memory_type: str, count: int) -> bool:
        """Returns True if within limits."""
```

#### 5.2.3: MCP Auth Integration
```python
# security/mcp_auth.py
def validate_api_key(key: str, expected: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    import hmac
    return hmac.compare_digest(key.encode(), expected.encode())
```

#### 5.2.4: Test Plan (8 tests)
| # | Test | What it verifies |
|---|------|----------------|
| 1 | `test_key_validation_accepts_valid` | Valid keys accepted |
| 2 | `test_key_validation_rejects_invalid` | Path traversal, special chars rejected |
| 3 | `test_value_size_limit` | >1MB values rejected |
| 4 | `test_kg_sanitization` | XSS/injection in node names cleaned |
| 5 | `test_resource_limits_enforced` | Max entries per type enforced |
| 6 | `test_mcp_auth_valid_key` | Valid API key accepted |
| 7 | `test_mcp_auth_invalid_key` | Invalid key rejected |
| 8 | `test_mcp_auth_timing_attack_resistant` | Constant-time comparison |

**Files to create:**
| File | Lines (est) |
|------|-------------|
| `security/__init__.py` | 10 |
| `security/input_validator.py` | 100 |
| `security/resource_limits.py` | 80 |
| `security/mcp_auth.py` | 50 |
| `tests/test_security.py` | 200 |

---

### Adım 5.3: Observability (1 saat)

**Dosyalar:** `src/bilinc/observability/`

#### 5.3.1: Metrics Collector
```python
# observability/metrics.py
class MetricsCollector:
    # Prometheus-compatible metrics
    commits_total: Counter
    recalls_total: Counter
    verification_failures: Counter
    working_memory_usage: Gauge
    consolidation_duration: Histogram
    agm_operations: Counter
    
    def export_prometheus(self) -> str:
        """Return metrics in Prometheus exposition format."""
    
    def export_json(self) -> Dict:
        """Return metrics as JSON for dashboards."""
```

#### 5.3.2: Health Check
```python
# observability/health.py
class HealthCheck:
    def check_all(self) -> Dict:
        return {
            "status": "healthy" | "degraded" | "unhealthy",
            "components": {
                "agm_engine": bool,
                "knowledge_graph": bool,
                "belief_sync": bool,
                "working_memory": bool,
                "audit_trail": bool,
            },
            "version": "1.0.0",
        }
```

#### 5.3.3: Structured Logging
```python
# observability/logging_config.py
def setup_structured_logging():
    """Configure JSON structured logging with request IDs."""
```

#### 5.3.4: Test Plan (5 tests)
| # | Test | What it verifies |
|---|------|-----------------|
| 1 | `test_metrics_counter_increment` | commit → counter increases |
| 2 | `test_metrics_histogram_records` | consolidation → latency recorded |
| 3 | `test_metrics_export_prometheus_format` | Export returns valid Prometheus text |
| 4 | `test_health_check_all_healthy` | Full init → healthy |
| 5 | `test_health_check_degraded` | Missing component → degraded |

**Files to create:**
| File | Lines (est) |
|------|-------------|
| `observability/__init__.py` | 10 |
| `observability/metrics.py` | 150 |
| `observability/health.py` | 80 |
| `tests/test_observability.py` | 150 |

---

### Adım 5.4: Documentation (1.5 saat)

**Dosyalar:** `docs/`

Bu markdown docs — Docusaurus-ready ama standalone olarak da okunabilir.

| File | Lines (est) | Content |
|------|-------------|---------|
| `docs/index.md` | 150 | Overview, getting started, feature matrix |
| `docs/architecture.md` | 200 | 7-layer diagram, data flow, component interaction |
| `docs/mcp-server.md` | 200 | 12 tool reference, setup guide, examples |
| `docs/security.md` | 150 | Input validation, rate limits, auth |
| `CHANGELOG.md` | 200 | v0.1.0 → v1.0.0 history |

**Total:** ~5 dosya, ~900 satır

---

### Adım 5.5: v1.0 Release (0.5 saat)

| Task | Command/Action |
|------|----------------|
| Version bump | `pyproject.toml`: `1.0.0` |
| `__init__.py` | `__version__ = "1.0.0"` |
| Test count verify | `pytest --tb=no -q` → 100+ |
| Git commit | `git commit -m "release: v1.0.0"` |
| Git tag | `git tag v1.0.0 && git push --tags` |
| PyPI build | `python3 -m build` |
| PyPI upload | `twine upload dist/*` (if creds available) |

---

## 📊 TEST & FILE SUMMARY

### Test Progress
| Source | Count |
|--------|-------|
| Phase 1 (existing) | 32 |
| Phase 2 (existing) | 15 |
| Phase 3 (AGM + KG + Sync) | 18 + 20 + 13 = 51 |
| Phase 3 Integration | 10 |
| Phase 4 (MCP v2) | 16 |
| **Pre-existing (86)** | |
| Phase 5.0: Pre-existing fixes | 9 fix → **95** |
| Phase 5.1: Benchmarks | 0 tests (benchmark scripts) |
| Phase 5.2: Security | 8 |
| Phase 5.3: Observability | 5 |
| **Phase 5 Total:** | **+22 tests** |
| **v1.0.0 Target:** | **~117 tests** |

### File Growth
| Phase | New Files | Updated Files | Cumulative |
|-------|-----------|---------------|------------|
| Phase 1 | 8 | 3 | 8 |
| Phase 2 | 2 | 2 | 10 |
| Phase 3 | 4 | 1 | 14 |
| Phase 4 | 3 | 2 | 17 |
| **Phase 5.0** | 0 | 3 | 17 |
| **Phase 5.1** | 4 (benchmark scripts) | 0 | 21 |
| **Phase 5.2** | 3 + 1 test | 1 | 25 |
| **Phase 5.3** | 2 + 1 test | 1 | 28 |
| **Phase 5.4** | 5 | 1 (README update) | 33 |
| **Phase 5.5** | 0 | 2 | 33 |
| **Grand Total:** | **~33 files** | |

---

## ⚠️ RISKS & MITIGATIONS

| Risk | Impact | Mitigation |
|------|--------|------------|
| Async/sync mismatch in StatePlane | 9 tests fail | Add sync wrappers in 5.0 |
| Benchmark dataset too large | Slow CI | Use smaller datasets, run full in CI only nightly |
| Prometheus format too complex | Metrics inaccurate | Use simple text format, validate with Grafana |
| Documentation out of sync with code | Confusion for users | Write docs AFTER code, not before |
| PyPI API key expired | Can't publish | Check `~/.pypirc` before attempting upload |

## 🎯 SUCCESS CRITERIA

- [ ] 90+ tests passing (all pre-existing fixed + Phase 5)
- [ ] Benchmark suite runs end-to-end (4 benchmarks)
- [ ] Security: input validation, rate limits, auth working
- [ ] Observability: metrics export, health check working
- [ ] Docs: 5 files covering architecture, MCP, security
- [ ] Git tag v1.0.0 pushed
- [ ] CHANGELOG.md complete
- [ ] PyPI upload (if creds available)

---

*Plan created: 2026-04-07. Ready for execution.*
