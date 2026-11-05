import importlib.util,sys,types,pathlib,tempfile,unittest,json,subprocess,hashlib
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[2]
pkg=types.ModuleType('endstone_music');pkg.__path__=[str(ROOT/'src/endstone_music')];sys.modules['endstone_music']=pkg
from endstone_music.pack_generator import PackGenerator,GLOBAL_PREFIX
class IndependentPack(unittest.TestCase):
 def link(self,path,target):
  try:path.symlink_to(target,target_is_directory=True)
  except OSError as error:
   if getattr(error,'winerror',None)==1314:self.skipTest('Windows account cannot create symlinks; covered by Linux CI')
   raise
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.temp.name);self.upload=self.root/'uploads';self.upload.mkdir();self.out=self.root/'packs';self.gen=PackGenerator(data_path=self.root/'data')
 def tearDown(self):self.temp.cleanup()
 def test_real_audio_preserved_and_nonspatial_alias(self):
  audio=self.upload/'Song One.wav';subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=0.2',str(audio)],check=True)
  before=audio.read_bytes();self.gen.generate(self.upload,self.out,'Test',{'party':{}})
  self.assertEqual(audio.read_bytes(),before)
  defs=json.loads((self.out/'endstone_music_pack/sounds/sound_definitions.json').read_text())['sound_definitions']
  alias=defs[GLOBAL_PREFIX+'custom.song_one']['sounds'][0];self.assertIs(alias['is3D'],False);self.assertIs(alias['stream'],True)
  self.assertIs(defs['custom.song_one']['sounds'][0]['is3D'],False)
  item=json.loads((self.out/'endstone_music_behavior/items/playlist_party.json').read_text());self.assertEqual(item['minecraft:item']['description']['identifier'],'endstone_music:playlist_party')
 def test_upgrade_existing_without_uploads(self):
  dest=self.out/'endstone_music_pack/sounds';dest.mkdir(parents=True);(dest/'sound_definitions.json').write_text(json.dumps({'format_version':'1.14.0','sound_definitions':{'custom.old':{'category':'neutral','sounds':['sounds/custom/old']}}}))
  self.gen.generate(self.upload,self.out,'Test',{});defs=json.loads((dest/'sound_definitions.json').read_text())['sound_definitions'];self.assertIn(GLOBAL_PREFIX+'custom.old',defs)
 def test_upgrade_preserves_existing_uuids_and_duration_registry(self):
  self.gen.generate(self.upload,self.out,'Before',{'party':{}})
  metadata=json.loads(self.gen.metadata_file.read_text());metadata['custom_extension']='retained';self.gen.metadata_file.write_text(json.dumps(metadata))
  (self.gen.data_path/'track_durations.json').write_text('{"custom.old":12.5}')
  definitions=self.out/'endstone_music_pack/sounds/sound_definitions.json';definitions.write_text(json.dumps({'sound_definitions':{'custom.old':{'category':'record','sounds':['sounds/custom/old']}}}))
  upgraded=PackGenerator(data_path=self.gen.data_path);upgraded.generate(self.upload,self.out,'After',{'party':{}})
  after=json.loads(upgraded.metadata_file.read_text())
  for key in ('pack_uuid','module_uuid','behavior_uuid','behavior_module_uuid','custom_extension'):self.assertEqual(after[key],metadata[key])
  self.assertEqual(upgraded.tracks['custom.old']['duration'],12.5)
  self.assertEqual(json.loads((upgraded.data_path/'track_durations.json').read_text()),{'custom.old':12.5})
 def test_metadata_failure_restores_both_packs_and_registries(self):
  self.gen.generate(self.upload,self.out,'Before',{'party':{}})
  paths=[self.out/'endstone_music_pack/manifest.json',self.out/'endstone_music_behavior/manifest.json',self.gen.metadata_file,self.gen.data_path/'track_durations.json']
  before=[p.read_bytes() for p in paths]
  from endstone_music.pack_generator import atomic_json
  def fail_duration(path,value):
   if pathlib.Path(path)==self.gen.data_path/'track_durations.json':raise OSError('simulated registry failure')
   return atomic_json(path,value)
  with patch('endstone_music.pack_generator.atomic_json',side_effect=fail_duration):
   with self.assertRaises(OSError):self.gen.generate(self.upload,self.out,'After',{})
  self.assertEqual([p.read_bytes() for p in paths],before)
 def test_malformed_lists_do_not_touch_world(self):
  world=self.root/'worlds/demo';world.mkdir(parents=True)
  rp=world/'world_resource_packs.json';bp=world/'world_behavior_packs.json';rp.write_text('[{"pack_id":"other","version":[1,0,0]}]');bp.write_text('{bad')
  before=rp.read_bytes()
  with self.assertRaises((ValueError,json.JSONDecodeError)):self.gen.install_to_world(world.parent,'demo')
  self.assertEqual(rp.read_bytes(),before)
 def test_no_escape_symlink_output_directory(self):
  outside=self.root/'unrelated';outside.mkdir();self.link(self.out,outside)
  try:self.gen.generate(self.upload,self.out,'Test',{})
  except (ValueError,OSError):pass
  self.assertEqual(list(outside.iterdir()),[])
 def test_pack_lists_preserve_other_entries_and_are_idempotent(self):
  world=self.root/'worlds/demo';world.mkdir(parents=True);out=world/'resource_packs';self.gen.generate(self.upload,out,'Test',{'party':{}})
  for name in ['world_resource_packs.json','world_behavior_packs.json']:(world/name).write_text('[{"pack_id":"other","version":[1,2,3]}]')
  self.gen.install_to_world(world.parent,'demo');self.gen.install_to_world(world.parent,'demo')
  for name in ['world_resource_packs.json','world_behavior_packs.json']:
   entries=json.loads((world/name).read_text());self.assertEqual(len(entries),2);self.assertIn({'pack_id':'other','version':[1,2,3]},entries)
  self.assertTrue((world/'behavior_packs/endstone_music_behavior/blocks/jukebox.json').exists())
 def test_no_escape_symlink_world(self):
  worlds=self.root/'worlds';worlds.mkdir();outside=self.root/'unrelated';outside.mkdir();self.link(worlds/'demo',outside)
  try:self.gen.install_to_world(worlds,'demo')
  except (ValueError,OSError):pass
  self.assertFalse((outside/'world_resource_packs.json').exists())
if __name__=='__main__':unittest.main(verbosity=2)
