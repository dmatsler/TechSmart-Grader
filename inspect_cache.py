# inspect_cache.py
import json
import sys

unit = sys.argv[1] if len(sys.argv) > 1 else '3_5'
with open(f'context_cache_{unit}.json') as f:
    d = json.load(f)

print(f"{'Assignment':<60} starter  solution")
print(f"{'-'*60} {'-'*7}  {'-'*8}")
for aid, entry in d['assignments'].items():
    s = len(entry.get('starter_code', '').splitlines())
    sol = len(entry.get('solution_code', '').splitlines())
    print(f"{aid:<60} {s:>7}  {sol:>8}")