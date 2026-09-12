#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import argparse, hashlib, json, os, re, shutil, sys
from bs4 import BeautifulSoup

TOOLS=Path(__file__).resolve().parent
ROOT=TOOLS.parent
DATA=ROOT/'assets'/'data'
STORAGE=TOOLS/'storage'
IMPORTS=STORAGE/'imports'
ARCHIVE=STORAGE/'archive'
BACKUPS=STORAGE/'backups'
REPORTS=STORAGE/'reports'
BOTS=DATA/'bots.json'
STATS=DATA/'bot-stats.json'
HISTORY=DATA/'bot-history.json'
EVENTS=DATA/'bot-events.json'
PUBLIC=DATA/'bot-public.json'
ARCHIVED=DATA/'archived-bots.json'
MILESTONES=[100,250,500,1000,2500,5000,10000]

STAT_KEYS=('id','name','title','url','visibility','messages','messagesDisplay','messagesApproximate','tokens','tokensDisplay','tokensApproximate','image','rawMessages','rawTokens')

def load_json(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:return default

def json_bytes(obj):
    raw=(json.dumps(obj,indent=2,ensure_ascii=False)+'\n').encode('utf-8')
    json.loads(raw.decode('utf-8'))
    return raw

def atomic_write_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=json_bytes(obj)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_bytes(raw)
    os.replace(tmp,path)

def parse_count(text):
    if text is None:return None,None,False
    raw=str(text).strip();s=raw.lower().replace(',','')
    m=re.fullmatch(r'([0-9]*\.?[0-9]+)\s*([km])?',s)
    if not m:return None,raw,False
    v=float(m.group(1));suf=m.group(2);approx=bool(suf)
    if suf=='k':v*=1000
    elif suf=='m':v*=1000000
    return int(round(v)),raw,approx

def extract(path:Path):
    soup=BeautifulSoup(path.read_text(encoding='utf-8',errors='ignore'),'html.parser');found={}
    for a in soup.select('a[aria-label^="chat-with-"][href*="/chat/"]'):
        href=a.get('href','');m=re.search(r'/chat/([0-9a-f-]{36})',href,re.I)
        if not m:continue
        bid=m.group(1).lower()
        if bid in found:continue
        card=a.find_parent('div',class_=lambda c:c and 'group' in c and 'rounded-xl' in c)
        if not card:continue
        name=(a.get('title') or a.get_text(strip=True) or a.get('aria-label','')[10:]).strip()
        if not name:name=a.get('aria-label','')[10:].strip()
        title=(card.get('data-ds-description-signature') or card.get('data-ds-language-description-signature') or '').strip()
        title=re.sub(r'^\d+:','',title).strip()

        # SpicyChat sometimes hides the Public/Unlisted badge while a bot is under
        # review. Absence of a badge must never be interpreted as "public".
        card_text=' '.join(card.stripped_strings)
        under_review=bool(re.search(r'\bUnder\s+Review\b',card_text,re.I))
        visibility=None
        for button in card.find_all('button'):
            candidates=[button.get('aria-label'),button.get('title'),button.get_text(' ',strip=True)]
            for candidate in candidates:
                label=(candidate or '').strip().lower()
                if label in ('public','unlisted','private'):
                    visibility=label;break
            if visibility:break
        if visibility is None:
            # Fallback for status pills that are not buttons in some saved layouts.
            for node in card.find_all(['span','p','div']):
                label=node.get_text(' ',strip=True).lower()
                if label in ('public','unlisted','private'):
                    visibility=label;break

        def stat(icon):
            svg=card.find('svg',class_=lambda c:c and icon in c)
            p=svg.parent.find('p') if svg and svg.parent else None
            return parse_count(p.get_text(strip=True) if p else None)
        messages,m_raw,m_approx=stat('lucide-message-square-text');tokens,t_raw,t_approx=stat('lucide-blocks')
        img=card.find('img',alt=name);src=img.get('src') if img else None;image=None
        if src:
            base=Path(src.split('?')[0].replace('\\','/')).name
            if re.fullmatch(r'[0-9a-f-]{36}\.(?:jpg|jpeg|png|webp)',base,re.I):image=f'https://cdn.nd-api.com/avatars/{base}?class=avatar256x256'
            elif src.startswith('http'):image=src
        found[bid]={'id':bid,'name':name,'title':title,'url':f'https://spicychat.ai/chat/{bid}','visibility':visibility,'underReview':under_review,'messages':messages,'messagesDisplay':m_raw,'messagesApproximate':m_approx,'tokens':tokens,'tokensDisplay':t_raw,'tokensApproximate':t_approx,'image':image,'rawMessages':m_raw,'rawTokens':t_raw}
    return list(found.values())

def comparable(bot):return {k:bot.get(k) for k in STAT_KEYS}


def latest_history_rows(history):
    """Return the most recent actually-observed row for every bot in history."""
    out={}
    snaps=sorted(history.get('snapshots',[]),key=lambda s:s.get('capturedAt') or '')
    for snap in snaps:
        seen_at=snap.get('capturedAt')
        for row in snap.get('bots',[]):
            bid=row.get('id')
            if not bid or row.get('carriedForward'):continue
            out[bid]=(dict(row),row.get('observedAt') or seen_at)
    return out

def normalize_history(history,curated_ids):
    """Repair partial local snapshots without inventing new observations.

    Once a bot has appeared in history, later partial My Creations exports may omit
    it (review state, pagination/layout changes, etc.). Carry its last known row
    forward for collection totals/ranks, but mark it so trend graphs do not treat
    the carry-forward as a fresh observation.
    """
    changed=False;last_known={}
    snaps=history.setdefault('snapshots',[])
    snaps.sort(key=lambda s:s.get('capturedAt') or '')
    for snap in snaps:
        at=snap.get('capturedAt');rows=snap.setdefault('bots',[]);present=set()
        for row in rows:
            bid=row.get('id')
            if not bid:continue
            present.add(bid)
            if row.get('carriedForward'):
                # Preserve the original observation time from the row we carried.
                if bid not in last_known:
                    last_known[bid]=(dict(row),row.get('observedAt') or at)
            else:
                last_known[bid]=(dict(row),row.get('observedAt') or at)
        for bid in curated_ids:
            if bid in present or bid not in last_known:continue
            base,observed_at=last_known[bid]
            carry={k:v for k,v in base.items() if k not in ('carriedForward','seenInLatestExport')}
            carry['carriedForward']=True
            carry['observedAt']=observed_at
            rows.append(carry);changed=True
    return changed

def latest_visibility_events(events_doc):
    """Last explicit visibility transition we recorded for each bot.

    Review-state imports never create visibility transitions, so these events are
    useful evidence of the status immediately before a bot went back into review.
    """
    out={}
    for e in sorted(events_doc.get('events',[]),key=lambda x:x.get('at') or ''):
        if e.get('type')!='visibility':continue
        state=e.get('to')
        bid=e.get('botId')
        if bid and state in ('public','unlisted','private'):out[bid]=state
    return out

def known_visibility(bid,curated,old_map,hist_map,public_by_id,visibility_events):
    # A recorded transition is strongest because under-review imports explicitly
    # do NOT generate one. This lets us recover from an older broken import that
    # accidentally rewrote the current stats row.
    event_state=visibility_events.get(bid)
    if event_state in ('public','unlisted','private'):return event_state

    # bots.json now stores the last authoritative status and is updated whenever
    # SpicyChat exposes a real Public/Unlisted/Private badge. While a bot is under
    # review, this value is preserved rather than replaced by the review state.
    b=curated.get(bid,{})
    explicit=b.get('visibility')
    if explicit in ('public','unlisted','private'):return explicit

    old=old_map.get(bid,{})
    if old.get('visibility') in ('public','unlisted','private'):return old.get('visibility')
    h=(hist_map.get(bid) or ({},None))[0]
    if h.get('visibility') in ('public','unlisted','private'):return h.get('visibility')

    # A public-baseline record is still useful if all current/curated state is
    # missing. It is intentionally only a fallback so a later real unlist wins.
    if public_by_id.get(bid):return 'public'
    return None

def effective_visibility(incoming,bid,curated,old_map,hist_map,public_by_id,visibility_events):
    raw=incoming.get('visibility')
    if incoming.get('underReview'):
        # Review is not a visibility. Preserve the pre-review state. If we have
        # never known one, default to unlisted until a real badge/public check
        # confirms otherwise.
        return known_visibility(bid,curated,old_map,hist_map,public_by_id,visibility_events) or 'unlisted'
    # Outside review, an actual badge is authoritative and may legitimately move
    # a bot Public -> Unlisted or Unlisted -> Public.
    if raw in ('public','unlisted','private'):return raw
    return known_visibility(bid,curated,old_map,hist_map,public_by_id,visibility_events)

def best_fallback_row(bid,old_map,hist_map):
    old=dict(old_map[bid]) if bid in old_map else None
    hist,observed_at=(hist_map.get(bid) or (None,None))
    hist=dict(hist) if hist else None
    if old and hist:
        # A damaged previous current-stats file can contain an identity row with
        # null stats. Fill those holes from the last real history observation.
        for key in STAT_KEYS:
            if old.get(key) is None and hist.get(key) is not None:old[key]=hist.get(key)
        return old,old.get('observedAt') or observed_at
    if old:return old,old.get('observedAt')
    if hist:return hist,observed_at
    return None,None

def merge_stat_row(incoming,bid,curated,old_map,hist_map,public_by_id,visibility_events,observed_at):
    fallback,fallback_at=best_fallback_row(bid,old_map,hist_map)
    row=comparable(incoming)
    # If a saved layout failed to expose one numeric field, retain the last known
    # value for that field rather than replacing it with null.
    if fallback:
        for key in ('messages','messagesDisplay','messagesApproximate','rawMessages','tokens','tokensDisplay','tokensApproximate','rawTokens'):
            if row.get(key) is None:row[key]=fallback.get(key)
    row['visibility']=effective_visibility(incoming,bid,curated,old_map,hist_map,public_by_id,visibility_events)
    row['observedAt']=observed_at
    row['seenInLatestExport']=True
    return row

def backup(paths,stamp):
    BACKUPS.mkdir(parents=True,exist_ok=True)
    for p in paths:
        if p.exists():shutil.copy2(p,BACKUPS/f'{p.stem}-{stamp}{p.suffix}')

def newest_import():
    IMPORTS.mkdir(parents=True,exist_ok=True)
    candidates=[p for p in IMPORTS.iterdir() if p.is_file() and p.suffix.lower() in ('.html','.htm')]
    return max(candidates,key=lambda p:p.stat().st_mtime) if candidates else None

def rank_map(rows):
    a=[x for x in rows if isinstance(x.get('messages'),int)]
    a.sort(key=lambda x:(-x['messages'],str(x.get('name','')).lower()))
    return {x['id']:i+1 for i,x in enumerate(a)}

def event_key(e):return (e.get('at'),e.get('botId'),e.get('type'),e.get('value'),e.get('from'),e.get('to'))

def add_event(doc,e):
    keys={event_key(x) for x in doc.setdefault('events',[])}
    if event_key(e) not in keys:doc['events'].append(e)

def validate_extraction(data,bots_doc,old_stats,force=False):
    ids=[x['id'] for x in data]
    if not data:raise ValueError('No SpicyChat creation cards found.')
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate bot IDs were extracted; page structure may have changed.')
    bad=[x for x in data if not x.get('name') or not x.get('id')]
    if bad:raise ValueError('One or more bot cards are missing required identity fields.')
    baseline=max(len(bots_doc.get('bots',[])),len(old_stats.get('bots',[])))
    if baseline>=10 and len(data)<max(5,int(baseline*.55)) and not force:
        raise ValueError(f'Only {len(data)} bots were extracted but the existing dataset has {baseline}. Aborting as a safety check. Use --force only if that drop is intentional.')
    if sum(1 for x in data if x.get('messagesDisplay') is not None)<max(1,int(len(data)*.6)) and not force:
        raise ValueError('Most message-count fields could not be parsed. SpicyChat may have changed the page layout; aborting.')

def main():
    ap=argparse.ArgumentParser(description='Update the bot site from a saved SpicyChat My Creations HTML export.')
    ap.add_argument('html',nargs='?',help='HTML file. If omitted, newest HTML in tools/storage/imports is used.')
    ap.add_argument('--no-archive',action='store_true',help='Do not archive/copy the source HTML after a successful import.')
    ap.add_argument('--force',action='store_true',help='Bypass suspicious-count/layout safety checks.')
    ap.add_argument('--dry-run',action='store_true',help='Parse and report changes without writing JSON or archives.')
    args=ap.parse_args();source=Path(args.html).expanduser().resolve() if args.html else newest_import()
    if not source or not source.exists():
        print(r'No HTML found. Put a saved My Creations page in tools\storage\imports or drag it onto update-chatbots.bat.');return 2
    bots_doc=load_json(BOTS,{'schemaVersion':3,'updatedAt':datetime.now().date().isoformat(),'newBadgeDays':14,'categories':[],'bots':[]});old_stats=load_json(STATS,{'schemaVersion':2,'bots':[]});history=load_json(HISTORY,{'schemaVersion':2,'snapshots':[]});events=load_json(EVENTS,{'schemaVersion':1,'milestones':MILESTONES,'events':[]});public_doc=load_json(PUBLIC,{'schemaVersion':1,'bots':[]});archived_doc=load_json(ARCHIVED,{'schemaVersion':1,'bots':[]});archived_ids={x.get('id') for x in archived_doc.get('bots',[]) if x.get('id')}
    try:
        data=[x for x in extract(source) if x.get('id') not in archived_ids];validate_extraction(data,bots_doc,old_stats,args.force)
        if not args.force and old_stats.get('bots'):
            om={x['id']:x for x in old_stats.get('bots',[])}
            pairs=[(om[x['id']],x) for x in data if x['id'] in om and isinstance(om[x['id']].get('messages'),int) and isinstance(x.get('messages'),int)]
            declines=[(a,b) for a,b in pairs if b['messages']<a['messages']]
            old_total=sum(a['messages'] for a,b in pairs);new_total=sum(b['messages'] for a,b in pairs)
            if pairs and (len(declines)>=max(3,int(len(pairs)*.10)) or (old_total and new_total<old_total*.95)):
                raise ValueError(f'{len(declines)} existing bots have lower message counts and comparable total fell from {old_total} to {new_total}. This looks like an older/stale export. Use --force only if the regression is intentional.')
    except Exception as e:
        print(f'Import aborted: {e}');return 3
    now=datetime.now().astimezone();stamp=now.strftime('%Y%m%d-%H%M%S');iso=now.isoformat(timespec='seconds');sha=hashlib.sha256(source.read_bytes()).hexdigest()
    old_map={x['id']:x for x in old_stats.get('bots',[]) if x.get('id')};curated={x['id']:x for x in bots_doc.get('bots',[]) if x.get('id')};incoming={x['id'] for x in data}
    new_ids=[x['id'] for x in data if x['id'] not in curated];missing=[x['id'] for x in bots_doc.get('bots',[]) if x['id'] not in incoming]
    visibility=[];renames=[];message_changes=[];token_changes=[];public_baselines=[]
    public_doc['schemaVersion']=max(2,int(public_doc.get('schemaVersion') or 1));public_doc['note']='Public dates are confirmed from SpicyChat approval emails when publicSinceAccuracy is confirmed. Message baselines are kept separately because the first saved message count can be later than the approval time.'
    public_entries=public_doc.setdefault('bots',[]);public_by_id={x.get('id'):x for x in public_entries if x.get('id')}
    visibility_events=latest_visibility_events(events)

    # Repair any partial snapshots left by older versions of the BAT before using
    # history as a fallback source.
    history_repaired=normalize_history(history,set(curated))
    hist_map=latest_history_rows(history)

    # Curate newly discovered identities first; current saved-export data may then
    # update only safe live fields (name/title/url/image/order).
    order={x['id']:i for i,x in enumerate(data,1)}
    for x in data:
        b=curated.get(x['id'])
        if b is None:
            initial_visibility=effective_visibility(x,x['id'],curated,old_map,hist_map,public_by_id,visibility_events)
            b={'id':x['id'],'name':x['name'],'category':'other','tags':[],'title':x['title'],'blurb':x['title'],'url':x['url'],'origin':'unknown','order':order[x['id']],'image':x.get('image'),'imageHidden':False,'addedAt':now.date().isoformat(),'knownSince':iso,'knownSinceSource':'first-import','firstSeenAt':iso,'createdAt':now.date().isoformat(),'createdAtSource':'first-import','needsReview':True}
            if initial_visibility in ('public','unlisted','private'):b['visibility']=initial_visibility
            curated[x['id']]=b
        b['name']=x['name'];b['title']=x['title'];b['url']=x['url'];b['order']=order[x['id']];b.pop('missingFromLatest',None)
        resolved_visibility=effective_visibility(x,x['id'],curated,old_map,hist_map,public_by_id,visibility_events)
        if resolved_visibility in ('public','unlisted','private'):
            # Real badges update the stored state. During review, resolved_visibility
            # is the preserved pre-review state, so it is safe to keep as well.
            b['visibility']=resolved_visibility
            if not x.get('underReview') and x.get('visibility') in ('public','unlisted','private'):
                b['visibilitySource']='saved-my-creations'
            elif x.get('underReview'):
                b.setdefault('visibilitySource','preserved-during-review')
        b.setdefault('knownSince',iso);b.setdefault('knownSinceSource','first-import');b.setdefault('firstSeenAt',b.get('knownSince') or iso);b.setdefault('createdAt',(b.get('knownSince') or iso)[:10]);b.setdefault('createdAtSource',b.get('knownSinceSource') or 'first-import')
        if not b.get('imageHidden'):b['image']=x.get('image') or b.get('image')
        if b.get('name')=='Doe':b['image']=None;b['imageHidden']=True

    # Recalculate history fallback now that brand-new bot IDs are known curated IDs.
    if new_ids:
        history_repaired=normalize_history(history,set(curated)) or history_repaired
        hist_map=latest_history_rows(history)

    # Build current rows from the new export, but keep last-known rows for bots that
    # are absent from this one saved page. This is the key non-destructive behavior.
    incoming_map={x['id']:x for x in data}
    parsed_rows={}
    for x in data:
        parsed_rows[x['id']]=merge_stat_row(x,x['id'],curated,old_map,hist_map,public_by_id,visibility_events,iso)

    rows=[];history_rows=[]
    current_ids=[x['id'] for x in data]
    tail=[b for b in bots_doc.get('bots',[]) if b['id'] not in current_ids]
    bots_doc['bots']=[curated[x['id']] for x in data]+tail;bots_doc['schemaVersion']=3;bots_doc['updatedAt']=now.date().isoformat()

    for b in bots_doc.get('bots',[]):
        bid=b['id']
        if bid in parsed_rows:
            row=dict(parsed_rows[bid]);hrow=dict(row);hrow.pop('seenInLatestExport',None)
        else:
            fallback,observed_at=best_fallback_row(bid,old_map,hist_map)
            if not fallback:continue
            row={k:fallback.get(k) for k in STAT_KEYS}
            for key in ('name','title','url'):
                if b.get(key):row[key]=b.get(key)
            if not b.get('imageHidden') and b.get('image'):row['image']=b.get('image')
            # Curated/confirmed status wins over an old scraped status.
            kv=known_visibility(bid,curated,old_map,hist_map,public_by_id,visibility_events)
            if kv:row['visibility']=kv
            row['observedAt']=observed_at or old_stats.get('capturedAt')
            row['seenInLatestExport']=False
            hrow=dict(row);hrow.pop('seenInLatestExport',None);hrow['carriedForward']=True
        if b.get('imageHidden'):row['image']=None;hrow['image']=None
        rows.append(row);history_rows.append(hrow)

    current_map={x['id']:x for x in rows}
    for x in data:
        old=old_map.get(x['id']) or (hist_map.get(x['id']) or (None,None))[0]
        cur=current_map.get(x['id'])
        if not old or not cur:continue
        if old.get('name')!=cur.get('name'):renames.append((old.get('name'),cur.get('name'),x['id']))
        if old.get('visibility')!=cur.get('visibility') and not x.get('underReview'):visibility.append((cur['name'],old.get('visibility'),cur.get('visibility')))
        if old.get('messages')!=cur.get('messages'):message_changes.append((cur['name'],old.get('messages'),cur.get('messages')))
        if old.get('tokens')!=cur.get('tokens'):token_changes.append((cur['name'],old.get('tokens'),cur.get('tokens')))

    # Add/fill public baselines only when this export explicitly says Public and
    # the card is not under review. Confirmed publication records may exist before
    # the first post-approval message snapshot; fill those on the first later import.
    for x in data:
        cur=current_map.get(x['id'])
        if not cur or x.get('underReview') or x.get('visibility')!='public':continue
        existing_public=public_by_id.get(x['id'])
        if existing_public and existing_public.get('messagesAtBaseline') is None and cur.get('messages') is not None:
            try:
                public_at=datetime.fromisoformat(str(existing_public.get('publicSinceAt','')).replace('Z','+00:00'))
                observed_at=datetime.fromisoformat(iso.replace('Z','+00:00'))
            except ValueError:
                public_at=observed_at=None
            if public_at is not None and observed_at is not None and observed_at>=public_at:
                lag=max(0,int(round((observed_at-public_at).total_seconds()/60)))
                existing_public.update({'baselineAt':iso,'messagesAtBaseline':cur.get('messages'),'messagesDisplayAtBaseline':cur.get('messagesDisplay') or str(cur.get('messages')),'messagesApproximateAtBaseline':bool(cur.get('messagesApproximate')),'baselineAccuracy':'first-post-public-observation','baselineLagMinutes':lag,'baselineSource':'saved-my-creations'})
                public_baselines.append(x['name'])
        if cur.get('visibility')=='public' and x['id'] not in public_by_id and cur.get('messages') is not None:
            old=old_map.get(x['id']) or (hist_map.get(x['id']) or (None,None))[0]
            entry={'id':x['id'],'name':x['name'],'publicSinceAt':iso,'publicSinceAccuracy':'first-observed','publicSinceSource':'saved-my-creations','firstPublicObservedAt':iso,'previousNonPublicObservedAt':(old_stats.get('capturedAt') if old and old.get('visibility') in ('unlisted','private') else None),'baselineAt':iso,'messagesAtBaseline':cur.get('messages'),'messagesDisplayAtBaseline':cur.get('messagesDisplay') or str(cur.get('messages')),'messagesApproximateAtBaseline':bool(cur.get('messagesApproximate')),'baselineAccuracy':'same-observation','baselineLagMinutes':0,'baselineSource':'saved-my-creations','accuracy':'first-observed','source':'saved-my-creations'}
            public_entries.append(entry);public_by_id[x['id']]=entry;public_baselines.append(x['name'])

    snapshot={'capturedAt':iso,'source':source.name,'sourceSha256':sha,'label':'Imported export','bots':history_rows}
    snaps=history.setdefault('snapshots',[]);last=snaps[-1] if snaps else None
    same=bool(last) and [comparable(x) for x in last.get('bots',[])]==[comparable(x) for x in history_rows]
    previous=last
    if not same:
        # Generate events against the previous normalized snapshot. Carried rows
        # keep totals stable but do not create fake message changes.
        pm={x['id']:x for x in (previous or {}).get('bots',[])};pr=rank_map((previous or {}).get('bots',[]));cr=rank_map(history_rows)
        for x in history_rows:
            if x.get('carriedForward'):continue
            base={'at':iso,'botId':x['id'],'botName':x['name']};old=pm.get(x['id'])
            if old is None:
                add_event(events,{**base,'type':'new'});continue
            if old.get('name')!=x.get('name'):add_event(events,{**base,'type':'rename','from':old.get('name'),'to':x.get('name')})
            incoming_state=incoming_map.get(x['id'],{})
            if old.get('visibility')!=x.get('visibility') and not incoming_state.get('underReview'):
                add_event(events,{**base,'type':'visibility','from':old.get('visibility'),'to':x.get('visibility')})
            ov,nv=old.get('messages'),x.get('messages')
            if isinstance(ov,int) and isinstance(nv,int) and nv>=ov:
                for m in MILESTONES:
                    if ov<m<=nv:add_event(events,{**base,'type':'milestone','value':m})
        snaps.append(snapshot)
        events['events'].sort(key=lambda e:e.get('at') or '')

    # If nothing changed, reuse the normalized latest snapshot so a rerun of the
    # same HTML repairs lost rows without inventing a new history point.
    latest_snapshot=snaps[-1] if snaps else snapshot
    stats_doc={'schemaVersion':2,**latest_snapshot}
    public_doc['bots'].sort(key=lambda x:(x.get('firstPublicObservedAt') or '',x.get('name') or ''))
    report_lines=[f'SpicyChat bot update - {iso}',f'Source: {source}',f'Extracted: {len(data)} bots',f'New: {len(new_ids)}',f'Missing from export: {len(missing)}',f'Renames: {len(renames)}',f'Visibility changes: {len(visibility)}',f'Public baselines added: {len(public_baselines)}',f'Message changes: {len(message_changes)}',f'Token changes: {len(token_changes)}',f'History snapshot: {"skipped (no stat changes)" if same else "added"}',f'Partial history repaired: {"yes" if history_repaired else "no"}',f'Dry run: {"yes" if args.dry_run else "no"}','']
    if new_ids:report_lines+=['NEW / NEEDS MANUAL INFO']+[f'- {curated[i]["name"]} ({i})' for i in new_ids]+['']
    if missing:report_lines+=['MISSING FROM EXPORT (not deleted)']+[f'- {curated[i]["name"]} ({i})' for i in missing if i in curated]+['']
    if renames:report_lines+=['RENAMES']+[f'- {a} -> {b} ({i})' for a,b,i in renames]+['']
    if visibility:report_lines+=['VISIBILITY']+[f'- {n}: {a} -> {b}' for n,a,b in visibility]+['']
    if public_baselines:report_lines+=['PUBLIC BASELINES']+[f'- {n}' for n in public_baselines]+['']
    if message_changes:
        report_lines+=['MESSAGES']
        for n,a,b in sorted(message_changes,key=lambda x:(x[2] or 0)-(x[1] or 0),reverse=True):
            delta=(b or 0)-(a or 0);gp=(delta/a*100) if a and a>0 else None;report_lines.append(f'- {n}: {a} -> {b} ({delta:+d}{" / "+format(gp,"+.1f")+"%" if gp is not None else ""})')
        report_lines+=['']
    if token_changes:report_lines+=['TOKENS']+[f'- {n}: {a} -> {b}' for n,a,b in token_changes]+['']
    report_lines+=['Updated: assets/data/bots.json','Updated: assets/data/bot-stats.json','Updated: assets/data/bot-history.json' if (not same or history_repaired) else 'History unchanged','Updated: assets/data/bot-events.json' if not same else 'Events unchanged','Updated: assets/data/bot-public.json' if public_baselines else 'Public baselines unchanged']
    report='\n'.join(report_lines)+'\n'
    if not args.dry_run:
        backup([BOTS,STATS,HISTORY,EVENTS,PUBLIC],stamp)
        atomic_write_json(BOTS,bots_doc);atomic_write_json(STATS,stats_doc);atomic_write_json(HISTORY,history);atomic_write_json(EVENTS,events);atomic_write_json(PUBLIC,public_doc)
        REPORTS.mkdir(parents=True,exist_ok=True);(REPORTS/'latest-update.txt').write_text(report,encoding='utf-8');(REPORTS/f'update-{stamp}.txt').write_text(report,encoding='utf-8')
        if not args.no_archive:
            ARCHIVE.mkdir(parents=True,exist_ok=True);dest=ARCHIVE/f'{stamp}-{source.name}'
            try:
                if source.parent.resolve()==IMPORTS.resolve():shutil.move(str(source),dest)
                else:shutil.copy2(source,dest)
            except Exception as e:print(f'Warning: could not archive source: {e}')
    print(report);return 0
if __name__=='__main__':raise SystemExit(main())
