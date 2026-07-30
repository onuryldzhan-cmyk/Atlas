# Atlas Phase 3E Parse Error Analysis

No files were modified, moved, or deleted.

## Classification counts

- `ACTIVE_CODE_REPAIR`: 2
- `SYNTAX_ERROR_REVIEW`: 7
- `TEST_CODE_REPAIR`: 4

## Files

### `atlas_os/configuration/__init__.py`

- Classification: `ACTIVE_CODE_REPAIR`
- Error: `invalid non-printable character U+FEFF`
- Location: line 1, column 1
- Imported by: 18 file(s)
- Recommendation: Repair syntax before further cleanup; real imports exist.

### `atlas_os/secrets/__init__.py`

- Classification: `ACTIVE_CODE_REPAIR`
- Error: `invalid non-printable character U+FEFF`
- Location: line 1, column 1
- Imported by: 20 file(s)
- Recommendation: Repair syntax before further cleanup; real imports exist.

### `atlas_paper_trading/paper_trading_engine.py`

- Classification: `SYNTAX_ERROR_REVIEW`
- Error: `invalid non-printable character U+FEFF`
- Location: line 1, column 1
- Imported by: 0 file(s)
- Recommendation: Manual review required before repair or quarantine.

### `atlas_paper_trading/paper_trading_main.py`

- Classification: `SYNTAX_ERROR_REVIEW`
- Error: `invalid non-printable character U+FEFF`
- Location: line 1, column 1
- Imported by: 0 file(s)
- Recommendation: Manual review required before repair or quarantine.

### `atlas_paper_trading/performance_report.py`

- Classification: `SYNTAX_ERROR_REVIEW`
- Error: `invalid non-printable character U+FEFF`
- Location: line 1, column 1
- Imported by: 0 file(s)
- Recommendation: Manual review required before repair or quarantine.

### `atlas_paper_trading/position_tracker.py`

- Classification: `SYNTAX_ERROR_REVIEW`
- Error: `invalid non-printable character U+FEFF`
- Location: line 1, column 1
- Imported by: 0 file(s)
- Recommendation: Manual review required before repair or quarantine.

### `atlas_paper_trading/risk_guardian.py`

- Classification: `SYNTAX_ERROR_REVIEW`
- Error: `invalid non-printable character U+FEFF`
- Location: line 1, column 1
- Imported by: 0 file(s)
- Recommendation: Manual review required before repair or quarantine.

### `inspect_atlas_os_lifecycle.py`

- Classification: `SYNTAX_ERROR_REVIEW`
- Error: `invalid non-printable character U+FEFF`
- Location: line 1, column 1
- Imported by: 0 file(s)
- Recommendation: Manual review required before repair or quarantine.

### `test_atlas_infrastructure.py`

- Classification: `TEST_CODE_REPAIR`
- Error: `invalid non-printable character U+FEFF`
- Location: line 1, column 1
- Imported by: 0 file(s)
- Recommendation: Repair or retire test after checking current test coverage.

### `test_atlas_runtime_empty.py`

- Classification: `TEST_CODE_REPAIR`
- Error: `invalid non-printable character U+FEFF`
- Location: line 1, column 1
- Imported by: 0 file(s)
- Recommendation: Repair or retire test after checking current test coverage.

### `test_atlas_secure_core.py`

- Classification: `TEST_CODE_REPAIR`
- Error: `invalid non-printable character U+FEFF`
- Location: line 1, column 1
- Imported by: 0 file(s)
- Recommendation: Repair or retire test after checking current test coverage.

### `test_configuration_secrets_service.py`

- Classification: `TEST_CODE_REPAIR`
- Error: `invalid non-printable character U+FEFF`
- Location: line 1, column 1
- Imported by: 0 file(s)
- Recommendation: Repair or retire test after checking current test coverage.

### `web_app.py`

- Classification: `SYNTAX_ERROR_REVIEW`
- Error: `invalid non-printable character U+FEFF`
- Location: line 1, column 1
- Imported by: 0 file(s)
- Recommendation: Manual review required before repair or quarantine.
