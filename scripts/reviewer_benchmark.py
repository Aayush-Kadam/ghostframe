"""Local recorder cost against a minimal virtual mutation; unequal feature sets."""
import copy
import importlib.metadata
import json
import platform
import tempfile
from pathlib import Path
from statistics import median
from time import perf_counter

from ghostframe.fixtures import flagship
from ghostframe.runtime import Engine
from ghostframe.store import Store


def main():
    rows = []
    fixture = flagship()
    for trial in range(31):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'bench.db')
            engine = Engine(store)
            start = perf_counter()
            files = copy.deepcopy(fixture['files'])
            del files[fixture['ticket']['target']]
            direct = perf_counter() - start
            if files != fixture['expected_files']:
                raise AssertionError('Standalone baseline state mismatch')
            start = perf_counter()
            rid = engine.run(fixture)
            recording = perf_counter() - start
            start = perf_counter()
            replay = engine.replay(rid)
            replay_seconds = perf_counter() - start
            if replay['status'] != 'REPLAY_SUCCESS':
                raise AssertionError(replay)
            physical = sum(p.stat().st_size for p in Path(directory).iterdir() if p.is_file())
            if trial:  # One declared warmup, excluded from statistics.
                rows.append({'trial': trial, 'direct_mutation_seconds': direct,
                             'record_seconds': recording, 'replay_seconds': replay_seconds,
                             'database_and_sidecar_bytes_after_two_runs': physical,
                             'replay': replay['status']})
    summary = {key: {'median': median(r[key] for r in rows),
                     'min': min(r[key] for r in rows), 'max': max(r[key] for r in rows)}
               for key in rows[0] if key.endswith(('seconds', 'two_runs'))}
    print(json.dumps({'python': platform.python_version(), 'os': platform.platform(),
                      'processor': platform.processor(), 'ghostframe': importlib.metadata.version('ghostframe'),
                      'trials': 30, 'excluded_warmup': 1,
                      'warning': 'Direct mutation has no ledger, checkpoints, redaction, replay or UI. Store initialization excluded from timing. Storage is physical file total at observation time. No LangGraph/Temporal performance claim.',
                      'summary': summary, 'rows': rows}, indent=2))


if __name__ == '__main__':
    main()
