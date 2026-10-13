import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('reviewed_playlists',ROOT/'src/endstone_music/playlists.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class IndependentCore(unittest.TestCase):
 def setUp(self):
  self.time=0.; self.events=[]
  self.player=m.Playback(lambda t:self.events.append(('play',t['sound'])),lambda s:self.events.append(('stop',s)),lambda:self.time)
  self.tracks=[{'sound':'custom.a','duration':2.,'pitch':2.},{'sound':'custom.b','duration':1.}]
 def test_deadline_pitch_and_lag_bounded(self):
  self.player.start('a',{'tracks':self.tracks,'loop':True})
  self.time=.99; self.player.tick(); self.assertEqual(len(self.events),1)
  self.time=1.; self.player.tick(); self.assertEqual(self.events[-1],('play','custom.b'))
  self.time=1000.; self.player.tick(); self.assertEqual(len(self.events),5)
  self.player.tick(); self.assertEqual(len(self.events),5)
 def test_snapshot_replacement_stop(self):
  source={'tracks':self.tracks,'loop':True};self.player.start('a',source)
  source['tracks'][0]['sound']='changed'
  self.player.start('b',{'tracks':[{'sound':'custom.c','duration':1}], 'loop':False})
  self.assertEqual(self.events[:3],[('play','custom.a'),('stop','custom.a'),('play','custom.c')])
  self.player.stop(); self.time=100.;self.player.tick();self.assertIsNone(self.player.session)
  self.assertEqual(len(self.events),4)
 def test_nonloop_terminal_no_repeat(self):
  self.player.start('a',{'tracks':self.tracks,'loop':False});self.time=1.;self.player.tick();self.time=2.;self.player.tick()
  self.assertIsNone(self.player.session);self.assertEqual(self.events[-1],('stop','custom.b'))
  self.player.tick();self.assertEqual(len(self.events),4)
 def test_store_atomic_invalid_reload_retains_memory(self):
  with tempfile.TemporaryDirectory() as d:
   path=pathlib.Path(d)/'playlists.json';store=m.PlaylistStore(path)
   store.put('party',self.tracks);store.bind('["overworld",0,1,2]','party');snapshot=json.loads(path.read_text())
   store2=m.PlaylistStore(path);self.assertEqual(store2.data,snapshot)
   path.write_text('{bad');self.assertRaises(json.JSONDecodeError,store2.reload);self.assertEqual(store2.data,snapshot)
 def test_delete_removes_bindings_and_validation_preserves_file(self):
  with tempfile.TemporaryDirectory() as d:
   path=pathlib.Path(d)/'playlists.json';store=m.PlaylistStore(path);store.put('party',self.tracks);store.bind('["overworld",0,1,2]','party')
   before=path.read_bytes()
   self.assertRaises(ValueError,store.put,'bad',[{'sound':'x','duration':float('nan')}]);self.assertEqual(path.read_bytes(),before)
   store.delete('party');self.assertEqual(store.data['jukeboxes'],{})
if __name__=='__main__':unittest.main(verbosity=2)
