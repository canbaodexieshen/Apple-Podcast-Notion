"""Native Notion tabs, self-contained Markmap uploads, and safe legacy migration."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, unquote
import requests

TAB_NAMES = ('ShowNotes', '脑图', '语音转文字', '音频')
LEGACY = {
    'Apple Podcasts · 节目说明': 'ShowNotes',
    'Apple Podcasts · 逐字稿': '语音转文字',
    'Apple Podcasts · 音频播放器': '音频',
    'Apple Podcasts · 思维导图': '脑图',
    'Apple Podcasts · 内容大纲': None,
}


def plain(block):
    return ''.join(x.get('plain_text', x.get('text',{}).get('content',''))
                   for x in block.get(block['type'],{}).get('rich_text',[]))


def text_block(text):
    from sync import rich
    return {'object':'block','type':'paragraph','paragraph':{'rich_text':rich(text)}}


def markup(outline):
    bundle = Path(__file__).resolve().parents[1]/'web/mindmap.bundle.js'
    if not bundle.exists():
        raise ValueError('Markmap bundle missing: run npm ci && npm run build')
    data=json.dumps(outline,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    javascript=bundle.read_text(encoding='utf-8').replace('</script','<\\/script')
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>播客脑图</title>
<style>*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;background:#fff;color:#333;font-family:system-ui,sans-serif}
body{min-height:480px}header{position:absolute;z-index:2;right:12px;top:12px;display:flex;gap:6px;padding:6px;background:#ffffffdd;border:1px solid #eee;border-radius:12px}
button{border:1px solid #ddd;background:#fff;color:inherit;border-radius:7px;padding:6px 10px;cursor:pointer}svg{width:100%;height:100vh;min-height:480px}
.markmap-foreign div{line-height:1.6}.dark,.dark body{background:#191919;color:#ddd}.dark header{background:#282828dd;border-color:#444}.dark button{background:#333;border-color:#555}
.dark .markmap-foreign{color:#ddd}.markmap-node{cursor:pointer}footer{position:absolute;bottom:8px;left:14px;font-size:11px;color:#999}
</style></head><body><header><button id="out" aria-label="缩小">−</button><button id="in" aria-label="放大">＋</button><button id="fit">适应窗口</button><button id="theme">深浅色</button></header>
<svg id="map"></svg><footer>点击节点可折叠 · 拖动和缩放查看</footer>
<script type="application/json" id="map-data">'''+data+'''</script><script>'''+javascript+'''</script></body></html>'''


def upload_html(notion, outline):
    from sync import check_response
    content=markup(outline).encode('utf-8')
    if len(content)>5*1024*1024:
        raise ValueError('Markmap HTML exceeds 5 MiB safe upload limit')
    headers={**notion.headers,'Notion-Version':'2026-03-11'}
    fingerprint=hashlib.sha256(('markmap-v1|'+outline).encode()).hexdigest()
    filename='mindmap-'+fingerprint+'.html'
    response=requests.post('https://api.notion.com/v1/file_uploads',headers=headers,
        json={'mode':'single_part','filename':filename,'content_type':'text/html'},timeout=(15,90))
    check_response(response,'notion_html_upload_create')
    upload_id=response.json()['id']
    response=requests.post('https://api.notion.com/v1/file_uploads/'+upload_id+'/send',headers=headers,
        files={'file':(filename,content,'text/html')},timeout=(15,120))
    check_response(response,'notion_html_upload_send')
    return {'object':'block','type':'embed','embed':{'type':'file_upload','file_upload':{'id':upload_id}}}


def children(notion, block):
    return list(notion.paginate('blocks/'+block+'/children'))


def find_tabs(notion, page):
    for block in children(notion,page):
        if block['type']=='tab':
            labels=children(notion,block['id'])
            if [plain(b) for b in labels]==list(TAB_NAMES):
                return block, {plain(b):b for b in labels}
    return None, {}


def ensure_tabs(notion,page):
    block,tabs=find_tabs(notion,page)
    if block:
        return tabs
    from sync import rich
    # Build only two nesting levels per request; fill each tab separately.
    response=notion.call('PATCH','blocks/'+page+'/children',{'children':[{
        'object':'block','type':'tab','tab':{'children':[
            {'object':'block','type':'paragraph','paragraph':{'rich_text':rich(name)}} for name in TAB_NAMES]}}]})
    container=response['results'][0]
    tabs={plain(b):b for b in children(notion,container['id'])}
    if list(tabs)!=list(TAB_NAMES):
        raise ValueError('Unexpected native tab structure; original content is preserved')
    return tabs


def clone_block(block):
    """Clone only supported managed leaf content, never IDs or user-authored notes."""
    kind=block['type']
    value=block[kind]
    if kind in ('paragraph','code'):
        from sync import rich
        payload={'rich_text':rich(plain(block))}
        if kind=='code':payload['language']=value['language']
        return {'object':'block','type':kind,kind:payload}
    if kind=='audio':
        if value.get('type')=='external':
            return {'object':'block','type':'audio','audio':{'type':'external','external':value['external']}}
    return None


def replace_tab(notion,tab,new_blocks):
    old=children(notion,tab['id'])
    # Same leaf type can be updated without appending. Otherwise create first,
    # then archive the old managed content only after successful attachment.
    if len(old)==len(new_blocks)==1 and old[0]['type']==new_blocks[0]['type']:
        kind=new_blocks[0]['type']
        notion.call('PATCH','blocks/'+old[0]['id'],{kind:new_blocks[0][kind]})
    else:
        if new_blocks:
            notion.call('PATCH','blocks/'+tab['id']+'/children',{'children':new_blocks})
        for block in old:
            notion.call('DELETE','blocks/'+block['id'])


def migrate(notion,page):
    root=children(notion,page)
    tabs=ensure_tabs(notion,page)
    for b in children(notion,tabs['脑图']['id']):
        if b['type']=='embed':
            caption=''.join(x.get('plain_text','') for x in b['embed'].get('caption',[]))
            if len(caption)==64 and all(c in '0123456789abcdef' for c in caption):
                notion.call('PATCH','blocks/'+b['id'],{'embed':{'caption':[]}})
    legacy=[b for b in root if b['type']=='toggle' and plain(b) in LEGACY]
    for b in legacy:
        name=LEGACY[plain(b)]
        if name is None or name=='脑图':
            continue  # Outline is converted first; never discard it prematurely.
        old=children(notion,b['id'])
        if not children(notion,tabs[name]['id']):
            copies=[clone_block(c) for c in old]
            if not all(copies):
                raise ValueError('Unsupported legacy content; migration stopped without deleting original')
            if copies:
                replace_tab(notion,tabs[name],copies)
        # Managed blocks contain only our leaf content; notes/comments must not
        # be silently discarded during a legacy migration.
        for c in old:
            if c.get('has_children'):
                raise ValueError('Legacy block has additional notes; preserve it for review')
        notion.call('DELETE','blocks/'+b['id'])
    return tabs


def get_transcript(notion,page):
    _,tabs=find_tabs(notion,page)
    if tabs:
        return '\n\n'.join(plain(b) for b in children(notion,tabs['语音转文字']['id']) if b['type']=='paragraph')
    for b in children(notion,page):
        if b['type']=='toggle' and plain(b)=='Apple Podcasts · 逐字稿':
            return '\n\n'.join(plain(c) for c in children(notion,b['id']) if c['type']=='paragraph')
    return ''


def set_content(notion,page,name,content,language=None):
    tabs=migrate(notion,page)
    if language=='audio':
        blocks=[{'object':'block','type':'audio','audio':{'type':'external','external':{'url':content}}}]
    elif name=='脑图':
        blocks=[upload_html(notion,content)]
    else:
        blocks=[text_block(content)]
    replace_tab(notion,tabs[name],blocks)


def legacy_outline(notion,page):
    for b in children(notion,page):
        if b['type']=='toggle' and plain(b)=='Apple Podcasts · 内容大纲':
            return '\n\n'.join(plain(c) for c in children(notion,b['id']) if c['type']=='paragraph')
    return ''


def set_mindmap(notion,page,outline):
    fingerprint=hashlib.sha256(('markmap-v1|'+outline).encode()).hexdigest()
    # The uploaded filename tracks content without a technical caption in the UI.
    _,tabs=find_tabs(notion,page)
    existing=children(notion,tabs['脑图']['id']) if tabs else []
    if any(b['type']=='embed' and fingerprint in unquote(urlsplit(b['embed'].get('url','')).path) for b in existing):
        return
    tabs=migrate(notion,page)
    block=upload_html(notion,outline)
    replace_tab(notion,tabs['脑图'],[block])
    # Remove only known old generated outline/diagram after the Markmap saved.
    for b in children(notion,page):
        if b['type']=='toggle' and plain(b) in ('Apple Podcasts · 内容大纲','Apple Podcasts · 思维导图'):
            notion.call('DELETE','blocks/'+b['id'])
