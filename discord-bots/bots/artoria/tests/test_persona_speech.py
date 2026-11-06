import asyncio,importlib,io,json,os,pathlib,struct,tempfile,unittest,wave
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
ROLE=os.environ['SPEECH_TEST_ROLE'];LEGACY=ROLE in ('aesc','morgan')
PREFIX='src.chat.services.persona_media' if LEGACY else 'src.chat.services'
m=importlib.import_module(PREFIX+'.speech_generation');d=importlib.import_module(PREFIX+'.speech_decision')
r=importlib.import_module(PREFIX+'.speech_replies');budget_module=importlib.import_module(PREFIX+'.fleet_budget')
def wav_bytes():
 b=io.BytesIO()
 with wave.open(b,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(b'\0'*4800)
 return b.getvalue()
class Response:
 status=200
 def __init__(self):self.status=Response.status;self.content_length=None;self.content=self
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
 async def iter_chunked(self,n):yield wav_bytes()
class Session:
 calls=[]
 def __init__(self,**kw):pass
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
 def post(self,url,**kw):Session.calls.append((url,kw));return Response()
class Slot:
 async def __aenter__(self):return True
 async def __aexit__(self,*args):pass
class Budget:
 path='mock'
 def __init__(self):self.acquire=AsyncMock(return_value='test');self.release=AsyncMock()
 def slot(self,*a,**kw):return Slot()
class Speech(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.s=m.SpeechGenerationService();self.b=Budget();Session.calls=[];Response.status=200
  self.s.enabled=AsyncMock(return_value=True);self.s._record=AsyncMock();self.s.japanese_text=AsyncMock(return_value='おはよう。');self.s.chinese_text=AsyncMock()
  self.s.current_provider=AsyncMock(return_value=self.s.provider('fish'));self.s._next_key=AsyncMock(return_value=('fake-key',1,2))
 async def generate(self):
  with patch.object(m,'fleet_budget',self.b),patch.object(m,'decode_memory_available',return_value=True),patch.object(m.aiohttp,'ClientSession',Session):return await self.s.generate('早上好',1)
 async def test_default_japanese(self):self.assertEqual(self.s.provider()['language'],'Japanese')
 async def test_exact_fish_voice(self):self.assertEqual(self.s.provider('fish')['voice_id'],{'aesc':'40fbb2a1edf1434bb397b3b01ece7194','morgan':'b2fa4286614b4b32b44d4c7273f5c609','artoria':'021306a4214c4203b6616d3d1cb5dae9','yuzuki':'a1bc0dd7625243b4b402db009e293d91','touko':'be67ba79424149ec8a4564cebd3e7938'}[ROLE])
 async def test_moss_capability(self):
  if ROLE=='aesc':self.assertEqual(self.s.provider('moss')['voice_id'],'83dbc8e9-850c-4914-9ad3-d36bee14f493')
  else:
   with self.assertRaises(m.SpeechError):self.s.provider('moss')
 async def test_fish_uses_japanese_translation(self):
  await self.generate();self.s.japanese_text.assert_awaited_once_with('早上好');self.s.chinese_text.assert_not_awaited()
  url,kw=Session.calls[0];self.assertEqual(url,'https://api.fish.audio/v1/tts');self.assertEqual(kw['headers']['model'],'s2.1-pro-free');self.assertEqual(kw['json']['text'],'おはよう。');self.assertFalse(kw['allow_redirects'])
 async def test_no_key_hopping_on_limit(self):
  Response.status=429
  with self.assertRaises(m.SpeechError):await self.generate()
  self.assertEqual(len(Session.calls),1);self.s._next_key.assert_awaited_once();self.b.release.assert_awaited_once()
 async def test_no_chinese_fallback(self):
  self.s.japanese_text.side_effect=m.SpeechError('translation')
  with self.assertRaises(m.SpeechError):await self.generate()
  self.assertFalse(Session.calls)
 async def test_moss_japanese_payload(self):
  if ROLE!='aesc':self.skipTest('No MOSS voice configured')
  self.s.current_provider=AsyncMock(return_value=self.s.provider('moss'));await self.generate();url,kw=Session.calls[0]
  self.assertEqual(url,'https://api.mosi.cn/v1/audio/speech');self.assertEqual(kw['json']['language'],'Japanese');self.assertEqual(kw['json']['input'],'おはよう。')
 async def test_key_configuration_separate(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=pathlib.Path(tmp)/'speech.env';p.write_text('FISH_API_KEYS=["fake-one","fake-two"]\nMOSS_API_KEYS=["fake-moss"]\n')
   with patch.dict(os.environ,{'SPEECH_ENV_FILE':str(p)}):self.assertEqual(self.s.key_count('fish'),2);self.assertEqual(self.s.key_count('moss'),1)
 async def test_atomic_rotation(self):
  with tempfile.TemporaryDirectory() as tmp:
   b=budget_module.FleetBudget(str(pathlib.Path(tmp)/'b.db'));self.s._keys=lambda provider:['fake-one','fake-two'];self.s._next_key=m.SpeechGenerationService._next_key.__get__(self.s)
   async with b.database():pass
   with patch.object(m,'fleet_budget',b):
    rows=await asyncio.gather(*(self.s._next_key('fish') for _ in range(4)));self.assertEqual(sorted(v[1] for v in rows),[1,1,2,2])
   self.assertNotIn(b'fake-one',(pathlib.Path(tmp)/'b.db').read_bytes())
 async def test_bad_translation_rejected(self):
  s=m.SpeechGenerationService()
  with patch.object(m.ai_service,'generate',AsyncMock(return_value=SimpleNamespace(content='{"japanese":"早上好。"}'))):
   with self.assertRaises(m.SpeechError):await s.japanese_text('早上好')
 async def test_wav(self):self.assertAlmostEqual(m.validate_audio(wav_bytes()).seconds,.1)
 async def test_fish_stream(self):
  b=bytearray(wav_bytes());struct.pack_into('<I',b,4,0xffffff24);struct.pack_into('<I',b,40,0xffffff00);self.assertAlmostEqual(m.validate_fish_audio(b).seconds,.1)
 async def test_truncated(self):
  with self.assertRaises(m.SpeechError):m.validate_audio(wav_bytes()[:-4])
 async def test_json_not_audio(self):
  with self.assertRaises(m.SpeechError):m.validate_fish_audio(b'{"error":1}')
 async def test_read_only_switch_denied_no_write(self):
  with patch.object(m.store,'set',AsyncMock()) as save:
   with self.assertRaises(m.SpeechError):await self.s.select_provider('unknown')
   save.assert_not_awaited()
 async def test_no_oversized_text(self):
  with self.assertRaises(m.SpeechError):
   with patch.object(m,'fleet_budget',self.b):await self.s.generate('a'*501,1)

class Decisions(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.msg=SimpleNamespace(id=1,content='请说：晚安。',guild=None,author=SimpleNamespace(id=0,bot=False),webhook_id=None,channel=SimpleNamespace(id=2),reply=AsyncMock())
 def parse(self,action,reference=None):return d.read_decision(json.dumps({'speech':action}),self.msg,'晚安，明天见。',reference,99)
 async def test_reply(self):self.assertEqual(self.parse({'generate':True}), '晚安，明天见。')
 async def test_false(self):self.assertIs(self.parse({'generate':False}),False)
 async def test_literal(self):self.assertEqual(self.parse({'generate':True,'source':'literal','text':'晚安。'}),'晚安。')
 async def test_wrong_literal(self):self.assertIsNone(self.parse({'generate':True,'source':'literal','text':'你好呀。'}))
 async def test_other_reference(self):self.assertIsNone(self.parse({'generate':True,'source':'reference'},SimpleNamespace(author=SimpleNamespace(id=98),content='hi')))
 async def test_boolean_type(self):self.assertIsNone(self.parse({'generate':'true'}))
 async def test_bot_denied(self):
  obj=r.SpeechRepliesMixin();self.msg.author.bot=True;self.assertFalse(await obj._queue_speech_decision(self.msg,'{}','hi'))
 async def test_webhook_denied(self):
  obj=r.SpeechRepliesMixin();self.msg.webhook_id=3;self.assertFalse(await obj._queue_speech_decision(self.msg,'{}','hi'))
 async def test_disabled(self):
  obj=r.SpeechRepliesMixin();setattr(obj,'_can_speech' if LEGACY else '_can_chat',AsyncMock(return_value=True))
  with patch.object(m.speech_generation,'enabled',AsyncMock(return_value=False)):self.assertFalse(await obj._queue_speech_decision(self.msg,'{}','hi'))
 async def test_permission_recheck(self):
  obj=r.SpeechRepliesMixin();setattr(obj,'_can_speech' if LEGACY else '_can_chat',AsyncMock(return_value=False));self.assertFalse(await obj._queue_speech_decision(self.msg,'{}','hi'))
 async def test_no_model_for_false(self):
  obj=r.SpeechRepliesMixin();obj.bot=SimpleNamespace(user=SimpleNamespace(id=99));obj.speech_jobs=set();obj.background=set();setattr(obj,'_can_speech' if LEGACY else '_can_chat',AsyncMock(return_value=True))
  with patch.object(m.speech_generation,'enabled',AsyncMock(return_value=True)),patch.object(r,'record_decision',AsyncMock()),patch.object(r,'fallback_decision',AsyncMock()) as fallback:
   self.assertFalse(await obj._queue_speech_decision(self.msg,'{"speech":{"generate":false}}','hi'));fallback.assert_not_awaited()

class LegacyGuards(unittest.IsolatedAsyncioTestCase):
 async def test_original_private_author_gate(self):
  if not LEGACY:self.skipTest('Lite core unchanged')
  import discord
  from src.chat.services.private_inbox import PrivateInbox
  from src.chat.services.persona_media.cog import PersonaMediaCog
  intents=discord.Intents.none();intents.messages=True
  async with discord.Client(intents=intents) as client:
   events=[];state=client._connection;state.dispatch=lambda e,*args:events.append((e,args))
   payload={'id':'0','channel_id':'0','type':0,'author':{'id':'0','username':'offline_fixture','discriminator':'0','avatar':None,'bot':False},'content':'offline','timestamp':'2026-11-03T01:00:00+00:00','edited_timestamp':None,'attachments':[],'embeds':[],'mentions':[],'mention_roles':[],'pinned':False,'tts':False,'mention_everyone':False,'flags':0}
   state.parse_message_create(payload);message=next(a[0] for e,a in events if e=='message');self.assertIsNone(message.channel.recipient)
   inbox=PrivateInbox(AsyncMock(),AsyncMock());self.assertTrue(inbox.allowed(message))
   obj=PersonaMediaCog(SimpleNamespace(get_cog=lambda name:SimpleNamespace(private_inbox=inbox)))
   from src.chat.features.chat_settings.services.chat_settings_service import chat_settings_service
   from src.chat.utils.database import chat_db_manager
   with patch('src.chat.config.chat_config.CHAT_ENABLED',True),patch('src.chat.services.persona_media.cog.takeover_service.message_active',AsyncMock(return_value=False)),patch.object(chat_settings_service,'is_chat_globally_enabled',AsyncMock(return_value=True)),patch.object(chat_db_manager,'is_user_globally_blacklisted',AsyncMock(return_value=False)),patch.object(chat_db_manager,'is_user_blacklisted',AsyncMock(return_value=False)):
    self.assertTrue(await obj._can_speech(message));message.author=SimpleNamespace(id=999,bot=False);self.assertFalse(await obj._can_speech(message))
   await inbox.close()
 async def test_admin_command_rejects_nonadmin(self):
  if LEGACY:
   from src.chat.services.persona_media.cog import PersonaMediaCog as Cog
  else:
   from src.chat.cogs.settings_cog import SettingsCog as Cog
  obj=Cog(SimpleNamespace());i=SimpleNamespace(guild=object(),user=SimpleNamespace(id=999,bot=False,guild_permissions=SimpleNamespace(administrator=False)),response=SimpleNamespace(send_message=AsyncMock()))
  await Cog.speech_control.callback(obj,i,上游=SimpleNamespace(value='fish'));i.response.send_message.assert_awaited_once();self.assertTrue(i.response.send_message.call_args.kwargs['ephemeral'])

if __name__=='__main__':unittest.main()
