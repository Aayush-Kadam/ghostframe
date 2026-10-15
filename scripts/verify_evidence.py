import argparse
import json
from pathlib import Path

from ghostframe.evidence import verify_bundle

p = argparse.ArgumentParser(description="Verify exported GhostFrame evidence without its database")
p.add_argument("bundle")
a = p.parse_args()
print(json.dumps(verify_bundle(json.loads(Path(a.bundle).read_text())), indent=2))
