#!/usr/bin/env python3
"""Read-only live pipeline. SMTP transport is independent of ChatGPT connectors."""
import argparse,datetime as dt,json,os,smtplib,sqlite3,time,traceback
from pathlib import Path
from email.message import EmailMessage
from zoneinfo import ZoneInfo
from gate_xauusd_cfd_audit import audit,collect,utc_iso,PERIODS,closed_bars
from abc_strategy import decide
BJT=ZoneInfo('Asia/Shanghai')
def redact_error(exc):
    text=str(exc)
    for key in ('SMTP_APP_PASSWORD','SMTP_PASSWORD','SMTP_USER','MAIL_TO'):
        if os.environ.get(key):text=text.replace(os.environ[key],'[REDACTED]')
    return f'{type(exc).__name__}: {text}'[:1500]
def evaluate(now=None,evidence_dir=None):
    try:
        raw=collect(evidence_dir)
        report=audit(raw,now=now)
        report['transport']={'ok':all(v and v[-1].get('ok') for v in raw['_transport'].values()),'base':'https://api.gateio.ws/api/v4'}
        return report,raw
    except Exception as exc:
        return {'status':'FAIL','approved_for_market_analysis':False,'approved_for_executable_signal':False,'approved_for_simulation':False,
            'source':'LIVE_GATE_CFD_ATTEMPT','symbol':'XAUUSD','audited_at_utc':utc_iso(time.time() if now is None else now),
            'issues':[redact_error(exc)],'market_data':{},'transport':{'ok':False}},None

def format_report(report,decision=None):
    verdict=report.get('status','FAIL');market=report.get('market_data',{});ticker=market.get('ticker',{})
    stamp=dt.datetime.fromisoformat(report['audited_at_utc']).astimezone(BJT)
    prefix='模拟信号' if decision and decision.get('signal') else ('休市' if verdict=='RESTING' else '观望' if verdict=='PASS' else '数据不足')
    subject=f'【{prefix}｜{verdict}】Gate XAUUSD CFD ABC {stamp:%Y-%m-%d %H:%M} 北京时间'
    lines=[subject,'仅模拟研究，不自动下单。',f'北京时间：{stamp.isoformat()}',f'行情审核：{verdict}',
        f'Gate CFD Bid/Ask：{ticker.get("bid")} / {ticker.get("ask")}；价差：{ticker.get("spread")} USD',
        f'交易状态：{ticker.get("status")}；trade_mode={ticker.get("trade_mode")}',
        f'API服务器响应时间：{ticker.get("server_timestamp_utc")}；该时间不是最后报价时间。',
        '最后逐笔报价更新时间：接口不提供；采用真实1分钟K线核验活跃程度。']
    for tf in ('4h','1h','15m','1m'):
        m=market.get(tf,{})
        end=m.get('last_closed_end_utc')
        end_bjt=dt.datetime.fromisoformat(end).astimezone(BJT).isoformat() if end else '不可得'
        lines.append(f'{tf}：已收盘{m.get("closed",0)}根；最新收盘北京时间{end_bjt}')
    if decision:
        lines += [f'4H趋势：{decision.get("trend_4h","不可计算")}；1H结构：{decision.get("structure_1h","不可计算")}']
        for tf in ('4h','1h'):
            i=report.get('indicators',{}).get(tf,{})
            lines.append(f'{tf} EMA20={i.get("ema20")}；EMA50={i.get("ema50")}；ATR14={i.get("atr14")}；Swing High={i.get("swing_high")}；Swing Low={i.get("swing_low")}；BOS={i.get("latest_bos")}；CHoCH={i.get("latest_choch")}')
        for name,p in decision.get('plans',{}).items():
            lines += [f'{name}：{p["status"]}｜{p.get("reason","")}',f'触发：{p.get("trigger")}；失效：{p.get("invalid")}']
            if p.get('level') is not None:lines.append(f'结构位：{p["level"]}；止损：{p.get("stop")}；目标：{p.get("target")}；空间R：{p.get("reward_risk")}')
        lines += [f'最优模拟方案：{decision.get("best_plan") or "无"}；最终决策：{decision.get("decision")}；满足入场条件：{decision.get("entry_allowed",False)}',
            '下一小时观察结构位：'+json.dumps(decision.get('watch_levels',{}),ensure_ascii=False),
            '宏观事件过滤：'+json.dumps(decision.get('macro_gate',{}),ensure_ascii=False)]
    lines += ['失败原因：'+('; '.join(report.get('issues',[])) or '无'),'限制：逐笔tick时间、账户专属交易权限、成交量/OI未验证；未完成收益回测认证。']
    return subject,'\n'.join(lines)

def send_email(subject,body,run_key=None,state_dir='state'):
    host=os.environ.get('SMTP_HOST') or 'smtp.gmail.com'
    port=int(os.environ.get('SMTP_PORT') or '465')
    user=os.environ.get('SMTP_USER');password=os.environ.get('SMTP_APP_PASSWORD')
    tos=[s.strip() for s in os.environ.get('MAIL_TO','').split(',') if s.strip()]
    if not user or not password:raise RuntimeError('SMTP credentials missing; connected Gmail is not transferable to GitHub Actions')
    if len(set(tos))!=2 or any('@' not in x or '\n' in x or '\r' in x for x in tos):raise ValueError('MAIL_TO must contain exactly two distinct authorized recipients from repository Secrets')
    Path(state_dir).mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(str(Path(state_dir)/'mail.sqlite3'))
    db.execute('CREATE TABLE IF NOT EXISTS deliveries (run_key TEXT PRIMARY KEY,status TEXT,result TEXT)')
    key=run_key or str(int(time.time()))
    row=db.execute('SELECT status,result FROM deliveries WHERE run_key=?',(key,)).fetchone()
    if row:return {'duplicate_suppressed':True,'previous_status':row[0],'previous_result':json.loads(row[1])}
    msg=EmailMessage();msg['From']=user;msg['To']=', '.join(tos);msg['Subject']=subject
    msg['Message-ID']=f'<gate-xauusd-{key}@{user.split("@")[-1]}>';msg.set_content(body)
    smtp=None
    # Retry only pre-submission transient transport failures; no blind retry after ambiguous DATA result.
    for attempt in range(1,4):
        try:
            smtp=smtplib.SMTP_SSL(host=host,port=port,timeout=20);smtp.login(user,password);break
        except smtplib.SMTPAuthenticationError:raise
        except (OSError,smtplib.SMTPConnectError,smtplib.SMTPServerDisconnected):
            if attempt==3:raise
            time.sleep(attempt)
    db.execute('INSERT INTO deliveries VALUES (?,?,?)',(key,'SUBMISSION_STARTED','{}'));db.commit()
    try:
        refused=smtp.send_message(msg)
        result={'submitted_to_smtp':not refused,'accepted_recipients':[x for x in tos if x not in refused],
                'refused_recipients':{k:str(v) for k,v in refused.items()},'message_id':msg['Message-ID'],'receipt_confirmed':False,'host':host}
        status='ACCEPTED' if not refused else 'PARTIAL'
    except Exception as exc:
        result={'submitted_to_smtp':False,'error':redact_error(exc),'delivery_uncertain':True,
                'automatic_retry_suppressed':True};status='UNKNOWN'
    finally:
        try:smtp.quit()
        except Exception:pass
    db.execute('UPDATE deliveries SET status=?,result=? WHERE run_key=?',(status,json.dumps(result),key));db.commit();db.close()
    return result

def main():
    cli=argparse.ArgumentParser()
    cli.add_argument('--out-dir',default='output')
    cli.add_argument('--state-dir',default='state')
    cli.add_argument('--send-mail',action='store_true')
    cli.add_argument('--calendar')
    args=cli.parse_args()
    output=Path(args.out_dir);output.mkdir(parents=True,exist_ok=True)
    started=time.time();report,raw=evaluate(evidence_dir=output/'http')
    now=int(time.time())
    calendar=json.load(open(args.calendar)) if args.calendar else None
    try:decision=decide(raw or {},report,now,calendar)
    except Exception as exc:
        report['status']='FAIL';report['approved_for_market_analysis']=False
        report['issues'].append('ABC error: '+redact_error(exc))
        decision={'signal':False,'entry_allowed':False,'decision':'计算失败，观望','plans':{}}
        (output/'error.log').write_text(traceback.format_exc())
    scheduled=(int(started)//3600)*3600+180
    if scheduled>started:scheduled-=3600
    timing={'actual_start_utc':utc_iso(started),'actual_end_utc':utc_iso(time.time()),'actual_start_bjt':dt.datetime.fromtimestamp(started,BJT).isoformat(),
        'nominal_hour_03_utc':utc_iso(scheduled),'delay_seconds':round(started-scheduled,3),
        'run_id':os.environ.get('GITHUB_RUN_ID'),'run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'),
        'event':os.environ.get('GITHUB_EVENT_NAME','manual_cloud_session'),'recurrence_verified':False}
    for name,value in [('audit.json',report),('decision.json',decision),('run.json',timing),('raw_gate_public.json',raw)]:
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    if raw and report.get('status')!='FAIL':
        import csv
        for tf in PERIODS:
            with (output/f'XAUUSD_{tf}.csv').open('w') as f:
                w=csv.writer(f);w.writerow(['timestamp','open','high','low','close'])
                for b in closed_bars(raw,tf,now):w.writerow([b[k] for k in ('t','o','h','l','c')])
    subject,body=format_report(report,decision)
    (output/'subject.txt').write_text(subject);(output/'report.txt').write_text(body)
    (output/'error.log').write_text('\n'.join(report.get('issues',[])) if not (output/'error.log').exists() else (output/'error.log').read_text())
    print(body)
    mail_ok=not args.send_mail
    if args.send_mail:
        try:
            key=dt.datetime.fromtimestamp(scheduled,dt.timezone.utc).strftime('%Y%m%dT%H03')
            status=send_email(subject,body,key,args.state_dir)
            mail_ok=status.get('submitted_to_smtp',False) or (status.get('duplicate_suppressed') and status.get('previous_status')=='ACCEPTED')
        except Exception as exc:status={'submitted_to_smtp':False,'error':redact_error(exc)}
        (output/'email_delivery.json').write_text(json.dumps(status,ensure_ascii=False,indent=2))
        print('EMAIL STATUS:',json.dumps({k:v for k,v in status.items() if k in ('submitted_to_smtp','duplicate_suppressed','previous_status','error','delivery_uncertain')},ensure_ascii=False))
    return 0 if report.get('status') in ('PASS','RESTING') and mail_ok else 2
if __name__=='__main__':raise SystemExit(main())

