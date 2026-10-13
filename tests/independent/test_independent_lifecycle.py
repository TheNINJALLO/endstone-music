import test_independent_controls as base
import sys,types,tempfile,pathlib,unittest,json
from unittest.mock import Mock
endstone=sys.modules['endstone'];endstone.ColorFormat=types.SimpleNamespace(RED='',GREEN='',YELLOW='',GRAY='')
forms=sys.modules['endstone.form']
for name in ['Dropdown','Slider']:setattr(forms,name,base.Form)
events=sys.modules['endstone.event']
def event_handler(f=None,**kw):
 def dec(fn):fn.event_options=kw;return fn
 return dec(f) if f else dec
events.event_handler=event_handler;events.EventPriority=types.SimpleNamespace(MONITOR=5,HIGHEST=4)
for name in ['PlayerJoinEvent','PlayerQuitEvent','BlockBreakEvent']:setattr(events,name,type(name,(),{}))
plugin=types.ModuleType('endstone.plugin');plugin.Plugin=object;sys.modules['endstone.plugin']=plugin
command=types.ModuleType('endstone.command');command.Command=object;command.CommandSender=object;sys.modules['endstone.command']=command
from endstone_music.plugin import EndstoneMusicPlugin
from endstone_music.playlists import Playback,PlaylistStore
class Task:
 def __init__(self,callback):self.callback=callback;self.cancelled=False
 def cancel(self):self.cancelled=True
class Scheduler:
 def __init__(self):self.tasks=[]
 def run_task(self,owner,callback,delay=0,period=0):
  task=Task(callback);self.tasks.append(task);return task
class Lifecycle(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.p=EndstoneMusicPlugin();p=self.p;p.data_path=self.root;p.cmusic_config_file=self.root/'config.json';p.cmusic_config={'triggers':[],'join_sound':{'enabled':True,'sound':'custom.join','duration':2}};p.cmusic_config_file.write_text(json.dumps(p.cmusic_config));p.playing_sounds={};p.legacy_join_tasks=[];p.legacy_generation=0;p.server=types.SimpleNamespace(scheduler=Scheduler(),online_players=[],dispatch_command=Mock(),command_sender=object());p.logger=Mock();p.setup_music();self.op=base.Player();p.get_available_sounds=lambda:['custom.a'];p.playlists.put('party',[{'sound':'custom.a','duration':2}],True);(self.root/'global_sounds_registry.json').write_text('["custom.a"]')
 def tearDown(self):self.tmp.cleanup()
 def test_pending_join_stop_does_not_interrupt_global(self):
  p=self.p;p.on_player_join(types.SimpleNamespace(player=self.op));callback=p.legacy_join_tasks[0].callback;p.server.online_players=[self.op];p.start_playlist(self.op,'party');prior=list(self.op.sounds);callback();self.assertEqual(self.op.sounds,prior)
 def test_legacy_trigger_does_not_interrupt_global(self):
  p=self.p;p.start_playlist(self.op,'party');event=base.Event(base.Player(False),types.SimpleNamespace(type=types.SimpleNamespace(id='minecraft:stick')),types.SimpleNamespace(type='minecraft:grass_block'));p.on_player_interact(event);p.server.dispatch_command.assert_not_called();self.assertIsNotNone(p.music.session)
 def test_disable_cancels_scheduler_and_join_callbacks(self):
  p=self.p;p.on_player_join(types.SimpleNamespace(player=self.op));p.server.online_players=[self.op];p.start_playlist(self.op,'party');p.on_disable();self.assertIsNone(p.music.session);self.assertTrue(all(t.cancelled for t in p.server.scheduler.tasks));self.assertEqual(p.legacy_join_tasks,[])
 def test_reload_valid_stops_invalid_keeps(self):
  p=self.p;p.start_playlist(self.op,'party');command=types.SimpleNamespace(name='cmusic');p.cmusic_config_file.write_text('{bad');p.on_command(self.op,command,['reload']);self.assertIsNotNone(p.music.session)
  p.cmusic_config_file.write_text('{"triggers":[]}');p.on_command(self.op,command,['reload']);self.assertIsNone(p.music.session)
if __name__=='__main__':unittest.main(verbosity=2)
