import asyncio,importlib,io,json,os,unittest,wave
from types import SimpleNamespace as N
from unittest.mock import AsyncMock,patch
ROLE=os.environ['SPEECH_TEST_ROLE']
PREFIX='src.chat.services.persona_speech' if ROLE=='mordred' else 'src.chat.services'
generation=importlib.import_module(PREFIX+'.speech_generation')
decision=importlib.import_module(PREFIX+'.speech_decision')
replies=importlib.import_module(PREFIX+'.speech_replies')
VOICES={'sakura': 'c8413ff753ee416e897bdefb7dc7c460'}

class Context:
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass

def wav_bytes():
 stream=io.BytesIO()
 with wave.open(stream,'wb') as w:
  w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(b'\x00\x00'*2400)
 return stream.getvalue()

class TestSpeech(unittest.IsolatedAsyncioTestCase):
 def message(self,text='发个语音说晚安'):
  return N(id=123,content=text,author=N(id=0,bot=False),webhook_id=None,
           channel=N(id=55,typing=lambda:Context(),send=AsyncMock()),reply=AsyncMock())
 def test_voice(self):
  p=generation.speech_generation.provider('fish')
  self.assertEqual((p['voice_id'],p['language'],p['model']),(VOICES[ROLE],'Japanese','s2.1-pro-free'))
 def test_other_provider(self):
  with self.assertRaises(generation.SpeechError):generation.speech_generation.provider('moss')
 def test_audio_validation(self):
  self.assertAlmostEqual(generation.validate_audio(wav_bytes()).seconds,.1)
  for bad in (b'',b'{"error":"no audio"}',wav_bytes()[:45]):
   with self.assertRaises(generation.SpeechError):generation.validate_audio(bad)
 def test_literal_and_reference_validation(self):
  m=self.message('念一下：晚安')
  self.assertEqual(decision.read_decision('{"speech":{"generate":true,"source":"literal","text":"晚安"}}',m,'好梦',None,100),'晚安')
  self.assertIsNone(decision.read_decision('{"speech":{"generate":true,"source":"literal","text":"冒充别人"}}',m,'好梦',None,100))
  ref=N(author=N(id=200),content='你好')
  self.assertIsNone(decision.read_decision('{"speech":{"generate":true,"source":"reference","text":""}}',m,'好梦',ref,100))
 def test_cancel(self):
  m=self.message('不要语音，只用文字')
  self.assertFalse(decision.read_decision('{"speech":{"generate":true,"source":"reply","text":""}}',m,'晚安',None,100))
 def test_natural_request(self):
  for text in ('发个语音呗','想听你说晚安','让我听听你的声音','把这句念一下'):
   self.assertTrue(decision.needs_review(self.message(text)))
  for text in ('声音好听','晚安','语音接口怎么实现','不要发语音'):
   self.assertFalse(decision.needs_review(self.message(text)))
 def test_prompt_shapes(self):
  for entries in ([{'role':'system','content':'base'}],[{'role':'system','parts':['base']}] ):
   got=decision.with_capability(entries,True);self.assertIn('TTS',str(got))
 async def test_japanese_gloss(self):
  with patch.object(generation.ai_service,'generate',AsyncMock(return_value=N(content='{"japanese":"おやすみなさい。","chinese":"晚安。"}'))):
   value=await generation.speech_generation.japanese_text('晚安。')
  self.assertEqual(str(value),'おやすみなさい。');self.assertEqual(value.gloss,'晚安。')
 async def test_bad_translation(self):
  for value in ('{"japanese":"晚安","chinese":"晚安"}','{"japanese":"おやすみ。","chinese":""}'):
   with patch.object(generation.ai_service,'generate',AsyncMock(return_value=N(content=value))):
    with self.assertRaises(generation.SpeechError):await generation.speech_generation.japanese_text('晚安')
 async def test_text_then_audio_and_gloss(self):
  cog=replies.SpeechRepliesMixin();cog.bot=N(user=N(id=100));cog.speech_jobs=set();cog.background=set();cog._can_chat=AsyncMock(return_value=True)
  m=self.message();order=['text_delivered']
  async def reply(**kw):
   self.assertIsNone(kw.get('content'));self.assertTrue(kw['file'].filename.endswith('_speech.wav'));order.append('audio')
  async def send(text,**kw):self.assertEqual(text,'晚安。');order.append('gloss')
  m.reply=reply;m.channel.send=send
  audio=generation.GeneratedSpeech(wav_bytes(),.1,'Japanese','晚安。')
  with patch.object(generation.speech_generation,'enabled',AsyncMock(return_value=True)),patch.object(generation.speech_generation,'generate',AsyncMock(return_value=audio)),patch.object(replies,'record_decision',AsyncMock()):
   queued=await cog._queue_speech_decision(m,'{"speech":{"generate":true,"source":"reply","text":""}}','晚安。')
   self.assertTrue(queued)
   await asyncio.gather(*list(cog.background))
  self.assertEqual(order,['text_delivered','audio','gloss']);self.assertFalse(cog.speech_jobs)
 async def test_bot_and_disabled_rejected(self):
  cog=replies.SpeechRepliesMixin();cog.bot=N(user=N(id=100));cog.speech_jobs=set();cog.background=set();cog._can_chat=AsyncMock(return_value=True)
  m=self.message();m.author.bot=True
  self.assertFalse(await cog._queue_speech_decision(m,'{}','hello'))
  m.author.bot=False
  with patch.object(generation.speech_generation,'enabled',AsyncMock(return_value=False)):
   self.assertFalse(await cog._queue_speech_decision(m,'{}','hello'))
  self.assertFalse(cog.background)
 async def test_valid_false_no_extra_model(self):
  cog=replies.SpeechRepliesMixin();cog.bot=N(user=N(id=100));cog.speech_jobs=set();cog.background=set();cog._can_chat=AsyncMock(return_value=True)
  with patch.object(generation.speech_generation,'enabled',AsyncMock(return_value=True)),patch.object(replies,'record_decision',AsyncMock()),patch.object(replies,'fallback_decision',AsyncMock()) as fallback:
   self.assertFalse(await cog._queue_speech_decision(self.message('今天天气不错'),'{"speech":{"generate":false,"source":"reply","text":""}}','是呀'))
   fallback.assert_not_called()
 async def test_false_request_review(self):
  cog=replies.SpeechRepliesMixin();cog.bot=N(user=N(id=100));cog.speech_jobs=set();cog.background=set();cog._can_chat=AsyncMock(return_value=True);cog._speech=AsyncMock()
  with patch.object(generation.speech_generation,'enabled',AsyncMock(return_value=True)),patch.object(replies,'record_decision',AsyncMock()),patch.object(replies,'fallback_decision',AsyncMock(return_value='晚安')) as fallback:
   self.assertTrue(await cog._queue_speech_decision(self.message(),'{"speech":{"generate":false,"source":"reply","text":""}}','晚安'))
   await asyncio.gather(*list(cog.background));fallback.assert_awaited_once();cog._speech.assert_awaited_once()


 async def test_alternate_voice_persistence(self):
  state={}
  async def get(k,default=None):return state.get(k,default)
  async def save(k,v):state[k]=v
  with patch.object(generation.store,'get',get),patch.object(generation.store,'set',save),patch.object(generation.speech_generation,'_keys',return_value=['fixture']):
   a=await generation.speech_generation.select_voice('alternate')
   self.assertEqual(a['voice_id'],'0d7bf7806c534ef0a7661b42c96d338f')
   self.assertEqual((await generation.speech_generation.current_provider())['voice_id'],a['voice_id'])
   self.assertEqual((await generation.speech_generation.select_voice('primary'))['voice_id'],VOICES[ROLE])
   with self.assertRaises(generation.SpeechError):await generation.speech_generation.select_voice('untrusted')

if __name__=='__main__':unittest.main()
