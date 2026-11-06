import asyncio,json,time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from contextlib import asynccontextmanager,nullcontext
import pytest
import aiosqlite
from src.chat.services.owner_voice import abstract_style,balanced_rows,VoiceGuard
from src.chat.services import owner_proxy as owner


def test_examples_not_a_script():
    s={'common_phrases':'常说“你也是神了”','humor':'轻松时接梗（如“你也是神了”），认真时倾听。','punctuation':'少句号'}
    cleaned=abstract_style(s)
    assert '你也是神了' not in json.dumps(cleaned,ensure_ascii=False)
    assert cleaned['punctuation']==s['punctuation'] and '认真时倾听' in cleaned['humor']


def test_sample_balance_and_duplicate_variants():
    rows=[('同一条内容🐷'+('！'*(i%3)),i) for i in range(100)]
    assert len(balanced_rows(rows))==1
    varied=[('不同问题'+str(i),i) for i in range(400)]
    selected=balanced_rows(varied)
    assert len(selected)==60 and selected[0][1]==0 and selected[-1][1]==399
    assert len({int(at//100) for _,at in selected})==4


def test_recent_repeated_evaluations_not_topic_terms():
    g=VoiceGuard(clock=lambda:10000)
    g.record(1,7,'你也是神了 🐷');g.record(2,7,'躺了一天 你也是神了')
    assert g.reason(7,'又躺了一天 你也是神了','我今天还是没起来')
    assert g.reason(7,'你也是神了 🐷','随便说两句')
    assert not g.reason(7,'你也是神了','请原样复述“你也是神了”')
    assert not g.reason(7,'这次API返回HTTP 429，稍后重试','API又报错')
    assert not g.reason(7,'https://example.com 是这次的来源','查一下')
    assert not g.reason(7,'我在','你好')
    assert not g.reason(7,'先吃点东西 休息一下再弄','今天忙得没吃饭')


def test_recent_cache_bound_expiry_bootstrap_order_and_dedup():
    g=VoiceGuard(clock=lambda:10000)
    for i in reversed(range(100)):g.record(i,7,'已发出的话'+str(i),at=9000+i)
    assert len(g.rows)==24 and g.rows[-1][0]==9099
    assert '已发出的话99' in g.recent(7)
    before=len(g.rows);g.record(99,7,'重复事件',at=9099);assert len(g.rows)==before
    assert '重复事件' not in g.recent(7)
    g.record(100,8,'另一频道的私密回应');assert '另一频道的私密回应' not in g.recent(7)
    g.record(101,7,'DISCORD_TOKEN=secret');assert all('secret' not in line for line in g.recent(7))
    g.clock=lambda:20000;assert not g.recent(7)


def test_old_style_is_sanitized_on_load_and_rollback(tmp_path,monkeypatch):
    async def run():
        monkeypatch.setattr(owner,'store',NS(get=AsyncMock(return_value={})))
        p=owner.OwnerProxy(tmp_path/'owner.db');await p.initialize()
        raw={k:'' for k in owner.FIELDS};raw['common_phrases']='“你也是神了”';raw['humor']='偶尔轻松调侃'
        async with aiosqlite.connect(p.path) as db:
            await db.execute("INSERT OR REPLACE INTO meta VALUES('active_style',?)",(json.dumps(raw,ensure_ascii=False),))
            await db.execute('INSERT INTO versions(at,style,samples) VALUES(?,?,?)',(time.time(),json.dumps(raw,ensure_ascii=False),30));await db.commit()
        await p.initialize();assert '你也是神了' not in p.style['common_phrases']
        await p.rollback(1);assert '你也是神了' not in p.style['common_phrases']
        async with aiosqlite.connect(p.path) as db:
            old=json.loads((await (await db.execute('SELECT style FROM versions WHERE id=1')).fetchone())[0])
        assert old['common_phrases']==raw['common_phrases']
    asyncio.run(run())


@pytest.mark.parametrize('case',['repeated','fresh','image','moderation','repair_busy'])
def test_one_text_repair_no_repeated_actions(monkeypatch,case):
    from src.chat.cogs import social_cog as social
    from src.chat.services import owner_voice as voice,temper
    async def run():
        g=VoiceGuard();g.record(1,7,'你也是神了');g.record(2,7,'躺了一天 你也是神了')
        monkeypatch.setattr(voice,'voice_guard',g)
        @asynccontextmanager
        async def processing(*a,**k):yield True
        monkeypatch.setattr(social,'vision_service',NS(processing=processing,load=AsyncMock(return_value={'images':[],'unavailable':[],'omitted':0})))
        monkeypatch.setattr(social,'image_sources',lambda *_:[])
        monkeypatch.setattr(social,'store',NS(memory=AsyncMock(return_value=([],False))))
        original={'reply':'今天也躺着 你也是神了'}
        if case=='fresh':original['reply']='先吃点东西 休息一下再弄'
        if case=='image':original['image']={'mode':'requested','prompt':'茶杯'}
        if case=='moderation':original['moderation']={'quote':'test'}
        first=NS(content=json.dumps(original,ensure_ascii=False));second=NS(content=json.dumps({'reply':'歇够了就起来走两步 透口气'},ensure_ascii=False))
        results=[first,second]
        if case=='repair_busy':results=[first,social.ModelError('busy')]
        generate=AsyncMock(side_effect=results);monkeypatch.setattr(social,'ai_service',NS(generate=generate))
        apply=AsyncMock();monkeypatch.setattr(temper,'apply_temper',apply)
        bot=NS(user=NS(id=99,display_name='佐助'))
        cog=social.SocialCog(bot);cog._can_chat=AsyncMock(return_value=True)
        cog._send_reply_parts=AsyncMock(return_value=NS(id=100));cog._semantic_image=lambda *a:None
        message=NS(id=55,author=NS(id=12,bot=False,display_name='用户'),guild=NS(id=0,emojis=[]),
                   channel=NS(id=7,typing=lambda:nullcontext()),content='我今天又躺了一天',reference=None)
        sent=await cog._respond(message,'direct')
        assert sent and apply.await_count==1 and cog._send_reply_parts.await_count==1
        repaired=case in ('repeated','repair_busy')
        assert generate.await_count==(2 if repaired else 1)
        reply=cog._send_reply_parts.call_args.args[1]
        if case=='repeated':assert reply.reply=='歇够了就起来走两步 透口气'
        if case=='repair_busy':assert reply.reply==original['reply']
        if case=='image':assert reply.image==original['image']
        if case=='moderation':assert reply.moderation==original['moderation']
        await cog.cog_unload()
    asyncio.run(run())
