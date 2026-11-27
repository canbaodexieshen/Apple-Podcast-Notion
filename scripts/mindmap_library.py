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


def append_tree(notion,parent,nodes):
    if not nodes:return
    # Submit one level per call, so the API's nested-block limit is never exceeded.
    for start in range(0,len(nodes),100):
        batch=nodes[start:start+100]
        blocks=[{'object':'block','type':heading_kind(node),heading_kind(node):{
            'rich_text':rich(node['label']),'is_toggleable':True}} for node in batch]
        result=notion.call('PATCH','blocks/'+parent+'/children',{'children':blocks})['results']
        for block,node in zip(result,batch):append_tree(notion,block['id'],node['children'])


def tree_prefix(notion,parent,nodes):
    from presentation import children, plain
    existing=children(notion,parent)
    return len(existing)<=len(nodes) and all(
        block['type']==heading_kind(node) and block[block['type']].get('is_toggleable') and plain(block)==node['label'] and
        tree_prefix(notion,block['id'],node['children'])
        for block,node in zip(existing,nodes))


def resume_tree(notion,parent,nodes):
    from presentation import children
    existing=children(notion,parent)
    for block,node in zip(existing,nodes):resume_tree(notion,block['id'],node['children'])
    append_tree(notion,parent,nodes[len(existing):])


def heading_kind(node):
    return 'heading_'+str(min(4,node['level']))


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
    content_hash=hashlib.sha256(('library-v2-headings|'+outline).encode()).hexdigest()
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
    summary=next((b for b in old if b['type']=='heading_1'),None)
    if diagram is None:
        block=html_block or upload_html(notion,outline)
        diagram=notion.call('PATCH','blocks/'+record['id']+'/children',{'children':[{
            'object':'block','type':'heading_2','heading_2':{'rich_text':rich('脑图'),
                'is_toggleable':True,'children':[block]}}],'position':{'type':'start'}})['results'][0]
    elif html_block:
        replace_tab(notion,diagram,[html_block])
    elif text_value(record,'内容指纹')!=content_hash:
        replace_tab(notion,diagram,[upload_html(notion,outline)])
    if not summary or text_value(record,'内容指纹')!=content_hash:
        pending=next((b for b in reversed(old) if b['type']=='heading_1' and plain(b)==title
                      and tree_prefix(notion,b['id'],nodes)),None)
        new=pending or notion.call('PATCH','blocks/'+record['id']+'/children',{'children':[{
            'object':'block','type':'heading_1','heading_1':{'rich_text':rich(title),'is_toggleable':True}}],
            'position':{'type':'after_block','after_block':{'id':diagram['id']}}})['results'][0]
        resume_tree(notion,new['id'],nodes)
        # Only retire the old generated section after every level was saved.
        if summary and summary['id']!=new['id']:notion.call('DELETE','blocks/'+summary['id'])
    record=notion.call('PATCH','pages/'+record['id'],{'properties':{'内容指纹':prop('rich_text',content_hash)}})
    notion._map_records[episode.replace('-','')]=record
    print(f'Mindmap library: {bounds["nodes"]} expanded nodes, {bounds["width"]}x{bounds["height"]} PNG saved',flush=True)
    return record
