#!/usr/bin/env python3
"""V2 repair: public symbol identity, partial HTTP evidence and session-aware QA."""
import datetime as dt
import hashlib,json,math,time
from pathlib import Path
import urllib.error,urllib.parse,urllib.request
from zoneinfo import ZoneInfo
from indicators import calculate
BASE='https://api.gateio.ws/api/v4'
SYMBOL='XAUUSD'
PERIODS={'4h':14400,'1h':3600,'15m':900,'1m':60}
MIN_CLOSED={'4h':120,'1h':60,'15m':60,'1m':8}
NY=ZoneInfo('America/New_York')
def utc_iso(t):return dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat()

def call_api(path,params=None,evidence_dir=None,name='request'):
    url=BASE+path+('?' + urllib.parse.urlencode(params) if params else '')
    attempts=[];payload=None
    for attempt in range(1,4):
        started=time.time();clock=time.monotonic()
        record={'url':url,'method':'GET','attempt':attempt,'requested_at_utc':utc_iso(started)}
        try:
            req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'Gate-CFD-ReadOnly-Audit/3.0','Cache-Control':'no-cache'})
            try:response=urllib.request.urlopen(req,timeout=20)
            except urllib.error.HTTPError as exc:response=exc
            with response:
                body=response.read()
                record.update(http_status=response.code,headers=dict(response.headers),body=body.decode('utf-8',errors='replace'),sha256=hashlib.sha256(body).hexdigest())
            record.update(received_at_utc=utc_iso(time.time()),elapsed_seconds=round(time.monotonic()-clock,6))
            if record['http_status']!=200:raise RuntimeError(f"HTTP {record['http_status']}")
            payload=json.loads(record['body'])
            if not isinstance(payload,dict) or not isinstance(payload.get('data'),dict) or payload.get('label'):raise ValueError('Gate error/invalid schema')
            record['ok']=True
        except Exception as exc:
            payload=None;record.update(ok=False,error=f'{type(exc).__name__}: {exc}',elapsed_seconds=round(time.monotonic()-clock,6))
        attempts.append(record)
        if evidence_dir:
            p=Path(evidence_dir);p.mkdir(parents=True,exist_ok=True)
            (p/f'{name}_attempt{attempt}.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
        if payload is not None or record.get('http_status') in (400,401,403,404,451):break
        if attempt<3:time.sleep(attempt)
    return payload,attempts

def collect(evidence_dir=None):
    raw={'_transport':{},'_provenance':'DIRECT_GATE_HTTPS'}
    requests=[('symbols','/tradfi/symbols',None)]
    requests += [(tf,f'/tradfi/symbols/{SYMBOL}/klines',{'kline_type':tf,'limit':n}) for tf,n in [('4h',220),('1h',180),('15m',500),('1m',120)]]
    requests += [('ticker',f'/tradfi/symbols/{SYMBOL}/tickers',None)]
    for name,path,params in requests:
        payload,attempts=call_api(path,params,evidence_dir,name)
        raw[name]=payload or {};raw['_transport'][name]=attempts
    return raw

def scheduled_closed(t):
    """Observed standard public-feed profile, not account beta trading rights.
    NY DST-aware maintenance 17:00-18:01; weekly Fri17-Sun17.
    Unrecognized holiday gaps block. Current session also checked against ticker.
    """
    x=dt.datetime.fromtimestamp(t,NY);minute=x.hour*60+x.minute;w=x.weekday()
    if w==5 or (w==4 and minute>=1020) or (w==6 and minute<1081):return True
    return w<4 and 1020<=minute<1081
def expected_gap(a,b,seconds):
    missing=list(range(a+seconds,b,seconds))
    return bool(missing) and all(scheduled_closed(t) for t in missing)

def closed_bars(raw,tf,now):
    cutoff=min([now]+[raw.get(k,{}).get('timestamp',now*1000)/1000 for k in PERIODS])
    return [dict(t=int(x['t']),**{k:float(x[k]) for k in ('o','h','l','c')}) for x in raw.get(tf,{}).get('data',{}).get('list',[]) if int(x['t'])+PERIODS[tf]<=cutoff-5]

def audit(raw,now=None,provenance='LIVE_GATE_CFD'):
    now=int(time.time() if now is None else now)
    cutoff=min([now]+[raw.get(k,{}).get('timestamp',now*1000)/1000 for k in PERIODS])
    issues=[];warnings=[];summary={};bars={};indicators={};cross={}
    ticker=raw.get('ticker',{}).get('data',{})
    status=ticker.get('status');bid=ask=None
    for name in ['symbols','ticker',*PERIODS]:
        stamp=raw.get(name,{}).get('timestamp')
        if not isinstance(stamp,(int,float)) or abs(now-stamp/1000)>120:issues.append(f'{name}: missing/stale API server timestamp (>120s)')
        transport=raw.get('_transport',{}).get(name)
        if not transport or not transport[-1].get('ok'):issues.append(f'{name}: no successful HTTP transport evidence')
    if provenance!='LIVE_GATE_CFD' or raw.get('_provenance')!='DIRECT_GATE_HTTPS':issues.append('unverified acquisition provenance')
    syms=raw.get('symbols',{}).get('data',{}).get('list',[])
    identity=next((x for x in syms if x.get('symbol')==SYMBOL),None)
    if not identity or identity.get('settlement_currency')!='USD':issues.append('public CFD symbol identity/settlement missing')
    if identity and identity.get('status')!=status:issues.append('symbol list/ticker states disagree; retry next cycle')
    try:
        bid=float(ticker['bid_price']);ask=float(ticker['ask_price'])
        if not (math.isfinite(bid) and math.isfinite(ask) and 0<bid<=ask):raise ValueError('invalid bid/ask')
    except (ValueError,TypeError,KeyError):issues.append('ticker invalid/missing bid/ask')
    if status not in ('open','closed'):issues.append('unexpected CFD trading state')
    if str(ticker.get('trade_mode')) not in ('0','1','2','3','4'):issues.append('unknown trade mode')
    opened=ticker.get('open_time',0);closed=ticker.get('close_time',0)
    if status=='open' and not (isinstance(opened,int) and isinstance(closed,int) and opened<=now<=closed):issues.append('open state contradicts live session timestamps')
    spread=round(ask-bid,5) if bid is not None and ask is not None else None
    stamp=raw.get('ticker',{}).get('timestamp')
    summary['ticker']={'bid':bid,'ask':ask,'spread':spread,'status':status,'trade_mode':ticker.get('trade_mode'),
        'server_timestamp_utc':utc_iso(stamp/1000) if isinstance(stamp,(int,float)) else None,
        'tick_timestamp_available':False,'actual_last_tick_time':None,'open_time_utc':utc_iso(opened) if opened else None,
        'close_time_utc':utc_iso(closed) if closed else None,'next_open_time':ticker.get('next_open_time')}
    if spread is not None and spread>.5:warnings.append('spread exceeds strategy 0.50 USD filter')
    for tf,seconds in PERIODS.items():
        rows=raw.get(tf,{}).get('data',{}).get('list',[]);parsed=[]
        if not isinstance(rows,list):issues.append(tf+': invalid list');continue
        for row in rows:
            try:
                b={'t':int(row['t']),**{k:float(row[k]) for k in ('o','h','l','c')}}
                if any(not math.isfinite(b[k]) for k in ('o','h','l','c')) or not 0<b['l']<=min(b['o'],b['c'])<=max(b['o'],b['c'])<=b['h']:raise ValueError('OHLC invalid')
                if b['t']>now+5 or b['t']<1420070400 or b['t']%min(seconds,3600):raise ValueError('timestamp invalid')
                parsed.append(b)
            except (ValueError,KeyError,TypeError) as exc:issues.append(f'{tf}: {exc}')
        times=[x['t'] for x in parsed]
        if len(set(times))!=len(times):issues.append(tf+': duplicate timestamps')
        if times!=sorted(times):issues.append(tf+': timestamps not increasing')
        parsed.sort(key=lambda b:b['t']);complete=[b for b in parsed if b['t']+seconds<=cutoff-5];gaps=[]
        for a,b in zip(parsed,parsed[1:]):
            delta=b['t']-a['t']
            if delta!=seconds:
                good=delta>seconds and expected_gap(a['t'],b['t'],seconds)
                gaps.append({'from_utc':utc_iso(a['t']),'to_utc':utc_iso(b['t']),'seconds':delta,'classification':'scheduled_public_feed_close' if good else 'UNEXPLAINED'})
                if not good:issues.append(f'{tf}: unexplained gap {utc_iso(a["t"])} -> {utc_iso(b["t"])}')
        if len(complete)<MIN_CLOSED[tf]:issues.append(f'{tf}: {len(complete)} closed bars, need {MIN_CLOSED[tf]}')
        if not complete:continue
        age=now-(complete[-1]['t']+seconds)
        if status=='open' and age>seconds+120:
            next_starts=range(complete[-1]['t']+seconds,now-seconds+1,seconds)
            if not all(scheduled_closed(t) for t in next_starts):issues.append(f'{tf}: closed bars stale {age}s')
        if tf=='1m' and status=='open' and (not parsed or now-parsed[-1]['t']>120):issues.append('1m: actual latest market bar stale >120s')
        bars[tf]=complete;calculated,events=calculate(complete,seconds);last=calculated[-1]
        if len(complete)>=50 and any(last[k] is None or not math.isfinite(last[k]) for k in ['ema20','ema50','atr14']):issues.append(tf+': indicator not finite')
        indicators[tf]={'ema20':last['ema20'],'ema50':last['ema50'],'atr14':last['atr14'],'swing_high':last['swing_high'],'swing_low':last['swing_low'],'structure':last['structure'],
            'latest_bos':next((e for e in reversed(events) if e['kind']=='BOS'),None),'latest_choch':next((e for e in reversed(events) if e['kind']=='CHoCH'),None)}
        summary[tf]={'received':len(parsed),'closed':len(complete),'last_closed_start_utc':utc_iso(complete[-1]['t']),'last_closed_end_utc':utc_iso(complete[-1]['t']+seconds),
            'last_closed_close':complete[-1]['c'],'actual_latest_bar_start_utc':utc_iso(parsed[-1]['t']),'last_close_age_seconds':age,'gaps':gaps}
    # Current partial bars and exact lower-TF aggregation verify t=open semantics.
    for small,big in [('1m','15m'),('15m','1h'),('15m','4h')]:
        s=PERIODS[small];duration=PERIODS[big];smallbars={b['t']:b for b in bars.get(small,[])};matched=0;conflicts=[]
        for b in bars.get(big,[]):
            part=[smallbars.get(t) for t in range(b['t'],b['t']+duration,s)]
            if not all(part):continue
            derived={'o':part[0]['o'],'h':max(x['h'] for x in part),'l':min(x['l'] for x in part),'c':part[-1]['c']};matched+=1
            diff={k:round(abs(derived[k]-b[k]),8) for k in derived}
            if max(diff.values())>.011:conflicts.append({'t':b['t'],'differences':diff})
        cross[small+'->'+big]={'matched':matched,'conflicts':conflicts,'tolerance_usd':.011}
        if matched<1:issues.append(small+'->'+big+': no overlap to validate candle-start semantics')
        if conflicts:issues.append(small+'->'+big+': native OHLC conflict')
    if bid is not None and ask is not None and bars.get('1m') and status=='open':
        deviation=abs((bid+ask)/2-bars['1m'][-1]['c'])/((bid+ask)/2);summary['ticker']['deviation_from_closed_1m']=deviation
        if deviation>.005:issues.append('ticker vs closed 1m deviation >0.50%')
    if status=='closed' and not ticker.get('next_open_time') and not scheduled_closed(now):issues.append('closed without verified schedule/next open; cannot classify RESTING')
    verdict='FAIL' if issues else ('RESTING' if status=='closed' else 'PASS')
    warnings += ['Actual tick timestamp is not provided. Freshness bounded by latest real 1m bar, not ticker server time.',
        'Standard public-feed profile is inferred from native session evidence and live open/close; account 7x23 beta rights unverified.',
        'Private /tradfi/symbols/detail requires authentication; public /tradfi/symbols used for identity. Contract size not inferred.']
    return {'status':verdict,'approved_for_market_analysis':not issues,'approved_for_executable_signal':False,
        'approved_for_simulation':verdict=='PASS' and str(ticker.get('trade_mode'))=='4' and spread is not None and spread<=.5,
        'source':provenance,'symbol':SYMBOL,'audited_at_utc':utc_iso(now),'closed_bar_cutoff_utc':utc_iso(cutoff-5),'issues':issues,'warnings':warnings,
        'market_data':summary,'identity':identity,'indicators':indicators,'cross_timeframe':cross,
        'session_profile':'Observed standard Gate public CFD feed; NY DST-aware; unmatched gaps block',
        'limitations':['No last tick timestamp','Account rights unverified','OHLC only, volume/OI unavailable','Not profitability certification']}

