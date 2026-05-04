Audit market data integrity in this repository.

Check for:
- missing OHLCV columns
- stale data
- gaps in history
- symbol normalization issues
- provider fallback weaknesses
- silent exception swallowing
- scan logic assumptions based on incomplete data

Output:
- findings
- affected files
- data integrity risks
- concrete remediation steps
- suggested validation tests

Use agent: reviewer
