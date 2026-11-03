"""ABC V1.0 causal state replay; simulation research only, no order capability.
Dynamic-zone implementation choices are documented in STRATEGY_MAPPING.md.
"""
import datetime as dt
from gate_xauusd_cfd_audit import PERIODS,closed_bars,utc_iso
from indicators import calculate

def trend(b):
    if b and b['ema50'] is not None:
        if b['ema20']<b['ema50'] and b['c']<b['ema50']:return 'bear'
        if b['ema20']>b['ema50'] and b['c']>b['ema50']:return 'bull'
    return 'range'

def crossed(b,p,level,buffer,body,side):
    if p is None or level is None or b['atr14'] is None or b['after_gap']:return False
    threshold=level+side*buffer*b['atr14']
    return b['body_ratio']>=body and ((b['c']>threshold and p['c']<=threshold) if side==1 else (b['c']<threshold and p['c']>=threshold))

def macro_gate(calendar,now):
    if not calendar or not calendar.get('source_urls') or not calendar.get('verified_at_utc'):
        return False,'重要美国宏观事件日历未核实，S4禁止'
    try:
        at=lambda x:dt.datetime.fromisoformat(x.replace('Z','+00:00')).timestamp()
        if not at(calendar['coverage_from_utc'])<=now-900 or not at(calendar['coverage_to_utc'])>=now+900:return False,'宏观日历未覆盖本轮前后15分钟'
        if now-at(calendar['verified_at_utc'])>86400:return False,'宏观日历核实已超过24小时'
        if any(abs(now-at(x['time_utc']))<=900 for x in calendar['events']):return False,'已核实重要事件前后15分钟'
    except (ValueError,KeyError,TypeError):return False,'宏观日历格式无效'
    return True,'已核实日历且不在事件窗口'

def decide(raw,audit,now,calendar=None):
    common={'version':'ABC V1.0','mode':'SIMULATION_ONLY','orders_enabled':False,'evaluated_at_utc':utc_iso(now),
            'audit_status':audit.get('status'),'signal':False,'best_plan':None,'entry_allowed':False}
    rules={
        'A':{'trigger':'4H空头且无4H向上BOS；反弹触及预先确认的1H摆动高点±0.2ATR；3根1H内向下BOS；3根15m内回踩突破位并跌破前低；有效支撑前>=2R',
             'invalid':'4H不再空头/4H上破；3根1H或3根15m到期；1H收回突破位+0.1ATR；突破反弹高点+0.2ATR'},
        'B':{'trigger':'4H空头；1H跌破预先确认4H摆动支撑0.15ATR，实体>=55%，振幅<=2.5ATR；3根1H内回踩；15m跌破前低；>=2R',
             'invalid':'4H不再空头；3根1H到期；1H收回支撑+0.1ATR；突破回踩最高点+0.2ATR'},
        'C':{'trigger':'触及预先确认4H摆动低点±0.3ATR；1H由下跌结构上行CHoCH(0.1ATR/实体55%)；15m回踩守住并突破前高；阻力前>=2R',
             'invalid':'底部结构最低点-0.2ATR被突破；1H跌回被突破点-0.1ATR；结构支撑更新使原底部失效；逆势优先级低'}}
    if audit.get('status')!='PASS':
        return {**common,'decision':'休市' if audit.get('status')=='RESTING' else '数据不足，禁止信号',
                'plans':{k:{'status':'RESTING' if audit.get('status')=='RESTING' else 'DATA_BLOCKED',**v} for k,v in rules.items()}}
    frames={tf:calculate(closed_bars(raw,tf,now),PERIODS[tf])[0] for tf in ('4h','1h','15m')}
    four=frames['4h'];one=frames['1h'];fifteen=frames['15m']
    state={k:{'status':'S0','reason':'未形成有效1H结构确认',**v} for k,v in rules.items()}
    pending={};zones={};last1=None;ix1=ix4=0;current4=None
    def transition(name,status,reason,**fields):
        state[name]={'status':status,'reason':reason,**rules[name],**fields}
    def setup(name,row,level,extreme,side,deadline,broke):
        pending[name]={'signal_time':row['end'],'level':level,'extreme':extreme,'side':side,'atr':row['atr14'],'deadline':deadline,'break_time':broke}
        transition(name,'S2','1H已确认，等待其后的15m回踩',level=level,signal_time_utc=utc_iso(row['end']),deadline_utc=utc_iso(deadline) if deadline else None)
    for i,b15 in enumerate(fifteen):
        end=b15['end']
        while ix4<len(four) and four[ix4]['end']<=end:
            current4=four[ix4];ix4+=1
        # Existing setups process this CLOSED 15m BEFORE a new same-time 1H setup.
        for name,s in list(pending.items()):
            side=s['side'];level=s['level'];atr=s['atr']
            if (s['deadline'] is not None and end>s['deadline']) or b15['after_gap']:
                state[name].update(status='EXPIRED',reason='信号超时或跨休市');del pending[name];continue
            if end<=s['signal_time'] or not i:continue
            if side*(b15['c']-s['extreme']) < -.2*atr:
                state[name].update(status='INVALID',reason='结构失效位被收盘突破');del pending[name];continue
            touch=b15['h']>=level-.2*atr and b15['l']<=level+.2*atr
            confirm=(b15['c']>level and b15['c']>fifteen[i-1]['h']) if side==1 else (b15['c']<level and b15['c']<fifteen[i-1]['l'])
            if name=='B':
                s['retest_extreme']=max(s.get('retest_extreme',b15['h']),b15['h']) if touch else s.get('retest_extreme')
                if not s.get('hourly_retest'):continue
            if touch and confirm:
                extreme=s['extreme'] if name!='B' else max(s.get('retest_extreme') or b15['h'],s['hourly_retest_high'])
                stop=extreme-side*.2*atr
                entry=b15['c']
                levels=[]
                # Only pivots ALREADY confirmed at the 15m confirmation time.
                for tf in (one,four):
                    for hist in tf:
                        if hist['end']>end:break
                        pivot=hist['swing_high' if side==1 else 'swing_low']
                        if pivot and side*(pivot['price']-entry)>0:levels.append(pivot['price'])
                target=(min(levels) if side==1 else max(levels)) if levels else None
                risk=side*(entry-stop)
                rr=side*(target-entry)/risk if target is not None and risk>0 else None
                transition(name,'S3','15m已确认，等待风控',confirmation_time_utc=utc_iso(end),entry_reference=entry,side=side,
                                   stop=stop,target=target,reward_risk=rr,level=level,confirmation_bar_start=b15['t'])
                # Confirmation is single-use; cannot be silently recycled next hour.
                del pending[name]
        while ix1<len(one) and one[ix1]['end']<=end:
            row=one[ix1];ix1+=1
            available4=next((x for x in reversed(four) if x['end']<=row['end']),None)
            if available4 is None or available4['ema50'] is None or row['atr14'] is None:
                last1=row;continue
            t4=trend(available4);atr=row['atr14']
            for name,s in list(pending.items()):
                if (name in ('A','B') and t4!='bear') or (s['side']==-1 and row['c']>s['level']+.1*s['atr']) or (s['side']==1 and row['c']<s['level']-.1*s['atr']):
                    state[name].update(status='INVALID',reason='1H回收结构或4H过滤失效');del pending[name]
                    continue
                if name=='B' and row['end']>s['signal_time'] and row['end']<=s['deadline'] and row['h']>=s['level']-.2*s['atr'] and row['l']<=s['level']+.2*s['atr']:
                    s['hourly_retest']=row['end'];s['hourly_retest_high']=max(s.get('hourly_retest_high',row['h']),row['h'])
            # A: use a level known BEFORE the touch, not a retrospectively selected top.
            ref=row['prev_hi']['price'] if row['prev_hi'] else None
            if t4=='bear' and ref is not None and available4['structure']!='up' and row['h']>=ref-.2*atr and row['l']<=ref+.2*atr:
                zones['A']={'index':ix1,'high':row['h'],'resistance':ref}
                transition('A','S1','已触及动态结构阻力，等待1H向下BOS',resistance_zone=[ref-.2*atr,ref+.2*atr])
            az=zones.get('A')
            if az:
                az['high']=max(az['high'],row['h'])
                if ix1-az['index']>3:
                    zones.pop('A');az=None
                    if state['A']['status']=='S1':transition('A','EXPIRED','阻力触及后3根1H内未出现有效向下BOS')
            support=available4['swing_low']
            prior_support=support if support and support['confirmed_at']<=row['t'] else available4['prev_lo']
            level=prior_support['price'] if prior_support else None
            if level is not None and row['h']>=level-.3*available4['atr14'] and row['l']<=level+.3*available4['atr14']:
                cz=zones.get('C')
                if not cz or cz['support_time']!=prior_support['t']:zones['C']={'low':row['l'],'support_time':prior_support['t'],'level':level}
                else:cz['low']=min(cz['low'],row['l'])
                if state['C']['status'] in ('S0','S1','EXPIRED','INVALID'):transition('C','S1','已触及动态支撑，等待上行CHoCH',support_zone=[level-.3*available4['atr14'],level+.3*available4['atr14']])
            if zones.get('C') and prior_support and zones['C']['support_time']!=prior_support['t']:
                zones.pop('C')
                if state['C']['status']=='S1':transition('C','INVALID','确认支撑已更新，原底部观察区失效')
            if az and t4=='bear' and available4['structure']!='up' and crossed(row,last1,row['prev_lo']['price'] if row['prev_lo'] else None,.1,.5,-1):
                setup('A',row,row['prev_lo']['price'],az['high'],-1,row['end']+2700,row['end']);zones.pop('A',None)
            if t4=='bear' and level is not None and crossed(row,last1,level,.15,.55,-1) and row['h']-row['l']<=2.5*atr:
                setup('B',row,level,row['h'],-1,row['end']+10800,row['end'])
            cz=zones.get('C')
            if cz and row['choch']=='up' and row['body_ratio']>=.55 and row['prev_hi']:
                # V1.0 has no C timeout. Operational validity is checked on every later 1H close.
                setup('C',row,row['prev_hi']['price'],cz['low'],1,None,row['end']);zones.pop('C',None)
            last1=row
    last4=four[-1];last=one[-1];last15=fifteen[-1]
    macro_ok,macro_reason=macro_gate(calendar,now)
    for name,s in state.items():
        if s['status']=='S3':
            reasons=[]
            side=s['side'];entry=audit['market_data']['ticker']['ask' if side==1 else 'bid'];s['entry_reference']=entry
            risk=side*(entry-s['stop'])
            s['reward_risk']=side*(s['target']-entry)/risk if s['target'] is not None and risk>0 else None
            if now-(s['confirmation_bar_start']+900)>900:reasons.append('15m确认已过期，禁止追单')
            if not audit.get('approved_for_simulation'):reasons.append('报价/交易模式/点差过滤不通过')
            if not macro_ok:reasons.append(macro_reason)
            if s['reward_risk'] is None or s['reward_risk']<2:reasons.append('最近有效结构目标空间不足2R或无法验证')
            if name in ('A','B') and trend(last4)!='bear':reasons.append('4H空头过滤已失效')
            if last15['after_gap']:reasons.append('休市后首根K线')
            if not reasons:s.update(status='S4',reason='模拟研究全部条件合格')
            else:s.update(reason='；'.join(reasons),risk_blocks=reasons)
    if last4['structure']=='up' and state['A']['status'] in ('S0','S1','EXPIRED','INVALID'):
        transition('A','S0','4H曾确认上行结构突破，A过滤未满足，等待新的向下结构确认')
    qualified=[k for k,v in state.items() if v['status']=='S4']
    if 'C' in qualified and any(x in qualified for x in ('A','B')):
        decision='多空方案冲突，观望';best=None
    else:
        best=next((k for k in 'ABC' if k in qualified),None);decision='模拟信号 '+best if best else '观望'
    return {**common,'decision':decision,'plans':state,'best_plan':best,'signal':bool(best),'entry_allowed':bool(best),
        'trend_4h':trend(last4),'structure_1h':last['structure'],'macro_gate':{'passed':macro_ok,'reason':macro_reason},
        'indicators':audit['indicators'],'watch_levels':{'1h_swing_high':last['swing_high'],'1h_swing_low':last['swing_low'],
        '4h_swing_high':last4['swing_high'],'4h_swing_low':last4['swing_low']},
        'risk_budget':'单笔<=0.5%，组合<=0.7%；不计算手数、不下单'}

