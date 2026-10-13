import sys,types,pathlib,unittest,tempfile,json
from unittest.mock import Mock
ROOT=pathlib.Path(__file__).resolve().parents[2]
pkg=types.ModuleType('endstone_music');pkg.__path__=[str(ROOT/'src/endstone_music')];sys.modules['endstone_music']=pkg
endstone=types.ModuleType('endstone')
class Player:
 def __init__(self,op=True):self.name='Tester';self.unique_id='test-id';self.location=object();self.op=op;self.messages=[];self.sounds=[];self.forms=[]
 def has_permission(self,p):return self.op
 def send_message(self,m):self.messages.append(m)
 def play_sound(self,*a):self.sounds.append(('play',a))
 def stop_sound(self,*a):self.sounds.append(('stop',a))
 def send_form(self,f):self.forms.append(f)
endstone.Player=Player;sys.modules['endstone']=endstone
forms=types.ModuleType('endstone.form')
class Form:
 def __init__(self,*a,**kw):self.kw=kw;self.buttons=[]
 def add_button(self,text,**kw):self.buttons.append((text,kw))
for name in ['ActionForm','ModalForm','TextInput','Toggle']:setattr(forms,name,Form)
sys.modules['endstone.form']=forms
inventory=types.ModuleType('endstone.inventory');inventory.ItemStack=lambda *a:a;sys.modules['endstone.inventory']=inventory
events=types.ModuleType('endstone.event')
class Event:
 class Action:RIGHT_CLICK_AIR=1;RIGHT_CLICK_BLOCK=2
 def __init__(self,player,item=None,block=None):self.player=player;self.item=item;self.block=block;self.action=2;self.cancelled=False
 def cancel(self):self.cancelled=True
events.PlayerInteractEvent=Event;sys.modules['endstone.event']=events
from endstone_music.music_controls import MusicControls,JUKEBOX,ITEM_PREFIX
from endstone_music.playlists import PlaylistStore,Playback
class Controls(MusicControls):
 def __init__(self,path):
  self.legacy_generation=0;self.legacy_join_tasks=[];self.data_path=path;self.playlists=PlaylistStore(path/'playlists.json');self.music=Playback(self._play_global,self._stop_global);self.music_clicks={};self.global_listeners={};self.server=types.SimpleNamespace(online_players=[]);self.stopped=[]
 def stop_custom_sounds_for_player(self,name):self.stopped.append(name)
 def get_available_sounds(self):return ['custom.a']
class IndependentControls(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.c=Controls(self.root);self.c.playlists.put('party',[{'sound':'custom.a','duration':2}]);(self.root/'global_sounds_registry.json').write_text('["custom.a"]');self.block=types.SimpleNamespace(type=JUKEBOX,dimension=types.SimpleNamespace(name='overworld'),x=1,y=2,z=3);self.item=types.SimpleNamespace(type=types.SimpleNamespace(id=ITEM_PREFIX+'party'));self.op=Player();self.normal=Player(False)
 def tearDown(self):self.tmp.cleanup()
 def test_real_block_type_string_and_operator_only(self):
  event=Event(self.normal,self.item,self.block);self.assertTrue(self.c.handle_music_interaction(event));self.assertTrue(event.cancelled);self.assertFalse(self.c.playlists.data['jukeboxes']);self.assertIsNone(self.c.music.session)
 def test_item_identity_no_display_name_trust(self):
  counterfeit=types.SimpleNamespace(type=types.SimpleNamespace(id='minecraft:stick'),display_name='Playlist: party');event=Event(self.op,counterfeit,None);self.assertFalse(self.c.handle_music_interaction(event));self.assertIsNone(self.c.music.session)
 def test_global_once_and_late_join(self):
  a=Player();b=Player();b.unique_id='b';self.c.server.online_players=[a];self.c.start_playlist(self.op,'party');self.assertEqual(len(a.sounds),1)
  self.c.server.online_players.append(b);self.assertEqual(b.sounds,[])
  self.c.music.next();self.assertEqual(b.sounds,[]);self.assertIsNone(self.c.music.session)
 def test_dimension_aware_binding_and_duplicate_interaction(self):
  event=Event(self.op,self.item,self.block);self.assertTrue(self.c.handle_music_interaction(event));self.assertIn('["overworld",1,2,3]',self.c.playlists.data['jukeboxes'])
  form_count=len(self.op.forms);self.c.handle_music_interaction(event);self.assertEqual(len(self.op.forms),form_count)
  self.c.music_clicks.clear();self.block.dimension.name='nether';self.c.handle_music_interaction(event);self.assertEqual(len(self.c.playlists.data['jukeboxes']),2)
 def test_missing_stale_form_cannot_rebind_or_play(self):
  key='["overworld",1,2,3]';self.c.jukebox_state=lambda key:'missing';self.c.bind_jukebox(self.op,key,'party');self.assertEqual(self.c.playlists.data['jukeboxes'],{})
  self.assertRaises(ValueError,self.c.start_playlist,self.op,'party',key);self.assertIsNone(self.c.music.session)
 def test_unlink_stops_only_linked_source(self):
  key='["overworld",1,2,3]';self.c.playlists.bind(key,'party');self.c.jukebox_state=lambda key:'present';self.c.start_playlist(self.op,'party',key);self.c.unbind_jukebox(self.op,key);self.assertIsNone(self.c.music.session);self.assertEqual(self.c.playlists.data['jukeboxes'],{})
 def test_loaded_missing_cleanup_and_unloaded_preservation(self):
  key='["overworld",1,2,3]';self.c.playlists.bind(key,'party');self.c.jukebox_state=lambda key:'present';self.c.start_playlist(self.op,'party',key)
  self.c.music_tick_count=19;self.c.jukebox_state=lambda key:'unloaded';self.c._music_tick();self.assertIsNone(self.c.music.session);self.assertIn(key,self.c.playlists.data['jukeboxes'])
  self.c.music_tick_count=19;self.c.jukebox_state=lambda key:'missing';self.c._music_tick();self.assertNotIn(key,self.c.playlists.data['jukeboxes'])
 def test_nonop_commands_do_not_mutate(self):
  for args in [['play','party'],['stop'],['next'],['playlist','delete','party']]:self.assertTrue(self.c.music_command(self.normal,args))
  self.assertIsNone(self.c.music.session);self.assertIn('party',self.c.playlists.data['playlists'])
if __name__=='__main__':unittest.main(verbosity=2)
