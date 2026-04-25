"""Apply data_fetcher.py fixes using precise line numbers (0-indexed)."""

import ast

with open("data_fetcher.py", encoding="utf-8") as f:
    lines = f.readlines()

inserts = {}

# Change 1: After line 116 (results = {}), add outcomes dict
inserts.setdefault(116, []).append("        outcomes: dict[str, str] = {}\n")

# Change 2: After line 128 (results[ticker] = cached), add skipped outcome
# Line 128 is "                results[ticker] = cached\n" (indent=16)
inserts.setdefault(128, []).append('                outcomes[ticker] = "skipped"\n')

# Change 3: After line 162 (blank line after except KeyError), insert None check
# Using exact indentation: if = 24 spaces, body = 28 spaces
inserts.setdefault(162, []).extend([
    "            if ticker_frame is None:\n",
    "                outcomes[ticker] = \"batch_missing\"\n",
    "                logger.warning(f\"⚠️ {ticker}: batch verisinde bulunamadı\")\n",
    "                unresolved.append(ticker)\n",
    "                continue\n",
    "\n",
])

# Change 4: After line 164 (if df is None:), add outcome
# Line 164: "            if df is None:\n" (indent=24)
# Insert at indent=28 (inside if block)
inserts.setdefault(164, []).append("                outcomes[ticker] = \"batch_normalize_failed\"\n")

# Change 5: After line 169 (results[ticker] = df), add success outcome
# Line 169: "            results[ticker] = df\n" (indent=24)
inserts.setdefault(169, []).append("            outcomes[ticker] = \"success\"\n")

# Change 6: Fallback loop modifications
# Line 202: "                if df is not None:\n" (indent=16)
# Line 203: "                    results[ticker] = df\n" (indent=20)
inserts.setdefault(203, []).extend([
    "                        outcomes[ticker] = \"fallback_success\"\n",
    "                    else:\n",
    "                        outcomes.setdefault(ticker, \"failed\")\n",
])

# Line 204: "            except Exception as e:\n" (indent=12)
inserts.setdefault(204, []).append("                    outcomes.setdefault(ticker, \"failed\")\n")

# Change 7: After line 217 (last logger.info separator), add coverage summary
# Line 218 is blank, we add before "return results"
inserts.setdefault(218, []).extend([
    "\n",
    "        for ticker in self.watchlist:\n",
    "            outcomes.setdefault(ticker, \"failed\")\n",
    "        ok = sum(1 for v in outcomes.values() if v in (\"skipped\", \"success\", \"fallback_success\"))\n",
    "        fail = sum(1 for v in outcomes.values() if v not in (\"skipped\", \"success\", \"fallback_success\"))\n",
    "        cov = ok / len(self.watchlist) * 100 if self.watchlist else 0\n",
    "        logger.info(\"fetch_all_coverage total=%s success=%s failed=%s coverage_pct=%.1f outcomes=%s\",\n",
    "                     len(self.watchlist), ok, fail, cov, outcomes)\n",
])

result = []
for i, line in enumerate(lines):
    result.append(line)
    if i in inserts:
        result.extend(inserts[i])

with open("data_fetcher.py", "w", encoding="utf-8", newline="") as f:
    f.writelines(result)

with open("data_fetcher.py", encoding="utf-8") as f:
    ast.parse(f.read())
print("OK - all changes applied and syntax verified")
