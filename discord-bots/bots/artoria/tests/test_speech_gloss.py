import asyncio,importlib,io,json,os,unittest,wave
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
ROLE=os.environ['SPEECH_TEST_ROLE'];LEGACY=ROLE in ('aesc','morgan');P='src.chat.services.persona_media' if LEGACY else 'src.chat.services'
m=importlib.import_module(P+'.speech_generation');r=importlib.import_module(P+'.speech_replies')
def wav_bytes():
 b=io.BytesIO()
 with wave.open(b,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(b'\0'*4800)
 return b.getvalue()
class Gloss(unittest.IsolatedAsyncioTestCase):
 async def response(self,data):
  with patch.object(m.ai_service,'generate',AsyncMock(return_value=SimpleNamespace(content=json.dumps(data,ensure_ascii=False)))):return await m.SpeechGenerationService().japanese_text('早上好。')
 async def test_pair(self):
  text=await self.response({'japanese':'おはよう。','chinese':'早上好。'});self.assertEqual(str(text),'おはよう。');self.assertEqual(text.gloss,'早上好。');self.assertEqual(json.loads(json.dumps({'text':text}))['text'],'おはよう。')
 async def test_missing_meaning_fails_closed(self):
  with self.assertRaises(m.SpeechError):await self.response({'japanese':'おはよう。'})
 async def test_missing_japanese(self):
  with self.assertRaises(m.SpeechError):await self.response({'chinese':'早上好。'})
 async def test_bad_meaning(self):
  with self.assertRaises(m.SpeechError):await self.response({'japanese':'おはよう。','chinese':'おはよう。'})
 async def test_chinese_not_spoken(self):
  with self.assertRaises(m.SpeechError):await self.response({'japanese':'早上好。','chinese':'早上好。'})
 async def test_short_gloss_no_label(self):
  text=await self.response({'japanese':'おはよう。','chinese':'中文释义：早上好。'});self.assertEqual(text.gloss,'早上好。')
 async def test_oversize_gloss(self):
  with self.assertRaises(m.SpeechError):await self.response({'japanese':'おはよう。','chinese':'中'*501})
 async def test_no_cross_request_state(self):
  a=await self.response({'japanese':'おはよう。','chinese':'早上好。'});b=await self.response({'japanese':'こんばんは。','chinese':'晚上好。'});self.assertEqual(a.gloss,'早上好。');self.assertEqual(b.gloss,'晚上好。')
 async def test_wav_defaults_backwards_compatible(self):
  audio=m.validate_audio(wav_bytes());self.assertEqual(audio.gloss,'');self.assertEqual(audio.language,'')
class Slot:
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
class Delivery(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.obj=r.SpeechRepliesMixin();setattr(self.obj,'_can_speech' if LEGACY else '_can_chat',AsyncMock(return_value=True));self.obj.speech_jobs={(2,1)}
  self.events=[]
  async def reply(*args,**kwargs):self.events.append(('audio' if kwargs.get('file') else 'error',args,kwargs));return SimpleNamespace(id=7)
  async def send(*args,**kwargs):self.events.append(('gloss',args,kwargs));return SimpleNamespace(id=8)
  self.message=SimpleNamespace(id=1,author=SimpleNamespace(id=3),channel=SimpleNamespace(id=2,typing=lambda:Slot(),send=AsyncMock(side_effect=send)),reply=AsyncMock(side_effect=reply))
 async def deliver(self,language,gloss):
  audio=m.GeneratedSpeech(wav_bytes(),.1,language,gloss)
  with patch.object(m.speech_generation,'generate',AsyncMock(return_value=audio)),patch.object(m.speech_generation,'enabled',AsyncMock(return_value=True)):await self.obj._speech(self.message,'文本',(2,1))
 async def test_japanese_audio_then_plain_chinese(self):
  await self.deliver('Japanese','早上好。');self.assertEqual([r[0] for r in self.events],['audio','gloss']);self.assertFalse(self.events[0][1]);self.assertEqual(self.events[1][1],('早上好。',));self.assertEqual(set(self.events[1][2]),{'allowed_mentions'});self.assertFalse(self.obj.speech_jobs)
 async def test_chinese_audio_no_gloss(self):
  await self.deliver('Chinese','早上好。');self.assertEqual([r[0] for r in self.events],['audio'])
 async def test_japanese_without_meaning_no_audio(self):
  await self.deliver('Japanese','');self.assertEqual([r[0] for r in self.events],['error'])
 async def test_permission_revoked_after_audio(self):
  getattr(self.obj,'_can_speech' if LEGACY else '_can_chat').side_effect=[True,True,False];await self.deliver('Japanese','早上好。');self.assertEqual([r[0] for r in self.events],['audio'])
if __name__=='__main__':unittest.main()
