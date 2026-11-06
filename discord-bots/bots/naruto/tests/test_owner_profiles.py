import asyncio,json,os,pathlib,subprocess,sys
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import discord
from src.chat.services.owner_profiles import OWNER,OWNER_NAME,ROLE_NAME,STATE_KEY
from src.chat.services.owner_proxy import OwnerProxy
from src.chat.services import owner_controls,temper


def test_fixed_profile_identities_and_namespaces():
    assert OWNER==0 and OWNER_NAME=='mhxy' and ROLE_NAME=='鸣人' and STATE_KEY=='naruto_proxy'
    script="import json;from src import config;from src.chat.services.owner_profiles import OWNER,STATE_KEY;from src.chat.cogs.settings_cog import SettingsCog;print(json.dumps({'owner':OWNER,'state':STATE_KEY,'group':SettingsCog.control.name}))"
    results=[]
    for profile in ('sasuke','naruto'):
        env=dict(os.environ,BOT_PROFILE=profile)
        results.append(json.loads(subprocess.check_output([sys.executable,'-X','utf8','-c',script],env=env)))
    assert results==[{'owner':0,'state':'sasuke_proxy','group':'佐助'},
                     {'owner':0,'state':'naruto_proxy','group':'鸣人'}]


def test_only_mhxy_controls_learning_or_speaks():
    async def run():
        response=NS(send_message=AsyncMock())
        i=NS(guild_id=0,user=NS(id=0,guild_permissions=discord.Permissions(administrator=True)),response=response)
        assert not await owner_controls.require_owner(i)
        assert await owner_controls.require_owner(i,emergency=True)
        i.user.id=OWNER;assert await owner_controls.require_owner(i)
        assert 'mhxy的鸣人形象化身' in OwnerProxy().prompt(NS(id=1))
    asyncio.run(run())


def test_owner_never_autotimed_out(monkeypatch):
    async def run():
        monkeypatch.setattr(temper,'store',NS(get=AsyncMock(return_value=True)))
        apply=AsyncMock();monkeypatch.setattr(temper,'anger_service',NS(apply=apply))
        message=NS(author=NS(id=OWNER,bot=False),guild=NS(),webhook_id=None,content='恶意侮辱你的话')
        reply=NS(moderation={'timeout':True,'quote':'恶意侮辱你的话','reason':'直接侮辱','severity':'abuse'})
        assert await temper.apply_temper(NS(),message,reply,'direct') is None
        assert apply.await_count==0
    asyncio.run(run())


def test_no_sasuke_corpus_or_asset_copy():
    from src import config
    assert config.PERSONAL_EMOTE_DIR==pathlib.Path('assets/naruto-emotes')
    assert len(config.PERSONAL_EMOJI_LABELS)==12 and all(n.startswith('nt_') for n in config.PERSONAL_EMOJI_LABELS)
    assert set(config.PERSONA['familiar_users'])=={str(OWNER)}
    assert not pathlib.Path('data/owner_proxy.db').exists()
