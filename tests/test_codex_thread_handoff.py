"""Regression checks for thread identity and valid completion boundaries."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from eval_framework.baselines._clients.harness_api import build_harness_target, _call_codex_exec_prompt
from eval_framework.memory_adapters.harness_native import HarnessMemoryAdapter


class ThreadHandoffTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target=replace(build_harness_target('Harness-Codex'),runner='codex',workdir=Path(self.temp.name),codex_persistent_session=True)
        self.commands=[]

    def fake(self,thread='thread-a',complete=True,answer='OK'):
        def run(cmd,**kwargs):
            self.commands.append(cmd)
            Path(cmd[cmd.index('--output-last-message')+1]).write_text(answer)
            events=[dict(type='thread.started',thread_id=thread)]
            if complete:events.append(dict(type='turn.completed',usage={'input_tokens':12}))
            return subprocess.CompletedProcess(cmd,0,'\n'.join(json.dumps(e) for e in events),'')
        return run

    def call(self,state):
        return _call_codex_exec_prompt(self.target,prompt='test',image_paths=None,max_images=0,max_image_bytes=0,thread_state=state)

    def test_resume_exact_id_and_reset(self):
        state={}
        with patch('subprocess.run',side_effect=self.fake()):
            self.call(state);self.call(state)
        self.assertEqual(state,{'thread_id':'thread-a'})
        self.assertNotIn('--ephemeral',self.commands[0])
        self.assertNotIn('resume',self.commands[0])
        self.assertIn('resume',self.commands[1])
        self.assertEqual(self.commands[1][-2: ],['thread-a','test'])
        self.assertNotIn('--sandbox',self.commands[1])
        adapter=HarnessMemoryAdapter(baseline_name='Harness-Codex')
        adapter._codex_thread_state=state
        adapter.reset()
        self.assertEqual(adapter._codex_thread_state,{})

    def test_wrong_thread_rejected(self):
        state={'thread_id':'original'}
        with patch('subprocess.run',side_effect=self.fake('wrong')):
            with self.assertRaisesRegex(RuntimeError,'different thread'):self.call(state)
        self.assertEqual(state,{'thread_id':'original'})

    def test_incomplete_or_empty_answer_does_not_set_thread(self):
        for options in [{'complete':False},{'answer':''}]:
            state={}
            with self.subTest(options=options),patch('subprocess.run',side_effect=self.fake(**options)):
                with self.assertRaises(RuntimeError):self.call(state)
            self.assertEqual(state,{})

    def test_legacy_call_stays_ephemeral(self):
        with patch('subprocess.run',side_effect=self.fake()):self.call(None)
        self.assertIn('--ephemeral',self.commands[0])
        self.assertNotIn('resume',self.commands[0])

    def test_attachment_gate_follows_delivery_not_preloading(self):
        adapter=HarnessMemoryAdapter(baseline_name='Harness-Codex')
        allowed=[]
        observed=[]
        adapter._session_input_observer=lambda sid, paths: allowed.extend(paths)
        def turn(sid,path):
            return SimpleNamespace(session_id=sid,turn_index=0,role='user',timestamp=None,text='synthetic',
                attachments=[SimpleNamespace(type='image_caption',image_id=sid,file_path=path,caption='synthetic')])
        adapter.ingest_turn(turn('S1','current.png'))
        adapter.end_session('S1')
        adapter.ingest_turn(turn('S2','future.png'))
        adapter.end_session('S2')
        self.assertEqual(allowed,[])
        with patch.object(adapter,'_send_message',side_effect=lambda msg: observed.append(list(allowed))):
            adapter.flush_ingest()
        self.assertEqual(observed,[['current.png'],['current.png','future.png']])


if __name__=='__main__':unittest.main()
