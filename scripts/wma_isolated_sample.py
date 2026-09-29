"""Prepare a fresh sample state and an external, credential-holding API proxy."""
import json
import os
from pathlib import Path
import tempfile
from wma_isolation import PORT, new_sample_uid
from wma_transport import start_proxy


def prepare(output, config):
    root = Path(tempfile.mkdtemp(prefix='wma-isolated-sample-'))
    uid = new_sample_uid()
    for name in ('work', 'tmp', 'home/.codex'):
        (root / name).mkdir(parents=True)
    # Copy only explicit model behavior settings, never user history/auth/MCP/hooks.
    selected = {k:config[k] for k in ('model_reasoning_effort', 'personality') if k in config}
    lines = [f'{k} = {json.dumps(v)}' for k,v in selected.items()]
    lines += ['model = "gpt-6-astra"', 'model_provider = "icodeeasy"',
              'cli_auth_credentials_store = "file"', 'suppress_unstable_features_warning = true',
              '[model_providers.icodeeasy]', 'name = "icodeeasy"',
              f'base_url = "http://127.0.0.1:{PORT}"', 'wire_api = "responses"',
              'requires_openai_auth = false', 'env_key = "OPENAI_API_KEY"']
    (root / 'home/.codex/config.toml').write_text('\n'.join(lines)+'\n')
    # Only paths just created for this sample; no recursive permission changes.
    for path in [root, root/'work', root/'tmp', root/'home', root/'home/.codex', root/'home/.codex/config.toml']:
        os.chown(path, uid, uid)
    bridge_root = Path(tempfile.mkdtemp(prefix='wma-api-bridge-'))
    bridge = bridge_root / 'responses.sock'
    proxy = start_proxy(output/'transport.jsonl', output/'request_audit.jsonl',
                        unix_socket=bridge, api_key=os.environ['OPENAI_API_KEY'])
    os.chown(bridge_root, uid, uid)
    os.chown(bridge, uid, uid)
    os.environ.update(WMA_ISOLATION_ROOT=str(root), WMA_ISOLATION_BRIDGE=str(bridge),
                      WMA_NATIVE_PROXY=f'http://127.0.0.1:{PORT}', WMA_NATIVE_TRACE=str(output/'codex_calls'),
                      WMA_ISOLATION_READ_FILES='[]')
    return root, proxy


def install_attachment_gate(output, dataset):
    from eval_framework.memory_adapters.harness_native import HarnessMemoryAdapter
    original_init = HarnessMemoryAdapter.__init__
    dataset = Path(dataset).resolve(strict=True)

    def initialize(self, **kwargs):
        original_init(self, **kwargs)
        allowed = set()

        def observe(session_id, paths):
            current = []
            for raw in paths:
                path = Path(raw).resolve(strict=True)
                if not path.is_relative_to(dataset) or path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
                    raise RuntimeError('Unexpected attachment in isolation gate')
                current.append(str(path))
            allowed.update(current)
            os.environ['WMA_ISOLATION_READ_FILES'] = json.dumps(sorted(allowed))
            with (output/'attachment_gate.jsonl').open('a') as f:
                f.write(json.dumps(dict(session_id=session_id, current=current, allowed=sorted(allowed)))+'\n')
        self._session_input_observer = observe

    HarnessMemoryAdapter.__init__ = initialize
