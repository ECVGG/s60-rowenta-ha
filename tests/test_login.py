from unittest.mock import patch
import pytest
from custom_components.s60_rowenta import auth

class R:
    def __init__(s,url,status=200,text="",headers=None): s.url,s.status,s._t,s.headers=url,status,text,headers or {}
    async def __aenter__(s): return s
    async def __aexit__(*a): pass
    async def text(s): return s._t

B="https://account.groupeseb.com"
LOGIN='<form id="p:f" name="p:f" method="post" action="/Login"></form><script>loginAF=function(userEmail,password){A4J.AJAX.Submit(\'p:f\',null,{\'similarityGroupingId\':\'p:f:go\'})}</script>'
FLOW='<form id="x" method="post" action="/apex/LoginFlow?a=1&amp;b=2"><input type="hidden" name="vs" value="V"/></form><script>A4J.AJAX.Submit(\'x\',null,{\'similarityGroupingId\':\'x:y\',\'parameters\':{\'x:y\':\'x:y\'} })</script>'
seen=[]; END={"v":"<script>window.location.replace('gsmoduser:\\/\\/tokens#access_token=a&refresh_token=RT')</script>"}
class S:
    def __init__(s,**k): pass
    async def __aenter__(s): return s
    async def __aexit__(*a): pass
    def get(s,url,**k):
        if "Continuation" in url: return R(url,text="<script>window.location.replace('"+B+"/authorize')</script>")
        if url.endswith("/authorize"): return R(B+"/Login",text=LOGIN)
        if "frontdoor" in url: return R(url,text="<script>handleRedirect('/apex/step')</script>")
        if url.endswith("/apex/step"): return R(url,text=FLOW)
        return R(url,text=END["v"])
    def post(s,url,data=None,**k):
        seen.append((url,data))
        if url.endswith("/Login"): return R(url,text='<meta name="Location" content="/frontdoor.jsp?sid=SECRET"/>')
        return R(url,text='<meta name="Location" content="/done?sid=SECRET"/>')

async def test_chain():
    with patch.object(auth.aiohttp,"ClientSession",S), patch.object(auth.aiohttp,"CookieJar",lambda:None):
        assert (await auth.async_login("e","p"))["refresh_token"]=="RT"
        url,data=seen[-1]; assert url==B+"/apex/LoginFlow?a=1&b=2" and data["vs"]=="V" and data["x:y"]=="x:y"
        END["v"]="nothing"
        with pytest.raises(auth.ProtocolMismatch) as e: await auth.async_login("e","p")
        print(e.value); assert "SECRET" not in str(e.value) and "/done 200" in str(e.value)

def test_exp():
    assert auth.parse_expiration("2026-01-01T00:00:00Z")>0 and auth.parse_expiration(5)==5 and auth.parse_expiration(None)==0
