"""Self-contained author-side acceptance procedure; never independent validation."""
import copy
import json
from pathlib import Path
import tempfile

from ghostframe.evidence import verify_bundle
from ghostframe.fixtures import flagship
from ghostframe.models import GFError
from ghostframe.runtime import Engine
from ghostframe.store import Store


def main():
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / 'review.db')
        engine = Engine(store)
        original = engine.run(flagship())
        replay = engine.replay(original)
        event = next(e for e in store.events(original)
                     if e['kind'] == 'TOOL_CALL_COMPLETED' and e['tool'] == 'read_ticket')
        branch = engine.fork(original, event['event_id'],
                             {'action': 'delete', 'target': '/documents/draft_report.txt'})
        exported = store.export(original)
        valid = verify_bundle(exported)
        damaged = copy.deepcopy(exported)
        damaged['bundle']['events'][0]['payload']['reviewer_tamper'] = True
        try:
            verify_bundle(damaged)
        except GFError as error:
            rejection = error.code
        else:
            raise AssertionError('Tampered evidence was accepted')
        result = {'replay': replay['status'], 'branch': branch['status'],
                  'original_correct': branch['comparison']['original_outcome']['task_correct'],
                  'branch_correct': branch['comparison']['branch_outcome']['task_correct'],
                  'valid_export': valid['valid'], 'tamper_rejection': rejection,
                  'scope': 'Synthetic document driver; unsigned consistency, not authenticity'}
        if not (result['replay'] == 'REPLAY_SUCCESS' and result['branch'] == 'BRANCH_SUCCESS'
                and not result['original_correct'] and result['branch_correct'] and result['valid_export']):
            raise AssertionError(result)
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
