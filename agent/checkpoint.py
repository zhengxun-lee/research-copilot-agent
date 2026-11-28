"""Atomic JSON checkpoints. A store is intended for one task owner at a time."""
import json
import os
from pathlib import Path
import tempfile


class CheckpointStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id):
        if not run_id or any(c not in '0123456789abcdef' for c in run_id):
            raise ValueError('Invalid run id')
        return self.directory / (run_id + '.json')

    def save(self, run_id, data):
        path = self._path(run_id)
        fd, temporary = tempfile.mkstemp(dir=self.directory, prefix='.checkpoint-')
        try:
            with os.fdopen(fd, 'w') as stream:
                os.chmod(temporary, 0o600)
                json.dump(data, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load(self, run_id):
        with self._path(run_id).open() as stream:
            data = json.load(stream)
        if data.get('version') != 1 or data['context']['run_id'] != run_id:
            raise ValueError('Invalid checkpoint')
        return data
