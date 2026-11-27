"""One private Notion mindmap record per episode, with a full expanded PNG."""
import hashlib
import re
import requests
from sync import rich, prop, text_value, check_response


def ensure_database(notion):
    if '思维导图' not in notion.dbs:
        result=notion.call('POST','databases',{
            'parent':{'type':'page_id','page_id':notion.root},'is_inline':True,
            'title':rich('思维导图'),
            'properties':{
                '名称':{'title':{}},'思维导图封面':{'files':{}},
                '播客单集':{'relation':{'database_id':notion.dbs['Episode'],
                    'type':'dual_property','dual_property':{'synced_property_name':'思维导图'}}},
                '内容指纹':{'rich_text':{}}}})
        notion.dbs['思维导图']=result['id']
        notion._map_schema=result['properties']
    if not hasattr(notion,'_map_schema'):
        notion._map_schema=notion.call('GET','databases/'+notion.dbs['思维导图'])['properties']
    for name,kind in {'名称':'title','思维导图封面':'files','播客单集':'relation',
                      '内容指纹':'rich_text'}.items():
        if notion._map_schema.get(name,{}).get('type')!=kind:
            raise ValueError('Existing 思维导图 schema mismatch: '+name)
    target=notion._map_schema['播客单集']['relation']['database_id']
    if target.replace('-','')!=notion.dbs['Episode'].replace('-',''):
        raise ValueError('思维导图.播客单集 points to a different database')
    return notion.dbs['思维导图']


def lookup(notion,episode,create=True):
    db=ensure_database(notion) if create else notion.dbs.get('思维导图')
    if not db:return None
    if not hasattr(notion,'_map_records'):
        notion._map_records={}
        for record in notion.paginate('databases/'+db+'/query',{}):
            for target in record['properties'].get('播客单集',{}).get('relation',[]):
                key=target['id'].replace('-','')
                if key in notion._map_records:
                    raise ValueError('Duplicate mindmap records for an episode; originals preserved')
                notion._map_records[key]=record
    return notion._map_records.get(episode.replace('-',''))


def upload_png(notion,content):
    if len(content)>5*1024*1024:raise ValueError('Mindmap PNG exceeds 5 MiB upload limit')
    headers={**notion.headers,'Notion-Version':'2026-03-11'}
    filename='mindmap-cover-'+hashlib.sha256(content).hexdigest()[:20]+'.png'
    result=requests.post('https://api.notion.com/v1/file_uploads',headers=headers,
        json={'mode':'single_part','filename':filename,'content_type':'image/png'},timeout=(15,90))
    check_response(result,'mindmap_cover_upload_create')
    upload=result.json()['id']
    result=requests.post('https://api.notion.com/v1/file_uploads/'+upload+'/send',headers=headers,
        files={'file':(filename,content,'image/png')},timeout=(15,120))
    check_response(result,'mindmap_cover_upload_send')
    return {'type':'file_upload','file_upload':{'id':upload}}


def outline_tree(markdown):
    lines=[(len(m[1]),m[2].strip()) for line in markdown.splitlines()
           if (m:=re.match(r'^(#{1,6})\s+(.+)',line.strip()))]
    if not lines:raise ValueError('Mindmap outline has no headings')
    title=lines[0][1] if lines[0][0]==1 else '播客要点'
    nodes=[];stack=[(0,nodes)]
    for level,label in (lines[1:] if lines[0][0]==1 else lines):
        while len(stack)>1 and stack[-1][0]>=level:stack.pop()
        node={'label':label,'level':level,'children':[]}
        stack[-1][1].append(node)
        stack.append((level,node['children']))
    return title,nodes


def heading_kind(node):
    return 'heading_'+str(min(4,node['level']))


def flat_outline(title,nodes):
    result=[{'label':title,'level':1}]
    def visit(items):
        for node in items:
            result.append({'label':node['label'],'level':min(4,node['level'])})
            visit(node['children'])
    visit(nodes)
    return result


def ordinary_heading(block,node):
    from presentation import plain
    kind=heading_kind(node)
    return (block['type']==kind and plain(block)==node['label'] and
            not block[kind].get('is_toggleable') and not block.get('has_children'))


def ensure_plain_outline(notion,page,diagram,title,nodes):
    """Preserve ordinary headings and notes; migrate only verified generated content."""
    from collections import Counter
    from presentation import children, plain
    desired=flat_outline(title,nodes)
    expected=[(heading_kind(node),node['label']) for node in desired]
    known=set(expected)
    roots=children(notion,page)
    start=next(i+1 for i,b in enumerate(roots) if b['id']==diagram['id'])
    prefix=[]
    for block,node in zip(roots[start:],desired):
        if not ordinary_heading(block,node):break
        prefix.append(block)
    prefix_ids={b['id'] for b in prefix}
    old=[b for b in roots if b['id']!=diagram['id'] and b['id'] not in prefix_ids and
         (b['type'],plain(b)) in known]
    def tokens(block):
        kind=block['type'];label=plain(block)
        if kind=='paragraph' and not label.strip() and not block.get('has_children'):return []
        if (kind,label) not in known:
            raise ValueError('Additional notes inside generated headings; originals preserved')
        result=[(kind,label)]
        if block.get('has_children') or block[kind].get('is_toggleable'):
            for child in children(notion,block['id']):result+=tokens(child)
        return result
    original=[item for block in old for item in tokens(block)]
    if len(prefix)==len(desired):
        if Counter(original)-Counter(expected):
            raise ValueError('Unmatched heading content; originals preserved')
    elif original and original not in (expected,expected[len(prefix):]):
        raise ValueError('Generated heading text differs from HTML; originals preserved')
    cursor=prefix[-1]['id'] if prefix else diagram['id']
    canonical=list(prefix)
    for offset in range(len(prefix),len(desired),100):
        batch=desired[offset:offset+100]
        result=notion.call('PATCH','blocks/'+page+'/children',{'children':[
            {'object':'block','type':heading_kind(node),heading_kind(node):{
                'rich_text':rich(node['label']),'is_toggleable':False}} for node in batch],
            'position':{'type':'after_block','after_block':{'id':cursor}}})['results']
        canonical.extend(result);cursor=result[-1]['id']
    # Recheck source blocks after saving the new layout; preserve concurrent notes.
    if [item for block in old for item in tokens(notion.call('GET','blocks/'+block['id']))]!=original:
        raise ValueError('Heading text changed during migration; originals preserved')
    for block in old:notion.call('DELETE','blocks/'+block['id'])
    return canonical


def retire_markdown_property(notion):
    """Remove the user-requested obsolete field only after every outline is in HTML."""
    from presentation import library_outline, restore_utf8_outline
    ensure_database(notion)
    old=notion._map_schema.get('脑图Markdown')
    if not old:return
    for record in notion.paginate('databases/'+notion.dbs['思维导图']+'/query',{}):
        original=text_value(record,'脑图Markdown')
        if original and library_outline(notion,record)!=restore_utf8_outline(original):
            raise ValueError('HTML outline not verified; 脑图Markdown kept to preserve data')
    notion.call('PATCH','databases/'+notion.dbs['思维导图'],{'properties':{old['id']:None}})
    notion._map_schema.pop('脑图Markdown',None)
    for record in getattr(notion,'_map_records',{}).values():
        record['properties'].pop('脑图Markdown',None)
    print('Mindmap library: 脑图Markdown removed after complete HTML recovery check',flush=True)


def publish(notion,episode,outline,html_block=None):
    from presentation import markup, upload_html, children, plain, replace_tab
    from render_mindmap import screenshot
    title,nodes=outline_tree(outline)
    content_hash=hashlib.sha256(('library-v3-plain-headings|'+outline).encode()).hexdigest()
    record=lookup(notion,episode)
    print('Mindmap library: rendering complete outline and saving private PNG',flush=True)
    # Capture the full expanded map on every sync, even when the AI outline is unchanged.
    png,bounds=screenshot(markup(outline))
    cover=upload_png(notion,png)
    properties={'名称':prop('title',title),'播客单集':prop('relation',[{'id':episode}]),
                '思维导图封面':{'files':[{'name':'思维导图封面.png',**cover}]}}
    if record:
        record=notion.call('PATCH','pages/'+record['id'],{'properties':properties,'cover':cover})
    else:
        record=notion.call('POST','pages',{'parent':{'database_id':notion.dbs['思维导图']},
            'properties':properties,'cover':cover,'icon':{'type':'emoji','emoji':'🧠'}})
    notion._map_records[episode.replace('-','')]=record
    old=children(notion,record['id'])
    diagram=next((b for b in old if b['type']=='heading_2' and plain(b)=='脑图'),None)
    if diagram is None:
        block=html_block or upload_html(notion,outline)
        diagram=notion.call('PATCH','blocks/'+record['id']+'/children',{'children':[{
            'object':'block','type':'heading_2','heading_2':{'rich_text':rich('脑图'),
                'is_toggleable':True,'children':[block]}}],'position':{'type':'start'}})['results'][0]
    elif html_block:
        replace_tab(notion,diagram,[html_block])
    elif text_value(record,'内容指纹')!=content_hash:
        replace_tab(notion,diagram,[upload_html(notion,outline)])
    ensure_plain_outline(notion,record['id'],diagram,title,nodes)
    record=notion.call('PATCH','pages/'+record['id'],{'properties':{'内容指纹':prop('rich_text',content_hash)}})
    notion._map_records[episode.replace('-','')]=record
    print(f'Mindmap library: {bounds["nodes"]} expanded nodes, {bounds["width"]}x{bounds["height"]} PNG saved',flush=True)
    return record
