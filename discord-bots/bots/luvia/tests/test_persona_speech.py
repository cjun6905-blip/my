import ast,asyncio,importlib,json,os,pathlib,unittest
from types import SimpleNamespace as N
from unittest.mock import AsyncMock,patch
ROLE=os.environ['SPEECH_TEST_ROLE'];LEGACY=ROLE in ('aesc','morgan');P='src.chat.services.persona_media' if LEGACY else 'src.chat.services'
d=importlib.import_module(P+'.speech_decision');r=importlib.import_module(P+'.speech_replies');g=importlib.import_module(P+'.speech_generation')
def message(text='想听你说晚安',uid=3):return N(id=1,content=text,author=N(id=uid,bot=False),channel=N(id=2),webhook_id=None,reply=AsyncMock())
class Decision(unittest.TestCase):
 def test_capability_content(self):
  x=[{'role':'system','content':'原人设'},{'role':'user','content':'原消息'}];self.assertIs(d.with_capability(x),x);self.assertTrue(x[0]['content'].startswith('原人设'));self.assertIn('真实TTS',x[0]['content']);self.assertEqual(x[1]['content'],'原消息')
 def test_capability_parts(self):
  x=[{'role':'system','parts':['原人设']}];d.with_capability(x);self.assertEqual(x[0]['parts'][0],'原人设');self.assertIn('真实TTS',x[0]['parts'][-1])
 def test_disabled_no_capability(self):
  x=[{'role':'system','content':'原人设'}];self.assertEqual(d.with_capability(x,False),x);self.assertEqual(x[0]['content'],'原人设')
 def test_no_system_preserves_input(self):
  x=[{'role':'user','content':'hello'}];y=d.with_capability(x);self.assertEqual(len(x),1);self.assertEqual(y[-1],x[0]);self.assertEqual(y[0]['role'],'system')
 def test_capability_and_structured_actions_present(self):
  x=g.with_speech_instruction([{'role':'system','content':'原人设'}],True);self.assertIn('真实TTS',x[0]['content']);self.assertIn('"speech"',x[0]['content']);self.assertIn('不能发语音',x[0]['content'])
 def test_cancel_beats_bad_positive(self):
  for text in ('不要发语音','别发声音了','取消语音','只用文字回复'):
   with self.subTest(text=text):self.assertIs(d.read_decision('{"speech":{"generate":true}}',message(text),'晚安',None,9),False)
 def test_literal_cancellation_words_not_command(self):
  self.assertEqual(d.read_decision('{"speech":{"generate":true,"source":"literal","text":"不要发语音"}}',message('念一下：不要发语音'),'好的',None,9),'不要发语音')
 def test_current_reply_source_only(self):
  self.assertEqual(d.read_decision('{"speech":{"generate":true,"source":"reply","text":"晚安"}}',message(),'晚安，好梦',None,9),'晚安')
  self.assertIsNone(d.read_decision('{"speech":{"generate":true,"source":"reply","text":"别人话"}}',message(),'晚安',None,9))
 def test_wrong_boolean(self):self.assertIsNone(d.read_decision('{"speech":{"generate":"true"}}',message(),'晚安',None,9))
 def test_reference_only_own_bot(self):
  action='{"speech":{"generate":true,"source":"reference","text":""}}';ref=N(author=N(id=9),content='自己的话');self.assertEqual(d.read_decision(action,message(),'晚安',ref,9),'自己的话');ref.author.id=8;self.assertIsNone(d.read_decision(action,message(),'晚安',ref,9))
 def test_natural_requests_select_review(self):
  for text in ('发个语音呗','让我听听你的声音','读出来给我听','把这句念一下','用日语亲口说早安','开口说一句'):
   with self.subTest(text=text):self.assertTrue(d.needs_review(message(text)))
 def test_normal_technical_negative_no_review(self):
  for text in ('晚安','声音很好听','TTS接口怎么配置','语音设置有什么选项','不要发语音','只用文字回复'):
   with self.subTest(text=text):self.assertFalse(d.needs_review(message(text)))
 def test_followup_same_author_only(self):
  rows=[{'user_id':3,'bot':False,'text':'想听你的声音'}];self.assertTrue(d.needs_review(message('再来一句'),rows));self.assertFalse(d.needs_review(message('再来一句',4),rows));self.assertFalse(d.needs_review(message('再来一句')))
 def test_latest_same_author_request_replaces_stale_voice(self):
  rows=[{'user_id':3,'bot':False,'text':'语音说晚安'},{'user_id':3,'bot':False,'text':'来句笑话'}];self.assertFalse(d.needs_review(message('再来一句'),rows))

class Queue(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.obj=r.SpeechRepliesMixin();setattr(self.obj,'_can_speech' if LEGACY else '_can_chat',AsyncMock(return_value=True));self.obj.speech_jobs=set();self.obj.background=set();self.obj.bot=N(user=N(id=9));self.obj._speech=AsyncMock();self.msg=message();self.enabled=patch.object(g.speech_generation,'enabled',AsyncMock(return_value=True));self.enabled.start();self.addCleanup(self.enabled.stop)
 async def run_decision(self,raw,text=None,answer='晚安'):
  if text is not None:self.msg.content=text
  result=await self.obj._queue_speech_decision(self.msg,raw,answer)
  while self.obj.background:await asyncio.gather(*list(self.obj.background))
  return result
 async def test_true_no_extra_classifier(self):
  with patch.object(r,'fallback_decision',AsyncMock()) as fallback,patch.object(r,'record_decision',AsyncMock()):await self.run_decision('{"speech":{"generate":true}}');fallback.assert_not_called();self.obj._speech.assert_awaited_once()
 async def test_likely_missed_false_one_semantic_review(self):
  with patch.object(r,'fallback_decision',AsyncMock(return_value='晚安')) as fallback,patch.object(r,'record_decision',AsyncMock()):await self.run_decision('{"speech":{"generate":false}}');fallback.assert_awaited_once();self.obj._speech.assert_awaited_once()
 async def test_normal_false_no_extra_model_or_audio(self):
  with patch.object(r,'fallback_decision',AsyncMock()) as fallback,patch.object(r,'record_decision',AsyncMock()):await self.run_decision('{"speech":{"generate":false}}','今天天气不错');fallback.assert_not_called();self.obj._speech.assert_not_called()
 async def test_review_reject_no_audio(self):
  with patch.object(r,'fallback_decision',AsyncMock(return_value=False)) as fallback,patch.object(r,'record_decision',AsyncMock()):await self.run_decision('{"speech":{"generate":false}}');fallback.assert_awaited_once();self.obj._speech.assert_not_called()
 async def test_busy_does_not_fan_out(self):
  self.obj.speech_jobs.add((8,8))
  with patch.object(r,'fallback_decision',AsyncMock()) as fallback,patch.object(r,'record_decision',AsyncMock()):await self.run_decision('{"speech":{"generate":false}}');fallback.assert_not_called();self.obj._speech.assert_not_called();self.assertEqual(self.obj.speech_jobs,{(8,8)})
 async def test_disabled(self):
  g.speech_generation.enabled.return_value=False
  self.assertFalse(await self.run_decision('{"speech":{"generate":true}}'));self.obj._speech.assert_not_called()
 async def test_unallowed_and_bot_and_webhook(self):
  for variant in ('deny','bot','webhook'):
   self.msg=message();getattr(self.obj,'_can_speech' if LEGACY else '_can_chat').return_value=variant!='deny';self.msg.author.bot=variant=='bot';self.msg.webhook_id=1 if variant=='webhook' else None
   self.assertFalse(await self.run_decision('{"speech":{"generate":true}}'));self.obj._speech.assert_not_called()

@unittest.skipUnless(LEGACY,'legacy relation adapter')
class Relation(unittest.TestCase):
 def test_runtime_familiar_users_are_string(self):
  cfg=importlib.import_module(P+'.config')
  for uid in (0,0,1):self.assertIsInstance(cfg.relationship_for(uid),str)
 def test_dictionary_prompt_normalized(self):
  cfg=importlib.import_module(P+'.config')
  with patch('src.chat.services.user_relationship_service.with_user_relationship',return_value={'prompt':'熟悉用户提示'}):self.assertEqual(cfg.relationship_for(3),'熟悉用户提示')
 def test_bad_type_not_dumped(self):
  cfg=importlib.import_module(P+'.config')
  for value in ({'prompt':{}},None,3):
   with patch('src.chat.services.user_relationship_service.with_user_relationship',return_value=value):self.assertEqual(cfg.relationship_for(3),'')
 def test_both_original_model_stages_have_capability(self):
  source=pathlib.Path('/app/src/chat/services/chat_service.py').read_text();self.assertIn('messages = with_capability(messages, speech_available)',source);self.assertIn('stage1_messages = with_capability(stage1_messages, speech_available)',source);ast.parse(source)



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


class ConfiguredOwnerVoice(unittest.TestCase):
 def test_fixed_voice_and_language(self):
  from src.chat.services.speech_generation import speech_generation
  voices={'mukuro':'5f7ecf8cc5ae4086a30baeeb3d0dff16'}
  actual=speech_generation.provider('fish');self.assertEqual(actual['voice_id'],voices[ROLE]);self.assertEqual(actual['language'],'Japanese');self.assertEqual(actual['model'],'s2.1-pro-free')
 def test_no_unconfigured_moss(self):
  from src.chat.services.speech_generation import speech_generation,SpeechError
  with self.assertRaises(SpeechError):speech_generation.provider('moss')
if __name__=='__main__':unittest.main()
