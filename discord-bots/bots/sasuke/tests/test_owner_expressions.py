import asyncio,time,json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from src.chat.services import owner_proxy as f
from src.chat.services import conversation as conv
from src.chat.services.owner_expressions import summarize,symbols,usable_reference

CODE='<:1776782619428:0>'
ANIM='<a:19bc7afd2849cfacfe9b9b77341ed085:0>'

@pytest.mark.parametrize('text',['🐷','😡','🤣',CODE,ANIM,'(^_^)','(￣▽￣)','QAQ','>_<'])
def test_literal_samples_survive(text):
    assert f.clean_sample(text)==text

@pytest.mark.parametrize('text',['DISCORD_TOKEN=private','API_KEY=private','Bearer private','-----BEGIN PRIVATE KEY-----'])
def test_credentials_still_rejected(text):assert not f.clean_sample(text)

def test_quote_code_url_and_mentions_removed():
    value=f.clean_sample('> 不是本人的话 🦆\n```🐍```\n<@0> 好吧🐷 '+CODE+' https://example.com')
    assert '🐷' in value and CODE in value
    assert all(x not in value for x in ('🦆','🐍','http','<@'))
    assert f.clean_sample('哈'*235+' '+CODE)=='哈'*235
    assert 'duck_private' not in f.clean_sample('<:duck_private:0>')

def test_bounded_literal_statistics():
    p=summarize(['好吧🐷'*20, '🐷', CODE, ANIM, '(^_^)','(￣▽￣)','QAQ','普通文本','(明天见)','(123)'])
    assert p['unicode']['🐷']==2 and p['custom'][CODE]==1
    assert p['sample_messages']==10 and p['symbol_messages']==7
    assert p['observed_message_ratio']==.7
    assert p['kaomoji']=={'(^_^)':1,'(￣▽￣)':1,'QAQ':1}
    assert symbols('👨\u200d👩\u200d👧\u200d👦 🇨🇳 1️⃣')[1]==['👨\u200d👩\u200d👧\u200d👦','🇨🇳','1️⃣']

def test_only_current_usable_codes_and_renames():
    p=summarize([CODE,ANIM,'🐷']);renamed='<:renamed:0>'
    ref=usable_reference(p,{renamed:'可用','<:unknown:0>':'其他'})
    assert ref['custom']=={renamed:1} and ANIM not in ref['custom']

def test_candidate_priority_and_prompt(monkeypatch):
    p=f.OwnerProxy();p.expressions=summarize([CODE,'🐷','(^_^)'])
    monkeypatch.setattr(f,'owner_proxy',p)
    class Emoji:
        def __init__(self,eid,name):self.id=eid;self.name=name
        def is_usable(self):return True
        def __str__(self):return '<:'+self.name+':'+str(self.id)+'>'
    e=Emoji(0,'1776782619428')
    g=NS(emojis=[Emoji(0+i,'unrelated') for i in range(40)]+[e])
    candidates=conv.emoji_candidates(g,'普通消息',123)
    assert CODE in candidates and '🐷' in candidates
    m=NS(id=1,author=NS(id=222,display_name='测试用户',bot=False),content='普通聊天',guild=NS(),channel=NS(id=1))
    messages=conv.messages_for(m,[],[],candidates,'direct')
    payload=json.loads(messages[1]['content'])
    assert payload['owner_expression_symbols']['custom']=={CODE:1}
    assert payload['owner_expression_symbols']['unicode']['🐷']==1
    assert '不要只把常用符号放进reaction' in messages[0]['content']
    result=conv.parse_reply(json.dumps({'reply':'好吧🐷 '+CODE}),candidates,{222},True)
    assert CODE in result.reply and '🐷' in result.reply
    result=conv.parse_reply(json.dumps({'reply':'好吧 <:fake:0>','messages':['🐷 '+CODE,'(^_^)']}),candidates,{222},True)
    assert result.parts==('🐷 '+CODE,'(^_^)') and 'fake' not in result.reply

def test_cache_rebuild_clear_and_expiry(tmp_path,monkeypatch):
    async def run():
        from tests.test_sasuke_proxy import message,service
        p=await service(tmp_path,monkeypatch)
        assert await p.collect(message(1,uid=f.OWNER,content='🐷'))
        assert await p.collect(message(2,uid=f.OWNER,content=CODE))
        assert not await p.collect(message(3,uid=999,content='😡'))
        assert p.expressions['unicode']=={'🐷':1} and p.expressions['custom']=={CODE:1}
        await p.deleted([1]);assert not p.expressions['unicode']
        p.clock=lambda:time.time()+31*86400
        await p.prune();assert p.expressions['sample_messages']==0
        p.expressions={'unicode':{'🐷':1}};await p.clear();assert not p.expressions
    asyncio.run(run())
