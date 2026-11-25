import asyncio, json, time
from unittest.mock import patch
from types import SimpleNamespace as NS
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.s60_rowenta.models import AWSCreds

BASE="VAC001/abc"; SH="$aws/things/VAC001-abc/shadow"
PUB=[]; Q=None; KW={}

class FakeMQTT:
    def __init__(self, **kw): KW.update(kw)
    async def __aenter__(self):
        global Q; Q=asyncio.Queue(); return self
    async def __aexit__(self,*a): pass
    async def subscribe(self,*a,**k): pass
    async def publish(self,t,p,qos=0): PUB.append((t,json.loads(p)))
    @property
    def messages(self):
        async def gen():
            while True: yield await Q.get()
        return gen()

class FakeCloud:
    refresh_token="r"
    def __init__(self,*a): pass
    def set_refresh_callback(self,cb): pass
    async def async_get_devices(self): return [{"device_id":"abc","thing_type":"VAC001","name":"Robo","model_code":"x"}]
    async def async_get_aws_creds(self): return AWSCreds("a","b","c",time.time()+3600)
    async def async_get_map(self,*a): return {"map":[{"x":128,"y":128,"type":1,"index":0},{"x":129,"y":128,"type":3,"index":1}]}

async def send(hass,topic,payload):
    await Q.put(NS(topic=topic,payload=json.dumps(payload).encode()))
    for _ in range(5):
        await asyncio.sleep(0.05); await hass.async_block_till_done()

async def test_all(hass, hass_client):
    from homeassistant.setup import async_setup_component
    await async_setup_component(hass,"http",{})
    with patch("custom_components.s60_rowenta.SebCloud",FakeCloud), patch("custom_components.s60_rowenta.mqtt.AsyncMQTT",FakeMQTT):
        e=MockConfigEntry(domain="s60_rowenta",data={"refresh_token":"r","profile_perimeter":"p"}); e.add_to_hass(hass)
        assert await asyncio.wait_for(hass.config_entries.async_setup(e.entry_id),10)
        await asyncio.sleep(0.2)
        assert Q is not None and (SH+"/get",{}) in PUB
        await send(hass,BASE+"/status",{"status":"CHARGING","battery":80,"method":"BACK_TO_DOCK","power":"NORMAL","errorCode":"NORMAL","mapId":"5","startTimestamp":1700000000000})
        await send(hass,SH+"/get/accepted",{"state":{"reported":{"status":{"connected":True},"schedules":[]}}})
        await send(hass,BASE+"/history",{"datasHistory":[{"mapId":5,"startTimestamp":1700000000000,"endTimestamp":1700000600000,"cleaningArea":12,"cleaningDuration":10,"status":{"errorCode":"NORMAL"}}],"totalNumberOfClean":1})
        st={s.entity_id:s for s in hass.states.async_all()}
        vac=next(k for k in st if k.startswith("vacuum."))
        assert st[vac].state=="docked"
        async def call(d,s,data,**kw):
            r=await hass.services.async_call(d,s,{"entity_id":vac,**data},blocking=True,**kw)
            await asyncio.sleep(0.05); await hass.async_block_till_done(); return r
        for s,exp in (("start",{"method":"SMART_CLEANING","power":"NORMAL"}),("return_to_base",{"method":"BACK_TO_DOCK"}),("clean_spot",{"method":"SPIRAL","power":"NORMAL"})):
            PUB.clear(); await call("vacuum",s,{}); assert (BASE+"/command",exp) in PUB,(s,PUB)
        PUB.clear()
        r=await call("s60_rowenta","set_schedule",{"name":"m","start":"09:00","days":["mon"],"mode":"small_room_clean","power":"silent"},return_response=True)
        assert any(t==SH+"/update" for t,_ in PUB)
        assert r[vac]["schedule"]["mode"]=="small_room_clean"
        await call("s60_rowenta","delete_schedule",{"schedule":"m"})
        # options flow saves
        f=await hass.config_entries.options.async_init(e.entry_id)
        f=await hass.config_entries.options.async_configure(f["flow_id"],{"next_step_id":"add"})
        PUB.clear()
        f=await hass.config_entries.options.async_configure(f["flow_id"],{"name":"o","start":"10:00:00","days":["tue"],"mode":"smart_cleaning","power":"normal","enabled":True})
        assert f["type"]=="create_entry" and any(t==SH+"/update" for t,_ in PUB),f
        await hass.async_block_till_done()
        img=next(k for k in st if k.startswith("image."))
        c=await hass_client(); resp=await c.get(f"/api/image_proxy/{img}"); assert resp.status==200 and (await resp.read())[:4]==b"\x89PNG"
        sel=next(k for k in st if k.startswith("select.") and "map" in k)
        opts=hass.states.get(sel).attributes["options"]; assert len(opts)==2,opts
        await hass.services.async_call("select","select_option",{"entity_id":sel,"option":opts[1]},blocking=True)
        assert hass.states.get(sel).state==opts[1]
        from datetime import timedelta
        from homeassistant.util import dt
        from pytest_homeassistant_custom_component.common import async_fire_time_changed
        PUB.clear(); async_fire_time_changed(hass, dt.utcnow()+timedelta(minutes=31)); await asyncio.sleep(0.2); await hass.async_block_till_done()
        t={x for x,_ in PUB}; assert BASE+"/getStatus" in t and BASE+"/getHistory" in t, t
        from custom_components.s60_rowenta.diagnostics import async_get_config_entry_diagnostics as diag
        out=await diag(hass,e); text=json.dumps(out)
        assert out["robots"][0]["data"]["status"]["battery"]==80 and "abc" not in text and "Robo" not in text
        assert await hass.config_entries.async_unload(e.entry_id)

async def test_renewal_and_error(hass):
    from custom_components.s60_rowenta import mqtt as m
    n=[]
    class C(FakeCloud):
        async def async_get_aws_creds(self):
            n.append(1); return AWSCreds("a","b","c",time.time()+3600)
    real=asyncio.timeout
    with patch.object(m,"AsyncMQTT",FakeMQTT), patch.object(m.asyncio,"timeout",lambda d: real(0.05)):
        b=m.MqttBroker(hass,C(),[],None,lambda up:None,lambda:None)
        t=asyncio.create_task(b.run()); await asyncio.sleep(0.4); b.stop(); t.cancel()
    assert len(n)>=3

async def test_network_error(hass):
    import aiohttp
    from custom_components.s60_rowenta.auth import async_get_market
    from custom_components.s60_rowenta.exceptions import CloudUnreachable
    class S:
        def get(self,*a,**k): raise aiohttp.ClientError("x")
    with pytest.raises(CloudUnreachable): await async_get_market(S(),"es")
