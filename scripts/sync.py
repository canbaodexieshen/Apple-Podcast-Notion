"""Apple Podcasts -> existing Podcast2Notion template. Credentials are environment-only."""
import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, parse_qsl, urlencode, urlunsplit

import requests

APPLE = 'https://amp-api.podcasts.apple.com'
INCLUDE = {'l': 'zh-Hans-CN', 'include[podcast-episodes]': 'channel,playback-position,podcast',
           'with': 'entitlements,hlsVideo'}


class AudioUnavailable(RuntimeError):
    """A publisher denied access to audio; account/AI API failures are different."""


class AudioTemporarilyUnavailable(AudioUnavailable):
    """Only a failed source download, before any AI request has been made."""


def required(name):
    value = os.getenv(name, '').strip()
    if not value:
        raise ValueError('Missing configuration: ' + name)
    return value


def safe_error(error):
    if isinstance(error, requests.HTTPError):
        return 'HTTP ' + str(error.response.status_code)
    if isinstance(error, (requests.RequestException, subprocess.SubprocessError)):
        return type(error).__name__
    message = str(error)
    for key, value in os.environ.items():
        if value and any(s in key for s in ('TOKEN', 'KEY', 'SECRET')):
            message = message.replace(value, '[redacted]')
    message = re.sub(r'https?://[^\s\"<>]+', '[url redacted]', message)
    message = re.sub(r'(?i)bearer\s+\S+|sk-[\w-]+', '[redacted]', message)
    return re.sub(r'(ntn_|secret_)[\w-]+', '[redacted]', message)[:500]


def check_response(response, stage):
    """Report the failed service, without logging headers, signed URLs or content."""
    if response.ok:
        return
    details = []
    if 'json' in response.headers.get('content-type', ''):
        try:
            body = response.json()
            error = body.get('error', body) if isinstance(body, dict) else {}
            if isinstance(error, dict):
                for key in ('code', 'type', 'message'):
                    value = error.get(key)
                    if isinstance(value, (str, int)):
                        details.append(f'{key}={safe_error(ValueError(str(value)))[:180]}')
        except ValueError:
            pass
    trace = response.headers.get('x-siliconcloud-trace-id') or response.headers.get('x-request-id')
    if trace and re.fullmatch(r'[\w.-]{1,120}',trace):
        details.append('request_id='+trace)
    host = urlsplit(response.url or '').hostname or 'unknown'
    error_type = AudioUnavailable if stage == 'audio_download' and response.status_code in (403,404,410) else RuntimeError
    raise error_type(f'{stage}: HTTP {response.status_code}, host={host}; '+ '; '.join(details))


def get_json(url, headers):
    for attempt in range(5):
        try:
            response = requests.get(url, headers=headers, timeout=(15, 90), allow_redirects=False)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(min(2 ** attempt, 16))
                continue
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError('Unexpected redirect from authenticated API')
            return response.json()
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 4:
                raise


def apple_pages(path, headers):
    url, seen, rows = urljoin(APPLE, path), set(), {}
    for _ in range(1000):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.netloc != urlsplit(APPLE).netloc or not parts.path.startswith('/v1/me/'):
            raise ValueError('Unsafe Apple pagination URL')
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update(INCLUDE)  # Apple next links omit relationship expansions.
        url = urlunsplit(parts._replace(query=urlencode(query)))
        if url in seen:
            raise ValueError('Repeated Apple pagination cursor')
        seen.add(url)
        result = get_json(url, headers)
        data = result.get('data')
        if not isinstance(data, list):
            raise ValueError('Unexpected Apple response data')
        for row in data:
            if not isinstance(row, dict) or not row.get('id'):
                raise ValueError('Apple record missing ID')
            rows[row['id']] = row
        nxt = result.get('next')
        if not nxt:
            return rows
        if not isinstance(nxt, str):
            raise ValueError('Invalid Apple pagination cursor')
        url = urljoin(url, nxt)
    raise ValueError('Apple pagination safety limit reached')


def relation(row, name):
    return row.get('relationships', {}).get(name, {}).get('data', [])


def position(row):
    values = relation(row, 'playback-position')
    return values[0].get('attributes', {}) if values else {}


def merge_episodes(saved, recent):
    result = dict(saved)
    for key, row in recent.items():
        old = result.get(key, {})
        merged = {**old, **row}
        merged['attributes'] = {**old.get('attributes', {}), **row.get('attributes', {})}
        merged['relationships'] = {**old.get('relationships', {}), **row.get('relationships', {})}
        # A missing/empty expansion must not erase known progress.
        if not position(row) and position(old):
            merged['relationships']['playback-position'] = old['relationships']['playback-position']
        result[key] = merged
    return result


def fetch_apple():
    bearer = required('APPLE_BEARER_TOKEN')
    headers = {'Authorization': bearer if bearer.lower().startswith('bearer ') else 'Bearer ' + bearer,
               'Media-User-Token': required('APPLE_MEDIA_USER_TOKEN'),
               'Origin': 'https://podcasts.apple.com', 'Referer': 'https://podcasts.apple.com/',
               'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    shows = apple_pages('/v1/me/library/podcasts?limit=30', headers)
    saved = apple_pages('/v1/me/library/podcast-episodes?limit=30', headers)
    recent = apple_pages('/v1/me/recent/played/podcast-episodes', headers)
    episodes = merge_episodes(saved, recent)
    for row in episodes.values():
        for show in relation(row, 'podcast'):
            previous = shows.get(show['id'], {})
            shows[show['id']] = {**show, **previous,
                'attributes': {**show.get('attributes', {}), **previous.get('attributes', {})}}
    print(f'Apple: {len(shows)} related shows, {len(saved)} saved, {len(recent)} recent, {len(episodes)} unique episodes')
    return shows, episodes, set(saved)


def rich(text):
    text = str(text or '')
    if len(text) > 150000:
        raise ValueError('Text too long for one Notion block; split the content')
    return [{'type': 'text', 'text': {'content': text[i:i+1800]}} for i in range(0, len(text), 1800)]


def prop(kind, value):
    if kind in ('title', 'rich_text'):
        return {kind: rich(value)}
    return {kind: value}


def text_value(page, name):
    p = page.get('properties', {}).get(name, {})
    return ''.join(x.get('plain_text', x.get('text', {}).get('content', '')) for x in p.get(p.get('type', 'rich_text'), []) or [])


def podcast_aliases():
    """Public Apple catalog ID -> existing Xiaoyuzhou ID; no private page IDs."""
    path=Path(__file__).resolve().parents[1]/'config/podcast_aliases.json'
    aliases=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if len(set(aliases.values())) != len(aliases):
        raise ValueError('Ambiguous podcast aliases')
    return aliases


class Notion:
    def __init__(self):
        self.headers = {'Authorization': 'Bearer ' + required('NOTION_TOKEN'), 'Notion-Version': '2022-06-28'}
        self.last = 0
        self.dbs = {}
        self.schemas = {}
        match = re.search(r'[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', required('NOTION_PAGE'))
        if not match:
            raise ValueError('Invalid NOTION_PAGE')
        self.root = match.group()
        self.discover(self.root)
        for name in ('Podcast', 'Episode', 'Author', '全部'):
            if name not in self.dbs:
                raise ValueError('Missing template database: ' + name)
        for name in ('Podcast', 'Episode', 'Author'):
            self.schemas[name] = self.call('GET', 'databases/' + self.dbs[name])['properties']

    def call(self, method, path, body=None):
        read = method == 'GET' or path.endswith('/query')
        for attempt in range(6):
            time.sleep(max(0, .4 - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            try:
                headers = {**self.headers, 'Notion-Version':'2026-03-11'} if path.startswith('blocks/') else self.headers
                response = requests.request(method, 'https://api.notion.com/v1/' + path,
                    headers=headers, json=body, timeout=(15, 90), allow_redirects=False)
            except (requests.Timeout, requests.ConnectionError):
                if not read or attempt == 5:
                    raise  # Never blindly repeat uncertain creates/appends.
                time.sleep(min(2 ** attempt, 16))
                continue
            if (response.status_code == 429 or (read and response.status_code in (500, 502, 503, 504))) and attempt < 5:
                try:
                    wait = float(response.headers.get('Retry-After', 2 ** attempt))
                    if not math.isfinite(wait) or wait < 0:
                        raise ValueError()
                except ValueError:
                    wait = 2 ** attempt
                time.sleep(min(wait, 60))
                continue
            if not response.ok:
                detail = response.json().get('message', '') if 'json' in response.headers.get('content-type', '') else ''
                raise RuntimeError(f'Notion HTTP {response.status_code}: {detail}')
            return response.json()

    def paginate(self, path, body=None):
        cursor = None
        while True:
            if body is None:
                data = self.call('GET', path + ('&' if '?' in path else '?') + 'page_size=100' + ('&start_cursor='+cursor if cursor else ''))
            else:
                data = self.call('POST', path, {**body, 'page_size': 100, **({'start_cursor': cursor} if cursor else {})})
            yield from data['results']
            if not data.get('has_more'):
                return
            cursor = data['next_cursor']

    def discover(self, root, depth=0):
        if depth > 8:
            return
        for b in self.paginate('blocks/' + root + '/children'):
            kind = b['type']
            if kind == 'child_database':
                name = b[kind]['title']
                if name not in ('Podcast', 'Episode', 'Author', '全部', '思维导图'):
                    continue  # Templates may contain multiple unrelated Untitled placeholders.
                if name in self.dbs:
                    raise ValueError('Duplicate database name: ' + name)
                self.dbs[name] = b['id']
            elif b.get('has_children') and kind not in ('child_page', 'synced_block'):
                self.discover(b['id'], depth+1)

    def prepare(self, write):
        needed = {
            'Podcast': {'播客':'title', 'Pid':'rich_text', '链接':'url', 'Description':'rich_text', '作者':'relation'},
            'Episode': {'标题':'title', 'Eid':'rich_text', 'Podcast':'relation', '音频':'rich_text', 'Description':'rich_text',
                        '发布时间':'date', '时间戳':'number', '时长':'number', '链接':'url', '状态':'status'},
            'Author': {'标题':'title'}}
        additions = {'来源':'rich_text', '播放位置':'number', '进度更新时间':'date', '收藏':'checkbox',
                     'AI状态':'rich_text', '转写指纹':'rich_text', '脑图指纹':'rich_text'}
        for db, expected in needed.items():
            for name, kind in expected.items():
                if self.schemas[db].get(name, {}).get('type') != kind:
                    raise ValueError(f'Template field mismatch: {db}.{name} must be {kind}')
        statuses = {x['name'] for x in self.schemas['Episode']['状态']['status']['options']}
        if not {'未听', '在听', '听过'} <= statuses:
            raise ValueError('Episode 状态 requires 未听 / 在听 / 听过')
        target = self.schemas['Episode']['Podcast']['relation']['database_id'].replace('-', '')
        if target != self.dbs['Podcast'].replace('-', ''):
            raise ValueError('Episode.Podcast points to a different database')
        author_target = self.schemas['Podcast']['作者']['relation']['database_id'].replace('-', '')
        if author_target != self.dbs['Author'].replace('-', ''):
            raise ValueError('Podcast.作者 points to a different database')
        # Podcast templates can carry enormous unrelated multi-select options.
        # Never patch that schema just to add a redundant source marker: Pid
        # already namespaces Apple records. Write 来源 only when it exists.
        podcast_source = self.schemas['Podcast'].get('来源')
        if podcast_source and podcast_source['type'] != 'rich_text':
            raise ValueError('Template field mismatch: Podcast.来源 must be rich_text')
        for db in ('Episode',):
            fields = additions
            missing = {}
            for name, kind in fields.items():
                existing = self.schemas[db].get(name)
                if existing and existing['type'] != kind:
                    raise ValueError(f'Template field mismatch: {db}.{name}')
                if not existing:
                    missing[name] = {kind: {}}
            if missing:
                print(f'{db}: extra fields needed: ' + ', '.join(missing))
                if write:
                    self.call('PATCH', 'databases/' + self.dbs[db], {'properties': missing})
        if not podcast_source:
            print('Podcast: source identified by apple: Pid; schema left unchanged')
        from metadata import prepare_episode_fields
        prepare_episode_fields(self,write)
        print('Notion core schema: OK')

    def index(self, db, key):
        result = {}
        apple_only = (db, key) in (('Podcast', 'Pid'), ('Episode', 'Eid'))
        query = {'filter': {'property': key, 'rich_text': {'starts_with': 'apple:'}}} if apple_only else {}
        aliases=podcast_aliases() if db=='Podcast' and key=='Pid' else {}
        reverse={legacy:'apple:'+apple for apple,legacy in aliases.items()}
        if reverse:
            query={'filter':{'or':[query['filter']]+[
                {'property':key,'rich_text':{'equals':legacy}} for legacy in reverse]}}
        for page in self.paginate('databases/'+self.dbs[db]+'/query', query):
            value = text_value(page, key)
            # Duplicate legacy IDs belong to the old source. Never reconcile,
            # update or reject those records during an Apple sync. Also check
            # locally so source isolation does not depend solely on the filter.
            if apple_only and not value.startswith('apple:') and value not in reverse:
                continue
            identity=reverse.get(value,value)
            if identity in result and identity:
                raise ValueError(f'Duplicate {db}.{key}: {identity}; reconcile source aliases before syncing')
            if identity:
                result[identity] = page
        return result

    def upsert(self, db, index, key, properties):
        if key in index:
            page = self.call('PATCH', 'pages/'+index[key]['id'], {'properties': properties})
        else:
            page = self.call('POST', 'pages', {'parent': {'database_id': self.dbs[db]}, 'properties': properties})
        index[key] = page
        return page

    def section(self, page, title, content, language=None):
        from presentation import LEGACY, set_content, set_mindmap
        if title == 'Apple Podcasts · 内容大纲':
            return  # Stored inside the Markmap HTML, not as a separate section.
        if title == 'Apple Podcasts · 思维导图':
            return set_mindmap(self,page,content)
        name=LEGACY.get(title)
        if not name:
            raise ValueError('Unknown managed section: '+title)
        return set_content(self,page,name,content,language)


def cover_url(attrs):
    return attrs.get('artwork', {}).get('url', '').replace('{w}','600').replace('{h}','600').replace('{f}','jpg')


def sync_records(notion, shows, episodes, saved):
    podcasts, entries, authors = notion.index('Podcast','Pid'), notion.index('Episode','Eid'), notion.index('Author','标题')
    show_pages = {}
    for sid, show in shows.items():
        a = show.get('attributes', {})
        name = a.get('name') or 'Apple Podcasts ' + sid
        old=podcasts.get('apple:'+sid,{})
        legacy=bool(old and not text_value(old,'Pid').startswith('apple:'))
        props = {'播客':prop('title',text_value(old,'播客') if legacy else name),
                 'Pid':prop('rich_text',text_value(old,'Pid') if legacy else 'apple:'+sid)}
        if not legacy:
            props['链接']=prop('url',a.get('url') or 'https://podcasts.apple.com/cn/podcast/id'+sid)
        if notion.schemas['Podcast'].get('来源', {}).get('type') == 'rich_text':
            props['来源'] = prop('rich_text','Apple Podcasts')
        if a.get('artistName') and not legacy:
            author = a['artistName']
            author_page = authors.get(author) or notion.upsert('Author',authors,author,{'标题':prop('title',author)})
            props['作者'] = prop('relation',[{'id':author_page['id']}])
            from metadata import fill_author_icon
            fill_author_icon(notion,author_page,[cover_url(a)])
        if a.get('description',{}).get('standard') and not legacy:
            props['Description'] = prop('rich_text',a['description']['standard'][:1800])
        page = notion.upsert('Podcast',podcasts,'apple:'+sid,props)
        show_pages[sid] = page['id']
        if cover_url(a):
            image={'type':'external','external':{'url':cover_url(a)}}
            notion.call('PATCH','pages/'+page['id'],{'icon':image,'cover':image})
    synced = []
    for eid, row in episodes.items():
        a, p = row.get('attributes',{}), position(row)
        key = 'apple:'+eid
        old = entries.get(key, {})
        props = {'标题':prop('title',a.get('name') or eid), 'Eid':prop('rich_text',key),
                 '来源':prop('rich_text','Apple Podcasts'), '收藏':prop('checkbox',eid in saved)}
        mappings = [('assetUrl','音频','rich_text'),('url','链接','url')]
        for src,dst,kind in mappings:
            if a.get(src): props[dst] = prop(kind,a[src])
        if isinstance(a.get('durationInMilliseconds'),(int,float)):
            props['时长'] = prop('number',a['durationInMilliseconds']/1000)
        if a.get('releaseDateTime'):
            props['发布时间'] = prop('date',{'start':a['releaseDateTime']})
            props['时间戳'] = prop('number',datetime.fromisoformat(a['releaseDateTime'].replace('Z','+00:00')).timestamp())
        podcast = relation(row,'podcast')
        if podcast and podcast[0]['id'] in show_pages:
            props['Podcast'] = prop('relation',[{'id':show_pages[podcast[0]['id']]}])
        if p:
            status = '听过' if p.get('completed') else ('在听' if p.get('positionInMilliseconds',0)>0 else '未听')
            props['状态'] = prop('status',{'name':status})
            if isinstance(p.get('positionInMilliseconds'),(int,float)):
                props['播放位置'] = prop('number',p['positionInMilliseconds']/1000)
            if p.get('recordedAtTimestamp'):
                props['进度更新时间'] = prop('date',{'start':p['recordedAtTimestamp']})
                props['最近收听时间'] = prop('date',{'start':p['recordedAtTimestamp']})
        elif not old:
            props['状态'] = prop('status',{'name':'未听'})
        description = a.get('description',{}).get('standard')
        if description:
            props['Description'] = prop('rich_text',description[:1800])
        page = notion.upsert('Episode',entries,key,props)
        art=cover_url(a)
        if not art and podcast:
            art=cover_url(shows.get(podcast[0]['id'],{}).get('attributes',{}))
        if art:
            image={'type':'external','external':{'url':art}}
            notion.call('PATCH','pages/'+page['id'],{'icon':image,'cover':image})
        if description:
            notion.section(page['id'],'Apple Podcasts · 节目说明',description)
        if a.get('assetUrl'):
            notion.section(page['id'],'Apple Podcasts · 音频播放器',a['assetUrl'],'audio')
        synced.append((page,row))
    return synced


def finalize_metadata(notion):
    # Normalize all existing Podcast links to the template's aggregation row.
    # Retain every other relation; never touch old IDs or listening totals.
    all_rows=list(notion.paginate('databases/'+notion.dbs['全部']+'/query',{}))
    all_page=next((p for p in all_rows if any(
        prop.get('type')=='title' and ''.join(x.get('plain_text','') for x in prop['title'])=='全部'
        for prop in p.get('properties',{}).values())),None)
    if all_page is None:
        db=notion.call('GET','databases/'+notion.dbs['全部'])
        title_key=next(k for k,v in db['properties'].items() if v['type']=='title')
        all_page=notion.call('POST','pages',{'parent':{'database_id':notion.dbs['全部']},
            'properties':{title_key:prop('title','全部')}})
    for page in notion.paginate('databases/'+notion.dbs['Podcast']+'/query',{}):
        existing=page['properties'].get('全部',{}).get('relation',[])
        if not any(r['id']==all_page['id'] for r in existing):
            notion.call('PATCH','pages/'+page['id'],{'properties':{'全部':prop('relation',
                [{'id':r['id']} for r in existing]+[{'id':all_page['id']}])}})
        if not page.get('cover') and (page.get('icon') or {}).get('type')=='external':
            notion.call('PATCH','pages/'+page['id'],{'cover':page['icon']})
    from metadata import fill_all_author_icons
    fill_all_author_icons(notion)


def download_audio(url, audio):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname:
        raise ValueError('Audio requires HTTPS')
    for attempt in range(2):
        try:
            # Session credentials are never forwarded to an audio host.
            with requests.get(url,stream=True,timeout=(15,120)) as response:
                if response.status_code in (429,500,502,503,504):
                    raise AudioTemporarilyUnavailable(f'audio_download: HTTP {response.status_code}, host={parts.hostname}')
                check_response(response, 'audio_download')
                size = 0
                with audio.open('wb') as f:
                    for chunk in response.iter_content(1024*256):
                        size += len(chunk)
                        if size > 512*1024*1024:
                            raise ValueError('Audio exceeds 512 MiB download safety limit')
                        f.write(chunk)
            return
        except (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as error:
            transient=AudioTemporarilyUnavailable(f'audio_download: {type(error).__name__}, host={parts.hostname}')
        except AudioTemporarilyUnavailable as error:
            transient=error
        if attempt==1:raise transient
        print('Audio download temporarily unavailable; retrying once before skipping',flush=True)
        time.sleep(2)


def transcribe(url, api_key, directory):
    audio = directory/'source.audio'
    download_audio(url,audio)
    # 30min mono 16k PCM = 57.6 MB, so use 20min chunks (<50MB).
    subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(audio),'-map','0:a:0','-ac','1','-ar','16000',
                    '-c:a','pcm_s16le','-f','segment','-segment_time','1200',str(directory/'part-%04d.wav')],check=True,
                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=900)
    texts = []
    for index, part in enumerate(sorted(directory.glob('part-*.wav')), 1):
        print(f'ASR: submitting chunk {index}, bytes={part.stat().st_size}', flush=True)
        with part.open('rb') as f:
            response = requests.post('https://api.siliconflow.cn/v1/audio/transcriptions',
                headers={'Authorization':'Bearer '+api_key},data={'model':'FunAudioLLM/SenseVoiceSmall'},
                files={'file':(part.name,f,'audio/wav')},timeout=(20,600))
        check_response(response, f'siliconflow_transcription chunk={index}')
        text = response.json().get('text','').strip()
        if not text:
            raise ValueError('ASR returned empty text')
        texts.append(text)
    if not texts:
        raise ValueError('No audio chunks generated')
    return '\n\n'.join(texts)


def deepseek(text, key):
    model = os.getenv('DEEPSEEK_MODEL','deepseek-flash')
    def completion(content, instruction):
        # Outline extraction does not need reasoning. Explicitly disable the
        # provider's default thinking mode so it cannot consume the output budget.
        for budget in (8192, 16384):
            response = requests.post('https://api.deepseek.com/chat/completions',
                headers={'Authorization':'Bearer '+key},json={'model':model,'messages':[
                    {'role':'system','content':instruction},{'role':'user','content':content}],
                    'thinking':{'type':'disabled'},'max_tokens':budget,'stream':False},timeout=(20,300))
            check_response(response, 'deepseek_outline')
            body = response.json()
            result = body['choices'][0]
            reason = result.get('finish_reason')
            usage = body.get('usage',{})
            print(f'DeepSeek: model={model}, thinking=disabled, finish_reason={reason}, '
                  f'output_tokens={usage.get("completion_tokens")}, budget={budget}',flush=True)
            if reason == 'length' and budget == 8192:
                print('DeepSeek: output reached budget, retry once with 16384 tokens',flush=True)
                continue
            if reason != 'stop':
                raise ValueError(f'DeepSeek output incomplete: finish_reason={reason}, budget={budget}')
            answer = result['message'].get('content')
            if not isinstance(answer,str) or not answer.strip():
                raise ValueError('DeepSeek returned empty outline')
            return answer
    chunks = [text[i:i+16000] for i in range(0,len(text),16000)]
    if len(chunks)>1:
        chunks = [completion(c,'根据播客逐字稿提炼中文要点，保留事实、分歧与关键数字，不补充外部知识。') for c in chunks]
    output = completion('\n\n'.join(chunks), '将播客内容整理为中文 Markdown 大纲。第一行必须为唯一的 # 总标题，概括整期主题；其余只输出 ##、###、#### 标题，每行一个简短要点，最多60行；忠于原文，不编造。')
    return output


def mermaid(markdown):
    lines = ['flowchart LR','  root["播客要点"]']
    parents = {0:'root'}
    count = 0
    for line in markdown.splitlines():
        m = re.match(r'^(#{1,4})\s+(.+)',line.strip())
        if not m:
            continue
        count += 1
        if count>60: break
        level = len(m[1])
        label = m[2][:100]
        # Numeric entities keep user/model text from becoming Mermaid syntax.
        label = ''.join(c if c.isalnum() or c.isspace() else '#'+str(ord(c))+';' for c in label)
        parent = next((parents[i] for i in range(level-1,-1,-1) if i in parents),'root')
        node = 'n'+str(count)
        lines.extend([f'  {node}["{label}"]',f'  {parent} --> {node}'])
        parents = {k:v for k,v in parents.items() if k<level}
        parents[level] = node
    if not count:
        raise ValueError('DeepSeek did not return a Markdown outline')
    return '\n'.join(lines)


def run_ai(notion, synced):
    asr_key, llm_key = os.getenv('SILICONFLOW_API_KEY'), os.getenv('DEEPSEEK_API_KEY')
    if not asr_key and not llm_key:
        print('AI disabled: no AI keys configured')
        return 0
    failures = used = blocked = 0
    limit = int(os.getenv('AI_MAX_EPISODES','3'))
    for page,row in synced:
        a = row.get('attributes',{})
        if not a.get('assetUrl'):
            continue
        fingerprint = hashlib.sha256((str(row['id'])+'|'+a['assetUrl']).encode()).hexdigest()
        transcript_done = text_value(page,'转写指纹') == fingerprint
        map_hash = hashlib.sha256((fingerprint+'|'+os.getenv('DEEPSEEK_MODEL','deepseek-flash')+'|v1').encode()).hexdigest()
        map_done = text_value(page,'脑图指纹') == map_hash
        if transcript_done and (map_done or not llm_key): continue
        if not transcript_done and not asr_key: continue
        if used>=limit: break
        used+=1
        stage = 'load_saved_transcript' if transcript_done else 'audio_download_or_transcription'
        print(f'AI episode {row["id"]}: reuse_transcript={transcript_done}',flush=True)
        try:
            if transcript_done:
                from presentation import get_transcript
                transcript=get_transcript(notion,page['id'])
                if not transcript:
                    raise ValueError('Saved transcript checkpoint has no readable content')
            else:
                with tempfile.TemporaryDirectory() as temp:
                    transcript = transcribe(a['assetUrl'],asr_key,Path(temp))
                stage = 'save_transcript'
                notion.section(page['id'],'Apple Podcasts · 逐字稿',transcript)
                notion.call('PATCH','pages/'+page['id'],{'properties':{'转写指纹':prop('rich_text',fingerprint),'AI状态':prop('rich_text','已转写')}})
            if llm_key:
                stage = 'deepseek_outline'
                outline = deepseek(transcript,llm_key)
                stage = 'save_markmap'
                notion.section(page['id'],'Apple Podcasts · 思维导图',outline)
                notion.call('PATCH','pages/'+page['id'],{'properties':{'脑图指纹':prop('rich_text',map_hash),'AI状态':prop('rich_text','已完成')}})
        except AudioUnavailable as error:
            blocked += 1
            used -= 1  # No AI request was made; do not starve later episodes.
            label='音源暂不可用，未转写：' if isinstance(error,AudioTemporarilyUnavailable) else '音源受限，未转写：'
            message = label + safe_error(error)
            print('Audio unavailable for episode '+row['id']+': '+message,flush=True)
            if os.getenv('GITHUB_ACTIONS') == 'true':
                print('::warning::Audio unavailable for episode '+row['id']+'; see AI状态 in Notion',flush=True)
            notion.call('PATCH','pages/'+page['id'],{'properties':{'AI状态':prop('rich_text',message)}})
        except Exception as error:
            failures+=1
            message = f'{stage}: {safe_error(error)}'
            print('AI failed for episode '+row['id']+': '+message,flush=True)
            notion.call('PATCH','pages/'+page['id'],{'properties':{'AI状态':prop('rich_text',message)}})
    print(f'AI: {used} processed, {blocked} audio unavailable (skipped with warning), {failures} failed')
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='Read-only Apple and Notion schema check')
    parser.add_argument('--no-ai',action='store_true')
    args = parser.parse_args()
    notion = Notion()
    notion.prepare(not args.check)
    shows,episodes,saved = fetch_apple()
    if args.check: return
    from mindmap_library import ensure_database
    ensure_database(notion)
    synced = sync_records(notion,shows,episodes,saved)
    finalize_metadata(notion)
    from presentation import migrate, saved_outline, set_mindmap
    for page,row in synced:
        migrate(notion,page['id'])
        outline=saved_outline(notion,page['id'])
        if outline:
            set_mindmap(notion,page['id'],outline)
    # Finish verified presentation/schema migration independently of new AI jobs.
    from mindmap_library import retire_markdown_property
    retire_markdown_property(notion)
    failures = 0 if args.no_ai else run_ai(notion,synced)
    print('Basic sync complete')
    if failures:
        raise RuntimeError(f'{failures} AI tasks failed; basic sync is saved. Rerun to resume.')


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        print('Sync failed: '+safe_error(error))
        raise SystemExit(1)
